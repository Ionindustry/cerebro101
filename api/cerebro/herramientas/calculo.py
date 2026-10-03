"""Herramientas de cálculo deterministas: cotizador y comparador de instaladores."""
from __future__ import annotations

from ..cotizador import Solicitud, calcular
from ..red_instaladores import Oferta, puntuar
from .base import Herramienta, registrar


async def cotizar(**campos) -> dict:
    return calcular(Solicitud(**campos)).como_dict()


async def comparar(ofertas: list[dict], pesos: dict | None = None) -> list[dict]:
    return [p.__dict__ for p in puntuar([Oferta(**o) for o in ofertas], pesos)]


registrar(Herramienta(
    nombre="cotizador",
    descripcion="Calcula un presupuesto de instalación con el motor del contador. "
                "Operación: cotizar(partidas, metros_cableado, materiales, cuadrilla_tecnicos, ...).",
    operaciones={"cotizar": cotizar},
))
registrar(Herramienta(
    nombre="comparador_instaladores",
    descripcion="Ordena presupuestos de instaladores por precio, rapidez y eficiencia. Operación: comparar(ofertas, pesos).",
    operaciones={"comparar": comparar},
))
