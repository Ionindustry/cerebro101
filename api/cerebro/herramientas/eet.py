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
    descripcion="EET Europarts (proveedor): consulta en tiempo real el precio de compra y el stock de referencias. Solo lectura: no hace pedidos. Los precios los da EET: no los recalcules ni inventes. Confidencial.",
    operaciones={"consultar": consultar},
    ayuda={"consultar": "precio, stock (y plazo, EAN y descripción) de una o varias «referencias» de EET, hasta 50 por consulta"},
    ejemplos={"consultar": {"referencias": ["LSU-15", "LS-150"]}},
    confidencial=True,
))
