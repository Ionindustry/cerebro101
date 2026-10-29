"""Importar la lista de precios de un proveedor desde un documento subido al chat: dar de alta el proveedor y cargar sus precios en el ERP.

Cómo se reparte el trabajo (y por qué):
  - La TABLA la lee el SISTEMA, de forma determinista, del documento subido (CSV, Excel, y como último recurso el texto de un PDF). El modelo solo dice qué columna es cada cosa y quién es el proveedor:
    transcribir cientos de líneas con un modelo local tardaría horas y se equivocaría. Cada línea sale del documento tal cual.
  - El agente PROPONE: se guarda la importación con sus líneas, las rechazadas y los avisos, y se comprueba contra el ERP qué artículos ya existen. No se escribe nada en el ERP.
  - Una PERSONA aprueba en la bandeja (con una vista previa: proveedor nuevo o existente, lista, artículos nuevos, rango de precios, primeras líneas). Solo entonces `aplicar` da de alta el proveedor, la
    lista de precios, los artículos nuevos y los precios, con la clave de Operaciones y solo en los datos maestros que su política permite (config/erp_acceso.yaml → «maestros»).
  - Se puede repetir sin duplicar: lo que ya está en el ERP no se vuelve a crear; un precio distinto se actualiza.

POR VERIFICAR con el ERPNext real de 101.cat: los nombres de los campos (Supplier, Item, Item Price, Price List), el grupo de artículos y la unidad por defecto (config/integraciones.yaml → listas_precios).
"""
from __future__ import annotations

import csv
import io
import logging
import re
import unicodedata
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import psycopg
import yaml
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from . import subidas
from .ajustes import ajustes
from .herramientas import erpnext
from .herramientas.facturas import DatosFactura, a_decimal

log = logging.getLogger("cerebro.listas_precios")
DEFECTO = {"item_group": "Products", "stock_uom": "Nos", "supplier_group": "All Supplier Groups", "supplier_type": "Company", "moneda": "EUR", "monedas": ["EUR", "USD", "GBP"],
           "max_lineas": 3000, "lote": 100, "prefijo_lista": "Compra"}
CAMPOS = ("referencia", "descripcion", "precio", "unidad", "descuento")
PRECIO_MAX = Decimal("10000000")
RE_NIF = re.compile(r"^[A-Z0-9]{8,14}$")
RE_FECHA = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MAX_RECHAZADAS = 200


class ErrorImportacion(ValueError):
    """Lo que la importación no admite; el mensaje es para quien la pidió (agente o persona)."""


class NoExiste(LookupError):
    pass


def configuracion() -> dict:
    try:
        c = (yaml.safe_load((Path(ajustes.dir_config) / "integraciones.yaml").read_text(encoding="utf-8")) or {}).get("listas_precios") or {}
    except OSError:
        c = {}
    cfg = {**DEFECTO, **c}
    cfg["max_lineas"] = min(max(int(cfg["max_lineas"]), 10), 20000)
    cfg["lote"] = min(max(int(cfg["lote"]), 10), 500)
    return cfg


def _conectar():
    return psycopg.AsyncConnection.connect(ajustes.database_url, row_factory=dict_row)


# ---- Leer la tabla del documento (puro) ----

def norm(t) -> str:
    return re.sub(r"\s+", " ", "".join(c for c in unicodedata.normalize("NFD", str(t or "").lower()) if unicodedata.category(c) != "Mn")).strip()


def detectar_delimitador(lineas: list[str]) -> str:
    """El separador de columnas de un CSV: el que da el mismo número (mayor que 0) en más líneas."""
    mejor, puntos = ";", 0
    muestra = [l for l in lineas if l.strip()][:30]
    for d in (";", "\t", ",", "|"):
        cuentas = [l.count(d) for l in muestra]
        if not cuentas or max(cuentas) == 0:
            continue
        frecuente = max(set(cuentas), key=cuentas.count)
        p = cuentas.count(frecuente) * (1 if frecuente > 0 else 0)
        if frecuente > 0 and p > puntos:
            mejor, puntos = d, p
    return mejor


def filas_de_pagina(texto: str, formato: str) -> list[list[str]]:
    """Las filas (listas de celdas) de una página del documento. Excel: «celda | celda»; CSV: con su separador; PDF/Word/texto: columnas separadas por tabuladores o 2 o más espacios."""
    lineas = [l for l in texto.replace("\x00", "").split("\n") if l.strip() and not l.startswith("[Hoja")]
    if formato in ("xlsx", "ods"):
        return [[c.strip() for c in l.split(" | ")] for l in lineas]
    if formato == "csv":
        d = detectar_delimitador(lineas)
        return [[c.strip() for c in fila] for fila in csv.reader(io.StringIO("\n".join(lineas)), delimiter=d) if any(c.strip() for c in fila)]
    return [[c.strip() for c in re.split(r"\t| {2,}| \| ", l.strip()) if c.strip()] for l in lineas]


def resolver_columnas(columnas: dict, cabecera: list[str]) -> dict[str, int]:
    """{campo: índice (0 = primera columna)} a partir de lo que dice el agente: un número de columna (desde 1) o el nombre que lleva en la cabecera. Lanza ErrorImportacion si no cuadra."""
    if not isinstance(columnas, dict):
        raise ErrorImportacion("columnas debe ser un objeto: {referencia: …, precio: …, descripcion: …}")
    desconocidas = set(columnas) - set(CAMPOS)
    if desconocidas:
        raise ErrorImportacion(f"Columnas desconocidas: {sorted(desconocidas)}. Valen: {', '.join(CAMPOS)}")
    for obligatorio in ("referencia", "precio"):
        if columnas.get(obligatorio) in (None, ""):
            raise ErrorImportacion(f"Falta la columna «{obligatorio}»")
    nombres = [norm(c) for c in cabecera]
    out: dict[str, int] = {}
    for campo, v in columnas.items():
        if v in (None, ""):
            continue
        if isinstance(v, bool):
            raise ErrorImportacion(f"La columna «{campo}» no es válida")
        if isinstance(v, int) or (isinstance(v, str) and v.strip().isdigit()):
            i = int(v) - 1
            if not 0 <= i < max(len(cabecera), 1) + 30:
                raise ErrorImportacion(f"La columna {v} de «{campo}» no existe")
            out[campo] = i
            continue
        n = norm(v)
        exactas = [i for i, h in enumerate(nombres) if h == n]
        parciales = [i for i, h in enumerate(nombres) if n and n in h]
        if len(exactas) == 1:
            out[campo] = exactas[0]
        elif not exactas and len(parciales) == 1:
            out[campo] = parciales[0]
        else:
            raise ErrorImportacion(f"La columna «{v}» ({campo}) " + ("aparece varias veces" if exactas or len(parciales) > 1 else "no está") + f" en la cabecera: {', '.join(c[:30] for c in cabecera[:12])}")
    if len(set(out.values())) != len(out):
        raise ErrorImportacion("Dos campos distintos apuntan a la misma columna")
    return out


def a_precio(valor, iva_incluido_pct: float | None = None) -> Decimal:
    """El precio de una celda como Decimal con 4 decimales, SIN IVA. Rechaza lo ambiguo, lo no numérico, lo ≤ 0 y lo absurdo."""
    try:
        d = a_decimal(valor)
    except DatosFactura as e:
        raise ErrorImportacion(str(e)) from None
    if iva_incluido_pct:
        d = d / (Decimal(1) + Decimal(str(iva_incluido_pct)) / 100)
    if d <= 0:
        raise ErrorImportacion("el precio debe ser mayor que 0")
    if d >= PRECIO_MAX:
        raise ErrorImportacion("el precio es absurdamente alto")
    return d.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def prefijo_proveedor(nombre: str) -> str:
    base = re.sub(r"[^A-Z0-9]", "", "".join(c for c in unicodedata.normalize("NFD", nombre.upper()) if unicodedata.category(c) != "Mn"))
    return base[:6] or "PROV"


def codigo_articulo(prefijo: str, ref: str) -> str:
    """El código del artículo en el ERP: prefijo del proveedor + su referencia (así dos proveedores con la misma referencia no chocan)."""
    r = re.sub(r"[^A-Za-z0-9._/+#-]", "", re.sub(r"\s+", "-", ref.strip()))
    if not r:
        raise ErrorImportacion("la referencia no tiene caracteres válidos")
    codigo = f"{prefijo}-{r}"
    if len(codigo) > 100:
        raise ErrorImportacion("la referencia es demasiado larga")
    return codigo


def construir_lineas(paginas: list[tuple[int, str]], formato: str, columnas: dict, fila_cabecera: int = 1, prefijo: str = "PROV", iva_incluido_pct: float | None = None,
                     max_lineas: int = 3000) -> dict:
    """Lee TODAS las filas de las páginas indicadas y devuelve {lineas, rechazadas, omitidas, avisos, columnas}. `fila_cabecera` es la fila (desde 1, de cada página u hoja) que lleva los títulos: se salta
    esa y las anteriores. Una fila sin referencia ni precio (un título de sección, una nota) se omite; con referencia pero sin precio válido, se rechaza con el motivo."""
    if isinstance(fila_cabecera, bool) or not isinstance(fila_cabecera, int) or not 0 <= fila_cabecera <= 50:
        raise ErrorImportacion("fila_cabecera debe ser un número de fila (desde 1; 0 si el documento no tiene cabecera)")
    if not paginas:
        raise ErrorImportacion("El documento no tiene páginas que leer")
    primera = filas_de_pagina(paginas[0][1], formato)
    if fila_cabecera > len(primera):
        raise ErrorImportacion(f"La primera página tiene {len(primera)} filas: no hay fila {fila_cabecera} de cabecera")
    cabecera = primera[fila_cabecera - 1] if fila_cabecera else []
    idx = resolver_columnas(columnas, cabecera)
    lineas, rechazadas, avisos, vistos = [], [], [], {}
    omitidas = 0
    for n, texto in paginas:
        filas = filas_de_pagina(texto, formato)
        for k, celdas in enumerate(filas, start=1):
            if k <= fila_cabecera:
                continue
            ref = celdas[idx["referencia"]].strip() if idx["referencia"] < len(celdas) else ""
            bruto = celdas[idx["precio"]].strip() if idx["precio"] < len(celdas) else ""
            etiqueta = f"p. {n}, fila {k}" if len(paginas) > 1 else f"fila {k}"
            if not ref and not bruto:
                omitidas += 1
                continue
            if not ref or not bruto:
                if not bruto and len(celdas) <= 2:                  # un título de sección o una nota, no una línea de precios
                    omitidas += 1
                else:
                    rechazadas.append({"fila": etiqueta, "motivo": "falta " + ("la referencia" if not ref else "el precio")})
                continue
            try:
                precio = a_precio(bruto, iva_incluido_pct)
                if "descuento" in idx and idx["descuento"] < len(celdas) and celdas[idx["descuento"]].strip():
                    d = a_decimal(celdas[idx["descuento"]].strip().rstrip("%"))
                    if not 0 <= d < 100:
                        raise ErrorImportacion("el descuento debe estar entre 0 y 100 %")
                    precio = (precio * (Decimal(100) - d) / 100).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
                    if precio <= 0:
                        raise ErrorImportacion("el precio con descuento es 0")
                codigo = codigo_articulo(prefijo, ref)
            except (ErrorImportacion, DatosFactura) as e:
                rechazadas.append({"fila": etiqueta, "motivo": f"{ref[:30]}: {e}"})
                continue
            if codigo in vistos:
                anterior = vistos[codigo]
                if anterior["precio"] != str(precio):
                    avisos.append(f"Referencia repetida con precio distinto ({ref[:30]}: {anterior['precio']} y {precio}, {etiqueta}): se conserva la primera")
                rechazadas.append({"fila": etiqueta, "motivo": f"{ref[:30]}: referencia repetida"})
                continue
            desc = ""
            if "descripcion" in idx and idx["descripcion"] < len(celdas):
                desc = re.sub(r"\s+", " ", celdas[idx["descripcion"]]).strip()[:300]
            unidad = ""
            if "unidad" in idx and idx["unidad"] < len(celdas):
                unidad = re.sub(r"[^\w .²³/-]", "", celdas[idx["unidad"]]).strip()[:30]
            linea = {"fila": etiqueta, "ref": ref[:80], "codigo": codigo, "desc": desc or ref[:140], "precio": str(precio), "unidad": unidad}
            vistos[codigo] = linea
            lineas.append(linea)
            if len(lineas) > max_lineas:
                raise ErrorImportacion(f"La lista tiene más de {max_lineas} líneas: divídela en varias")
    if not lineas:
        raise ErrorImportacion("No se ha encontrado ninguna línea de precios con esas columnas" + (f" (rechazadas: {len(rechazadas)}; primera: {rechazadas[0]['motivo']})" if rechazadas else ""))
    if len(rechazadas) > max(5, len(lineas)):
        raise ErrorImportacion(f"Se rechazan más filas ({len(rechazadas)}) que las que valen ({len(lineas)}): las columnas indicadas no parecen las correctas. Primer motivo: {rechazadas[0]['motivo']}")
    if len(rechazadas) > 0:
        avisos.append(f"{len(rechazadas)} fila(s) rechazada(s); revisa los motivos antes de aprobar")
    return {"lineas": lineas, "rechazadas": rechazadas[:MAX_RECHAZADAS], "n_rechazadas": len(rechazadas), "omitidas": omitidas, "avisos": avisos, "columnas": {k: int(v) + 1 for k, v in idx.items()}}


def validar_proveedor(p: dict, texto: str) -> tuple[dict, list[str]]:
    """El proveedor que dice el agente, normalizado. Que su nombre o NIF no salgan en el documento no se rechaza (puede venir en un logo): se avisa para que la persona lo mire al aprobar."""
    if not isinstance(p, dict):
        raise ErrorImportacion("proveedor debe ser un objeto: {nombre, nif, email, telefono, pais}")
    nombre = re.sub(r"\s+", " ", re.sub(r"[\x00-\x1f\x7f]", " ", str(p.get("nombre") or ""))).strip()
    if not 2 <= len(nombre) <= 120:
        raise ErrorImportacion("El nombre del proveedor debe tener entre 2 y 120 caracteres")
    nif = re.sub(r"[\s.-]", "", str(p.get("nif") or "")).upper()
    if nif and not RE_NIF.match(nif):
        raise ErrorImportacion(f"El NIF «{nif[:20]}» no parece válido (de 8 a 14 letras y números)")
    email = str(p.get("email") or "").strip()[:120]
    if email and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise ErrorImportacion("El correo del proveedor no es válido")
    telefono = re.sub(r"[^\d+ ().-]", "", str(p.get("telefono") or ""))[:30].strip()
    pais = str(p.get("pais") or "").strip()[:60]
    avisos = []
    t = norm(texto)
    if norm(nombre) not in t:
        avisos.append(f"El nombre «{nombre}» no aparece en el texto del documento: confirma que es el proveedor correcto")
    if nif and nif.lower() not in re.sub(r"[\s.-]", "", t):
        avisos.append(f"El NIF {nif} no aparece en el texto del documento")
    return {"nombre": nombre, "nif": nif, "email": email, "telefono": telefono, "pais": pais}, avisos


def nombre_lista(cfg: dict, proveedor_nombre: str) -> str:
    return f"{cfg['prefijo_lista']} {proveedor_nombre}"[:140]


# ---- Proponer ----

async def tabla(documento: str, pagina: int = 1, filas: int = 12) -> dict:
    """Las primeras filas de una página del documento tal como las leerá el sistema: sirve para decidir qué columna es cada cosa y en qué fila está la cabecera."""
    ficha, paginas = await subidas.paginas(documento)
    if isinstance(pagina, bool) or not isinstance(pagina, int) or pagina not in dict(paginas):
        raise ErrorImportacion(f"pagina debe estar entre 1 y {len(paginas)}")
    filas = min(max(int(filas), 3), 40) if isinstance(filas, int) and not isinstance(filas, bool) else 12
    todas = filas_de_pagina(dict(paginas)[pagina], ficha["formato"])
    return {"documento": ficha["id"], "nombre": ficha["nombre"], "formato": ficha["formato"], "pagina": pagina, "de": len(paginas), "filas_en_la_pagina": len(todas),
            "filas": [{"fila": i, "celdas": [c[:60] for c in f[:15]], "n_celdas": len(f)} for i, f in enumerate(todas[:filas], start=1)], "nota": subidas.AVISO_TERCEROS,
            "ayuda": "Las columnas se numeran desde 1, de izquierda a derecha. Indica a «proponer» qué columna es la referencia, el precio, etc., y en qué fila está la cabecera (fila_cabecera)."}


async def _existentes(departamento: str, doctype: str, campo: str, valores: list[str], lote: int, extra: list | None = None) -> set[str]:
    out: set[str] = set()
    for i in range(0, len(valores), 80):
        trozo = valores[i:i + 80]
        filas = await erpnext.listar(doctype, departamento, filtros=[[campo, "in", trozo]] + (extra or []), campos=[campo], limite=len(trozo) + 5)
        out |= {str(f.get(campo)) for f in filas}
    return out


async def proponer(documento: str, proveedor: dict, columnas: dict, agente: str, departamento: str, fila_cabecera: int = 1, paginas: list[int] | None = None, moneda: str | None = None,
                   iva_incluido_pct: float | None = None, vigente_desde: str | None = None, consulta_erp=None) -> dict:
    """Lee la tabla del documento con las columnas que dice el agente, la valida, comprueba contra el ERP qué existe y GUARDA la propuesta. No escribe nada en el ERP."""
    cfg = configuracion()
    moneda = str(moneda or cfg["moneda"]).upper()
    if moneda not in cfg["monedas"]:
        raise ErrorImportacion(f"moneda debe ser una de: {', '.join(cfg['monedas'])}")
    if iva_incluido_pct is not None and (isinstance(iva_incluido_pct, bool) or not isinstance(iva_incluido_pct, (int, float)) or not 0 < iva_incluido_pct < 100):
        raise ErrorImportacion("iva_incluido_pct es el IVA (p. ej. 21) si los precios del documento lo llevan incluido; si no, no lo indiques")
    if vigente_desde is not None and not (isinstance(vigente_desde, str) and RE_FECHA.match(vigente_desde)):
        raise ErrorImportacion("vigente_desde debe ser una fecha aaaa-mm-dd")
    ficha, todas = await subidas.paginas(documento)
    texto = "\n".join(t for _, t in todas)
    if paginas is not None:
        if not isinstance(paginas, list) or not all(isinstance(n, int) and not isinstance(n, bool) for n in paginas):
            raise ErrorImportacion("paginas debe ser una lista de números de página (u hoja)")
        todas = [(n, t) for n, t in todas if n in set(paginas)]
    prov, avisos_prov = validar_proveedor(proveedor, texto)
    prefijo = prefijo_proveedor(prov["nombre"])
    r = construir_lineas(todas, ficha["formato"], columnas, fila_cabecera, prefijo, iva_incluido_pct, cfg["max_lineas"])
    lista = nombre_lista(cfg, prov["nombre"])
    avisos = avisos_prov + r["avisos"]
    precios = sorted(Decimal(l["precio"]) for l in r["lineas"])
    if precios[-1] > precios[0] * 5000:
        avisos.append("Hay una diferencia enorme entre el precio más bajo y el más alto: puede haber una columna equivocada")
    existe_prov, nuevos, existentes = None, None, None
    try:
        codigos = [l["codigo"] for l in r["lineas"]]
        ya = await _existentes(departamento, "Item", "item_code", codigos, cfg["lote"])
        existentes, nuevos = len(ya), len(codigos) - len(ya)
        for l in r["lineas"]:
            l["existe"] = l["codigo"] in ya
        filtro = [["tax_id", "=", prov["nif"]]] if prov["nif"] else [["supplier_name", "=", prov["nombre"]]]
        encontrados = await erpnext.listar("Supplier", departamento, filtros=filtro, campos=["name"], limite=3)
        existe_prov = bool(encontrados)
    except Exception as e:  # noqa: BLE001 — sin ERP se propone igual, avisando de que no se ha podido comprobar
        log.warning("listas de precios: no se pudo comprobar el ERP: %s: %s", type(e).__name__, e)
        avisos.append("No se ha podido consultar el ERP para ver qué artículos y proveedor existen ya: se comprobará al aplicar")
    resumen = {"lineas": len(r["lineas"]), "rechazadas": r["n_rechazadas"], "omitidas": r["omitidas"], "articulos_existentes": existentes, "articulos_nuevos": nuevos, "proveedor_existe": existe_prov,
               "precio_min": str(precios[0]), "precio_max": str(precios[-1]), "columnas": r["columnas"], "vigente_desde": vigente_desde, "documento": ficha["nombre"]}
    async with await _conectar() as conn:
        cur = await conn.execute(
            """INSERT INTO importaciones_precios (documento_id, agente, departamento, proveedor, moneda, lista, lineas, rechazadas, avisos, resumen)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            [ficha["id"], agente, departamento, Jsonb(prov), moneda, lista, Jsonb(r["lineas"]), Jsonb(r["rechazadas"]), Jsonb(avisos), Jsonb(resumen)])
        iid = (await cur.fetchone())["id"]
    log.info("listas de precios: %s propone la importación %s (%s, %d líneas)", agente, iid, prov["nombre"], len(r["lineas"]))
    return {"importacion": iid, "proveedor": {**prov, "existe_en_el_erp": existe_prov}, "lista": lista, "moneda": moneda, **{k: v for k, v in resumen.items() if k != "documento"},
            "rechazadas_primeras": r["rechazadas"][:10], "avisos": avisos, "muestra": [{k: l[k] for k in ("ref", "desc", "precio")} for l in r["lineas"][:5]],
            "siguiente": "Si todo es correcto, propón la acción «aplicar» de esta herramienta con este número de importación: una persona la revisará y la aprobará antes de que se escriba nada en el ERP."}


# ---- Lo guardado ----

async def _cargar(iid) -> dict:
    if isinstance(iid, bool) or not isinstance(iid, int):
        raise ErrorImportacion("importacion es el número que devolvió «proponer»")
    async with await _conectar() as conn:
        cur = await conn.execute("SELECT * FROM importaciones_precios WHERE id = %s", [iid])
        f = await cur.fetchone()
    if not f:
        raise NoExiste("No existe esa importación")
    return f


async def estado(importacion: int) -> dict:
    f = await _cargar(importacion)
    return {"importacion": f["id"], "estado": f["estado"], "proveedor": f["proveedor"]["nombre"], "lista": f["lista"], "lineas": len(f["lineas"]), "resultado": f["resultado"], "avisos": f["avisos"]}


async def descartar(importacion: int) -> dict:
    async with await _conectar() as conn:
        cur = await conn.execute("UPDATE importaciones_precios SET estado = 'descartada' WHERE id = %s AND estado IN ('propuesta', 'error') RETURNING id", [importacion])
        if not await cur.fetchone():
            raise ErrorImportacion("Solo se puede descartar una importación propuesta o con error")
    return {"importacion": importacion, "estado": "descartada"}


async def vista_aplicar(importacion: int, departamento: str) -> dict:
    """Lo que ve la persona que aprueba: quién es el proveedor, qué se crea y qué se actualiza, y las primeras líneas."""
    f = await _cargar(importacion)
    if f["estado"] not in ("propuesta", "error"):
        raise ErrorImportacion(f"Esta importación está «{f['estado']}»: no se puede aplicar")
    r, p = f["resumen"], f["proveedor"]
    campos = [["Proveedor", f"{p['nombre']}" + (f" · NIF {p['nif']}" if p["nif"] else "") + (" · YA EXISTE en el ERP (solo se cargan precios)" if r.get("proveedor_existe") else " · SE DA DE ALTA como proveedor nuevo" if r.get("proveedor_existe") is False else " · (no se ha podido comprobar si existe)")],
              ["Lista de precios", f"{f['lista']} ({f['moneda']})" + (f", vigente desde {r['vigente_desde']}" if r.get("vigente_desde") else "")],
              ["Documento", r.get("documento", "")],
              ["Líneas", f"{r['lineas']} con precio · {r['rechazadas']} rechazadas · rango {r['precio_min']} – {r['precio_max']} {f['moneda']} (sin IVA)"],
              ["Artículos", "no se ha podido comprobar" if r.get("articulos_nuevos") is None else f"{r['articulos_nuevos']} nuevos (se crean) · {r['articulos_existentes']} que ya existen (solo precio)"]]
    if f["avisos"]:
        campos.append(["Avisos", "\n".join(f"- {a}" for a in f["avisos"][:8])])
    campos.append(["Primeras líneas", "\n".join(f"{l['ref']} · {l['desc'][:60]} · {l['precio']}" + ("" if l.get("existe", True) else " (nuevo)") for l in f["lineas"][:12])])
    return {"titulo": f"Cargar lista de precios de {p['nombre']} en el ERP (importación {f['id']})", "campos": campos}


# ---- Aplicar (tras la aprobación) ----

async def aplicar(importacion: int, departamento: str, ahora: date | None = None) -> dict:
    """Da de alta el proveedor, la lista, los artículos nuevos y los precios en el ERP. Solo se llega aquí tras la aprobación de una persona. Es repetible: lo que ya está no se duplica."""
    cfg = configuracion()
    async with await _conectar() as conn:
        cur = await conn.execute("UPDATE importaciones_precios SET estado = 'aplicando' WHERE id = %s AND estado IN ('propuesta', 'error') RETURNING *", [importacion])
        f = await cur.fetchone()
    if not f:
        e = await _cargar(importacion)
        raise ErrorImportacion(f"Esta importación está «{e['estado']}»: no se puede aplicar")
    res = {"proveedor": None, "proveedor_creado": False, "lista_creada": False, "articulos_creados": 0, "precios_nuevos": 0, "precios_actualizados": 0, "precios_sin_cambios": 0, "errores": []}
    try:
        p, lista, moneda, lineas = f["proveedor"], f["lista"], f["moneda"], f["lineas"]
        desde = f["resumen"].get("vigente_desde")
        filtro = [["tax_id", "=", p["nif"]]] if p["nif"] else [["supplier_name", "=", p["nombre"]]]
        encontrado = await erpnext.listar("Supplier", departamento, filtros=filtro, campos=["name"], limite=1)
        if encontrado:
            res["proveedor"] = encontrado[0]["name"]
        else:
            datos = {"supplier_name": p["nombre"], "supplier_group": cfg["supplier_group"], "supplier_type": cfg["supplier_type"], "default_currency": moneda}
            if p["nif"]:
                datos["tax_id"] = p["nif"]
            if p["email"]:
                datos["email_id"] = p["email"]
            if p["pais"]:
                datos["country"] = p["pais"]
            res["proveedor"] = (await erpnext.crear_maestro("Supplier", datos, departamento))["name"]
            res["proveedor_creado"] = True
        if not await erpnext.listar("Price List", departamento, filtros=[["name", "=", lista]], campos=["name"], limite=1):
            await erpnext.crear_maestro("Price List", {"price_list_name": lista, "currency": moneda, "enabled": 1, "buying": 1, "selling": 0}, departamento)
            res["lista_creada"] = True
        codigos = [l["codigo"] for l in lineas]
        ya = await _existentes(departamento, "Item", "item_code", codigos, cfg["lote"])
        nuevos = [l for l in lineas if l["codigo"] not in ya]
        docs = [{"item_code": l["codigo"], "item_name": l["desc"][:140], "description": l["desc"], "item_group": cfg["item_group"], "stock_uom": l["unidad"] or cfg["stock_uom"],
                 "is_stock_item": 1, "is_purchase_item": 1, "supplier_items": [{"supplier": res["proveedor"], "supplier_part_no": l["ref"]}]} for l in nuevos]
        if docs:
            res["articulos_creados"] = len(await erpnext.insertar_varios("Item", docs, departamento, cfg["lote"]))
        existentes: dict[str, tuple[str, str]] = {}
        for i in range(0, len(codigos), 80):
            trozo = codigos[i:i + 80]
            for r in await erpnext.listar("Item Price", departamento, filtros=[["price_list", "=", lista], ["item_code", "in", trozo]], campos=["name", "item_code", "price_list_rate"], limite=len(trozo) + 20):
                existentes[str(r["item_code"])] = (str(r["name"]), str(r.get("price_list_rate")))
        crear = []
        for l in lineas:
            actual = existentes.get(l["codigo"])
            if actual is None:
                d = {"item_code": l["codigo"], "price_list": lista, "buying": 1, "selling": 0, "supplier": res["proveedor"], "currency": moneda, "price_list_rate": float(l["precio"])}
                if desde:
                    d["valid_from"] = desde
                crear.append(d)
            elif abs(Decimal(actual[1] or "0") - Decimal(l["precio"])) < Decimal("0.0001"):
                res["precios_sin_cambios"] += 1
            else:
                try:
                    await erpnext.modificar("Item Price", actual[0], {"price_list_rate": float(l["precio"])}, departamento)
                    res["precios_actualizados"] += 1
                except Exception as e:  # noqa: BLE001
                    res["errores"].append(f"{l['ref'][:30]}: {type(e).__name__}")
        if crear:
            res["precios_nuevos"] = len(await erpnext.insertar_varios("Item Price", crear, departamento, cfg["lote"]))
    except Exception as e:  # noqa: BLE001 — se guarda lo hecho y el motivo; repetir `aplicar` sigue por donde se quedó
        res["errores"].append(f"{type(e).__name__}: {str(e)[:300]}")
        log.exception("listas de precios: fallo al aplicar la importación %s", importacion)
    final = "error" if res["errores"] else "aplicada"
    async with await _conectar() as conn:
        await conn.execute("UPDATE importaciones_precios SET estado = %s, resultado = %s, aplicada_en = CASE WHEN %s = 'aplicada' THEN now() ELSE aplicada_en END WHERE id = %s",
                           [final, Jsonb(res), final, importacion])
    if final == "error":
        raise ErrorImportacion("La carga no ha terminado: " + "; ".join(res["errores"][:3]) + f". Se ha guardado lo hecho ({res['articulos_creados']} artículos y {res['precios_nuevos']} precios nuevos); se puede repetir sin duplicar.")
    log.info("listas de precios: importación %s aplicada: %s", importacion, res)
    return {"importacion": importacion, "estado": "aplicada", **res}
