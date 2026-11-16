"""Herramienta «eet»: precio y stock de EET Europarts en tiempo real (solo lectura). Ver cerebro/eet.py y docs/EET.md.

Los precios son los costes de compra: confidencial (tras usarla el agente solo trabaja con modelos locales)."""
from __future__ import annotations

from .. import eet
from .base import Herramienta, registrar


async def consultar(referencias: list | str) -> dict:
    refs = [r for r in referencias.replace(";", ",").split(",")] if isinstance(referencias, str) else list(referencias or [])
    try:
        return await eet.consultar(refs)
    except eet.ErrorEET as e:
        return {"error": str(e)}


registrar(Herramienta(
    nombre="eet",
    descripcion="EET (proveedor): precio de compra y stock en vivo. Solo lectura. Confidencial.",
    operaciones={"consultar": consultar},
    ayuda={"consultar": "precio y stock de «referencias» de EET (hasta 50)"},
    confidencial=True,
))
