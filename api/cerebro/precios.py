"""Precios de venta a partir del coste: márgenes por familia SOBRE LA VENTA, redondeo y coste en euros de cada canal de compra (config/precios.yaml).

Todo es CÓDIGO DETERMINISTA con `Decimal`: la IA no calcula importes (la propuesta de los agentes se apoya en esto y en referencias de mercado con su fuente). Es PURO: no toca base de datos ni red.

El margen es sobre la venta: `venta = coste ÷ (1 − margen)`. Con coste 100 y margen 50 %, la venta es 200; un «recargo del 50 % sobre el coste» sería 150, que equivale a un margen del 33,3 % sobre la venta.
Los precios de los proveedores y los de venta son SIN IVA.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from pathlib import Path

import yaml

from .ajustes import ajustes

CENT = Decimal("0.01")
MARGEN_MAX = Decimal("0.95")
DEFECTO = {"margen": {"base": "venta", "por_defecto": 0.50, "minimo": 0.10, "familias": {}}, "redondeo": {"modo": "centimo", "terminacion": 0.90},
           "canales": {"fabricante": {"moneda": "USD", "logistica_pct": None}, "distribuidor": {"moneda": "EUR", "logistica_pct": 0}},
           "cambio_a_eur": {"USD": None, "GBP": None}, "provisional": []}


class ErrorPrecios(ValueError):
    """Un dato que no permite calcular; el mensaje es para la persona."""


def norm(t) -> str:
    t = unicodedata.normalize("NFKD", str(t if t is not None else "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", t)).strip()


def _d(v, nombre: str) -> Decimal | None:
    if v is None or v == "":
        return None
    try:
        d = Decimal(str(v))
    except Exception:  # noqa: BLE001
        raise ErrorPrecios(f"{nombre} no es un número: «{v}»") from None
    if not d.is_finite():
        raise ErrorPrecios(f"{nombre} no es un número: «{v}»")
    return d


def configuracion(cfg: dict | None = None) -> dict:
    """La configuración validada (config/precios.yaml, o la que se pase). Un valor imposible (margen del 100 %, redondeo desconocido) es un error claro, no un precio raro."""
    if cfg is None:
        try:
            cfg = yaml.safe_load((Path(ajustes.dir_config) / "precios.yaml").read_text(encoding="utf-8")) or {}
        except OSError:
            cfg = {}
    m = {**DEFECTO["margen"], **(cfg.get("margen") or {})}
    if m.get("base", "venta") != "venta":
        raise ErrorPrecios("Solo se calcula el margen sobre la venta (base: venta)")
    for k in ("por_defecto", "minimo"):
        v = _d(m.get(k), f"margen.{k}")
        if v is None or not Decimal(0) <= v <= MARGEN_MAX:
            raise ErrorPrecios(f"margen.{k} debe estar entre 0 y {MARGEN_MAX} (0.50 = 50 % de la venta)")
        m[k] = v
    fam = {}
    for nombre, v in (m.get("familias") or {}).items():
        d = _d(v, f"margen de «{nombre}»")
        if d is None or not Decimal(0) <= d <= MARGEN_MAX:
            raise ErrorPrecios(f"El margen de «{nombre}» debe estar entre 0 y {MARGEN_MAX}")
        fam[norm(nombre)] = d
    m["familias"] = fam
    r = {**DEFECTO["redondeo"], **(cfg.get("redondeo") or {})}
    if r["modo"] not in ("centimo", "euro", "terminar_en"):
        raise ErrorPrecios("redondeo.modo debe ser centimo, euro o terminar_en")
    r["terminacion"] = _d(r.get("terminacion"), "redondeo.terminacion") or Decimal("0.90")
    if not Decimal(0) <= r["terminacion"] < 1:
        raise ErrorPrecios("redondeo.terminacion debe estar entre 0 y 0,99")
    canales = {}
    for nombre, c in {**DEFECTO["canales"], **(cfg.get("canales") or {})}.items():
        canales[nombre] = {"moneda": str((c or {}).get("moneda") or "EUR").upper(), "logistica_pct": _d((c or {}).get("logistica_pct"), f"logística de «{nombre}»")}
    cambio = {str(k).upper(): _d(v, f"cambio {k}") for k, v in {**DEFECTO["cambio_a_eur"], **(cfg.get("cambio_a_eur") or {})}.items()}
    return {"margen": m, "redondeo": r, "canales": canales, "cambio_a_eur": cambio, "provisional": list(cfg.get("provisional") or [])}


def margen_de(familia: str, cfg: dict) -> Decimal:
    """El margen de una familia (por nombre, sin importar tildes ni mayúsculas) o el general. Con una jerarquía («Accesorios / Cableado / RJ45») se prueba el camino completo y luego cada camino más corto
    («Accesorios / Cableado», «Accesorios»): manda el más concreto que figure en la configuración."""
    partes = [p.strip() for p in re.split(r"\s*/\s*", str(familia or "")) if p.strip()]
    for n in range(len(partes), 0, -1):
        clave = norm(" / ".join(partes[:n]))
        if clave in cfg["margen"]["familias"]:
            return cfg["margen"]["familias"][clave]
    return cfg["margen"]["por_defecto"]


def coste_en_euros(coste, moneda: str, canal: str, cfg: dict) -> tuple[Decimal, list[str]]:
    """El coste de un producto YA EN EUROS y con la logística de su canal: `coste × cambio × (1 + logística)`. Devuelve (coste, avisos). Sin tipo de cambio para esa moneda es un error: no se adivina."""
    c = _d(coste, "El coste")
    if c is None or c <= 0:
        raise ErrorPrecios("El coste debe ser mayor que cero")
    avisos: list[str] = []
    moneda = (moneda or cfg["canales"].get(canal, {}).get("moneda") or "EUR").upper()
    if moneda != "EUR":
        cambio = cfg["cambio_a_eur"].get(moneda)
        if cambio is None or cambio <= 0:
            raise ErrorPrecios(f"Falta el tipo de cambio de {moneda} a EUR (cambio_a_eur en config/precios.yaml)")
        c = c * cambio
        if f"cambio_a_eur.{moneda}" in cfg["provisional"]:
            avisos.append(f"cambio {moneda}→EUR provisional")
    log = (cfg["canales"].get(canal) or {}).get("logistica_pct")
    if log is None:
        avisos.append(f"sin logística del canal «{canal}»: no se ha sumado nada")
    else:
        c = c * (1 + log)
        if f"canales.{canal}.logistica_pct" in cfg["provisional"]:
            avisos.append(f"logística de «{canal}» provisional")
    return c, avisos


def precio_venta(coste_eur: Decimal, margen: Decimal) -> Decimal:
    """`coste ÷ (1 − margen)`, sin redondear."""
    if not Decimal(0) <= margen <= MARGEN_MAX:
        raise ErrorPrecios("El margen debe estar entre 0 y 0,95")
    return coste_eur / (1 - margen)


def redondear(precio: Decimal, cfg: dict) -> Decimal:
    """Según config: al céntimo, hacia arriba a euros enteros, o hacia arriba hasta acabar en la terminación (…,90 / …,99). Hacia arriba nunca baja el margen."""
    modo = cfg["redondeo"]["modo"]
    if modo == "centimo":
        return precio.quantize(CENT, rounding=ROUND_HALF_UP)
    if modo == "euro":
        return precio.quantize(Decimal(1), rounding=ROUND_CEILING)
    t = cfg["redondeo"]["terminacion"]
    base = precio.quantize(Decimal(1), rounding=ROUND_FLOOR) + t
    return (base if base >= precio else base + 1).quantize(CENT)


@dataclass
class Calculo:
    coste_eur: Decimal
    margen_objetivo: Decimal
    venta: Decimal
    margen_real: Decimal                # sobre la venta, con el precio ya redondeado
    recargo_sobre_coste: Decimal        # lo mismo expresado sobre la compra: (venta − coste) ÷ coste
    avisos: list[str] = field(default_factory=list)


def calcular(coste, moneda: str, canal: str, familia: str, cfg: dict, margen: Decimal | None = None) -> Calculo:
    """Del coste de compra al precio de venta: coste en euros (cambio y logística del canal), margen de la familia (o el indicado), redondeo y las dos formas de decir cuánto se gana."""
    c, avisos = coste_en_euros(coste, moneda, canal, cfg)
    m = margen if margen is not None else margen_de(familia, cfg)
    if f"margen.por_defecto" in cfg["provisional"] and margen is None and norm(familia) not in cfg["margen"]["familias"]:
        avisos.append("margen general provisional")
    venta = redondear(precio_venta(c, m), cfg)
    real = (venta - c) / venta
    if real < cfg["margen"]["minimo"]:
        avisos.append(f"margen por debajo del mínimo ({cfg['margen']['minimo'] * 100:.0f} %)")
    return Calculo(coste_eur=c.quantize(CENT, rounding=ROUND_HALF_UP), margen_objetivo=m, venta=venta, margen_real=real.quantize(Decimal("0.0001")),
                   recargo_sobre_coste=((venta - c) / c).quantize(Decimal("0.0001")), avisos=avisos)


def mejor_coste(ofertas: list[dict], cfg: dict, solo_con_stock: bool = True) -> dict | None:
    """De varios proveedores del mismo producto, el de menor coste YA EN EUROS (con logística). Cada oferta: {proveedor, canal, coste, moneda, stock?}. Con `solo_con_stock`, prefiere los que tienen stock y,
    si ninguno lo tiene, elige entre todos. Devuelve la oferta elegida con `coste_eur` y los avisos, o None si no hay ninguna calculable."""
    calculables = []
    for o in ofertas:
        try:
            c, av = coste_en_euros(o["coste"], o.get("moneda", ""), o.get("canal", ""), cfg)
        except ErrorPrecios:
            continue
        calculables.append({**o, "coste_eur": c, "avisos": av})
    if not calculables:
        return None
    if solo_con_stock:
        con = [o for o in calculables if o.get("stock") is not None and Decimal(str(o["stock"])) > 0]
        calculables = con or calculables
    return min(calculables, key=lambda o: o["coste_eur"])
