"""Constancia de las acciones ejecutadas (registro_acciones) con garantías: reintento, cola local y alerta.

Una acción aprobada se ejecuta aunque la base de datos falle justo después; lo que no puede pasar es que no quede rastro.
1. Se reintenta la escritura (la base puede estar reiniciándose).
2. Si sigue fallando, la fila se guarda en un fichero local de solo anexado (`/datos/constancia_pendiente.jsonl`, permisos 0600).
3. Se avisa: log CRITICAL, observación en Langfuse con nivel ERROR, aviso en la respuesta de la acción y `/salud/constancia`
   en 503 mientras haya filas sin volcar (para que la monitorización dispare la alerta).
4. `volcar_pendientes()` las pasa a la base al arrancar y cada pocos minutos (tarea de Celery), conservando la hora original.
"""
from __future__ import annotations

import asyncio
import fcntl
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import psycopg

from .ajustes import ajustes
from .observabilidad import generacion

log = logging.getLogger("cerebro.constancia")
REINTENTOS = (0.5, 1.5)          # esperas entre intentos
ESTADO = {"fallos": 0, "ultimo_fallo": None}


def _fichero() -> Path:
    return Path(os.environ.get("CEREBRO_DATOS", "/datos")) / "constancia_pendiente.jsonl"


async def _insertar(f: dict) -> None:
    async with await psycopg.AsyncConnection.connect(ajustes.database_url, connect_timeout=5) as conn:
        await conn.execute(
            """INSERT INTO registro_acciones (hilo, agente, herramienta, operacion, aprobacion, resultado, creado)
               VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (f["hilo"], f["agente"], f["herramienta"], f["operacion"], f["aprobacion"], f["resultado"][:4000], f["creado"]))


def _guardar_local(f: dict) -> bool:
    try:
        ruta = _fichero()
        ruta.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(ruta, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            fh.write(json.dumps(f, ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        return True
    except OSError:
        log.exception("No se pudo guardar la constancia en el fichero local")
        return False


def pendientes() -> int:
    try:
        with open(_fichero(), encoding="utf-8") as fh:
            return sum(1 for linea in fh if linea.strip())
    except FileNotFoundError:
        return 0


async def dejar_constancia(hilo: str | None, agente: str, herramienta: str, operacion: str,
                           aprobacion: str | None, resultado: str) -> str:
    """Devuelve «ok», «en_cola» (guardada en local, pendiente de volcar) o «perdida» (no se pudo guardar en ningún sitio)."""
    f = {"hilo": hilo, "agente": agente, "herramienta": herramienta, "operacion": operacion, "aprobacion": aprobacion,
         "resultado": resultado[:4000], "creado": datetime.now(timezone.utc).isoformat()}
    error: Exception | None = None
    for espera in (*REINTENTOS, None):
        try:
            await _insertar(f)
            return "ok"
        except Exception as e:  # noqa: BLE001
            error = e
            if espera is not None:
                await asyncio.sleep(espera)
    estado = "en_cola" if _guardar_local(f) else "perdida"
    ESTADO["fallos"] += 1
    ESTADO["ultimo_fallo"] = f["creado"]
    log.critical("FALLO DE CONSTANCIA (%s): la acción %s.%s del agente %s (aprobación %s) se ejecutó y no consta en registro_acciones: %s",
                 estado, herramienta, operacion, agente, aprobacion, error)
    with generacion("constancia:fallo", None, {"herramienta": herramienta, "operacion": operacion, "estado": estado},
                    tipo="span", agente=agente, aprobacion=aprobacion) as obs:
        if obs is not None:
            try:
                obs.update(level="ERROR", status_message=f"Acción ejecutada sin constancia ({estado}): {type(error).__name__}"[:300])
            except Exception:  # noqa: BLE001
                pass
    return estado


async def volcar_pendientes() -> dict:
    """Pasa a la base las filas guardadas en local. Lo que siga fallando se conserva para el próximo intento."""
    ruta = _fichero()
    if not ruta.exists():
        return {"volcadas": 0, "quedan": 0}
    with open(ruta, "r+", encoding="utf-8") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        filas = [json.loads(linea) for linea in fh if linea.strip()]
        quedan, volcadas = [], 0
        for f in filas:
            try:
                await _insertar(f)
                volcadas += 1
            except Exception as e:  # noqa: BLE001
                quedan.append(f)
                log.warning("Sigue sin poder volcarse la constancia pendiente: %s", e)
        fh.seek(0)
        fh.truncate()
        for f in quedan:
            fh.write(json.dumps(f, ensure_ascii=False) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    if volcadas:
        log.warning("Constancia pendiente volcada a registro_acciones: %d fila(s); quedan %d", volcadas, len(quedan))
    return {"volcadas": volcadas, "quedan": len(quedan)}
