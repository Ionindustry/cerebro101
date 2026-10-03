"""Mayorista de telecomunicaciones.

PENDIENTE: cada mayorista ofrece su propia API o portal. Cuando elijáis mayorista,
implementad aquí las cinco operaciones con su API; la interfaz que usan los agentes
de Telecom no cambia. Mientras tanto devuelven un aviso claro en lugar de inventar datos.
"""
from __future__ import annotations

from .base import Herramienta, registrar

AVISO = {"error": "Mayorista no conectado todavía: ver docs/PENDIENTES.md"}


async def cobertura(direccion: str) -> dict:
    return AVISO


async def estado_pedido(id: str) -> dict:
    return AVISO


async def consumos(mes: str) -> dict:
    return AVISO


async def alta(**datos) -> dict:
    return AVISO


async def abrir_incidencia(**datos) -> dict:
    return AVISO


registrar(Herramienta(
    nombre="mayorista",
    descripcion="Mayorista de telecom. Operaciones: cobertura(direccion), estado_pedido(id), consumos(mes), "
                "alta(...) y abrir_incidencia(...) — estas dos requieren aprobación.",
    operaciones={"cobertura": cobertura, "estado_pedido": estado_pedido, "consumos": consumos,
                 "alta": alta, "abrir_incidencia": abrir_incidencia},
    externas=frozenset({"alta", "abrir_incidencia"}),
))
