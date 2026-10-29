"""Coste estimado de una oferta a partir de un presupuesto (Quotation) del ERP, para el simulador de ofertas.

Solo lectura y por la política de acceso del departamento de Licitaciones (config/erp_acceso.yaml: Quotation e Item). El coste de cada línea es su coste unitario × cantidad: el
«valuation_rate» de la línea del presupuesto si lo trae; si no, el del artículo, y si tampoco, su último precio de compra. Las líneas sin ningún coste NO se inventan: se
listan, y el coste se marca como incompleto (el simulador lo avisa y no lo da por bueno).

POR VERIFICAR con el ERPNext real de 101.cat: que los artículos tengan «valuation_rate» o «last_purchase_rate» informado y que el presupuesto esté en euros.
"""
from __future__ import annotations

import logging

import httpx

from ..herramientas import erpnext

log = logging.getLogger("cerebro.licitaciones.coste_erp")
DEPARTAMENTO = "licitaciones"
MAX_LINEAS = 200


class ErrorCoste(ValueError):
    """Lo que no se puede hacer con ese presupuesto; el mensaje es para la persona."""


def _num(v) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return 0.0
    return x if x == x and x >= 0 else 0.0


async def _coste_articulo(codigo: str, memo: dict) -> tuple[float, str]:
    if codigo not in memo:
        try:
            a = await erpnext.leer("Item", codigo, DEPARTAMENTO)
        except (PermissionError, httpx.HTTPError):
            memo[codigo] = (0.0, "")
        else:
            v = _num(a.get("valuation_rate"))
            memo[codigo] = (v, "coste del artículo") if v > 0 else ((_num(a.get("last_purchase_rate")), "último precio de compra") if _num(a.get("last_purchase_rate")) > 0 else (0.0, ""))
    return memo[codigo]


async def coste_de_presupuesto(nombre: str) -> dict:
    """{presupuesto, moneda, coste, completo, lineas, sin_coste, precio_neto}. `coste` suma solo las líneas con coste; `completo` dice si todas lo tienen."""
    nombre = str(nombre or "").strip()
    if not nombre:
        raise ErrorCoste("Escribe el código del presupuesto del ERP")
    try:
        q = await erpnext.leer("Quotation", nombre, DEPARTAMENTO)
    except PermissionError as e:
        raise ErrorCoste(str(e)) from None
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise ErrorCoste(f"No existe el presupuesto «{nombre[:60]}» en el ERP") from None
        raise ErrorCoste("El ERP ha dado un error al leer el presupuesto: inténtalo más tarde") from None
    except httpx.HTTPError:
        raise ErrorCoste("El ERP no responde ahora: inténtalo más tarde o escribe el coste a mano") from None
    if q.get("docstatus") == 2:
        raise ErrorCoste("Ese presupuesto está cancelado en el ERP")
    moneda = str(q.get("currency") or "EUR").upper()
    if moneda != "EUR":
        raise ErrorCoste(f"El presupuesto está en {moneda}: el simulador trabaja en euros (escribe el coste a mano)")
    items = q.get("items") or []
    if not items:
        raise ErrorCoste("El presupuesto no tiene líneas")
    if len(items) > MAX_LINEAS:
        raise ErrorCoste(f"El presupuesto tiene más de {MAX_LINEAS} líneas: escribe el coste a mano")
    memo: dict = {}
    lineas, sin_coste, total = [], [], 0.0
    for it in items:
        codigo = str(it.get("item_code") or "")
        cant = _num(it.get("qty"))
        unit, origen = _num(it.get("valuation_rate")), "coste de la línea"
        if unit <= 0 and codigo:
            unit, origen = await _coste_articulo(codigo, memo)
        if cant <= 0:
            continue
        if unit <= 0:
            sin_coste.append({"articulo": codigo or str(it.get("item_name") or "")[:60], "cantidad": cant})
            continue
        sub = round(unit * cant, 2)
        total += sub
        lineas.append({"articulo": codigo, "cantidad": cant, "coste_unitario": round(unit, 4), "coste": sub, "origen": origen})
    if not lineas:
        raise ErrorCoste("Ninguna línea del presupuesto tiene coste en el ERP: escribe el coste a mano")
    log.info("coste desde el ERP: %s → %.2f € (%d líneas, %d sin coste)", nombre, total, len(lineas), len(sin_coste))
    return {"presupuesto": nombre, "moneda": "EUR", "coste": round(total, 2), "completo": not sin_coste, "lineas": lineas[:50], "sin_coste": sin_coste[:50],
            "precio_neto": _num(q.get("net_total")) or None}
