"""Registro de herramientas y punto único de uso.

Todo uso de herramienta pasa por `usar()`, que:
  1. comprueba que la herramienta está en la ficha del agente,
  2. cambia a la alternativa local si los datos son demasiado sensibles,
  3. bloquea las acciones con impacto externo que no vengan de una aprobación,
  4. deja registro para la auditoría (Langfuse y tabla registro_acciones).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from ..politicas import herramienta_efectiva
from ..registro import Ficha

log = logging.getLogger("cerebro.herramientas")

Funcion = Callable[..., Awaitable[Any]]


@dataclass
class Herramienta:
    nombre: str
    descripcion: str                  # lo que lee el modelo para decidir si usarla
    operaciones: dict[str, Funcion]   # operación → función async
    externas: frozenset[str] = frozenset()  # operaciones con impacto externo (requieren aprobación)


_REGISTRO: dict[str, Herramienta] = {}


def registrar(h: Herramienta) -> Herramienta:
    _REGISTRO[h.nombre] = h
    return h


def disponibles_para(ficha: Ficha) -> dict[str, Herramienta]:
    return {n: _REGISTRO[n] for n in ficha.herramientas if n in _REGISTRO}


class OperacionRequiereAprobacion(PermissionError):
    pass


async def usar(ficha: Ficha, nombre: str, operacion: str, sensibilidad: str | None = None,
               aprobada: bool = False, **argumentos: Any) -> Any:
    efectiva = herramienta_efectiva(ficha, nombre, sensibilidad)
    h = _REGISTRO.get(efectiva)
    if h is None:
        raise LookupError(f"La herramienta «{efectiva}» no está instalada")
    if operacion not in h.operaciones:
        raise LookupError(f"«{efectiva}» no tiene la operación «{operacion}»")
    if operacion in h.externas and not aprobada:
        raise OperacionRequiereAprobacion(f"{efectiva}.{operacion} tiene impacto externo y necesita aprobación")
    log.info("agente=%s herramienta=%s operacion=%s aprobada=%s", ficha.id, efectiva, operacion, aprobada)
    return await h.operaciones[operacion](**argumentos)
