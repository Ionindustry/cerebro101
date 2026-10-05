"""Control del contexto que se envía al modelo.

Ollama recorta en silencio por el principio lo que no cabe en la ventana (`num_ctx`), y lo primero que hay son las
instrucciones del sistema: con una entrada demasiado grande el agente deja de conocer sus reglas o se queda sin sitio para
responder. Aquí se estima el tamaño y se recortan los resultados de herramientas antiguos (nunca el sistema ni la petición).
"""
from __future__ import annotations

import os

CARACTERES_POR_TOKEN = 3        # estimación prudente para español (la real ronda 3,5-4)
MARCA = "\n[…resultado recortado para que quepa en el contexto…]"


def estimar_tokens(mensajes: list[dict]) -> int:
    return sum(len(m.get("content") or "") for m in mensajes) // CARACTERES_POR_TOKEN + 4 * len(mensajes)


def limite_resultado() -> int:
    """Caracteres máximos de un resultado de herramienta que se devuelve al modelo."""
    try:
        return int(os.environ.get("OLLAMA_RESULTADO_MAX") or 6000)
    except ValueError:
        return 6000


def recortar(mensajes: list[dict], presupuesto_tokens: int, minimo: int = 1200) -> list[dict]:
    """Copia de `mensajes` que cabe en el presupuesto. Se recorta primero el mensaje más largo (excepto el sistema, la
    petición original y la última respuesta del modelo); si ya no hay nada que acortar, se descartan los pasos más antiguos."""
    m = [dict(x) for x in mensajes]
    protegidos = {0, 1}
    while estimar_tokens(m) > presupuesto_tokens:
        candidatos = [(len(x.get("content") or ""), i) for i, x in enumerate(m)
                      if i not in protegidos and len(x.get("content") or "") > minimo + len(MARCA)]
        if candidatos:
            _, i = max(candidatos)
            m[i]["content"] = m[i]["content"][:minimo] + MARCA
        elif len(m) > 4:                      # sistema, petición y dos mensajes como mínimo: se quitan los pasos más antiguos
            del m[2:4]
        else:
            break
    return m
