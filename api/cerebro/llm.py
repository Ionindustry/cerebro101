"""Cliente de los modelos locales (Ollama).

Siempre se pide salida estructurada (JSON con esquema) cuando el agente tiene que
decidir algo: así los modelos pequeños responden en un formato que el código puede
validar, y si fallan se reintenta con el modelo principal.
"""
from __future__ import annotations

import json
from typing import Any

import httpx

from .ajustes import ajustes
from .router_modelos import Asignacion


class ErrorModelo(RuntimeError):
    pass


async def chat(asignacion: Asignacion, mensajes: list[dict], esquema: dict | None = None,
               imagenes: list[str] | None = None, temperatura: float = 0.2,
               timeout: float = 300) -> str | dict:
    """Llama a /api/chat de Ollama. Con `esquema`, devuelve el JSON ya validado como dict."""
    if imagenes:
        mensajes = [*mensajes[:-1], {**mensajes[-1], "images": imagenes}]
    cuerpo: dict[str, Any] = {
        "model": asignacion.modelo,
        "messages": mensajes,
        "stream": False,
        "keep_alive": asignacion.mantener_cargado,
        "options": {"temperature": temperatura},
    }
    if esquema:
        cuerpo["format"] = esquema
    async with httpx.AsyncClient(base_url=ajustes.ollama_url, timeout=timeout) as cliente:
        r = await cliente.post("/api/chat", json=cuerpo)
    if r.status_code != 200:
        raise ErrorModelo(f"Ollama devolvió {r.status_code}: {r.text[:300]}")
    contenido = r.json()["message"]["content"]
    if not esquema:
        return contenido
    try:
        datos = json.loads(contenido)
    except json.JSONDecodeError as e:
        raise ErrorModelo(f"El modelo {asignacion.modelo} no devolvió JSON válido") from e
    faltan = [k for k in esquema.get("required", []) if k not in datos]
    if faltan:
        raise ErrorModelo(f"Faltan campos en la respuesta: {faltan}")
    return datos


async def embeddings(textos: list[str], modelo: str = "bge-m3") -> list[list[float]]:
    async with httpx.AsyncClient(base_url=ajustes.ollama_url, timeout=120) as cliente:
        r = await cliente.post("/api/embed", json={"model": modelo, "input": textos})
    if r.status_code != 200:
        raise ErrorModelo(f"Embeddings fallidos: {r.text[:300]}")
    return r.json()["embeddings"]
