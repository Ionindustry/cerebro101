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
    descripcion="Mayorista de telecom (pendiente de conectar con el mayorista elegido).",
    operaciones={"cobertura": cobertura, "estado_pedido": estado_pedido, "consumos": consumos,
                 "alta": alta, "abrir_incidencia": abrir_incidencia},
    externas=frozenset({"alta", "abrir_incidencia"}),
    ayuda={"cobertura": "cobertura de fibra/móvil en una dirección", "estado_pedido": "estado de un pedido por su id",
           "consumos": "consumos de un mes (AAAA-MM)", "alta": "da de alta una línea o servicio",
           "abrir_incidencia": "abre una incidencia con el mayorista"},
    campos={"alta": {"datos": "campos libres del alta (cliente, servicio, dirección…)"},
            "abrir_incidencia": {"datos": "campos libres de la incidencia (línea, descripción…)"}},
    ejemplos={"cobertura": {"direccion": "Calle Mayor 12, 43201 Reus"}},
))
