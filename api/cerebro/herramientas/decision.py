"""Decisiones de elegir, puntuar o responder sí/no.

Tres implementaciones intercambiables con la misma interfaz:
  - `local`: el modelo local con salida estructurada (funciona desde el primer día).
  - `jeff`:  sustituto autoalojado compatible con la API de Jev.
  - `jev`:   Jev en la nube de TypeSafe (solo datos de sensibilidad baja, o media con
             retención cero y anonimización).

Jev y jeff hablan la misma API (`POST /v1/systemone`, https://docs.typesafe.ai/api): un `state`
y un mapa de preguntas tipadas (noul / choice / score) y devuelven respuestas con probabilidades.
Si la llamada falla (sin clave, red caída, límite de uso), se usa el modelo `local`.
"""
from __future__ import annotations

import logging

import httpx

from ..ajustes import ajustes
from ..llm import chat
from ..registro import registro
from ..router_modelos import asignar
from .base import Herramienta, registrar

log = logging.getLogger("cerebro.decision")


async def _local(texto: str, tipo: str, opciones: list[str] | None, rubrica: str | None) -> dict:
    ficha = registro().fichas["director-general"]  # el modelo rápido basta para decidir
    if tipo == "eleccion":
        esquema = {"type": "object", "properties": {
            "eleccion": {"type": "string", "enum": opciones}, "confianza": {"type": "number"},
            "motivo": {"type": "string"}}, "required": ["eleccion", "confianza", "motivo"]}
        pregunta = f"Elige una opción de {opciones} para el texto."
    elif tipo == "puntuacion":
        esquema = {"type": "object", "properties": {
            "puntuacion": {"type": "number", "minimum": 0, "maximum": 10}, "motivo": {"type": "string"}},
            "required": ["puntuacion", "motivo"]}
        pregunta = f"Puntúa de 0 a 10 según esta rúbrica: {rubrica}"
    else:
        esquema = {"type": "object", "properties": {
            "si": {"type": "boolean"}, "confianza": {"type": "number"}, "motivo": {"type": "string"}},
            "required": ["si", "confianza", "motivo"]}
        pregunta = "Responde sí o no."
    mensajes = [{"role": "system", "content": "Eres un clasificador preciso. Responde solo con el JSON pedido."},
                {"role": "user", "content": f"{pregunta}\n\nTexto:\n{texto}"}]
    return await chat(asignar(ficha), mensajes, esquema=esquema, temperatura=0)


URL_JEV = "https://api.typesafe.ai"
NIVELES_PUNTUACION = 10   # Jev admite como máximo 10 niveles (0..9); se reescala a 0..10, como el modelo local


def _pregunta(tipo: str, opciones: list[str] | None, rubrica: str | None) -> dict:
    if tipo == "eleccion":
        return {"type": "choice", "instructions": "Elige la opción que mejor encaja con el estado.",
                "criteria": {o: None for o in opciones or []}}
    if tipo == "puntuacion":
        ultimo = NIVELES_PUNTUACION - 1
        return {"type": "score", "instructions": f"Puntúa según esta rúbrica: {rubrica}",
                "criteria": [f"Nivel {i} de {ultimo}" + (" (mínimo)" if i == 0 else " (máximo)" if i == ultimo else "")
                             for i in range(NIVELES_PUNTUACION)]}
    return {"type": "noul", "instructions": "¿Es cierto lo que se pregunta o se afirma en el estado?"}


def _traducir(tipo: str, respuesta: dict) -> dict:
    """Pasa la respuesta de Jev al mismo formato que devuelve `_local`."""
    if tipo == "eleccion":
        return {"eleccion": respuesta["choice"], "confianza": respuesta["confidence"],
                "motivo": f"Jev: probabilidades {respuesta['probabilities']}"}
    if tipo == "puntuacion":
        return {"puntuacion": round(respuesta["score"] * 10 / (NIVELES_PUNTUACION - 1), 2), "confianza": respuesta["confidence"],
                "motivo": f"Jev: probabilidades {respuesta['probabilities']}"}
    p = respuesta["noul"]
    return {"si": p >= 0.5, "confianza": round(max(p, 1 - p), 3), "motivo": f"Jev: probabilidad de sí {p}"}


async def _llamar_api(base_url: str, clave: str, texto: str, tipo: str, opciones, rubrica,
                      transporte: httpx.AsyncBaseTransport | None = None) -> dict:
    if tipo == "eleccion" and not opciones:
        raise ValueError("La elección necesita opciones")
    cuerpo = {"model": "jev-latest", "state": texto, "questions": {"q": _pregunta(tipo, opciones, rubrica)}}
    cabeceras = {"Authorization": f"Bearer {clave}"} if clave else {}
    async with httpx.AsyncClient(base_url=base_url or URL_JEV, timeout=30, transport=transporte) as c:
        r = await c.post("/v1/systemone", json=cuerpo, headers=cabeceras)
    r.raise_for_status()
    return _traducir(tipo, r.json()["answers"]["q"])


def _crear(proveedor: str):
    async def decidir(texto: str, tipo: str = "si_no", opciones: list[str] | None = None,
                      rubrica: str | None = None) -> dict:
        if proveedor == "jev" and not ajustes.usar_jev_nube:
            log.info("Jev en la nube desactivado (USAR_JEV_NUBE=false): se usa el modelo local")
            return await _local(texto, tipo, opciones, rubrica)
        url, clave = (ajustes.jev_url, ajustes.jev_api_key) if proveedor == "jev" else (ajustes.jeff_url, "")
        if proveedor == "jev" and not clave:
            log.warning("Falta JEV_API_KEY: se usa el modelo local")
            return await _local(texto, tipo, opciones, rubrica)
        try:
            return await _llamar_api(url, clave, texto, tipo, opciones, rubrica)
        except (httpx.HTTPError, KeyError, ValueError) as e:
            log.warning("%s no disponible (%s): se usa el modelo local", proveedor, e)
            return await _local(texto, tipo, opciones, rubrica)
    return decidir


for _p, _desc in (("jev", "Jev en la nube (solo datos públicos o anonimizados)"),
                  ("jeff", "Sustituto local de Jev")):
    registrar(Herramienta(
        nombre=_p,
        descripcion=f"{_desc}. Operación: decidir(texto, tipo='eleccion'|'puntuacion'|'si_no', opciones, rubrica).",
        operaciones={"decidir": _crear(_p)},
    ))
