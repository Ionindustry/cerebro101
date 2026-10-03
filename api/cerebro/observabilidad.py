"""Registro de cada llamada a modelo y herramienta en Langfuse (evidencia para ENS/ISO).

Si LANGFUSE_HOST no está configurado, el Cerebro funciona igual pero sin trazas.
Uso: pasar `callbacks()` en la configuración al invocar el grafo.
"""
from __future__ import annotations

import os


def callbacks() -> list:
    if not os.environ.get("LANGFUSE_HOST"):
        return []
    from langfuse.callback import CallbackHandler  # import diferido
    return [CallbackHandler()]
