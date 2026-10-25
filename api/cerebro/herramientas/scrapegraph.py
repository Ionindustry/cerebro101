"""ScrapeGraphAI con modelos locales para investigar competidores, fabricantes e instaladores.

Normas que aplica el código (no solo las instrucciones):
  - respeta robots.txt de cada web,
  - como máximo una visita por dominio cada `ESPERA_SEGUNDOS`,
  - solo URL públicas http(s), nunca zonas con usuario y contraseña.
"""
from __future__ import annotations

import asyncio
import time
import urllib.robotparser
from urllib.parse import urlparse

from ..ajustes import ajustes
from ..router_modelos import _modelos
from .base import Herramienta, registrar

AGENTE_HTTP = "Cerebro101-Investigacion/0.1 (+https://101.cat)"
ESPERA_SEGUNDOS = 10
_ultima_visita: dict[str, float] = {}


def _permitido(url: str) -> bool:
    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        return False
    rp = urllib.robotparser.RobotFileParser(f"{p.scheme}://{p.netloc}/robots.txt")
    try:
        rp.read()
    except Exception:
        return False
    return rp.can_fetch(AGENTE_HTTP, url)


async def _esperar_turno(url: str) -> None:
    dominio = urlparse(url).netloc
    espera = ESPERA_SEGUNDOS - (time.monotonic() - _ultima_visita.get(dominio, 0))
    if espera > 0:
        await asyncio.sleep(espera)
    _ultima_visita[dominio] = time.monotonic()


def _config_grafo() -> dict:
    cfg = _modelos(str(ajustes.dir_config))
    principal = cfg["perfiles"][ajustes.perfil_hardware]["principal"]["modelo"]
    return {
        "llm": {"model": f"ollama/{principal}", "base_url": ajustes.ollama_url, "format": "json"},
        "embeddings": {"model": f"ollama/{cfg['embeddings']['modelo']}", "base_url": ajustes.ollama_url},
        "headless": True,
        "verbose": False,
        "loader_kwargs": {"user_agent": AGENTE_HTTP},
    }


async def extraer(url: str, instruccion: str) -> dict:
    if not await asyncio.to_thread(_permitido, url):
        return {"error": "robots.txt no permite visitar esta página o no es una URL pública"}
    await _esperar_turno(url)
    from scrapegraphai.graphs import SmartScraperGraph  # import diferido: librería pesada
    grafo = SmartScraperGraph(prompt=instruccion, source=url, config=_config_grafo())
    return await asyncio.to_thread(grafo.run)


async def extraer_documento(contenido: str, instruccion: str) -> dict:
    from scrapegraphai.graphs import SmartScraperGraph
    grafo = SmartScraperGraph(prompt=instruccion, source=contenido, config=_config_grafo())
    return await asyncio.to_thread(grafo.run)


registrar(Herramienta(
    nombre="scrapegraph",
    descripcion="Extrae datos estructurados de una web pública o de un documento descargado.",
    operaciones={"extraer": extraer, "extraer_documento": extraer_documento},
    ayuda={"extraer": "lee una página web pública y devuelve lo que pide la instrucción",
           "extraer_documento": "lo mismo sobre el texto de un documento ya descargado"},
    ejemplos={"extraer": {"url": "https://www.ejemplo.com/tarifas", "instruccion": "lista de productos con su precio"}},
))
