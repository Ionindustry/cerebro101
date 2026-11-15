"""Ranking de ventas por tipo de producto (CCTV, control de accesos, intrusión…): los 10 artículos y los 10 fabricantes que más venden en cada tipo.

Sale de los pedidos de venta CONFIRMADOS del ERP en un periodo (solo lectura). La clasificación por tipo y las sumas las hace el código con config/tipos_producto.yaml: primero por el grupo de
artículo del ERP y, si no encaja, por palabras del nombre. Lo que no encaja va a «Otros» (se ve cuánto pesa, para ajustar el fichero). Se ordena por IMPORTE NETO en la moneda de la empresa
(a igualdad, por unidades). Las ventas son datos de la empresa: solo las ve Dirección y no salen a ningún modelo externo.
"""
from __future__ import annotations

import logging
import unicodedata
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path

import yaml

from .ajustes import ajustes

log = logging.getLogger("cerebro.ventas")
PERIODOS = (30, 90, 180, 365, 730)
OTROS = "otros"
MAX_TOP = 25
DEPARTAMENTO = "direccion"


def _plano(t) -> str:
    return " ".join("".join(c for c in unicodedata.normalize("NFD", str(t or "").lower()) if unicodedata.category(c) != "Mn").split())


@lru_cache(maxsize=2)
def _tipos(ruta: str) -> tuple[dict, ...]:
    try:
        datos = yaml.safe_load(Path(ruta).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return ()
    out = []
    for tid, t in (datos.get("tipos") or {}).items():
        if isinstance(t, dict):
            out.append({"id": str(tid), "nombre": str(t.get("nombre") or tid), "grupos": {_plano(g) for g in t.get("grupos") or []}, "palabras": [_plano(p) for p in t.get("palabras") or [] if _plano(p)]})
    return tuple(out)


def tipos() -> tuple[dict, ...]:
    return _tipos(str(Path(ajustes.dir_config) / "tipos_producto.yaml"))


def clasificar(linea: dict, catalogo: tuple[dict, ...]) -> str:
    """El id del tipo de una línea: por grupo de artículo y, si no, por palabras del nombre; «otros» si no encaja. Pura."""
    grupo = _plano(linea.get("item_group"))
    for t in catalogo:
        if grupo and grupo in t["grupos"]:
            return t["id"]
    texto = f" {_plano(linea.get('item_name'))} {_plano(linea.get('item_code'))} "
    for t in catalogo:
        if any(p in texto for p in t["palabras"]):
            return t["id"]
    return OTROS


def _num(v) -> Decimal:
    try:
        return Decimal(str(v if v not in (None, "") else 0))
    except InvalidOperation:
        return Decimal(0)


def _orden(d: dict):
    return (-d["importe"], -d["unidades"], d["nombre"])


def ranking(lineas: list[dict], catalogo: tuple[dict, ...], top: int = 10) -> dict:
    """Por tipo: total vendido, y los `top` artículos y fabricantes con más importe. Pura (no toca el ERP). Los importes salen como texto con dos decimales."""
    top = max(1, min(int(top or 10), MAX_TOP))
    nombres = {t["id"]: t["nombre"] for t in catalogo} | {OTROS: "Otros (sin tipo)"}
    por_tipo: dict[str, dict] = {}
    for l in lineas:
        tid = clasificar(l, catalogo)
        g = por_tipo.setdefault(tid, {"importe": Decimal(0), "unidades": Decimal(0), "pedidos": set(), "articulos": {}, "marcas": {}})
        imp, uds = _num(l.get("importe")), _num(l.get("qty"))
        g["importe"] += imp
        g["unidades"] += uds
        g["pedidos"].add(l.get("name"))
        a = g["articulos"].setdefault(l.get("item_code") or "?", {"codigo": l.get("item_code") or "?", "nombre": str(l.get("item_name") or l.get("item_code") or "?")[:120],
                                                                     "marca": str(l.get("brand") or "").strip(), "importe": Decimal(0), "unidades": Decimal(0)})
        a["importe"] += imp
        a["unidades"] += uds
        marca = str(l.get("brand") or "").strip() or "(sin marca)"
        m = g["marcas"].setdefault(_plano(marca), {"nombre": marca, "importe": Decimal(0), "unidades": Decimal(0)})
        m["importe"] += imp
        m["unidades"] += uds
    total = sum((g["importe"] for g in por_tipo.values()), Decimal(0))
    fmt = lambda d: str(d.quantize(Decimal("0.01")))   # noqa: E731
    salida = []
    for tid, g in sorted(por_tipo.items(), key=lambda kv: (-kv[1]["importe"], kv[0])):
        salida.append({
            "tipo": tid, "nombre": nombres.get(tid, tid), "importe": fmt(g["importe"]), "unidades": fmt(g["unidades"]), "pedidos": len(g["pedidos"]),
            "cuota_pct": fmt(g["importe"] * 100 / total) if total else "0.00",
            "articulos": [{**{k: a[k] for k in ("codigo", "nombre", "marca")}, "importe": fmt(a["importe"]), "unidades": fmt(a["unidades"])} for a in sorted(g["articulos"].values(), key=lambda a: _orden({**a, "nombre": a["nombre"]}))[:top]],
            "fabricantes": [{"nombre": m["nombre"], "importe": fmt(m["importe"]), "unidades": fmt(m["unidades"])} for m in sorted(g["marcas"].values(), key=_orden)[:top]],
        })
    return {"tipos": salida, "total": fmt(total), "lineas": len(lineas)}


def periodo(dias: int, hoy: date | None = None) -> tuple[str, str]:
    if dias not in PERIODOS:
        raise ValueError(f"El periodo debe ser uno de {', '.join(map(str, PERIODOS))} días")
    hoy = hoy or date.today()
    hasta = hoy + timedelta(days=1)
    return (hasta - timedelta(days=dias)).isoformat(), hasta.isoformat()


def texto_diagnostico(total: int, confirmados: int, borradores: int) -> str:
    """Por qué no sale nada, dicho con los números de pedidos que hay en el ERP en el periodo. Pura."""
    if total == 0:
        return "En el ERP no hay ningún pedido de venta con fecha en este periodo. Si facturas sin crear antes el pedido, estas ventas no se cuentan: habría que leer las facturas de venta."
    if confirmados == 0:
        return f"Hay {total} pedidos de venta en el periodo pero ninguno confirmado ({borradores} en borrador): solo se cuentan los confirmados (Submitted)."
    return (f"Hay {confirmados} pedidos confirmados en el periodo, pero la consulta no ha devuelto sus líneas (artículos). Puede ser un permiso de ERPNext sobre las líneas del pedido; "
            "avísanos con este mensaje.")


async def diagnostico(desde: str, hasta: str, contar=None) -> str | None:
    """Cuenta los pedidos de venta del periodo (todos, confirmados y en borrador) para explicar un resultado vacío. None si ni eso se puede leer."""
    if contar is None:
        from .herramientas import erpnext

        async def contar(filtros):
            return int(await erpnext.metrica(DEPARTAMENTO, "Sales Order", filtros, "contar", campo_fecha="transaction_date", desde=desde, hasta=hasta, ttl=0))
    try:
        total, confirmados, borradores = await contar([]), await contar([["docstatus", "=", 1]]), await contar([["docstatus", "=", 0]])
    except Exception as e:  # noqa: BLE001 — es solo una ayuda: si falla, el resultado vacío se enseña igual
        log.info("ventas: no se ha podido diagnosticar el resultado vacío: %s", type(e).__name__)
        return None
    return texto_diagnostico(int(total), int(confirmados), int(borradores))


async def obtener(dias: int = 365, top: int = 10, leer=None, catalogo: tuple[dict, ...] | None = None, hoy: date | None = None, contar=None) -> dict:
    """El ranking de ventas de los últimos `dias` días. `leer` es la lectura del ERP (por defecto la real; inyectable para probar)."""
    desde, hasta = periodo(dias, hoy)
    if leer is None:
        from .herramientas import erpnext
        leer = erpnext.lineas_de_pedidos
    lineas = await leer(DEPARTAMENTO, desde, hasta)
    cat = catalogo if catalogo is not None else tipos()
    r = ranking(lineas, cat, top)
    sin_tipo = next((t for t in r["tipos"] if t["tipo"] == OTROS), None)
    aviso = None
    if sin_tipo and r["tipos"] and float(sin_tipo["cuota_pct"]) > 25:
        aviso = f"El {sin_tipo['cuota_pct']} % de lo vendido no encaja en ningún tipo: ajusta config/tipos_producto.yaml (grupos y palabras)"
    if not lineas:
        aviso = await diagnostico(desde, hasta, contar) or aviso
    return {**r, "dias": dias, "desde": desde, "hasta": hasta, "aviso": aviso, "moneda": "moneda de la empresa (importe neto de pedidos confirmados)"}
