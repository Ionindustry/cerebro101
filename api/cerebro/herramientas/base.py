"""Registro de herramientas y punto único de uso.

Todo uso de herramienta pasa por `usar()`, que:
  1. comprueba que la herramienta está en la ficha del agente,
  2. cambia a la alternativa local si los datos son demasiado sensibles,
  3. bloquea las acciones con impacto externo que no vengan de una aprobación,
  4. deja registro para la auditoría (Langfuse y tabla registro_acciones).
"""
from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from ..observabilidad import anotar, generacion
from ..politicas import herramienta_efectiva
from ..registro import Ficha
from .esquemas import ArgumentosNoValidos, describir, validar  # noqa: F401

log = logging.getLogger("cerebro.herramientas")

Funcion = Callable[..., Awaitable[Any]]


@dataclass
class Herramienta:
    nombre: str
    descripcion: str                  # lo que lee el modelo para decidir si usarla
    operaciones: dict[str, Funcion]   # operación → función async
    externas: frozenset[str] = frozenset()  # operaciones con impacto externo (requieren aprobación)
    ayuda: dict[str, str] = field(default_factory=dict)       # operación → para qué sirve y cómo se usa
    campos: dict[str, dict[str, str]] = field(default_factory=dict)   # operación con **campos → {campo: descripción}
    ejemplos: dict[str, dict] = field(default_factory=dict)   # operación → argumentos de ejemplo (el primero va al prompt)


_REGISTRO: dict[str, Herramienta] = {}


def registrar(h: Herramienta) -> Herramienta:
    _REGISTRO[h.nombre] = h
    return h


def validar_llamada(ficha: Ficha, nombre: str, operacion: str, argumentos: dict, sensibilidad: str | None = None) -> str | None:
    """Comprueba una llamada (o una acción propuesta) sin ejecutarla: devuelve el motivo si no es válida, o None."""
    try:
        h = _REGISTRO.get(herramienta_efectiva(ficha, nombre, sensibilidad))
        if h is None:
            return f"La herramienta «{nombre}» no está instalada"
        validar(h, operacion, argumentos or {})
    except (ValueError, LookupError, PermissionError) as e:
        return str(e)
    return None


def disponibles_para(ficha: Ficha) -> dict[str, Herramienta]:
    return {n: _REGISTRO[n] for n in ficha.herramientas if n in _REGISTRO}


class OperacionRequiereAprobacion(PermissionError):
    pass


async def usar(ficha: Ficha, nombre: str, operacion: str, sensibilidad: str | None = None,
               aprobada: bool = False, **argumentos: Any) -> Any:
    efectiva = herramienta_efectiva(ficha, nombre, sensibilidad)
    # Cada intento de usar una herramienta queda en la traza, también los rechazados (evidencia ISO 27001:
    # qué hizo o intentó hacer el agente, con qué autorización y qué control lo frenó)
    with generacion(f"herramienta:{efectiva}.{operacion}", None, argumentos, tipo="tool", agente=ficha.id,
                    departamento=ficha.departamento, aprobada=aprobada, sensibilidad=sensibilidad,
                    solicitada=nombre) as obs:
        h = _REGISTRO.get(efectiva)
        if h is None:
            raise LookupError(f"La herramienta «{efectiva}» no está instalada")
        if operacion not in h.operaciones:
            raise LookupError(f"«{efectiva}» no tiene la operación «{operacion}». Operaciones: {', '.join(h.operaciones)}")
        if operacion in h.externas and not aprobada:
            raise OperacionRequiereAprobacion(f"{efectiva}.{operacion} tiene impacto externo y necesita aprobación: "
                                              "no la llames, propónla en «acciones» para que una persona la apruebe")
        validar(h, operacion, argumentos)
        if "sensibilidad" in inspect.signature(h.operaciones[operacion]).parameters:
            # el modelo no puede pedir documentos más sensibles de los que le corresponden
            argumentos = {**argumentos, "sensibilidad": sensibilidad or ficha.sensibilidad}
        log.info("agente=%s herramienta=%s operacion=%s aprobada=%s", ficha.id, efectiva, operacion, aprobada)
        resultado = await h.operaciones[operacion](**argumentos)
        anotar(obs, output=str(resultado)[:4000])
        return resultado
