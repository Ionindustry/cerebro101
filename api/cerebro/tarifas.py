"""Lectura flexible de las tarifas de los proveedores (de un fabricante o de un distribuidor): Excel con varias hojas y varias tablas, o CSV.

Qué resuelve: cada proveedor entrega la tarifa a su manera. Un fabricante manda un Excel con ocho hojas, la cabecera en la fila 1, 3 o 7, columnas que se llaman «EXW CHINA», «EXW Price» o «Standard Price» según la hoja,
productos que aún no existen («TBE»), que están en fin de vida («EOL») o son muestras, y hojas que no son productos. Un distribuidor manda un CSV con el precio como «17,50 €», las categorías en jerarquía y las
características técnicas en JSON. Esta pieza lo lleva todo a UNA forma común, sin modelo de IA: lo que sale de cada fila sale del documento tal cual.

Es PURA (sin base de datos ni red): recibe los bytes y devuelve productos, hojas leídas u omitidas y avisos. Qué es cada fichero se decide por su CONTENIDO, no por la extensión. El Excel es un documento de terceros:
quien la llame desde el sistema debe hacerlo en un proceso aparte con límites, como el lector de pliegos (cerebro/licitaciones/pliegos.py → extractor).

Lo que NO hace (a propósito): no decide el coste con el que se calcula un precio (eso es de cada canal de compra), no convierte monedas, no descuenta IVA y no crea nada en el ERP.
"""
from __future__ import annotations

import csv
import io
import json
import re
import unicodedata
import zipfile
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

MAX_FILAS = 60_000
MAX_HOJAS = 40
MAX_TEXTO = 500
MAX_ESPECIFICACIONES = 40
MAX_JSON = 30_000

# Nombres con los que aparece cada dato en las tarifas, normalizados (sin tildes, en minúsculas, sin signos). Gana el primero que esté en la cabecera.
SINONIMOS = {
    "referencia": ["order model name", "reference", "referencia", "ref", "model", "modelo", "part number", "part no", "codigo", "sku", "material code", "main model name"],
    "codigo_proveedor": ["material code", "codigo proveedor", "supplier code", "codigo interno"],
    "referencia_fabricante": ["main model name", "reference", "referencia fabricante", "model", "modelo"],
    "descripcion": ["product name", "nombre", "name", "descripcion", "description", "producto", "denominacion", "articulo", "item"],
    "coste": ["exw china", "exw price", "exw", "standard price", "precio coste", "coste", "cost", "dealer price", "net price", "precio neto", "precio distribuidor", "price", "precio", "tarifa"],
    "pvp_recomendado": ["msrp price", "msrp", "rrp", "pvp", "pvpr", "precio recomendado", "precio publico", "retail price"],
    "stock": ["stock", "existencias", "disponible", "disponibilidad", "inventory", "qty", "cantidad disponible"],
    "familia": ["categories", "categorias", "categoria", "familia", "family", "series", "serie", "gama", "grupo"],
    "estado": ["production status", "estado", "status", "situacion"],
    "ean": ["ean", "ean13", "gtin", "upc", "codigo de barras"],
    "marca": ["brand", "marca", "fabricante", "manufacturer"],
    "especificaciones": ["specs", "especificaciones", "caracteristicas", "características tecnicas", "caracteristicas tecnicas"],
}
# Columnas que son imágenes o enlaces: no son una característica del producto
IGNORAR_COMO_ESPECIFICACION = ("img", "image", "picture", "pictures", "imagen", "foto", "photo", "link", "url")
ESTADOS = (("mp", "disponible"), ("new", "disponible"), ("tbe", "proximamente"), ("eol", "fin_de_vida"), ("sample", "muestra"), ("discontinued", "fin_de_vida"),
           ("descatalogado", "fin_de_vida"), ("proximamente", "proximamente"), ("activo", "disponible"), ("active", "disponible"))


class ErrorTarifa(ValueError):
    """Lo que el fichero no admite; el mensaje es para la persona."""


@dataclass
class Producto:
    hoja: str
    fila: int
    referencia: str
    descripcion: str = ""
    coste: Decimal | None = None
    pvp_recomendado: Decimal | None = None
    stock: Decimal | None = None
    familia: str = ""
    categorias: list[str] = field(default_factory=list)
    estado: str = ""                              # disponible | proximamente | fin_de_vida | muestra | "" (no consta)
    estado_original: str = ""
    ean: str = ""
    marca: str = ""
    referencia_fabricante: str = ""
    codigo_proveedor: str = ""                    # el código interno del proveedor (p. ej. «Material Code»), distinto de la referencia del fabricante
    linea: str = ""                               # la hoja (o el fichero) de donde sale: sirve de familia cuando la tarifa no trae una
    especificaciones: dict = field(default_factory=dict)
    moneda: str = ""                              # solo si el propio fichero la dice (€, $, EUR, USD…)
    avisos: list[str] = field(default_factory=list)


@dataclass
class Tarifa:
    formato: str
    productos: list[Producto] = field(default_factory=list)
    hojas: list[dict] = field(default_factory=list)      # {"hoja", "estado": leida|omitida, "motivo", "productos", "filas_sin_precio"}
    avisos: list[str] = field(default_factory=list)


def norm(t) -> str:
    t = unicodedata.normalize("NFKD", str(t if t is not None else "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", t)).strip()


def _texto(v, n: int = MAX_TEXTO) -> str:
    if v is None:
        return ""
    t = re.sub(r"[ \t]+", " ", str(v).replace("\xa0", " ")).strip()
    return t[:n]


def _una_linea(v, n: int = MAX_TEXTO) -> str:
    return re.sub(r"\s*\n\s*", " · ", _texto(v, n * 2)).strip(" ·")[:n]


def numero(valor) -> tuple[Decimal | None, str]:
    """(importe, moneda) de «17,50 €», «3.145,00 €», «1,234.50», 247.5, «$ 1,200»… o (None, "") si no es un número claro. Un valor como «1.234» es ambiguo: se toma como miles solo si va con 3 dígitos tras el punto."""
    if valor is None or isinstance(valor, bool):
        return None, ""
    if isinstance(valor, (int, float, Decimal)):
        d = Decimal(str(valor))
        return (d, "") if d.is_finite() else (None, "")
    t = str(valor).replace("\xa0", " ").strip()
    moneda = "EUR" if re.search(r"€|\beur\b", t, re.I) else "USD" if re.search(r"\$|\busd\b", t, re.I) else "GBP" if re.search(r"£|\bgbp\b", t, re.I) else ""
    s = re.sub(r"[€$£\s]|eur|usd|gbp", "", t, flags=re.I)
    if not re.fullmatch(r"-?[\d.,]+", s) or not re.search(r"\d", s):
        return None, ""
    if "," in s and "." in s:
        dec = "," if s.rfind(",") > s.rfind(".") else "."
        s = s.replace("." if dec == "," else ",", "").replace(dec, ".")
    elif "," in s or "." in s:
        sep = "," if "," in s else "."
        partes = s.split(sep)
        if len(partes) > 2:
            s = "".join(partes)
        elif len(partes[1]) != 3:
            s = f"{partes[0]}.{partes[1]}"
        elif sep == "." or moneda in ("USD", "GBP"):    # «1.234» (miles en castellano) o «$ 1,200» (miles en inglés)
            s = "".join(partes)
        else:                                   # «1,234 €»: decimales con tres cifras (muy raro, pero es lo que dice la coma)
            s = f"{partes[0]}.{partes[1]}"
    try:
        d = Decimal(s)
    except InvalidOperation:
        return None, ""
    return (d, moneda) if d.is_finite() else (None, "")


def estado_de(valor) -> tuple[str, str]:
    original = _una_linea(valor, 40)
    n = norm(original)
    for clave, estado in ESTADOS:
        if n == clave or n.startswith(clave + " "):
            return estado, original
    return "", original


def _columnas(cabecera: list[str]) -> dict[str, int]:
    """Qué columna es cada dato, por los nombres de la cabecera (normalizados). Cada columna se usa para un solo dato, salvo «referencia_fabricante» (puede compartir la del modelo)."""
    ncab = [norm(c) for c in cabecera]
    mapa: dict[str, int] = {}
    usadas: set[int] = set()
    for campo, nombres in SINONIMOS.items():
        for nombre in nombres:
            if nombre in ncab:
                i = ncab.index(nombre)
                if i in usadas and campo != "referencia_fabricante":
                    continue
                mapa[campo] = i
                if campo != "referencia_fabricante":
                    usadas.add(i)
                break
    return mapa


def _es_cabecera(fila: list[str]) -> bool:
    """Una fila es cabecera si trae nombres de un dato de referencia Y de un precio, y es sobre todo texto (no números)."""
    llenas = [c for c in fila if c.strip()]
    if len(llenas) < 2 or sum(1 for c in llenas if numero(c)[0] is not None) > len(llenas) // 3:
        return False
    m = _columnas(fila)
    return "referencia" in m and "coste" in m


def _especificaciones(fila: list[str], cabecera: list[str], mapa: dict[str, int]) -> dict:
    """Las columnas que no son ningún dato conocido son características técnicas: «Resolution: 2MP 1920*1080»."""
    centrales = set(mapa.values())
    out: dict[str, str] = {}
    for i, c in enumerate(cabecera):
        if i in centrales or i >= len(fila) or not c.strip():
            continue
        nc = norm(c)
        if any(nc == k or nc.startswith(k) for k in IGNORAR_COMO_ESPECIFICACION):
            continue
        v = _una_linea(fila[i], 200)
        if not v or v.lower() in ("n/a", "na", "-", "—", "none") or v.startswith("=DISPIMG"):
            continue
        out[_una_linea(c, 60)] = v
        if len(out) >= MAX_ESPECIFICACIONES:
            break
    return out


def _json_a_texto(s: str) -> dict:
    """Las características que algunos distribuidores dan como JSON anidado, aplanadas a «Sección · dato: valor»."""
    if not s or len(s) > MAX_JSON:
        return {}
    try:
        d = json.loads(s)
    except ValueError:
        return {}
    out: dict[str, str] = {}

    def recorre(nodo, camino):
        if len(out) >= MAX_ESPECIFICACIONES:
            return
        if isinstance(nodo, dict):
            for k, v in nodo.items():
                recorre(v, camino + [str(k)])
        elif isinstance(nodo, list):
            for v in nodo:
                recorre(v, camino)
        elif nodo not in (None, ""):
            out[_una_linea(" · ".join(camino[:-1] + [camino[-1]]) if len(camino) < 2 else f"{camino[0]} · {camino[-1]}", 100)] = _una_linea(nodo, 200)
    recorre(d, [])
    return out


def _producto(hoja: str, n: int, fila: list[str], cabecera: list[str], mapa: dict[str, int]) -> tuple[Producto | None, str]:
    def celda(campo):
        i = mapa.get(campo)
        return fila[i] if i is not None and i < len(fila) else ""
    ref = _una_linea(celda("referencia"), 120)
    if not ref:
        return None, "sin referencia"
    coste, moneda = numero(celda("coste"))
    if coste is None:
        return None, "sin precio"
    if coste <= 0 or coste > Decimal("100000000"):
        return None, "precio fuera de lo razonable"
    p = Producto(hoja=hoja, fila=n, referencia=ref, coste=coste, moneda=moneda)
    p.descripcion = _una_linea(celda("descripcion"), 300)
    p.referencia_fabricante = _una_linea(celda("referencia_fabricante"), 120)
    p.codigo_proveedor = _una_linea(celda("codigo_proveedor"), 80)
    p.linea = hoja
    pvp, m2 = numero(celda("pvp_recomendado"))
    p.pvp_recomendado = pvp if pvp and pvp > 0 else None
    p.moneda = p.moneda or m2
    p.stock = numero(celda("stock"))[0]
    p.estado, p.estado_original = estado_de(celda("estado"))
    p.ean = re.sub(r"\D", "", _texto(celda("ean"), 20))[:14]
    p.marca = _una_linea(celda("marca"), 60)
    cats = [c.strip() for c in re.split(r",\s*(?=[^,]*)", _texto(celda("familia"), 400)) if c.strip()]
    p.categorias = cats[:10]
    p.familia = (cats[0].split(" / ")[0].strip() if cats else "")
    esp = _especificaciones(fila, cabecera, mapa)
    esp.update(_json_a_texto(_texto(celda("especificaciones"), MAX_JSON + 1)))
    p.especificaciones = esp
    if p.pvp_recomendado and p.coste > p.pvp_recomendado:
        p.avisos.append("el coste es mayor que el precio recomendado: revisa las columnas")
    return p, ""


def _leer_filas(hoja: str, filas, t: Tarifa, contador: list[int]) -> None:
    """Recorre las filas de UNA hoja: busca la cabecera (en la fila que sea), lee los productos y, si aparece otra cabecera más abajo (otra tabla), cambia de columnas."""
    cabecera: list[str] | None = None
    mapa: dict[str, int] = {}
    leidos = sin_precio = 0
    for n, fila in enumerate(filas, start=1):
        contador[0] += 1
        if contador[0] > MAX_FILAS:
            t.avisos.append(f"Se ha llegado al máximo de {MAX_FILAS} filas: el resto no se lee")
            break
        celdas = [_texto(c, MAX_JSON + 1) if not isinstance(c, (int, float, Decimal)) else c for c in fila]   # cada dato se recorta luego a su medida; el JSON de características necesita entero
        celdas_txt = [str(c) if c is not None else "" for c in celdas]
        if not any(c.strip() for c in celdas_txt):
            continue
        if _es_cabecera(celdas_txt):
            cabecera, mapa = celdas_txt, _columnas(celdas_txt)
            continue
        if not cabecera:
            continue
        crudo = [c if isinstance(c, (int, float, Decimal)) else (c or "") for c in celdas]
        p, motivo = _producto(hoja, n, [x for x in crudo], cabecera, mapa)
        if p:
            t.productos.append(p)
            leidos += 1
        elif motivo == "sin precio":
            sin_precio += 1
    estado = "leida" if leidos else "omitida"
    t.hojas.append({"hoja": hoja, "estado": estado, "productos": leidos, "filas_sin_precio": sin_precio,
                    "motivo": "" if leidos else ("no se ha encontrado una cabecera con referencia y precio" if cabecera is None else "no hay filas con referencia y precio")})


def _leer_xlsx(datos: bytes, t: Tarifa) -> None:
    import openpyxl
    try:
        wb = openpyxl.load_workbook(io.BytesIO(datos), read_only=True, data_only=True)
    except Exception as e:      # noqa: BLE001 — un Excel dañado o cifrado
        raise ErrorTarifa("No se ha podido abrir el Excel: está dañado o protegido con contraseña") from e
    contador = [0]
    for ws in wb.worksheets[:MAX_HOJAS]:
        if getattr(ws, "sheet_state", "visible") != "visible":
            t.hojas.append({"hoja": ws.title, "estado": "omitida", "productos": 0, "filas_sin_precio": 0, "motivo": "hoja oculta"})
            continue
        _leer_filas(ws.title, ws.iter_rows(values_only=True), t, contador)
        if contador[0] > MAX_FILAS:
            break
    if len(wb.worksheets) > MAX_HOJAS:
        t.avisos.append(f"El Excel tiene más de {MAX_HOJAS} hojas: solo se leen las primeras")


def _texto_csv(datos: bytes) -> str:
    for cod in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return datos.decode(cod)
        except UnicodeDecodeError:
            continue
    return datos.decode("utf-8", "replace")


def _leer_csv(datos: bytes, t: Tarifa, nombre_hoja: str = "CSV") -> None:
    txt = _texto_csv(datos)
    muestra = txt[:20000]
    try:
        delim = csv.Sniffer().sniff(muestra, delimiters=",;\t|").delimiter
    except csv.Error:
        delim = ";" if muestra.count(";") > muestra.count(",") else ","
    csv.field_size_limit(MAX_JSON * 2)
    _leer_filas(nombre_hoja, csv.reader(io.StringIO(txt), delimiter=delim), t, [0])


def leer(datos: bytes, nombre: str = "", moneda: str = "") -> Tarifa:
    """Lee una tarifa (Excel .xlsx o CSV/texto) y devuelve sus productos normalizados. `moneda` es la del proveedor (un fabricante que trabaja en dólares, USD; uno que trabaja en euros, EUR) y se aplica a los precios
    cuyo fichero no la dice; si el fichero la dice y es otra, queda un aviso. Los precios se entienden SIN IVA (el IVA va aparte). Por el CONTENIDO: un Excel es un ZIP con [Content_Types].xml; HTML, PDF y ejecutables se rechazan (el PDF tiene otro camino)."""
    if not datos:
        raise ErrorTarifa("El fichero está vacío")
    cabeza = datos[:8].lstrip()
    if datos[:4] == b"PK\x03\x04":
        try:
            with zipfile.ZipFile(io.BytesIO(datos)) as z:
                if "[Content_Types].xml" not in z.namelist() or not any(n.startswith("xl/") for n in z.namelist()):
                    raise ErrorTarifa("El ZIP no es un Excel (.xlsx)")
        except zipfile.BadZipFile as e:
            raise ErrorTarifa("El fichero está dañado") from e
        t = Tarifa(formato="xlsx")
        _leer_xlsx(datos, t)
    elif datos[:5] == b"%PDF-":
        raise ErrorTarifa("Es un PDF: las tarifas en PDF se leen por otro camino (menos fiable); si puedes, pide al proveedor el Excel o el CSV")
    elif datos[:2] == b"MZ" or datos[:4] == b"\x7fELF" or cabeza[:1] == b"<" or datos[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        raise ErrorTarifa("El fichero no es un Excel (.xlsx) ni un CSV. Si es un Excel antiguo (.xls), guárdalo como .xlsx")
    else:
        t = Tarifa(formato="csv")
        _leer_csv(datos, t)
    if not t.productos:
        raise ErrorTarifa("No se ha encontrado ninguna tabla con referencia y precio: comprueba que el fichero es una tarifa y que la cabecera tiene columnas de referencia y de precio")
    moneda = moneda.upper().strip()
    if moneda:
        distintas = 0
        for p in t.productos:
            if p.moneda and p.moneda != moneda:
                distintas += 1
            p.moneda = p.moneda or moneda
        if distintas:
            t.avisos.append(f"{distintas} precios traen una moneda distinta de la del proveedor ({moneda}): revísalo")
    _avisos_generales(t)
    return t


def _avisos_generales(t: Tarifa) -> None:
    n = len(t.productos)
    no_disp = sum(1 for p in t.productos if p.estado in ("proximamente", "fin_de_vida", "muestra"))
    if no_disp:
        t.avisos.append(f"{no_disp} de {n} productos no están disponibles todavía o ya no se fabrican (próximamente, fin de vida o muestra): no se deben ofrecer como disponibles")
    monedas = {p.moneda for p in t.productos if p.moneda}
    if not monedas:
        t.avisos.append("El fichero no dice la moneda de los precios: hay que indicarla antes de calcular nada")
    elif len(monedas) > 1:
        t.avisos.append("El fichero mezcla monedas (" + ", ".join(sorted(monedas)) + "): hay que revisarlo")
    refs: dict[str, int] = {}
    for p in t.productos:
        refs[p.referencia.upper()] = refs.get(p.referencia.upper(), 0) + 1
    dup = sum(1 for v in refs.values() if v > 1)
    if dup:
        t.avisos.append(f"{dup} referencias aparecen más de una vez (en hojas distintas o repetidas): revisa cuál vale")
