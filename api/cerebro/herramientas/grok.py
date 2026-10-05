"""Grok (xAI): búsqueda en X y en la web en tiempo real para el Radar y el Detector de Intención.

Solo recibe consultas sobre temas públicos (sensibilidad máxima: baja).
VERIFICAR en https://docs.x.ai antes de producción: nombre del modelo, endpoint y
formato de las herramientas de búsqueda cambian con frecuencia.
"""
from __future__ import annotations

import os

import httpx

from ..ajustes import ajustes
from .base import Herramienta, registrar

MODELO = os.environ.get("XAI_MODELO", "grok-4")


async def buscar(consulta: str, en_x: bool = True, en_web: bool = True, max_resultados: int = 10) -> dict:
    herramientas = []
    if en_web:
        herramientas.append({"type": "web_search"})
    if en_x:
        herramientas.append({"type": "x_search"})
    cuerpo = {
        "model": MODELO,
        "input": [{"role": "user", "content":
                   f"Busca y resume lo más relevante y reciente sobre: {consulta}. "
                   f"Devuelve hasta {max_resultados} hallazgos con fuente, fecha y por qué importa "
                   "a una instaladora de seguridad y telecomunicaciones en Cataluña."}],
        "tools": herramientas,
    }
    async with httpx.AsyncClient(base_url="https://api.x.ai/v1", timeout=120,
                                 headers={"Authorization": f"Bearer {ajustes.xai_api_key}"}) as c:
        r = await c.post("/responses", json=cuerpo)
    r.raise_for_status()
    return r.json()


registrar(Herramienta(
    nombre="grok",
    descripcion="Tendencias y noticias en tiempo real en X y la web. Solo temas públicos, nunca datos de clientes o internos.",
    operaciones={"buscar": buscar},
    ayuda={"buscar": "busca en X y en la web; devuelve un resumen con enlaces"},
    ejemplos={"buscar": {"consulta": "cámaras de videovigilancia con inteligencia artificial", "en_x": True, "en_web": True}},
))
