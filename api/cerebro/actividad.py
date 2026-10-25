"""Qué está haciendo cada agente en este momento, para la pestaña «Oficina» del panel.

Es solo información de estado: nunca debe frenar ni hacer fallar el trabajo del agente, así que los errores se ignoran (quedan en el log).
No se guarda el texto de la petición de la persona (puede llevar datos personales), solo qué herramienta usa el agente.
"""
from __future__ import annotations

import asyncio
import logging
import time

import psycopg

from .ajustes import ajustes

log = logging.getLogger("cerebro.actividad")
CADUCA_SEGUNDOS = 600            # un «trabajando» sin novedades en 10 minutos se da por colgado y se muestra en reposo


_FALLO = {"hasta": 0.0}          # tras un fallo de la base no se reintenta durante unos segundos: no se retrasa al agente


async def _escribir(sql: str, params: tuple) -> None:
    if time.monotonic() < _FALLO["hasta"]:
        return
    try:
        await _escribir_ya(sql, params)
    except Exception:
        _FALLO["hasta"] = time.monotonic() + 30
        raise


async def _escribir_ya(sql: str, params: tuple) -> None:
    async with await psycopg.AsyncConnection.connect(ajustes.database_url, connect_timeout=3) as c:
        await c.execute(sql, params)


async def marcar(agente: str, detalle: str, hilo: str | None = None) -> None:
    try:
        await asyncio.wait_for(_escribir(
            """INSERT INTO actividad_agentes (agente, estado, detalle, hilo, actualizado) VALUES (%s,'trabajando',%s,%s,now())
               ON CONFLICT (agente) DO UPDATE SET estado='trabajando', detalle=EXCLUDED.detalle, hilo=EXCLUDED.hilo, actualizado=now()""",
            (agente, detalle[:120], hilo)), 3)
    except Exception as e:  # noqa: BLE001
        log.debug("No se pudo marcar la actividad de %s: %s", agente, e)


async def reposo(agente: str, ultima: str | None = None) -> None:
    try:
        await asyncio.wait_for(_escribir(
            """INSERT INTO actividad_agentes (agente, estado, ultima, ultima_fecha, actualizado) VALUES (%s,'reposo',%s,now(),now())
               ON CONFLICT (agente) DO UPDATE SET estado='reposo', detalle=NULL, hilo=NULL,
                 ultima=COALESCE(EXCLUDED.ultima, actividad_agentes.ultima),
                 ultima_fecha=CASE WHEN EXCLUDED.ultima IS NULL THEN actividad_agentes.ultima_fecha ELSE now() END, actualizado=now()""",
            (agente, ultima[:120] if ultima else None)), 3)
    except Exception as e:  # noqa: BLE001
        log.debug("No se pudo marcar el reposo de %s: %s", agente, e)


async def instantanea() -> dict:
    """{agente: {estado, detalle, ultima, ultima_fecha, actualizado}} + pendientes de aprobación por agente + últimas acciones."""
    from psycopg.rows import dict_row
    async with await psycopg.AsyncConnection.connect(ajustes.database_url, row_factory=dict_row, connect_timeout=3) as c:
        act = await (await c.execute(
            """SELECT agente, CASE WHEN estado='trabajando' AND actualizado > now() - make_interval(secs => %s) THEN 'trabajando' ELSE 'reposo' END AS estado,
                      detalle, ultima, ultima_fecha, actualizado FROM actividad_agentes""", (CADUCA_SEGUNDOS,))).fetchall()
        pend = await (await c.execute("SELECT agente, count(*) AS n FROM aprobaciones WHERE estado='pendiente' GROUP BY agente")).fetchall()
        ult = await (await c.execute(
            """SELECT id, agente, herramienta, operacion, creado, (resultado LIKE 'OK%%') AS ok FROM registro_acciones
               ORDER BY id DESC LIMIT 25""")).fetchall()
    return {"actividad": {a["agente"]: a for a in act}, "pendientes": {p["agente"]: p["n"] for p in pend}, "ultimas": ult}
