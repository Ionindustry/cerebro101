"""Consulta del radar: búsqueda con filtros, ficha con procedencia e historial, radar por categorías y «mis oportunidades». Solo lectura salvo lo que cada persona guarda para sí.

Todo lo que se devuelve son datos de fuentes oficiales (terceros): quien los muestre a un modelo debe tratarlos como datos, nunca como instrucciones.
"""
from __future__ import annotations

import re
import uuid
from datetime import date, datetime
from decimal import Decimal

import psycopg
from psycopg.rows import dict_row

from ..ajustes import ajustes
from .normalizar import ESTADOS, INSTRUMENTOS

LIMITE_MAXIMO = 100
ORDENES = {"relevancia", "plazo", "nueva", "importe"}
DIAS_NOVEDAD = 7


class ErrorConsulta(ValueError):
    """Lo que no se puede consultar; el mensaje es para la persona (o el agente)."""


def _conectar():
    return psycopg.AsyncConnection.connect(ajustes.database_url, row_factory=dict_row)


def _json(v):
    if isinstance(v, dict):
        return {k: _json(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_json(x) for x in v]
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, uuid.UUID):
        return str(v)
    return v


def _id(valor) -> str:
    try:
        return str(uuid.UUID(str(valor)))
    except ValueError:
        raise ErrorConsulta("El identificador de la oportunidad no es válido") from None


def _lista(v) -> list[str]:
    if v in (None, ""):
        return []
    return [str(x).strip() for x in (v if isinstance(v, (list, tuple)) else [v]) if str(x).strip()][:20]


_RESUMEN = ("o.id::text AS id, o.canonical_id, o.title, o.issuing_organization, o.program_name, o.country, o.region, o.province, o.geographic_scope, o.funding_type, o.total_budget, "
            "o.maximum_amount, o.currency, o.publication_date, o.opening_date, o.deadline, o.status, o.official_url, o.sector, o.eligible_beneficiaries, o.detected_at, o.last_checked_at, "
            "o.confidence_score, (o.detected_at >= now() - make_interval(days => %(dn)s)) AS is_new, "
            "EXISTS (SELECT 1 FROM funding_opportunity_changes c WHERE c.opportunity_id = o.id AND c.changed_at >= now() - make_interval(days => %(dn)s) AND c.changed_at > o.detected_at + interval '1 minute') AS has_changes")


def construir_busqueda(f: dict) -> tuple[str, dict]:
    """La consulta SQL y sus parámetros a partir de los filtros (todos opcionales). Pura: los valores nunca se concatenan al SQL."""
    where, p = [], {"dn": DIAS_NOVEDAD}
    texto = " ".join(str(f.get("texto") or "").split())[:200]
    if texto:
        where.append("o.tsv @@ websearch_to_tsquery('spanish', %(texto)s)")
        p["texto"] = texto
    for clave, col in (("pais", "o.country"), ("region", "o.region"), ("provincia", "o.province"), ("ambito", "o.geographic_scope")):
        v = _lista(f.get(clave))
        if v:
            where.append(f"lower({col}) = ANY(%({clave})s)")
            p[clave] = [x.lower() for x in v]
    org = " ".join(str(f.get("organismo") or "").split())[:120]
    if org:
        where.append("o.issuing_organization ILIKE %(org)s")
        p["org"] = f"%{org}%"
    prog = " ".join(str(f.get("programa") or "").split())[:120]
    if prog:
        where.append("o.program_name ILIKE %(prog)s")
        p["prog"] = f"%{prog}%"
    for clave, col in (("sector", "o.sector"), ("beneficiario", "o.eligible_beneficiaries"), ("tamano", "o.company_sizes")):
        v = _lista(f.get(clave))
        if v:
            where.append(f"EXISTS (SELECT 1 FROM unnest({col}) x WHERE x ILIKE ANY(%({clave})s))")
            p[clave] = [f"%{x}%" for x in v]
    inst = [x for x in _lista(f.get("instrumento")) if x in INSTRUMENTOS]
    if inst:
        where.append("o.funding_type = ANY(%(inst)s)")
        p["inst"] = inst
    est = [x.upper() for x in _lista(f.get("estado")) if x.upper() in ESTADOS]
    if est:
        where.append("o.status = ANY(%(est)s)")
        p["est"] = est
    fuente = _lista(f.get("fuente"))
    if fuente:
        where.append("EXISTS (SELECT 1 FROM funding_source_records r JOIN funding_sources s ON s.id = r.source_id WHERE r.opportunity_id = o.id AND s.source_code = ANY(%(fuente)s))")
        p["fuente"] = [x.upper() for x in fuente]
    for clave, col, op in (("importe_min", "o.total_budget", ">="), ("importe_max", "o.total_budget", "<=")):
        if f.get(clave) not in (None, ""):
            try:
                p[clave] = Decimal(str(f[clave]))
            except Exception:
                raise ErrorConsulta(f"{clave} no es un número") from None
            where.append(f"{col} {op} %({clave})s")
    for clave, col, op in (("plazo_desde", "o.deadline", ">="), ("plazo_hasta", "o.deadline", "<="), ("publicada_desde", "o.publication_date", ">=")):
        if f.get(clave):
            try:
                p[clave] = date.fromisoformat(str(f[clave])[:10])
            except ValueError:
                raise ErrorConsulta(f"{clave} debe ser una fecha AAAA-MM-DD") from None
            where.append(f"{col} {op} %({clave})s")
    if f.get("solo_nuevas"):
        where.append("o.detected_at >= now() - make_interval(days => %(dn)s)")
    orden = f.get("orden") or ("relevancia" if texto else "plazo")
    if orden not in ORDENES:
        raise ErrorConsulta(f"orden debe ser uno de: {', '.join(sorted(ORDENES))}")
    ordenar = {"relevancia": "ts_rank(o.tsv, websearch_to_tsquery('spanish', %(texto)s)) DESC, o.deadline NULLS LAST" if texto else "o.detected_at DESC",
               "plazo": "(o.deadline IS NULL), o.deadline, o.detected_at DESC", "nueva": "o.detected_at DESC", "importe": "o.total_budget DESC NULLS LAST"}[orden]
    try:
        limite = max(1, min(int(f.get("limite") or 25), LIMITE_MAXIMO))
        pagina = max(0, int(f.get("pagina") or 0))
    except (TypeError, ValueError):
        raise ErrorConsulta("limite y pagina deben ser números") from None
    p["limite"], p["salto"] = limite, pagina * limite
    donde = ("WHERE " + " AND ".join(where)) if where else ""
    return f"SELECT {_RESUMEN}, count(*) OVER () AS total FROM funding_opportunities o {donde} ORDER BY {ordenar} LIMIT %(limite)s OFFSET %(salto)s", p


async def buscar(filtros: dict) -> dict:
    sql, p = construir_busqueda(filtros or {})
    async with await _conectar() as c:
        cur = await c.execute(sql, p)
        filas = await cur.fetchall()
    total = filas[0]["total"] if filas else 0
    for f in filas:
        f.pop("total", None)
        nueva, cambiada = f.pop("is_new"), f.pop("has_changes")
        f["novedad"] = "NEW" if nueva else "UPDATED" if cambiada else None
    return {"total": total, "resultados": _json(filas)}


async def ficha(opp_id: str, usuario: str | None = None) -> dict:
    """La oportunidad completa: datos, fuentes oficiales (procedencia), documentos, historial de cambios y, si se indica la persona, lo que ella tiene guardado."""
    oid = _id(opp_id)
    async with await _conectar() as c:
        cur = await c.execute("SELECT *, id::text AS id FROM funding_opportunities WHERE id = %s", [oid])
        o = await cur.fetchone()
        if not o:
            raise ErrorConsulta("No existe esa oportunidad")
        o.pop("tsv", None)
        cur = await c.execute("SELECT s.source_code, s.source_name, s.official_url AS source_url, r.external_id, r.source_url AS record_url, r.first_seen, r.last_seen FROM funding_source_records r "
                              "JOIN funding_sources s ON s.id = r.source_id WHERE r.opportunity_id = %s ORDER BY r.first_seen", [oid])
        fuentes = await cur.fetchall()
        cur = await c.execute("SELECT title, url, doc_type, detected_at FROM funding_documents WHERE opportunity_id = %s ORDER BY detected_at", [oid])
        docs = await cur.fetchall()
        cur = await c.execute("SELECT c.changed_at, c.field, c.old_value, c.new_value, s.source_code FROM funding_opportunity_changes c LEFT JOIN funding_sources s ON s.id = c.source_id "
                              "WHERE c.opportunity_id = %s ORDER BY c.changed_at DESC, c.id DESC LIMIT 100", [oid])
        historial = await cur.fetchall()
        guardada = None
        if usuario:
            cur = await c.execute("SELECT estado, empresa, proyecto, nota FROM funding_saved_opportunities WHERE usuario = %s AND opportunity_id = %s", [usuario, oid])
            guardada = await cur.fetchone()
    return _json({**o, "fuentes": fuentes, "documentos": docs, "historial": historial, "guardada": guardada})


async def analisis(opp_id: str) -> dict:
    """De qué trata, a quién va dirigida y bases para presentarse (ver `analisis.construir`)."""
    from . import analisis as A
    return A.construir(await ficha(opp_id))


async def radar(usuario: str | None = None, limite: int = 10) -> dict:
    """Las categorías del radar: nuevas, abiertas, próximas a abrir, próximas a cerrar y modificadas, con su número y las primeras de cada una."""
    limite = max(1, min(int(limite), 50))
    consultas = {
        "nuevas": ("o.detected_at >= now() - make_interval(days => %(dn)s)", "o.detected_at DESC"),
        "abiertas": ("o.status IN ('OPEN', 'CLOSING_SOON')", "(o.deadline IS NULL), o.deadline"),
        "proximas_a_abrir": ("o.status = 'OPENING_SOON'", "o.opening_date"),
        "proximas_a_cerrar": ("o.status = 'CLOSING_SOON'", "o.deadline"),
        "modificadas": ("EXISTS (SELECT 1 FROM funding_opportunity_changes c WHERE c.opportunity_id = o.id AND c.changed_at >= now() - make_interval(days => %(dn)s) "
                        "AND c.changed_at > o.detected_at + interval '1 minute')", "o.updated_at DESC"),
    }
    salida = {}
    async with await _conectar() as c:
        for nombre, (cond, orden) in consultas.items():
            cur = await c.execute(f"SELECT {_RESUMEN}, count(*) OVER () AS total FROM funding_opportunities o WHERE {cond} ORDER BY {orden} LIMIT %(lim)s", {"dn": DIAS_NOVEDAD, "lim": limite})
            filas = await cur.fetchall()
            salida[nombre] = {"total": filas[0]["total"] if filas else 0, "oportunidades": [{k: v for k, v in f.items() if k not in ("total", "is_new", "has_changes")} for f in filas]}
        cur = await c.execute("SELECT max(last_success_at) AS u FROM funding_sources WHERE is_enabled")
        ultima = (await cur.fetchone())["u"]
    salida["relevantes_para_tu_empresa"] = {"total": 0, "oportunidades": [], "nota": "El cruce con los perfiles de empresa llega en la fase de inteligencia (matching explicable); todavía no se puntúa nada."}
    salida["ultima_sincronizacion_correcta"] = ultima
    return _json(salida)


# ---- Mis oportunidades ----

async def guardar(usuario: str, opp_id: str, estado: str = "seguida", empresa: str | None = None, proyecto: str | None = None, nota: str = "") -> dict:
    oid = _id(opp_id)
    if estado not in ("seguida", "descartada"):
        raise ErrorConsulta("estado debe ser «seguida» o «descartada»")
    async with await _conectar() as c:
        cur = await c.execute("SELECT 1 FROM funding_opportunities WHERE id = %s", [oid])
        if not await cur.fetchone():
            raise ErrorConsulta("No existe esa oportunidad")
        cur = await c.execute(
            """INSERT INTO funding_saved_opportunities (usuario, opportunity_id, estado, empresa, proyecto, nota) VALUES (%s,%s,%s,%s,%s,%s)
               ON CONFLICT (usuario, opportunity_id) DO UPDATE SET estado = EXCLUDED.estado, empresa = EXCLUDED.empresa, proyecto = EXCLUDED.proyecto, nota = EXCLUDED.nota, actualizada = now()
               RETURNING opportunity_id::text AS opportunity_id, estado, empresa, proyecto, nota""",
            [usuario, oid, estado, (empresa or "").strip()[:200] or None, (proyecto or "").strip()[:200] or None, " ".join(str(nota or "").split())[:2000]])
        return _json(await cur.fetchone())


async def quitar(usuario: str, opp_id: str) -> bool:
    async with await _conectar() as c:
        cur = await c.execute("DELETE FROM funding_saved_opportunities WHERE usuario = %s AND opportunity_id = %s", [usuario, _id(opp_id)])
        return cur.rowcount > 0


async def guardadas(usuario: str, estado: str | None = None) -> list[dict]:
    async with await _conectar() as c:
        cur = await c.execute(f"SELECT {_RESUMEN}, g.estado AS guardada, g.empresa, g.proyecto, g.nota FROM funding_saved_opportunities g JOIN funding_opportunities o ON o.id = g.opportunity_id "
                              "WHERE g.usuario = %(u)s AND (%(e)s::text IS NULL OR g.estado = %(e)s) ORDER BY g.actualizada DESC", {"u": usuario, "e": estado, "dn": DIAS_NOVEDAD})
        filas = await cur.fetchall()
    for f in filas:
        f.pop("is_new", None)
        f.pop("has_changes", None)
    return _json(filas)
