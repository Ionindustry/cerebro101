"""Comprobación de que las licitaciones están al día, que el panel lanza cada vez que se abre la aplicación.

Mira cuánto hace de la última ingesta correcta de cada fuente (`/ops/status` del motor). Si es reciente, dice «al día». Si es vieja (más de `umbral_min`, por defecto 20 minutos: el ingestor
mira la fuente cada 15) o el motor aún no ha completado ninguna, PIDE al motor una actualización inmediata (`POST /ops/actualizar`: el ingestor empieza su vuelta en como mucho 10 segundos
en vez de esperar al intervalo) y dice «actualizando». Si el motor no responde, lo dice. Nunca lanza: el panel solo enseña el estado.
"""
from __future__ import annotations

import logging
from pathlib import Path

import yaml

from ..ajustes import ajustes
from ..herramientas import licitaciones as motor

log = logging.getLogger("cerebro.licitaciones.frescura")
DEFECTO = {"umbral_min": 20}


def configuracion() -> dict:
    try:
        c = (yaml.safe_load((Path(ajustes.dir_config) / "licitaciones.yaml").read_text(encoding="utf-8")) or {}).get("actualizacion") or {}
    except OSError:
        c = {}
    cfg = {**DEFECTO, **c}
    cfg["umbral_min"] = min(max(int(cfg["umbral_min"]), 5), 24 * 60)
    return cfg


def edad_maxima(estado: dict) -> tuple[int | None, bool]:
    """(antigüedad en segundos de la fuente más atrasada, si alguna fuente no ha completado nunca una ingesta). Sin fuentes: (None, True)."""
    fuentes = estado.get("fuentes") or []
    if not fuentes:
        return None, True
    edades = [f.get("antiguedad_s") for f in fuentes]
    sin = any(e is None for e in edades)
    conocidas = [int(e) for e in edades if e is not None]
    return (max(conocidas) if conocidas else None), sin


async def comprobar(usuario: str, consulta=None, pedir=None, cfg: dict | None = None) -> dict:
    """{estado: al_dia | actualizando | motor_no_responde, antiguedad_s, solicitada}. `consulta` y `pedir` se pueden sustituir (pruebas)."""
    cfg = cfg or configuracion()
    consulta, pedir = consulta or motor._get, pedir or motor.pedir_actualizacion
    try:
        estado = await consulta("/ops/status", None)
    except (motor.MotorNoDisponible, ValueError):
        return {"estado": "motor_no_responde", "antiguedad_s": None, "solicitada": False}
    edad, sin_ingesta = edad_maxima(estado)
    if not sin_ingesta and edad is not None and edad <= cfg["umbral_min"] * 60:
        return {"estado": "al_dia", "antiguedad_s": edad, "solicitada": False}
    try:
        solicitada = await pedir(usuario)
    except motor.MotorNoDisponible as e:
        log.warning("frescura: no se ha podido pedir la actualización: %s", e)
        return {"estado": "motor_no_responde", "antiguedad_s": edad, "solicitada": False}
    log.info("frescura: %s abre la aplicación con lo último ingerido de hace %s s: se pide actualizar (nueva=%s)", usuario, edad, solicitada)
    return {"estado": "actualizando", "antiguedad_s": edad, "solicitada": solicitada}
