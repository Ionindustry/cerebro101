from __future__ import annotations

from typing import Any, TypedDict


class Accion(TypedDict, total=False):
    accion: str            # nombre de la acción (enviar_correo, presentar_licitacion…)
    herramienta: str
    operacion: str
    argumentos: dict
    resumen: str           # lo que verá la persona en la bandeja
    solicitud_id: str
    estado: str            # pendiente | aprobada | rechazada | ejecutada | error
    resultado: Any


class Estado(TypedDict, total=False):
    peticion: str
    usuario: str
    origen: str            # jarvis | peticion | programada
    sensibilidad: str      # sensibilidad de los datos de la petición, si se conoce
    departamento: str
    agente: str
    pasos: list[dict]      # traza de herramientas usadas por el agente
    respuesta: str
    acciones: list[Accion]
    error: str
