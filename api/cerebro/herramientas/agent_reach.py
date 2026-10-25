"""Agent Reach: lectura de YouTube, Reddit y GitHub desde un contenedor aislado.

El Cerebro no ejecuta Agent Reach en su propio contenedor: llama al pequeño
servicio de servicios/agent-reach, que solo expone canales de la lista permitida
y nunca usa cookies de cuentas personales.
"""
from __future__ import annotations

import httpx

from ..ajustes import ajustes
from .base import Herramienta, registrar


async def _get(ruta: str, **params) -> dict:
    async with httpx.AsyncClient(base_url=ajustes.agent_reach_url, timeout=180) as c:
        r = await c.get(ruta, params=params)
    r.raise_for_status()
    return r.json()


async def estado() -> dict:
    return await _get("/doctor")


async def transcripcion_youtube(url: str) -> dict:
    return await _get("/youtube/transcripcion", url=url)


registrar(Herramienta(
    nombre="agent_reach",
    descripcion="Lectura de contenido público de YouTube (transcripciones).",
    operaciones={"estado": estado, "transcripcion_youtube": transcripcion_youtube},
    ayuda={"estado": "comprueba que el servicio funciona", "transcripcion_youtube": "transcripción de un vídeo público"},
    ejemplos={"transcripcion_youtube": {"url": "https://www.youtube.com/watch?v=XXXXXXXXXXX"}},
))
