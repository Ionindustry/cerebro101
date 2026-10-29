"""Ofertas de licitación: el borrador de la oferta de cada licitación, en sus tres sobres, dividido en secciones que los agentes redactan y las personas revisan.

Reglas (las que hacen que esto sea seguro de usar):
  - Un agente SOLO escribe BORRADORES. No puede revisar ni aprobar una sección, no puede fijar el precio, y no puede pisar lo que una persona ya editó o aprobó.
  - El precio de la oferta lo fija una PERSONA (con el simulador como ayuda). La «proposición económica» se genera sola con ese precio; mientras no haya precio, dice que está pendiente.
  - Lo que un agente cita de un pliego son ids de requisitos que existen y están CONFIRMADOS por una persona: no puede inventarse una cita.
  - Nada se presenta ni se firma desde aquí: se exporta a Word para que una persona lo revise, lo firme y lo presente. Lo no aprobado sale marcado como borrador.
  - Cada versión de una sección queda en el historial: lo que escribe un agente nunca destruye lo anterior.

El esqueleto de secciones sale del pliego (criterios de la ficha del motor y requisitos confirmados), no de una plantilla fija.
"""
from __future__ import annotations

import io
import logging
import re
import unicodedata
import zipfile
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from xml.sax.saxutils import escape

import psycopg
from psycopg.rows import dict_row

from ..ajustes import ajustes
from ..herramientas import licitaciones as motor
from . import pliegos

log = logging.getLogger("cerebro.licitaciones.ofertas")
SOBRES = ("administrativo", "tecnico", "economico")
TITULO_SOBRE = {"administrativo": "Sobre administrativo", "tecnico": "Sobre técnico (criterios de juicio de valor)", "economico": "Sobre económico"}
ESTADOS = ("vacia", "borrador", "revisada", "aprobada")
CONTENIDO_MAX = 60_000
MAX_SECCIONES = 60
MAX_CITAS = 30
RE_CLAVE = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
PROPOSICION = "proposicion-economica"
TIPOS_TECNICOS = ("criterio_juicio_valor", "tecnico", "formato_oferta", "plazo", "garantia")
TIPOS_SOLVENCIA = ("solvencia_economica", "solvencia_tecnica")
TIPOS_ADMIN = ("administrativo",) + TIPOS_SOLVENCIA
SUBJETIVOS = {"SUBJ", "JUICIO_DE_VALOR", "SUBJETIVO", "JUICIO DE VALOR"}


class ErrorOferta(ValueError):
    """Lo que no se puede hacer con la oferta; el mensaje es para quien lo pidió (persona o agente)."""


class NoExiste(LookupError):
    pass


def _conectar():
    return psycopg.AsyncConnection.connect(ajustes.database_url, row_factory=dict_row)


def _id(motor_id: str) -> str:
    if not isinstance(motor_id, str) or not motor._UUID.match(motor_id.strip()):
        raise ErrorOferta("licitacion debe ser el identificador (UUID) de la licitación")
    return motor_id.strip().lower()


def _una_linea(t, n: int) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[\x00-\x1f\x7f]", " ", str(t or ""))).strip()[:n]


def _sin_acentos(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", str(t or "").lower()) if unicodedata.category(c) != "Mn")


def _es_precio(descripcion: str) -> bool:
    d = _sin_acentos(descripcion)
    return "precio" in d or "oferta economica" in d or "proposicion economica" in d


# ---- El esqueleto, a partir del pliego (puro) ----

def _citas_texto(reqs: list[dict], limite: int = 12) -> str:
    return "\n".join(f"  [{r['id']}] {_una_linea(r['resumen'], 160)} (pág. {r['pagina']})" for r in reqs[:limite]) + ("\n  …" if len(reqs) > limite else "")


def esqueleto(ficha: dict, requisitos: list[dict]) -> list[dict]:
    """Las secciones de la oferta, de los tres sobres: [{sobre, clave, titulo, orden, guia}]. `requisitos` son los CONFIRMADOS del pliego."""
    criterios = [c for c in (ficha.get("criterios") or []) if isinstance(c, dict)]
    subj = [c for c in criterios if str(c.get("tipo") or "").upper() in SUBJETIVOS]
    auto = [c for c in criterios if c not in subj and not _es_precio(c.get("descripcion"))]
    tecnicos = [r for r in requisitos if r["tipo"] in TIPOS_TECNICOS]
    out: list[dict] = []

    def add(sobre, clave, titulo, guia=""):
        out.append({"sobre": sobre, "clave": clave, "titulo": _una_linea(titulo, 200), "orden": len([s for s in out if s["sobre"] == sobre]) + 1, "guia": guia[:4000]})

    guia = "Describe la solución propuesta de forma que cubra los requisitos técnicos del pliego."
    if tecnicos:
        guia += "\nRequisitos del pliego que debe cubrir la oferta (ids para citar):\n" + _citas_texto(tecnicos)
    add("tecnico", "descripcion-solucion", "Descripción de la solución", guia)
    for i, c in enumerate(subj[:25], 1):
        peso = c.get("peso")
        add("tecnico", f"crit-{i}", str(c.get("descripcion") or f"Criterio {i}"),
            f"Criterio de juicio de valor{f' (hasta {peso:g} puntos)' if isinstance(peso, (int, float)) else ''}: {_una_linea(c.get('descripcion'), 600)}\n"
            "Responde a este criterio con compromisos concretos y verificables; la mesa puntúa lo que se puede comprobar.")
    if not subj:
        add("tecnico", "plan-de-trabajo", "Plan de trabajo y plazos", "Fases, hitos y plazo de ejecución.")
        add("tecnico", "equipo-y-medios", "Equipo y medios", "Personal, certificaciones y medios que se dedican al contrato.")
        add("tecnico", "mantenimiento-y-garantia", "Mantenimiento y garantía", "Garantía, soporte y mantenimiento ofrecidos.")

    add("economico", PROPOSICION, "Proposición económica",
        "Se genera sola con el precio que fije una persona. Si el pliego trae un modelo oficial de proposición, úsalo en su lugar.")
    if auto:
        add("economico", "criterios-automaticos", "Criterios valorables mediante fórmula (mejoras, plazos, garantías)",
            "Compromisos que puntúan por fórmula, sin juicio de valor. Son compromisos de la empresa: los decide una persona.\n" +
            "\n".join(f"  - {_una_linea(c.get('descripcion'), 200)}" + (f" ({c['peso']:g} puntos)" if isinstance(c.get("peso"), (int, float)) else "") for c in auto[:15]))
    add("economico", "justificacion-precio", "Justificación del precio (desglose)", "Desglose de costes y justificación de que el precio es viable (útil si hay riesgo de baja anormal).")

    sol = [r for r in requisitos if r["tipo"] in TIPOS_SOLVENCIA]
    adm = [r for r in requisitos if r["tipo"] == "administrativo"]
    add("administrativo", "declaracion-responsable", "Declaración responsable / DEUC",
        "Declaración responsable de capacidad y ausencia de prohibiciones para contratar. Es una declaración que firma una persona con poder: aquí solo se prepara el texto." +
        ("\nRequisitos administrativos del pliego:\n" + _citas_texto(adm) if adm else ""))
    add("administrativo", "solvencia", "Solvencia económica y técnica",
        "Cómo se acredita la solvencia exigida, con los certificados y documentos que se aportarán." + ("\nRequisitos de solvencia:\n" + _citas_texto(sol) if sol else ""))
    add("administrativo", "otros-documentos", "Otros documentos exigidos", "Cualquier otro documento que pida el pliego para este sobre.")
    return out


# ---- Lectura ----

async def _requisitos_confirmados(motor_id: str) -> list[dict]:
    return [r for r in (await pliegos.requisitos(motor_id))["requisitos"] if r["estado"] == "confirmado"]


def _seccion(f: dict, con_contenido: bool = True, max_chars: int | None = None) -> dict:
    c = f["contenido"]
    return {"id": f["id"], "sobre": f["sobre"], "clave": f["clave"], "titulo": f["titulo"], "orden": f["orden"], "guia": f["guia"], "estado": f["estado"], "version": f["version"],
            "por": f["por"], "actualizado": f["actualizado"].isoformat() if f["actualizado"] else None, "revisado_por": f["revisado_por"],
            "revisado": f["revisado"].isoformat() if f["revisado"] else None, "citas": list(f["citas"] or []),
            "caracteres": len(c), **({"contenido": c[:max_chars] if max_chars else c} if con_contenido else {})}


def cobertura(secciones: list[dict], requisitos: list[dict]) -> dict:
    """Qué requisitos técnicos confirmados del pliego no cita ninguna sección (pueden estar sin cubrir)."""
    citados = {i for s in secciones for i in (s.get("citas") or [])}
    pedidos = [r for r in requisitos if r["tipo"] in TIPOS_TECNICOS]
    sin = [r for r in pedidos if r["id"] not in citados]
    return {"requisitos_tecnicos": len(pedidos), "sin_cubrir": [{"id": r["id"], "tipo": r["tipo"], "resumen": _una_linea(r["resumen"], 200), "pagina": r["pagina"]} for r in sin[:30]]}


async def leer(motor_id: str, con_contenido: bool = True, max_chars: int | None = None) -> dict:
    """La oferta con sus secciones, el recuento por estado y qué requisitos técnicos quedan sin cubrir. {"existe": False} si aún no se ha preparado."""
    motor_id = _id(motor_id)
    async with await _conectar() as conn:
        cur = await conn.execute("SELECT * FROM ofertas WHERE motor_id = %s", [motor_id])
        o = await cur.fetchone()
        if not o:
            return {"existe": False, "licitacion": motor_id}
        cur = await conn.execute(
            "SELECT * FROM ofertas_secciones WHERE motor_id = %s ORDER BY array_position(ARRAY['administrativo','tecnico','economico'], sobre), orden, id", [motor_id])
        filas = await cur.fetchall()
    secciones = [_seccion(f, con_contenido, max_chars) for f in filas]
    reqs = await _requisitos_confirmados(motor_id)
    return {"existe": True, "licitacion": motor_id, "precio_sin_iva": float(o["precio_sin_iva"]) if o["precio_sin_iva"] is not None else None, "iva_pct": float(o["iva_pct"]),
            "precio_por": o["precio_por"], "precio_en": o["precio_en"].isoformat() if o["precio_en"] else None, "actualizado": o["actualizado"].isoformat(),
            "secciones": secciones, "resumen": {e: sum(1 for s in secciones if s["estado"] == e) for e in ESTADOS},
            "cobertura": cobertura(secciones, reqs), "nota": pliegos.AVISO_TERCEROS}


async def plan(motor_id: str, ficha: dict, usuario: str) -> dict:
    """Prepara la oferta: crea las secciones que falten a partir del pliego (criterios de la ficha y requisitos confirmados). Es idempotente: no toca el contenido de las que ya existen,
    solo refresca su guía."""
    motor_id = _id(motor_id)
    secciones = esqueleto(ficha or {}, await _requisitos_confirmados(motor_id))
    async with await _conectar() as conn:
        await conn.execute("INSERT INTO ofertas (motor_id, creado_por) VALUES (%s, %s) ON CONFLICT (motor_id) DO NOTHING", [motor_id, str(usuario)[:200]])
        for s in secciones:
            await conn.execute(
                """INSERT INTO ofertas_secciones (motor_id, sobre, clave, titulo, orden, guia) VALUES (%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (motor_id, sobre, clave) DO UPDATE SET guia = EXCLUDED.guia""", [motor_id, s["sobre"], s["clave"], s["titulo"], s["orden"], s["guia"]])
    log.info("oferta: %s prepara la oferta de %s (%d secciones)", usuario, motor_id, len(secciones))
    return await leer(motor_id)


# ---- Escritura ----

def _decimal(v, nombre: str, minimo: float, maximo: float, incluye_minimo: bool = False) -> Decimal:
    if isinstance(v, bool) or v is None or (isinstance(v, str) and not v.strip()):
        raise ErrorOferta(f"Falta {nombre}")
    try:
        x = Decimal(str(v).strip().replace(",", "."))
    except InvalidOperation:
        raise ErrorOferta(f"{nombre} debe ser un número") from None
    if not x.is_finite() or x > Decimal(str(maximo)) or x < Decimal(str(minimo)) or (x == Decimal(str(minimo)) and not incluye_minimo):
        raise ErrorOferta(f"{nombre} debe estar entre {minimo:g} y {maximo:g}")
    return x


async def _citas_validas(conn, motor_id: str, citas) -> list[int]:
    if citas is None:
        return []
    if not isinstance(citas, list) or len(citas) > MAX_CITAS or not all(isinstance(i, int) and not isinstance(i, bool) for i in citas):
        raise ErrorOferta(f"citas: una lista de hasta {MAX_CITAS} ids de requisitos del pliego (números)")
    ids = sorted(set(citas))
    if not ids:
        return []
    cur = await conn.execute(
        """SELECT r.id FROM pliegos_requisitos r JOIN pliegos_documentos d ON d.id = r.documento_id WHERE d.motor_id = %s AND r.estado = 'confirmado' AND r.id = ANY(%s)""", [motor_id, ids])
    ok = {f["id"] for f in await cur.fetchall()}
    malos = [i for i in ids if i not in ok]
    if malos:
        raise ErrorOferta(f"citas: los requisitos {malos} no existen en el pliego de esta licitación o no están confirmados por una persona")
    return ids


async def escribir_seccion(motor_id: str, sobre: str, clave: str, contenido: str, citas=None, titulo: str | None = None, agente: str | None = None, usuario: str | None = None) -> dict:
    """Guarda el contenido de una sección. Con `agente` es un BORRADOR y tiene límites (no pisa lo editado por una persona ni lo revisado, ni la proposición económica); con `usuario`, una persona
    puede escribir siempre y la sección vuelve a «borrador» (hay que volver a revisarla)."""
    motor_id = _id(motor_id)
    if (agente is None) == (usuario is None):
        raise ErrorOferta("hace falta un autor: un agente o una persona")
    if sobre not in SOBRES:
        raise ErrorOferta("sobre debe ser uno de: " + ", ".join(SOBRES))
    if not isinstance(clave, str) or not RE_CLAVE.match(clave):
        raise ErrorOferta("clave: minúsculas, números y guiones (máximo 41 caracteres)")
    if not isinstance(contenido, str):
        raise ErrorOferta("contenido debe ser texto")
    contenido = contenido.replace("\r\n", "\n").strip()
    if len(contenido) > CONTENIDO_MAX:
        raise ErrorOferta(f"El contenido supera los {CONTENIDO_MAX} caracteres: divídelo en secciones")
    if agente is not None and clave == PROPOSICION:
        raise ErrorOferta("La proposición económica se genera sola con el precio que fije una persona: no la escribas")
    por = f"agente:{agente}" if agente else str(usuario)[:200]
    async with await _conectar() as conn:
        async with conn.transaction():
            cur = await conn.execute("SELECT 1 FROM ofertas WHERE motor_id = %s", [motor_id])
            if not await cur.fetchone():
                raise NoExiste("Esta licitación aún no tiene la oferta preparada: usa primero «plan»")
            ids = await _citas_validas(conn, motor_id, citas)
            cur = await conn.execute("SELECT * FROM ofertas_secciones WHERE motor_id = %s AND sobre = %s AND clave = %s FOR UPDATE", [motor_id, sobre, clave])
            f = await cur.fetchone()
            if f is None:
                if sobre == "economico":
                    raise ErrorOferta("En el sobre económico solo se escriben las secciones que ya trae el plan")
                if not titulo or not _una_linea(titulo, 200):
                    raise ErrorOferta("Esa sección no existe: para crearla indica un titulo")
                cur = await conn.execute("SELECT count(*) AS n FROM ofertas_secciones WHERE motor_id = %s", [motor_id])
                if (await cur.fetchone())["n"] >= MAX_SECCIONES:
                    raise ErrorOferta(f"La oferta ya tiene {MAX_SECCIONES} secciones")
                cur = await conn.execute(
                    "INSERT INTO ofertas_secciones (motor_id, sobre, clave, titulo, orden) VALUES (%s,%s,%s,%s,(SELECT coalesce(max(orden),0)+1 FROM ofertas_secciones WHERE motor_id=%s AND sobre=%s)) RETURNING *",
                    [motor_id, sobre, clave, _una_linea(titulo, 200), motor_id, sobre])
                f = await cur.fetchone()
            elif agente is not None:
                if f["estado"] in ("revisada", "aprobada"):
                    raise ErrorOferta(f"La sección «{f['titulo']}» ya está {f['estado']} por una persona: no la modifiques")
                if f["version"] > 0 and not str(f["por"]).startswith("agente:"):
                    raise ErrorOferta(f"La sección «{f['titulo']}» la ha editado una persona: no la sobrescribas")
            if f["contenido"] == contenido and ids == list(f["citas"] or []):
                return _seccion(f)                      # sin cambios: no sube la versión ni pierde la revisión
            version = f["version"] + 1
            estado = "borrador" if contenido else "vacia"
            await conn.execute("INSERT INTO ofertas_secciones_historial (seccion_id, version, contenido, por) VALUES (%s,%s,%s,%s)", [f["id"], version, contenido, por])
            cur = await conn.execute(
                """UPDATE ofertas_secciones SET contenido = %s, estado = %s, version = %s, por = %s, actualizado = now(), revisado_por = NULL, revisado = NULL, citas = %s::jsonb
                   WHERE id = %s RETURNING *""", [contenido, estado, version, por, "[" + ",".join(str(i) for i in ids) + "]", f["id"]])
            f = await cur.fetchone()
            await conn.execute("UPDATE ofertas SET actualizado = now() WHERE motor_id = %s", [motor_id])
    log.info("oferta: %s escribe %s/%s de %s (v%d, %d caracteres)", por, sobre, clave, motor_id, version, len(contenido))
    return _seccion(f)


async def revisar_seccion(seccion_id: int, estado: str, usuario: str) -> dict:
    """Una PERSONA marca una sección como revisada o aprobada (o la devuelve a borrador). El agente no tiene esta operación."""
    if estado not in ("borrador", "revisada", "aprobada"):
        raise ErrorOferta("estado debe ser borrador, revisada o aprobada")
    async with await _conectar() as conn:
        async with conn.transaction():
            cur = await conn.execute("SELECT * FROM ofertas_secciones WHERE id = %s FOR UPDATE", [seccion_id])
            f = await cur.fetchone()
            if not f:
                raise NoExiste("No existe esa sección")
            if estado != "borrador" and not f["contenido"].strip():
                raise ErrorOferta("No se puede revisar ni aprobar una sección vacía")
            if f["estado"] == "vacia" and estado != "borrador":
                raise ErrorOferta("No se puede revisar ni aprobar una sección vacía")
            cur = await conn.execute(
                "UPDATE ofertas_secciones SET estado = %s, revisado_por = %s, revisado = now() WHERE id = %s RETURNING *",
                [estado if f["contenido"].strip() else "vacia", str(usuario)[:200] if estado != "borrador" else None, seccion_id])
            f = await cur.fetchone()
            if estado == "borrador":
                await conn.execute("UPDATE ofertas_secciones SET revisado = NULL WHERE id = %s", [seccion_id])
    return _seccion(f)


async def fijar_precio(motor_id: str, precio, iva_pct, usuario: str) -> dict:
    """Una PERSONA fija el precio de la oferta (sin IVA) y el IVA. Los agentes no tienen esta operación; con el precio fijado, la proposición económica se genera sola."""
    motor_id = _id(motor_id)
    p = _decimal(precio, "El precio", 0, 1e10)
    iva = _decimal(iva_pct if iva_pct not in (None, "") else 21, "El IVA (%)", 0, 100, incluye_minimo=True)
    async with await _conectar() as conn:
        cur = await conn.execute("UPDATE ofertas SET precio_sin_iva = %s, iva_pct = %s, precio_por = %s, precio_en = now(), actualizado = now() WHERE motor_id = %s RETURNING motor_id",
                                 [p, iva, str(usuario)[:200], motor_id])
        if not await cur.fetchone():
            raise NoExiste("Esta licitación aún no tiene la oferta preparada")
    log.info("oferta: %s fija el precio de %s en %s € (IVA %s %%)", usuario, motor_id, p, iva)
    return await leer(motor_id)


async def historial(seccion_id: int) -> list[dict]:
    async with await _conectar() as conn:
        cur = await conn.execute("SELECT version, por, creado, length(contenido) AS caracteres FROM ofertas_secciones_historial WHERE seccion_id = %s ORDER BY version DESC LIMIT 50", [seccion_id])
        return [{**f, "creado": f["creado"].isoformat()} for f in await cur.fetchall()]


# ---- Word (.docx) sin dependencias: el formato es un zip de XML ----

_XML_MALO = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")
_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def _t(texto: str) -> str:
    return escape(_XML_MALO.sub("", str(texto)))


def _p(texto: str, estilo: str | None = None, negrita: bool = False, cursiva: bool = False) -> str:
    ppr = f'<w:pPr><w:pStyle w:val="{estilo}"/></w:pPr>' if estilo else ""
    rpr = ("<w:rPr>" + ("<w:b/>" if negrita else "") + ("<w:i/>" if cursiva else "") + "</w:rPr>") if (negrita or cursiva) else ""
    return f'<w:p>{ppr}<w:r>{rpr}<w:t xml:space="preserve">{_t(texto)}</w:t></w:r></w:p>'


def _tabla(filas: list[list[str]], cabecera: bool = True) -> str:
    def celda(t, neg):
        return f'<w:tc><w:tcPr><w:tcW w:w="0" w:type="auto"/></w:tcPr>{_p(t, negrita=neg)}</w:tc>'
    cuerpo = "".join("<w:tr>" + "".join(celda(c, cabecera and i == 0) for c in fila) + "</w:tr>" for i, fila in enumerate(filas))
    return f'<w:tbl><w:tblPr><w:tblStyle w:val="TableGrid"/><w:tblW w:w="0" w:type="auto"/></w:tblPr>{cuerpo}</w:tbl>' + _p("")


def _parrafos(contenido: str) -> list[str]:
    out = []
    for bloque in re.split(r"\n\s*\n", contenido.strip()):
        lineas = [l.rstrip() for l in bloque.split("\n") if l.strip()]
        if lineas and all(re.match(r"^\s*[-*•]\s+", l) for l in lineas):
            out += [_p("• " + re.sub(r"^\s*[-*•]\s+", "", l)) for l in lineas]
        else:
            out.append(_p(" ".join(l.strip() for l in lineas)))
    return out


def construir_docx(cuerpo_xml: str) -> bytes:
    estilos = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:styles {_NS}>'
               '<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Calibri"/><w:sz w:val="22"/><w:lang w:val="es-ES"/></w:rPr></w:rPrDefault>'
               '<w:pPrDefault><w:pPr><w:spacing w:after="120" w:line="276" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>'
               '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>'
               '<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="240"/></w:pPr><w:rPr><w:b/><w:sz w:val="40"/></w:rPr></w:style>'
               '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:pPr><w:keepNext/><w:spacing w:before="360" w:after="120"/><w:outlineLvl w:val="0"/></w:pPr><w:rPr><w:b/><w:sz w:val="32"/></w:rPr></w:style>'
               '<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:pPr><w:keepNext/><w:spacing w:before="240" w:after="80"/><w:outlineLvl w:val="1"/></w:pPr><w:rPr><w:b/><w:sz w:val="26"/></w:rPr></w:style>'
               '<w:style w:type="table" w:styleId="TableGrid"><w:name w:val="Table Grid"/><w:tblPr><w:tblBorders>'
               + "".join(f'<w:{l} w:val="single" w:sz="4" w:space="0" w:color="999999"/>' for l in ("top", "left", "bottom", "right", "insideH", "insideV")) +
               '</w:tblBorders></w:tblPr></w:style></w:styles>')
    documento = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {_NS}><w:body>{cuerpo_xml}'
                 '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1417" w:right="1417" w:bottom="1417" w:left="1417" w:header="708" w:footer="708" w:gutter="0"/></w:sectPr></w:body></w:document>')
    tipos = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
             '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
             '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
             '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
    rels_doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", tipos)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/document.xml", documento)
        z.writestr("word/styles.xml", estilos)
        z.writestr("word/_rels/document.xml.rels", rels_doc)
    return buf.getvalue()


def _euros(x) -> str:
    return f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " €"


def proposicion_texto(o: dict) -> str:
    """El texto de la proposición económica, con el precio que fijó una persona; sin precio, dice que falta."""
    p = o.get("precio_sin_iva")
    if p is None:
        return "[PRECIO PENDIENTE: lo tiene que fijar una persona. Hasta entonces esta proposición no se puede presentar.]"
    iva = float(o.get("iva_pct") or 0)
    cuota = round(p * iva / 100, 2)
    return (f"El licitador se compromete a ejecutar el contrato por un importe de {_euros(p)} (IVA excluido). IVA al {iva:g} %: {_euros(cuota)}. "
            f"Importe total, IVA incluido: {_euros(round(p + cuota, 2))}.")


async def exportar_docx(motor_id: str, titulo_licitacion: str = "", ahora: datetime | None = None) -> bytes:
    """El borrador de la oferta en Word. Lo no aprobado sale marcado; las secciones sin redactar, también. Incluye, en el sobre administrativo, la relación de requisitos con su cumplimiento."""
    o = await leer(motor_id)
    if not o["existe"]:
        raise NoExiste("Esta licitación aún no tiene la oferta preparada")
    ahora = (ahora or datetime.now(timezone.utc)).astimezone()
    x = [_p("Oferta" + (f": {_una_linea(titulo_licitacion, 200)}" if titulo_licitacion else ""), "Title"),
         _p(f"Borrador generado por el Cerebro el {ahora:%d/%m/%Y %H:%M}. Debe revisarlo, completarlo y firmarlo una persona con poder antes de presentarlo.", cursiva=True),
         _p("Estado de las secciones: " + ", ".join(f"{n} {e}" for e, n in o["resumen"].items() if n) + ".", cursiva=True)]
    sin = o["cobertura"]["sin_cubrir"]
    if sin:
        x.append(_p(f"Atención: {len(sin)} requisito(s) técnico(s) del pliego no están citados por ninguna sección.", negrita=True))
    for sobre in SOBRES:
        secs = [s for s in o["secciones"] if s["sobre"] == sobre]
        if not secs:
            continue
        x.append(_p(TITULO_SOBRE[sobre], "Heading1"))
        for s in secs:
            x.append(_p(s["titulo"], "Heading2"))
            if s["clave"] == PROPOSICION:
                x.append(_p(proposicion_texto(o)))
                if s["contenido"]:
                    x += _parrafos(s["contenido"])
                continue
            if s["estado"] == "vacia":
                x.append(_p("[SECCIÓN SIN REDACTAR]", negrita=True))
                continue
            if s["estado"] != "aprobada":
                x.append(_p("[BORRADOR — pendiente de revisión]" if s["estado"] == "borrador" else "[REVISADA — pendiente de aprobación]", negrita=True))
            x += _parrafos(s["contenido"])
    reqs = [r for r in await _requisitos_confirmados(_id(motor_id)) if r["tipo"] in TIPOS_ADMIN]
    if reqs:
        x.append(_p("Relación de requisitos administrativos y de solvencia", "Heading2"))
        x.append(_tabla([["Requisito", "Pliego (pág.)", "Cumplimiento"]] +
                        [[_una_linea(r["resumen"], 300), f"{r['documento']}, pág. {r['pagina']}", {"pendiente": "pendiente", "cumple": "cumple", "parcial": "parcial", "no_cumple": "NO cumple", "no_aplica": "no aplica"}.get(r["cumplimiento"], r["cumplimiento"])]
                         for r in reqs[:80]]))
    return construir_docx("".join(x))
