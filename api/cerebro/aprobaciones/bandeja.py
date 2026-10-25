"""Persistencia de la bandeja de aprobaciones en PostgreSQL."""
from __future__ import annotations

import json
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row

from ..ajustes import ajustes
from .logica import Solicitud, decidir


def _a_solicitud(fila: dict) -> Solicitud:
    return Solicitud(id=str(fila["id"]), agente=fila["agente"], departamento=fila["departamento"],
                     accion=fila["accion"], nivel=fila["nivel"], aprobadores=tuple(fila["aprobadores"]),
                     voz_permitida=fila["voz_permitida"], datos=fila["datos"],
                     decisiones=fila["decisiones"], estado=fila["estado"])


async def crear(hilo: str, agente: str, departamento: str, accion: str, nivel: str,
                aprobadores: tuple[str, ...], voz_permitida: bool, datos: dict) -> str:
    sid = str(uuid.uuid4())
    async with await psycopg.AsyncConnection.connect(ajustes.database_url) as conn:
        await conn.execute(
            """INSERT INTO aprobaciones (id, hilo, agente, departamento, accion, nivel, aprobadores,
                                         voz_permitida, datos, decisiones, estado)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'[]','pendiente')""",
            (sid, hilo, agente, departamento, accion, nivel, list(aprobadores), voz_permitida, json.dumps(datos)))
    return sid


async def pendientes(departamentos: set[str] | None = None) -> list[dict]:
    async with await psycopg.AsyncConnection.connect(ajustes.database_url, row_factory=dict_row) as conn:
        cur = await conn.execute("SELECT * FROM aprobaciones WHERE estado='pendiente' ORDER BY creado")
        filas = await cur.fetchall()
    return [f for f in filas if not departamentos or f["departamento"] in departamentos]


async def historial(departamentos: set[str] | None = None, decision: str | None = None, texto: str | None = None,
                    limite: int = 30, pagina: int = 0, departamento: str | None = None) -> dict:
    """Solicitudes ya resueltas (aprobadas o rechazadas), de la más reciente a la más antigua, con lo que se ejecutó al aprobarlas.
    `departamentos` None = todas (dirección). `decision`: «aprobada» | «rechazada» | None. `texto` busca en la acción, el resumen y el agente.
    `departamento` filtra por uno concreto (se suma a lo que la persona puede ver)."""
    cond, params = ["a.estado IN ('aprobada','rechazada')"], []
    if departamentos is not None:
        cond.append("a.departamento = ANY(%s)")
        params.append(sorted(departamentos))
    if departamento:
        cond.append("a.departamento = %s")
        params.append(departamento)
    if decision in ("aprobada", "rechazada"):
        cond.append("a.estado = %s")
        params.append(decision)
    if texto and texto.strip():
        cond.append("(a.accion ILIKE %s OR a.agente ILIKE %s OR a.datos->>'resumen' ILIKE %s)")
        params += [f"%{texto.strip()[:80]}%"] * 3
    donde = " AND ".join(cond)
    limite = max(1, min(int(limite), 100))
    async with await psycopg.AsyncConnection.connect(ajustes.database_url, row_factory=dict_row) as conn:
        total = (await (await conn.execute(f"SELECT count(*) AS n FROM aprobaciones a WHERE {donde}", params)).fetchone())["n"]
        cur = await conn.execute(
            f"""SELECT a.*, (SELECT r.resultado FROM registro_acciones r WHERE r.aprobacion = a.id ORDER BY r.id DESC LIMIT 1) AS resultado
                FROM aprobaciones a WHERE {donde} ORDER BY a.actualizado DESC LIMIT %s OFFSET %s""",
            params + [limite, max(0, int(pagina)) * limite])
        filas = await cur.fetchall()
    return {"total": total, "pagina": max(0, int(pagina)), "limite": limite, "items": filas}


def calcular_resumen(filas: list[dict], dias: int = 30, ahora: datetime | None = None, zona: str = "Europe/Madrid") -> dict:
    """Cifras para el dashboard de Aprobaciones a partir de las solicitudes (pendientes y las resueltas en el periodo). Sin base de datos: se prueba sola.

    `filas`: departamento, agente, accion, estado, creado, actualizado. Los días se cuentan en la zona de la empresa."""
    dias = max(1, min(int(dias), 365))
    ahora = ahora or datetime.now(timezone.utc)
    z = ZoneInfo(zona)
    hoy = ahora.astimezone(z).date()
    serie = {hoy - timedelta(days=i): {"creadas": 0, "aprobadas": 0, "rechazadas": 0} for i in range(dias - 1, -1, -1)}
    pend = [f for f in filas if f["estado"] == "pendiente"]
    res = [f for f in filas if f["estado"] in ("aprobada", "rechazada")]
    por_dep_pend = Counter(f["departamento"] for f in pend)
    por_dep_res: dict[str, dict] = {}
    for f in res:
        d = por_dep_res.setdefault(f["departamento"], {"aprobadas": 0, "rechazadas": 0})
        d["aprobadas" if f["estado"] == "aprobada" else "rechazadas"] += 1
        dia = f["actualizado"].astimezone(z).date()
        if dia in serie:
            serie[dia]["aprobadas" if f["estado"] == "aprobada" else "rechazadas"] += 1
    for f in filas:
        dia = f["creado"].astimezone(z).date()
        if dia in serie:
            serie[dia]["creadas"] += 1
    esperas = [(f["actualizado"] - f["creado"]).total_seconds() / 3600 for f in res]
    aprobadas = sum(1 for f in res if f["estado"] == "aprobada")
    antigua = min((f["creado"] for f in pend), default=None)
    top = lambda campo: [{campo: k, "total": n} for k, n in Counter(f[campo] for f in filas).most_common(5)]
    return {
        "dias": dias,
        "pendientes": {"total": len(pend), "mas_antigua": antigua.isoformat() if antigua else None,
                       "espera_max_horas": round((ahora - antigua).total_seconds() / 3600, 1) if antigua else None,
                       "por_departamento": dict(por_dep_pend)},
        "resueltas": {"total": len(res), "aprobadas": aprobadas, "rechazadas": len(res) - aprobadas,
                      "tasa_aprobacion": round(aprobadas * 100 / len(res)) if res else None,
                      "tiempo_medio_horas": round(sum(esperas) / len(esperas), 1) if esperas else None,
                      "por_departamento": por_dep_res},
        "por_dia": [{"dia": d.isoformat(), **v} for d, v in serie.items()],
        "por_agente": top("agente"), "por_accion": top("accion"),
    }


async def resumen(departamentos: set[str] | None = None, dias: int = 30) -> dict:
    """Dashboard de Aprobaciones: lo pendiente ahora y lo resuelto en los últimos `dias` días. `departamentos` None = todos (dirección)."""
    dias = max(1, min(int(dias), 365))
    cond, params = "", [dias]
    if departamentos is not None:
        cond, params = "AND departamento = ANY(%s)", [dias, sorted(departamentos)]
    async with await psycopg.AsyncConnection.connect(ajustes.database_url, row_factory=dict_row) as conn:
        cur = await conn.execute(
            f"""SELECT departamento, agente, accion, estado, creado, actualizado FROM aprobaciones
                WHERE (estado = 'pendiente' OR actualizado >= now() - make_interval(days => %s)) {cond}""", params)
        filas = await cur.fetchall()
    return calcular_resumen(filas, dias, zona=ajustes.zona_horaria)


async def registrar_decision(sid: str, usuario: str, roles: set[str], departamentos: set[str],
                             aprobado: bool, canal: str, comentario: str = "") -> tuple[Solicitud, str]:
    async with await psycopg.AsyncConnection.connect(ajustes.database_url, row_factory=dict_row) as conn:
        async with conn.transaction():
            cur = await conn.execute("SELECT * FROM aprobaciones WHERE id=%s FOR UPDATE", (sid,))
            fila = await cur.fetchone()
            if fila is None:
                raise LookupError("Solicitud no encontrada")
            s = decidir(_a_solicitud(fila), usuario, roles, departamentos, aprobado, canal, comentario)
            await conn.execute("UPDATE aprobaciones SET decisiones=%s, estado=%s, actualizado=now() WHERE id=%s",
                               (json.dumps(s.decisiones), s.estado, sid))
    return s, fila["hilo"]


async def estados_del_hilo(hilo: str) -> dict[str, str]:
    """Estado de todas las solicitudes de una conversación: {id: estado}."""
    async with await psycopg.AsyncConnection.connect(ajustes.database_url) as conn:
        cur = await conn.execute("SELECT id, estado FROM aprobaciones WHERE hilo=%s", (hilo,))
        return {str(i): e for i, e in await cur.fetchall()}


async def registrar_accion(hilo: str | None, agente: str, herramienta: str, operacion: str,
                           aprobacion: str | None, resultado: str) -> None:
    """Deja constancia de una acción ejecutada (evidencia ENS / ISO 27001). La tabla es de solo anexado."""
    async with await psycopg.AsyncConnection.connect(ajustes.database_url) as conn:
        await conn.execute(
            """INSERT INTO registro_acciones (hilo, agente, herramienta, operacion, aprobacion, resultado)
               VALUES (%s,%s,%s,%s,%s,%s)""",
            (hilo, agente, herramienta, operacion, aprobacion, resultado[:4000]))
