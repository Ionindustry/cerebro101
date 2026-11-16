"""Comprobación de que las licitaciones están al día, que el panel lanza cada vez que se abre la aplicación.

Mira cuánto hace de la última ingesta correcta de cada fuente (`/ops/status` del motor). Si es reciente Y el ingestor no se está poniendo al día de días atrasados (`al_dia` de cada fuente, tras una parada: el equipo apagado), dice «al día». Si es vieja (más de `umbral_min`, por defecto 20 minutos: el ingestor
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
    atrasada = any(f.get("al_dia") is False for f in (estado.get("fuentes") or []))      # el ingestor se está poniendo al día de días atrasados (tras una parada)
    if not sin_ingesta and not atrasada and edad is not None and edad <= cfg["umbral_min"] * 60:
        return {"estado": "al_dia", "antiguedad_s": edad, "solicitada": False}
    try:
        solicitada = await pedir(usuario)
    except motor.MotorNoDisponible as e:
        log.warning("frescura: no se ha podido pedir la actualización: %s", e)
        return {"estado": "motor_no_responde", "antiguedad_s": edad, "solicitada": False}
    log.info("frescura: %s abre la aplicación con lo último ingerido de hace %s s: se pide actualizar (nueva=%s)", usuario, edad, solicitada)
    return {"estado": "actualizando", "antiguedad_s": edad, "solicitada": solicitada, "poniendose_al_dia": atrasada}


# ---- Actualización MANUAL (botón «Actualizar concursos ahora» de Licitaciones) ----
def progreso_de(estado: dict) -> dict:
    """De lo que dice el motor: la edad de la ingesta más reciente y de la más atrasada (segundos) y cuántas fuentes hay. None = ninguna ingesta completa todavía. Pura."""
    fuentes = estado.get("fuentes") or []
    edades = [f.get("antiguedad_s") for f in fuentes if f.get("antiguedad_s") is not None]
    return {"mas_reciente_s": int(min(edades)) if edades else None, "mas_atrasada_s": int(max(edades)) if edades and len(edades) == len(fuentes) else None, "fuentes": len(fuentes),
            "sin_ingesta": sum(1 for f in fuentes if f.get("antiguedad_s") is None)}


async def progreso(consulta=None) -> dict:
    """{estado: ok | motor_no_responde, mas_reciente_s, mas_atrasada_s, fuentes, sin_ingesta}. El panel lo mira cada pocos segundos tras pedir la actualización: cuando «mas_reciente_s» baja, hay una ingesta nueva."""
    consulta = consulta or motor._get
    try:
        estado = await consulta("/ops/status", None)
    except (motor.MotorNoDisponible, ValueError):
        return {"estado": "motor_no_responde", "mas_reciente_s": None, "mas_atrasada_s": None, "fuentes": 0, "sin_ingesta": 0}
    return {"estado": "ok", **progreso_de(estado)}


async def actualizar_ahora(usuario: str, consulta=None, pedir=None) -> dict:
    """Pide al motor que el ingestor empiece una vuelta YA, sin mirar lo viejo que esté lo último. {estado: actualizando | motor_no_responde, solicitada, mas_reciente_s, mensaje}.
    `solicitada` False = ya había una petición de hace menos de un minuto (el motor no las repite). Nunca ingiere nada por sí mismo ni cambia datos."""
    pedir = pedir or motor.pedir_actualizacion
    antes = await progreso(consulta)
    if antes["estado"] == "motor_no_responde":
        return {"estado": "motor_no_responde", "solicitada": False, "mas_reciente_s": None, "mensaje": "El motor de licitaciones no responde: no se puede pedir la actualización. Si sigue así, avisa a Tecnología."}
    try:
        solicitada = await pedir(usuario)
    except motor.MotorNoDisponible as e:
        log.warning("frescura: no se ha podido pedir la actualización manual: %s", e)
        return {"estado": "motor_no_responde", "solicitada": False, "mas_reciente_s": antes["mas_reciente_s"], "mensaje": str(e)[:300]}
    log.info("frescura: %s pide actualizar los concursos a mano (nueva=%s, lo más reciente de hace %s s)", usuario, solicitada, antes["mas_reciente_s"])
    return {"estado": "actualizando", "solicitada": solicitada, "mas_reciente_s": antes["mas_reciente_s"],
            "mensaje": "Pedido. El ingestor empieza en unos segundos y tarda unos minutos en traer lo nuevo." if solicitada else "Ya se había pedido hace menos de un minuto: el ingestor está en ello."}
