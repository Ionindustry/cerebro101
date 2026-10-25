"""Registro de cada llamada a modelo y herramienta en Langfuse v3 (evidencia para ENS/ISO).

Si falta LANGFUSE_HOST o las claves, el Cerebro funciona igual pero sin trazas.
Uso: pasar `callbacks()` en la configuración al invocar el grafo y `metadatos()` para atribuir la traza.
"""
from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Any, Iterator

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


def _contenido(valor: Any) -> Any:
    """LANGFUSE_REGISTRAR_CONTENIDO=false guarda solo metadatos (modelo, tokens, duración), no los textos."""
    if os.environ.get("LANGFUSE_REGISTRAR_CONTENIDO", "true").lower() == "false":
        return "[contenido no registrado]"
    return valor


@contextmanager
def generacion(nombre: str, modelo: str | None, entrada: Any, tipo: str = "generation",
               parametros: dict | None = None, **metadatos: Any) -> Iterator[Any]:
    """Registra una llamada a un modelo como observación de Langfuse, dentro de la traza en curso.

    Entrega un objeto con `.update(...)` o `None` si Langfuse está desactivado. Nunca rompe la
    llamada al modelo: un fallo de Langfuse solo deja un aviso. Las excepciones del cuerpo se
    anotan como error en la observación y se vuelven a lanzar.
    """
    if not activo():
        yield None
        return
    try:
        from langfuse import get_client
        extra = {"model": modelo, "model_parameters": parametros} if tipo in ("generation", "embedding") else {}
        cm = get_client().start_as_current_observation(
            as_type=tipo, name=nombre, input=_contenido(entrada), metadata=metadatos or None, **extra)
        obs = cm.__enter__()
    except Exception as e:  # noqa: BLE001
        log.warning("No se pudo registrar la llamada al modelo en Langfuse: %s", e)
        yield None
        return
    try:
        yield obs
    except BaseException as e:
        try:
            obs.update(level="ERROR", status_message=f"{type(e).__name__}: {e}"[:500])
        except Exception:  # noqa: BLE001
            pass
        cm.__exit__(type(e), e, e.__traceback__)
        raise
    else:
        cm.__exit__(None, None, None)


def anotar(obs: Any, **campos: Any) -> None:
    """`obs.update(...)` tolerante: ignora `None` y fallos de Langfuse."""
    if obs is None:
        return
    if "output" in campos:
        campos["output"] = _contenido(campos["output"])
    try:
        obs.update(**campos)
    except Exception as e:  # noqa: BLE001
        log.warning("No se pudo anotar la observación de Langfuse: %s", e)
