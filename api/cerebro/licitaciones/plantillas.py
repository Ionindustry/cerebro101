"""Documentación administrativa de una oferta: rellena las PLANTILLAS del concurso (declaración responsable, anexos, modelos…) con los datos de la sociedad que se presenta.

Los concursos traen sus propias plantillas y hay que rellenarlas tal cual. Aquí se toman los documentos del pliego que ya han pasado el antivirus (Word y PDF con formulario), se detectan sus huecos
(formularios.py) y se rellenan en una COPIA que mantiene el documento original, con datos que salen del ERP (empresa.py) y de la ficha de la licitación. Nada se inventa: cada dato rellenado lleva su
origen y lo que no se sabe queda como hueco, con el motivo, para que una persona lo complete (en el ERP, si es un dato de la empresa) antes de firmar.

Un agente puede ayudar en lo dudoso, pero solo ELIGE QUÉ DATO va en un hueco (`asignaciones`), nunca escribe el valor: el valor siempre sale del ERP o de la ficha.

Lo que sale queda LISTO PARA FIRMAR con certificado digital (p. ej. AutoFirma), que hace siempre una persona: aquí no se firma, ni se presenta, ni se declara nada en nombre de nadie."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
from pathlib import Path

from psycopg.types.json import Jsonb

from . import empresa as E
from . import formularios as F
from . import ofertas as O
from . import pliegos as P

log = logging.getLogger("cerebro.licitaciones.plantillas")

RAIZ = Path(os.environ.get("OFERTAS_DIR", "/datos/licitaciones/ofertas"))
CLAVES_LICITACION = {"licitacion.expediente": "la ficha de la licitación (número de expediente)", "licitacion.objeto": "la ficha de la licitación (título)",
                     "licitacion.organo": "la ficha de la licitación (órgano de contratación)"}
CLAVES_VALIDAS = set(E.CLAVES) | set(CLAVES_LICITACION) | {F.SIN_DATO}
MAX_PLANTILLAS = 40
RE_MODELO = re.compile(r"(?i)anexo|annex|anexe|modelo|model|declaraci|deuc|formulari|plantilla")
FORMATOS_SIN_SOPORTE = ("odt", "ods", "xlsx")
MIME = {"docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "pdf": "application/pdf"}
NOTA_FIRMA = ("Revisa cada documento y fírmalo con tu certificado digital (por ejemplo con AutoFirma). Los huecos de fecha se completan al firmar. "
              "Nada se firma ni se presenta desde aquí.")
COLS = "id, n, nombre, miembro, formato, estado, empresa, nombre_salida, sha256, bytes, campos, pendientes, avisos, asignaciones, por, creado"


class ErrorPlantilla(ValueError):
    pass


def datos_licitacion(ficha: dict) -> dict[str, dict]:
    """Los datos de la licitación que piden las plantillas (expediente, objeto, órgano), de la ficha del motor."""
    out: dict[str, dict] = {}
    origen = "Motor de licitaciones · ficha"
    for clave, valor in (("licitacion.expediente", (ficha or {}).get("expediente")), ("licitacion.objeto", (ficha or {}).get("titulo")),
                         ("licitacion.organo", ((ficha or {}).get("comprador") or {}).get("nombre"))):
        v = re.sub(r"\s+", " ", str(valor or "")).strip()[:400]
        if v:
            out[clave] = {"valor": v, "origen": origen}
    return out


def _donde(clave: str) -> str:
    return E.CLAVES.get(clave) or CLAVES_LICITACION.get(clave) or clave


def _nombre_salida(n: int, nombre: str, formato: str, sub: int | None = None) -> str:
    base = re.sub(r"\.[A-Za-z0-9]{2,5}$", "", nombre.replace("\\", "/").split("/")[-1])
    base = re.sub(r"[^\w .()\-]", "", base, flags=re.UNICODE).strip(" .")[:80] or "documento"
    return f"{n:02d}{f'.{sub:02d}' if sub else ''} - {base} (rellenado).{formato}"


def clasificar(campos: list[dict], asignaciones: dict, fuente: dict[str, dict]) -> tuple[dict[str, str], list[dict], list[dict]]:
    """Reparte los huecos de un documento: (valores que se pueden escribir, rellenados con su origen, pendientes con su motivo). Función pura.
    Pendiente «bloquea» si sin ello el documento no está listo para firmar; la fecha no bloquea (se completa al firmar) y lo opcional sin dato tampoco."""
    valores, rellenados, pendientes = {}, [], []
    for c in campos:
        fid, etiqueta = c["id"], c["etiqueta"]
        clave = asignaciones.get(fid, c.get("clave"))
        if clave not in CLAVES_VALIDAS:
            clave = None
        base = {"id": fid, "etiqueta": etiqueta, "tipo": c["tipo"], "anexo": c.get("anexo", "")}
        if c["fijo"]:
            if c["tipo"] == "casilla":
                pendientes.append({**base, "clave": None, "bloquea": True, "motivo": "Casilla: la marca una persona (es una declaración o una opción)"})
            continue
        if clave == F.SIN_DATO:
            pendientes.append({**base, "clave": clave, "bloquea": False, "motivo": "Se completa al firmar (fecha)"})
        elif clave is None:
            if not c["opcional"]:
                pendientes.append({**base, "clave": None, "bloquea": True, "motivo": "No está claro qué dato va aquí: elige uno o complétalo a mano"})
        elif clave in fuente:
            valores[fid] = fuente[clave]["valor"]
            rellenados.append({**base, "clave": clave, "valor": fuente[clave]["valor"], "origen": fuente[clave]["origen"]})
        elif not c["opcional"]:
            pendientes.append({**base, "clave": clave, "bloquea": True, "motivo": f"Falta el dato en {_donde(clave)}"})
    return valores, rellenados, pendientes


def estado_de(campos: list[dict], valores: dict, pendientes: list[dict]) -> str:
    if not campos:
        return "sin_huecos"
    if any(p["bloquea"] for p in pendientes) or not valores:
        return "faltan_datos"
    return "lista_para_firma"


async def _candidatos(motor_id: str, n: int | None) -> list[dict]:
    async with await P._conectar() as conn:
        cur = await conn.execute("SELECT id, n, nombre, formato, sha256 FROM pliegos_documentos WHERE motor_id = %s AND estado = 'limpio' AND formato IN ('docx', 'pdf', 'zip', 'odt', 'ods', 'xlsx') "
                                 + ("AND n = %s " if n else "") + "ORDER BY n, id LIMIT %s", [motor_id] + ([n] if n else []) + [MAX_PLANTILLAS])
        return await cur.fetchall()


async def _guardar(motor_id: str, doc: dict, estado: str, empresa: str, salida: str, sha: str, tam: int, rellenados, pendientes, avisos, asignaciones, por: str) -> None:
    async with await O._conectar() as conn:
        await conn.execute(
            """INSERT INTO ofertas_documentos (motor_id, documento_id, miembro, n, nombre, formato, estado, empresa, nombre_salida, sha256, bytes, campos, pendientes, avisos, asignaciones, por)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (motor_id, documento_id, miembro) DO UPDATE SET n = EXCLUDED.n, nombre = EXCLUDED.nombre, formato = EXCLUDED.formato, estado = EXCLUDED.estado, empresa = EXCLUDED.empresa,
                 nombre_salida = EXCLUDED.nombre_salida, sha256 = EXCLUDED.sha256, bytes = EXCLUDED.bytes, campos = EXCLUDED.campos, pendientes = EXCLUDED.pendientes,
                 avisos = EXCLUDED.avisos, asignaciones = EXCLUDED.asignaciones, por = EXCLUDED.por, creado = now()""",
            [motor_id, doc["id"], doc.get("miembro", ""), doc["n"], doc["nombre"], doc["formato"], estado, empresa, salida, sha, tam, Jsonb(rellenados), Jsonb(pendientes), Jsonb(avisos), Jsonb(asignaciones), por[:200]])


async def _asignaciones_previas(motor_id: str, documento_id: int, miembro: str = "") -> dict:
    async with await O._conectar() as conn:
        cur = await conn.execute("SELECT asignaciones FROM ofertas_documentos WHERE motor_id = %s AND documento_id = %s AND miembro = %s", [motor_id, documento_id, miembro])
        f = await cur.fetchone()
    return dict((f or {}).get("asignaciones") or {})


async def _procesar(motor_id: str, doc: dict, fuente: dict[str, dict], empresa: str, nuevas: dict, por: str, explicito: bool) -> dict | None:
    """Detecta y rellena UNA plantilla. None si el documento no tiene huecos y nadie lo ha pedido por su nombre (no es una plantilla: p. ej. el pliego)."""
    origen = Path(doc["ruta"]) if doc.get("ruta") else P.carpeta(motor_id, "limpio") / f"{doc['sha256']}.{doc['formato']}"
    try:
        det = await asyncio.to_thread(F.ejecutar_aislado, {"accion": "detectar", "ruta": str(origen), "formato": doc["formato"]})
    except F.ErrorFormulario as e:
        if not explicito:
            return None
        await _guardar(motor_id, doc, "error", empresa, "", "", 0, [], [], [str(e)[:300]], {}, por)
        return {"documento": doc["n"], "estado": "error", "aviso": str(e)}
    if not det["campos"] and not explicito:
        return None
    asignaciones = {**await _asignaciones_previas(motor_id, doc["id"], doc.get("miembro", "")), **{k: v for k, v in nuevas.items() if v in CLAVES_VALIDAS}}
    valores, rellenados, pendientes = clasificar(det["campos"], asignaciones, fuente)
    salida, sha, tam = "", "", 0
    if valores:
        nombre = _nombre_salida(doc["n"], doc.get("miembro") or doc["nombre"], doc["formato"], doc.get("sub"))
        destino = RAIZ / motor_id / nombre
        destino.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        await asyncio.to_thread(F.ejecutar_aislado, {"accion": "rellenar", "ruta": str(origen), "formato": doc["formato"], "destino": str(destino), "valores": valores})
        datos = destino.read_bytes()
        os.chmod(destino, 0o600)
        salida, sha, tam = nombre, hashlib.sha256(datos).hexdigest(), len(datos)
    estado = estado_de(det["campos"], valores, pendientes)
    await _guardar(motor_id, doc, estado, empresa, salida, sha, tam, rellenados, pendientes, det["avisos"], asignaciones, por)
    log.info("plantillas: %s rellena «%s» de %s con la sociedad %s → %s (%d huecos rellenados, %d pendientes)", por, doc["nombre"], motor_id, empresa, estado, len(rellenados), len(pendientes))
    return {"documento": doc["n"], "estado": estado}


async def _tratar(motor_id: str, doc: dict, fuente: dict, empresa: str, asignaciones: dict, usuario: str, explicito: bool, miembro: str | None = None) -> None:
    """Un documento del pliego: si es Word o PDF se rellena; si es un ZIP de documentación se abre y se rellena cada anexo/modelo de dentro; si es un modelo en un formato que no se rellena solo
    (odt, xlsx…) se deja constancia para que nadie lo pase por alto."""
    if doc["formato"] in ("docx", "pdf"):
        await _procesar(motor_id, doc, fuente, empresa, asignaciones, usuario, explicito)
    elif doc["formato"] == "zip":
        origen = P.carpeta(motor_id, "limpio") / f"{doc['sha256']}.zip"
        res = await asyncio.to_thread(F.ejecutar_aislado, {"accion": "extraer_zip", "ruta": str(origen), "formato": "zip", "destino": str(RAIZ / motor_id / "_zip" / doc["sha256"])})
        hechos = 0
        if miembro and miembro not in {m["miembro"] for m in res["miembros"]}:
            raise ErrorPlantilla(f"El ZIP no tiene el fichero «{miembro[:80]}» (o no es Word ni PDF)")
        for k, m in enumerate(res["miembros"], 1):
            if miembro and m["miembro"] != miembro:
                continue
            sub = {**doc, "nombre": f"{doc['nombre']} › {m['miembro']}", "miembro": m["miembro"], "formato": m["formato"], "ruta": m["ruta"], "sub": k}
            if await _procesar(motor_id, sub, fuente, empresa, asignaciones, usuario, explicito):
                hechos += 1
        if res["avisos"] and not miembro:
            pend = [{"id": f"z{i}", "etiqueta": a[:90], "tipo": "documento", "anexo": "", "clave": None, "bloquea": True, "motivo": a} for i, a in enumerate(res["avisos"][:20], 1)]
            await _guardar(motor_id, doc, "faltan_datos" if hechos else "error", empresa, "", "", 0, [], pend, res["avisos"][:20], {}, usuario)
        elif not hechos and explicito and not miembro:
            await _guardar(motor_id, doc, "sin_huecos", empresa, "", "", 0, [], [], ["El ZIP no trae ningún Word ni PDF con huecos que rellenar"], {}, usuario)
    elif explicito or RE_MODELO.search(doc["nombre"]):
        aviso = f"Este documento está en formato {doc['formato']} y no se rellena solo: hay que rellenarlo a mano o pedir la versión en Word"
        await _guardar(motor_id, doc, "error", empresa, "", "", 0, [], [], [aviso], {}, usuario)


async def preparar(motor_id: str, ficha: dict | None, usuario: str, empresa: str | None = None, n: int | None = None, asignaciones: dict | None = None, miembro: str | None = None) -> dict:
    """Rellena las plantillas del concurso (todas, o solo el documento `n`) con los datos de la sociedad elegida. Se puede repetir: rehace lo rellenado desde el original, conservando lo que
    un agente eligió para los huecos dudosos. Lanza E.VariasEmpresas si el ERP tiene varias y no se ha elegido, y NoExiste si la oferta aún no está preparada."""
    motor_id = O._id(motor_id)
    o = await O.leer(motor_id, con_contenido=False)
    if not o["existe"]:
        raise O.NoExiste("Esta licitación aún no tiene la oferta preparada")
    nombre = await E.elegir(empresa or o.get("empresa"))
    if nombre != o.get("empresa"):
        await O.fijar_empresa(motor_id, nombre)
    datos = await E.datos(nombre)
    fuente = {**datos["valores"], **datos_licitacion(ficha or {})}
    docs = await _candidatos(motor_id, n)
    if asignaciones and docs and any(d["formato"] == "zip" for d in docs) and not miembro:
        raise ErrorPlantilla("Ese documento es un ZIP con varios anexos: indica de cuál (miembro) son los huecos que eliges")
    if n and not docs:
        raise ErrorPlantilla(f"El documento {n} no está bajado y analizado: pide «descargar» primero")
    for doc in docs:
        try:
            await _tratar(motor_id, doc, fuente, nombre, asignaciones or {}, str(usuario), bool(n), miembro)
        except (F.ErrorFormulario, OSError) as e:
            log.warning("plantillas: no se ha podido rellenar «%s» de %s: %s", doc["nombre"], motor_id, e)
            await _guardar(motor_id, doc, "error", nombre, "", "", 0, [], [], [str(e)[:300]], {}, str(usuario))
    return await listar(motor_id)


def _publico(f: dict) -> dict:
    return {"id": f["id"], "documento": f["n"], "nombre": f["nombre"], "miembro": f["miembro"] or None, "formato": f["formato"], "estado": f["estado"], "empresa": f["empresa"], "fichero": f["nombre_salida"] or None,
            "bytes": f["bytes"], "rellenados": list(f["campos"] or []), "pendientes": list(f["pendientes"] or []), "avisos": list(f["avisos"] or []), "por": f["por"],
            "creado": f["creado"].isoformat()}


async def listar(motor_id: str) -> dict:
    """Las plantillas ya preparadas de la oferta, con lo rellenado (y de dónde sale cada dato) y lo que falta."""
    motor_id = O._id(motor_id)
    async with await O._conectar() as conn:
        cur = await conn.execute(f"SELECT {COLS} FROM ofertas_documentos WHERE motor_id = %s ORDER BY n, id", [motor_id])
        filas = await cur.fetchall()
        cur = await conn.execute("SELECT empresa FROM ofertas WHERE motor_id = %s", [motor_id])
        o = await cur.fetchone()
    docs = [_publico(f) for f in filas]
    return {"licitacion": motor_id, "empresa": (o or {}).get("empresa"), "documentos": docs, "nota": NOTA_FIRMA,
            "resumen": {e: sum(1 for d in docs if d["estado"] == e) for e in ("lista_para_firma", "faltan_datos", "sin_huecos", "error")}}


async def fichero(motor_id: str, doc_id: int) -> tuple[str, bytes, str]:
    """El documento rellenado, para descargarlo: (nombre, contenido, tipo). Comprueba que sea el que se generó (huella) y que esté dentro de la carpeta de la oferta."""
    motor_id = O._id(motor_id)
    async with await O._conectar() as conn:
        cur = await conn.execute("SELECT nombre_salida, sha256, formato FROM ofertas_documentos WHERE motor_id = %s AND id = %s", [motor_id, doc_id])
        f = await cur.fetchone()
    if not f or not f["nombre_salida"]:
        raise O.NoExiste("Ese documento no está preparado")
    ruta = (RAIZ / motor_id / f["nombre_salida"]).resolve()
    if ruta.parent != (RAIZ / motor_id).resolve() or not ruta.is_file():
        raise O.NoExiste("El fichero ya no está: vuelve a preparar las plantillas")
    datos = ruta.read_bytes()
    if hashlib.sha256(datos).hexdigest() != f["sha256"]:
        raise ErrorPlantilla("El fichero no coincide con el que se generó: vuelve a preparar las plantillas")
    return f["nombre_salida"], datos, MIME[f["formato"]]


async def claves_disponibles(empresa: str | None, ficha: dict | None) -> dict:
    """Qué datos hay para rellenar (con su origen) y cuáles faltan (con dónde completarlos): lo que un agente necesita para elegir qué dato va en un hueco dudoso."""
    nombre = await E.elegir(empresa)
    datos = await E.datos(nombre)
    fuente = {**datos["valores"], **datos_licitacion(ficha or {})}
    return {"empresa": nombre, "disponibles": {k: v["valor"] for k, v in fuente.items()},
            "faltan": {k: _donde(k) for k in [*E.CLAVES, *CLAVES_LICITACION] if k not in fuente}, "al_firmar": F.SIN_DATO}
