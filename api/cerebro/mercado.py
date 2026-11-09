"""Precios de la competencia y del mercado para proponer precios de venta (paso 4 de docs/PRECIOS_PROVEEDORES.md).

Un agente (o una persona) BUSCA precios de un producto en internet, en otras tarifas o en adjudicaciones, y los ANOTA aquí con su fuente y su fecha. El sistema no se fía de la cifra: la guarda como una referencia
con su origen para que Dirección la vea, y el cálculo de las estrategias de precio (`precios.estrategias_de_precio`) lo hace el código. Ninguna cifra se inventa: sin fuente no se anota.
  - tipo `tienda` | `distribuidor` | `tarifa`: precio unitario de un producto concreto (de tiendas y distribuidores en internet o de la tarifa de otro proveedor). Cuentan para las estrategias.
  - tipo `adjudicacion`: importe de un contrato público que incluye este producto. NO es un precio unitario (un contrato suma muchos conceptos): se muestra como contexto y no entra en las estrategias.
Un precio de tienda lleva IVA: se le quita (`mercado.iva_pct`) para compararlo con los nuestros, que van sin IVA. Un precio con más de `mercado.max_dias` días no cuenta.
"""
from __future__ import annotations

import logging
import re
import statistics
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from urllib.parse import urlparse

from psycopg.types.json import Jsonb  # noqa: F401 — (reservado: notas estructuradas)

from . import listas_precios as LP, precios

log = logging.getLogger("cerebro.mercado")
TIPOS = ("tienda", "distribuidor", "tarifa", "adjudicacion")
CENT = Decimal("0.01")


class ErrorMercado(ValueError):
    """Lo que la referencia no admite; el mensaje es para quien la anota."""


def _precio(v) -> Decimal:
    try:
        d = Decimal(str(v).replace(",", ".").strip())
    except InvalidOperation:
        raise ErrorMercado(f"«{str(v)[:30]}» no es un precio") from None
    if not Decimal("0.01") <= d < Decimal("10000000"):
        raise ErrorMercado("El precio debe ser mayor que 0 y razonable")
    return d.quantize(CENT, rounding=ROUND_HALF_UP)


def validar(tipo, precio, fuente, url=None, moneda="EUR", iva_incluido_pct=None, fecha=None, nota=None, hoy: date | None = None, iva_defecto: Decimal = Decimal(21)) -> dict:
    """La referencia normalizada: precio SIN IVA en euros, con su fuente y su fecha. Pura (sin base de datos)."""
    hoy = hoy or date.today()
    if tipo not in TIPOS:
        raise ErrorMercado("tipo debe ser: " + ", ".join(TIPOS))
    fuente = re.sub(r"\s+", " ", str(fuente or "")).strip()
    if len(fuente) < 3:
        raise ErrorMercado("Hace falta la fuente (la tienda, el distribuidor, la licitación…): sin fuente no se anota un precio")
    if str(moneda or "EUR").upper() != "EUR":
        raise ErrorMercado("Anota el precio en euros (si es en otra moneda, conviértelo y di cómo en la nota)")
    if url:
        u = urlparse(str(url))
        if u.scheme != "https" or not u.hostname or len(str(url)) > 500:
            raise ErrorMercado("url debe ser un enlace https")
    try:
        f = date.fromisoformat(str(fecha)) if fecha else hoy
    except ValueError:
        raise ErrorMercado("fecha debe ser aaaa-mm-dd") from None
    if f > hoy:
        raise ErrorMercado("La fecha del precio no puede ser futura")
    p = _precio(precio)
    iva = iva_incluido_pct
    if iva is None:
        iva = iva_defecto if tipo == "tienda" else Decimal(0)         # los precios de tienda llevan IVA; los de tarifas y distribuidores profesionales, no
    iva = Decimal(str(iva))
    if not Decimal(0) <= iva < 50:
        raise ErrorMercado("iva_incluido_pct es el IVA que lleva el precio (p. ej. 21); 0 si va sin IVA")
    sin_iva = (p / (1 + iva / 100)).quantize(CENT, rounding=ROUND_HALF_UP)
    return {"tipo": tipo, "fuente": fuente[:200], "url": str(url)[:500] if url else None, "precio": str(p), "iva_incluido_pct": str(iva), "precio_sin_iva": str(sin_iva), "fecha": f.isoformat(),
            "nota": re.sub(r"\s+", " ", str(nota or "")).strip()[:300] or None}


def estadisticas(refs: list[dict], max_dias: int, hoy: date | None = None) -> dict | None:
    """{n, minimo, mediana, maximo, mas_reciente, antiguas, contexto} de las referencias que cuentan (precio unitario, no más viejo que `max_dias`). Sin ninguna, None. Pura."""
    hoy = hoy or date.today()
    validas, antiguas = [], 0
    contexto = [r for r in refs if r["tipo"] == "adjudicacion"]
    for r in refs:
        if r["tipo"] == "adjudicacion":
            continue
        f = r["fecha"] if isinstance(r["fecha"], date) else date.fromisoformat(str(r["fecha"]))
        if (hoy - f).days > max_dias:
            antiguas += 1
            continue
        validas.append((Decimal(str(r["precio_sin_iva"])), f))
    if not validas:
        return {"n": 0, "antiguas": antiguas, "contexto": len(contexto)} if (antiguas or contexto) else None
    ps = sorted(p for p, _ in validas)
    return {"n": len(ps), "minimo": str(ps[0].quantize(CENT)), "mediana": str(Decimal(str(statistics.median(ps))).quantize(CENT, rounding=ROUND_HALF_UP)), "maximo": str(ps[-1].quantize(CENT)),
            "mas_reciente": max(f for _, f in validas).isoformat(), "antiguas": antiguas, "contexto": len(contexto)}


async def anotar(codigo: str, tipo: str, precio, fuente: str, agente: str, url=None, iva_incluido_pct=None, fecha=None, nota=None, moneda="EUR") -> dict:
    cfg = precios.configuracion()
    codigo = str(codigo or "").strip()
    from . import precios_venta as V
    ofertas, _ = await V._ofertas()
    if codigo not in ofertas:
        raise ErrorMercado("Ese código de artículo no tiene coste cargado: usa el código que sale en la propuesta de precios (marca + referencia)")
    r = validar(tipo, precio, fuente, url, moneda, iva_incluido_pct, fecha, nota, iva_defecto=cfg["mercado"]["iva_pct"])
    async with await LP._conectar() as conn:
        cur = await conn.execute(
            "INSERT INTO referencias_mercado (codigo, tipo, fuente, url, precio, iva_incluido_pct, precio_sin_iva, fecha, nota, agente) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            [codigo, r["tipo"], r["fuente"], r["url"], r["precio"], r["iva_incluido_pct"], r["precio_sin_iva"], r["fecha"], r["nota"], agente])
        rid = (await cur.fetchone())["id"]
    log.info("mercado: %s anota %s %s (%s) para %s", agente, r["precio"], r["tipo"], r["fuente"], codigo)
    return {"referencia": rid, "codigo": codigo, **r}


async def listar(codigo: str | None = None, limite: int = 50) -> dict:
    limite = min(max(int(limite), 1), 200) if isinstance(limite, int) and not isinstance(limite, bool) else 50
    async with await LP._conectar() as conn:
        cur = await conn.execute("SELECT id, codigo, tipo, fuente, url, precio, iva_incluido_pct, precio_sin_iva, fecha, nota, agente FROM referencias_mercado WHERE retirada = false"
                                 + (" AND codigo = %s" if codigo else "") + " ORDER BY fecha DESC, id DESC LIMIT %s", ([codigo] if codigo else []) + [limite])
        filas = await cur.fetchall()
    cfg = precios.configuracion()
    for f in filas:
        for k in ("precio", "iva_incluido_pct", "precio_sin_iva"):
            f[k] = str(f[k])
        f["fecha"] = f["fecha"].isoformat()
    return {"referencias": filas, "estadisticas": estadisticas(filas, cfg["mercado"]["max_dias"]) if codigo else None,
            "nota": "Son datos anotados por agentes o personas con su fuente: Dirección debe poder comprobarlos. Las adjudicaciones son contexto, no precio unitario."}


async def retirar(referencia: int) -> dict:
    async with await LP._conectar() as conn:
        cur = await conn.execute("UPDATE referencias_mercado SET retirada = true WHERE id = %s AND retirada = false RETURNING id", [referencia if isinstance(referencia, int) and not isinstance(referencia, bool) else -1])
        if not await cur.fetchone():
            raise ErrorMercado("No existe esa referencia (o ya estaba retirada)")
    return {"referencia": referencia, "retirada": True}


async def de_codigos(codigos: list[str]) -> dict[str, list[dict]]:
    """Las referencias vigentes de cada artículo, para calcular las estrategias de una propuesta."""
    out: dict[str, list[dict]] = {}
    for i in range(0, len(codigos), 500):
        async with await LP._conectar() as conn:
            cur = await conn.execute("SELECT codigo, tipo, precio_sin_iva, fecha FROM referencias_mercado WHERE retirada = false AND codigo = ANY(%s)", [codigos[i:i + 500]])
            for f in await cur.fetchall():
                out.setdefault(f["codigo"], []).append({"tipo": f["tipo"], "precio_sin_iva": str(f["precio_sin_iva"]), "fecha": f["fecha"]})
    return out
