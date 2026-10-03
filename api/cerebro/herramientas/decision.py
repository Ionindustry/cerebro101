"""Decisiones de elegir, puntuar o responder sí/no.

Tres implementaciones intercambiables con la misma interfaz:
  - `local`: el modelo local con salida estructurada (funciona desde el primer día).
  - `jeff`:  sustituto autoalojado compatible con la API de Jev.
  - `jev`:   Jev en la nube de TypeSafe (solo datos de sensibilidad baja, o media con
             retención cero y anonimización).

PENDIENTE: la API pública de Jev/jeff no está documentada en este repositorio. Cuando
tengáis la documentación, completad `_llamar_api` con el formato real; mientras tanto,
`jev` y `jeff` caen automáticamente en `local`.
"""
from __future__ import annotations

import logging

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


async def _llamar_api(base_url: str, clave: str, texto: str, tipo: str, opciones, rubrica) -> dict:
    raise NotImplementedError("Completar con la API documentada de Jev/jeff")


def _crear(proveedor: str):
    async def decidir(texto: str, tipo: str = "si_no", opciones: list[str] | None = None,
                      rubrica: str | None = None) -> dict:
        if proveedor == "jev" and not ajustes.usar_jev_nube:
            log.info("Jev en la nube desactivado (USAR_JEV_NUBE=false): se usa el modelo local")
            return await _local(texto, tipo, opciones, rubrica)
        url, clave = (ajustes.jev_url, ajustes.jev_api_key) if proveedor == "jev" else (ajustes.jeff_url, "")
        try:
            return await _llamar_api(url, clave, texto, tipo, opciones, rubrica)
        except NotImplementedError:
            return await _local(texto, tipo, opciones, rubrica)
    return decidir


for _p, _desc in (("jev", "Jev en la nube (solo datos públicos o anonimizados)"),
                  ("jeff", "Sustituto local de Jev")):
    registrar(Herramienta(
        nombre=_p,
        descripcion=f"{_desc}. Operación: decidir(texto, tipo='eleccion'|'puntuacion'|'si_no', opciones, rubrica).",
        operaciones={"decidir": _crear(_p)},
    ))
