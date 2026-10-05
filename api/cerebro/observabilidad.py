"""Registro de cada llamada a modelo y herramienta en Langfuse v3 (evidencia para ENS/ISO).

Si falta LANGFUSE_HOST o las claves, el Cerebro funciona igual pero sin trazas.
Uso: pasar `callbacks()` en la configuración al invocar el grafo y `metadatos()` para atribuir la traza.
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)


def activo() -> bool:
    return all(os.environ.get(v) for v in ("LANGFUSE_HOST", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"))


def callbacks() -> list:
    if not activo():
        return []
    try:
        from langfuse.langchain import CallbackHandler  # import diferido; lee LANGFUSE_* del entorno
        return [CallbackHandler()]
    except Exception as e:  # SDK no instalado o incompatible: seguir sin trazas
        log.warning("Langfuse desactivado: %s", e)
        return []


def metadatos(hilo: str, usuario: str) -> dict:
    """Agrupa las trazas por conversación y por persona en Langfuse."""
    return {"langfuse_session_id": hilo, "langfuse_user_id": usuario}
