"""Vigilancia del antivirus (ClamAV): firmas al día y servicio en marcha.

Los pliegos y los documentos que se suben a Jarvis solo se aceptan si el antivirus los analiza con firmas de menos de `firmas_max_horas` (48 h; pliegos.py: falla cerrado). Si `freshclam` deja de actualizar
(p. ej. el DNS de Docker falló al encender el PC), el sistema empieza a rechazar documentos y nadie se entera hasta que algo falla. Aquí se mira ANTES: cada 3 horas (tarea `vigilar_antivirus`) se pregunta a clamd por
su versión y, si las firmas tienen más de `HORAS_AVISO` (36) horas o clamd no responde, se avisa a soporte@ (una vez cada 24 h por problema). La tarjeta de Jarvis (pantalla Agentes) lo enseña con `estado()`. Sin IA.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

import psycopg
from psycopg.rows import dict_row

from .ajustes import ajustes
from .licitaciones import pliegos

log = logging.getLogger("cerebro.antivirus")
HORAS_AVISO = 36        # firmas más viejas que esto: se avisa (el límite duro de rechazo es pliegos.firmas_max_horas = 48)
REPETIR_AVISO_H = 24


def fecha_firmas(version: str) -> datetime | None:
    """«ClamAV 1.4.6/28173/Tue Nov  3 06:27:52 2026» → la fecha de las firmas (UTC), o None si no se puede leer."""
    try:
        return datetime.strptime(str(version).strip("\x00 \n").rsplit("/", 1)[-1], "%a %b %d %H:%M:%S %Y").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


async def _version_de_clamd() -> str:
    host, puerto = os.environ.get("CLAMD_HOST", "clamav"), int(os.environ.get("CLAMD_PORT", "3310"))
    return await pliegos._orden(host, puerto, b"zVERSION\0", timeout=20)


async def estado(ahora: datetime | None = None, consultar=None, limite_h: int | None = None) -> dict:
    """{"estado": «ok»|«viejas»|«no_responde», "version", "fecha_firmas", "edad_horas", "aviso_horas", "limite_horas", "motivo"}. `viejas` = más de HORAS_AVISO horas (aún se aceptan documentos hasta el límite)."""
    ahora = ahora or datetime.now(timezone.utc)
    limite = limite_h or pliegos.configuracion()["firmas_max_horas"]
    base = {"aviso_horas": HORAS_AVISO, "limite_horas": limite}
    try:
        version = await (consultar or _version_de_clamd)()
    except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError) as e:
        return {**base, "estado": "no_responde", "version": None, "fecha_firmas": None, "edad_horas": None, "motivo": f"El antivirus no responde ({type(e).__name__}): los documentos quedan en cuarentena"}
    version = str(version).strip("\x00 \n")
    f = fecha_firmas(version)
    if f is None:
        return {**base, "estado": "viejas", "version": version[:80], "fecha_firmas": None, "edad_horas": None, "motivo": "No se puede leer la fecha de las firmas: se trata como vieja"}
    edad = (ahora - f).total_seconds() / 3600
    if edad > HORAS_AVISO:
        motivo = f"Las firmas del antivirus tienen {edad:.0f} horas" + (f": ya se rechazan los documentos (el límite es {limite} h)" if edad > limite else f": a las {limite} h se empezarán a rechazar los documentos")
        return {**base, "estado": "viejas", "version": version[:80], "fecha_firmas": f.isoformat(), "edad_horas": round(edad, 1), "motivo": motivo}
    return {**base, "estado": "ok", "version": version[:80], "fecha_firmas": f.isoformat(), "edad_horas": round(edad, 1), "motivo": ""}


def _conectar():
    return psycopg.AsyncConnection.connect(ajustes.database_url, row_factory=dict_row)


async def vigilar(enviar=None, ahora: datetime | None = None, consultar=None) -> dict:
    """Una pasada: avisa a soporte@ si hay problema y no se avisó ya en las últimas 24 h. Devuelve {"estado": «ok»|«avisado»|«ya_avisado»|«sin_destinatarios»|«error_correo», "antivirus": estado}."""
    ahora = ahora or datetime.now(timezone.utc)
    e = await estado(ahora, consultar)
    if e["estado"] == "ok":
        return {"estado": "ok", "antivirus": e["estado"]}
    clave = "antivirus"
    async with await _conectar() as conn:
        cur = await conn.execute("SELECT avisado_en FROM vigilancia_avisos WHERE clave = %s", [clave])
        previo = await cur.fetchone()
    if previo and ahora - previo["avisado_en"] < timedelta(hours=REPETIR_AVISO_H):
        return {"estado": "ya_avisado", "antivirus": e["estado"]}
    from . import avisar_soporte
    asunto = "Antivirus: las firmas están viejas" if e["estado"] == "viejas" else "Antivirus: no responde"
    cuerpo = (f"{e['motivo']}.\n\nMientras siga así, los documentos que se suban a Jarvis y los pliegos de las licitaciones se rechazan o quedan en cuarentena.\n\nQué hacer, en el servidor:\n"
              "  docker compose logs --tail 30 clamav\n  docker compose exec clamav sh -c \"getent hosts database.clamav.net\"   (si no sale nada, es el DNS de Docker)\n"
              "  docker compose exec clamav freshclam --log=/tmp/freshclam.log\n  docker compose exec clamav clamdscan --reload\n  docker compose restart clamav")
    ok, mal = avisar_soporte.avisar(asunto, cuerpo, enviar)
    if not ok and not mal:
        return {"estado": "sin_destinatarios", "antivirus": e["estado"]}
    if mal and not ok:
        return {"estado": "error_correo", "antivirus": e["estado"]}
    async with await _conectar() as conn:
        await conn.execute("INSERT INTO vigilancia_avisos (clave, avisado_en, detalle) VALUES (%s,%s,%s) ON CONFLICT (clave) DO UPDATE SET avisado_en = EXCLUDED.avisado_en, detalle = EXCLUDED.detalle", [clave, ahora, e["motivo"][:300]])
    return {"estado": "avisado", "antivirus": e["estado"]}
