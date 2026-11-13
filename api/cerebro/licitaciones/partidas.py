"""Partidas de equipos de una oferta y su coste real con las tarifas de proveedor.

Une tres cosas que ya existen: lo que la tabla de equivalencias recomienda para cada parámetro del pliego, las tarifas de proveedor cargadas (con su moneda, cambio del día y logística: `precios`) y la cantidad
que pone una persona. Sale una tabla de partidas (producto, cantidad, coste unitario en euros, proveedor, subtotal) con totales, y un coste de referencia para Costes y Precio.

Reglas:
  · El COSTE lo calcula el código (`precios.mejor_coste` y `precios.calcular`, con cambio y logística); ningún modelo escribe una cifra.
  · Las tarifas son CONFIDENCIALES: el coste no se guarda en la oferta (se recalcula al leer, así nunca hay copias viejas) y el texto que lo lleva (`texto_para`) solo se le da al modelo LOCAL de Costes y de Precio.
    Nunca a Claude ni a ChatGPT, elijas lo que elijas en el selector de pasos.
  · Un producto que no se encuentra en las tarifas cargadas sale «sin coste en las tarifas»: no se estima ni se inventa. Una cantidad sin poner también se dice: el total solo suma lo completo.
  · Los importes son de referencia: el precio lo fija una persona.
"""
from __future__ import annotations

import logging
import re
from decimal import Decimal, InvalidOperation

from psycopg.types.json import Jsonb

from .. import cambio, precios
from .. import precios_venta as PV
from . import equivalencia as Q
from . import ofertas as O

log = logging.getLogger("cerebro.partidas")
MAX_PARTIDAS = 60
MAX_CANTIDAD = Decimal("1000000")


class ErrorPartida(ValueError):
    pass


def _alnum(t) -> str:
    return re.sub(r"[^a-z0-9]", "", Q.C._norm(t))


def clave_de(producto: str) -> str:
    return _alnum(producto)[:120]


def emparejar(producto: str, ofertas: dict[str, dict[str, dict]]) -> str | None:
    """El código de artículo de las tarifas que corresponde a un producto escrito en texto libre («Milesight MS-C8573»): el de la referencia más larga (mínimo 4 caracteres, sin contar signos) que aparece
    dentro del texto. Si dos artículos distintos empatan, no se elige ninguno (mejor «sin coste» que el producto equivocado). Pura."""
    p = _alnum(producto)
    mejores: dict[str, str] = {}
    for codigo, por_lista in ofertas.items():
        for o in por_lista.values():
            r = _alnum(o.get("ref"))
            if len(r) >= 4 and r in p:
                mejores[codigo] = r
    if not mejores:
        return None
    mayor = max(len(r) for r in mejores.values())
    top = sorted(c for c, r in mejores.items() if len(r) == mayor)
    if len(top) > 1:
        marcas = [c for c in top if _alnum(next(iter(ofertas[c].values())).get("marca")) and _alnum(next(iter(ofertas[c].values())).get("marca")) in p]
        top = marcas if len(marcas) == 1 else top
    return top[0] if len(top) == 1 else None


def costear(codigo: str | None, ofertas: dict[str, dict[str, dict]], cfg: dict) -> dict:
    """El mejor coste (ya en euros, con logística y cambio) y la venta de referencia de un artículo. Pura. Sin código o sin coste calculable: {coste_unit_eur: None, motivo}."""
    if not codigo or codigo not in ofertas:
        return {"coste_unit_eur": None, "motivo": "No está en las tarifas cargadas"}
    mejor = precios.mejor_coste(list(ofertas[codigo].values()), cfg)
    if mejor is None:
        return {"coste_unit_eur": None, "motivo": "Hay tarifa pero no se puede calcular el coste (falta el cambio o el coste no es válido)"}
    c = precios.calcular(mejor["coste"], mejor["moneda"], mejor["canal"], mejor.get("familia") or "", cfg)
    return {"coste_unit_eur": c.coste_eur, "venta_unit_eur": c.venta, "proveedor": mejor["proveedor"], "canal": mejor["canal"], "moneda": mejor["moneda"], "coste_origen": str(mejor["coste"]),
            "stock": mejor.get("stock"), "ref": mejor.get("ref"), "marca": mejor.get("marca"), "ofertas": len(ofertas[codigo]),
            "avisos": list(dict.fromkeys([*c.avisos, *mejor.get("avisos", [])]))[:4], "motivo": ""}


def _dec(v) -> Decimal | None:
    if v is None or v == "":
        return None
    try:
        d = Decimal(str(v).replace(",", "."))
    except InvalidOperation:
        raise ErrorPartida("La cantidad no es un número") from None
    if d < 0 or d > MAX_CANTIDAD or not d.is_finite():
        raise ErrorPartida(f"La cantidad debe estar entre 0 y {MAX_CANTIDAD:,.0f}".replace(",", "."))
    return d


def calcular_filas(partidas: list[dict], ofertas: dict, cfg: dict) -> list[dict]:
    """Cada partida con su coste. Pura."""
    out = []
    for p in partidas:
        codigo = emparejar(p["producto"], ofertas)
        c = costear(codigo, ofertas, cfg)
        cant = None if p.get("cantidad") is None else Decimal(str(p["cantidad"]))
        unit = c["coste_unit_eur"]
        out.append({**{k: p[k] for k in ("id", "producto", "parametros", "origen", "excluida")}, "cantidad": None if cant is None else str(cant), "codigo": codigo, **{k: (str(v) if isinstance(v, Decimal) else v) for k, v in c.items()},
                    "subtotal_eur": None if (unit is None or cant is None) else str((unit * cant).quantize(Decimal("0.01")))})
    return out


def totales(filas: list[dict]) -> dict:
    """El total de coste y de venta de referencia de lo COMPLETO (con cantidad y coste, y no excluido), y lo que falta. Pura."""
    vivas = [f for f in filas if not f["excluida"]]
    coste = venta = Decimal("0")
    completas, sin_coste, sin_cantidad = 0, [], []
    for f in vivas:
        if f.get("coste_unit_eur") is None:
            sin_coste.append(f["producto"])
        elif f["cantidad"] is None:
            sin_cantidad.append(f["producto"])
        else:
            completas += 1
            cant = Decimal(f["cantidad"])
            coste += Decimal(f["coste_unit_eur"]) * cant
            venta += Decimal(f["venta_unit_eur"]) * cant
    return {"coste_eur": str(coste.quantize(Decimal("0.01"))), "venta_referencia_eur": str(venta.quantize(Decimal("0.01"))), "partidas": len(vivas), "completas": completas,
            "sin_coste": sin_coste, "sin_cantidad": sin_cantidad, "completo": bool(vivas) and not sin_coste and not sin_cantidad}


def texto_de_partidas(filas: list[dict], tot: dict, maximo: int = 3000) -> str:
    """Las partidas como texto para el modelo LOCAL de Costes y de Precio. CONFIDENCIAL. Pura."""
    if not filas:
        return ""
    lineas = []
    for f in filas:
        if f["excluida"]:
            continue
        if f.get("coste_unit_eur") is None:
            lineas.append(f"- {f['producto']}: SIN COSTE EN LAS TARIFAS ({f.get('motivo')}); cantidad {f['cantidad'] or 'sin poner'}")
            continue
        av = f" · avisos: {'; '.join(f['avisos'])}" if f.get("avisos") else ""
        sub = f"{f['subtotal_eur']} €" if f["subtotal_eur"] else "falta la cantidad"
        lineas.append(f"- {f['producto']} ({f.get('ref') or f['codigo']}): coste unitario {Decimal(f['coste_unit_eur']):.2f} € ({f['proveedor']}, {f['canal']}, {f['moneda']}) × {f['cantidad'] or '?'} = {sub}{av}")
    cab = ("COSTE DE LOS EQUIPOS (CONFIDENCIAL: tarifas de proveedor, calculadas por el sistema con el cambio del día y la logística; solo para ti, no las copies a ningún texto que salga de la empresa). "
           "Usa estas cifras tal cual: no las recalcules ni inventes otras; lo que diga «SIN COSTE» o «sin poner» es un dato pendiente, márcalo como tal.")
    pie = (f"Total coste de lo completo ({tot['completas']} de {tot['partidas']} partidas): {tot['coste_eur']} € · venta de referencia con el margen de la familia: {tot['venta_referencia_eur']} € (sin IVA)."
           + ("" if tot["completo"] else " TOTAL INCOMPLETO: faltan partidas por costear o sin cantidad."))
    return (cab + "\n" + "\n".join(lineas) + "\n" + pie)[:maximo]


# ---------------------------------------------------------------- base de datos
async def _partidas(motor_id: str) -> list[dict]:
    async with await O._conectar() as conn:
        cur = await conn.execute("SELECT id, producto, parametros, cantidad, origen, excluida FROM ofertas_partidas WHERE motor_id = %s ORDER BY id", [motor_id])
        return await cur.fetchall()


async def _material():
    ofertas, _sin_tarifa = await PV._ofertas()
    return ofertas, await cambio.configuracion_de_precios()


async def listar(motor_id: str) -> dict:
    motor_id = O._id(motor_id)
    partidas = await _partidas(motor_id)
    try:
        ofertas, cfg = await _material()
        filas = calcular_filas(partidas, ofertas, cfg)
        aviso = "" if ofertas else "No hay tarifas de proveedor cargadas: no se puede calcular ningún coste."
    except Exception as e:      # noqa: BLE001 — sin tarifas se enseñan las partidas sin coste
        log.warning("partidas de %s: no se han podido leer las tarifas: %s: %s", motor_id, type(e).__name__, e)
        filas = [{**{k: p[k] for k in ("id", "producto", "parametros", "origen", "excluida")}, "cantidad": None if p["cantidad"] is None else str(p["cantidad"]), "codigo": None, "coste_unit_eur": None,
                  "motivo": "No se han podido leer las tarifas", "subtotal_eur": None} for p in partidas]
        aviso = f"No se han podido leer las tarifas de proveedor ({type(e).__name__})."
    return {"partidas": filas, "totales": totales(filas), "aviso": aviso}


def desde_equivalencia(contenido: dict) -> list[dict]:
    """Los productos que la tabla recomienda (uno por parámetro, ya verificado por el código), agrupados por producto con los parámetros que cubren. Pura."""
    por: dict[str, dict] = {}
    for p in (contenido or {}).get("parametros", []):
        rec = (p.get("recomendado") or "").strip()
        if not rec or not clave_de(rec):
            continue
        d = por.setdefault(clave_de(rec), {"producto": rec, "parametros": []})
        d["parametros"].append(f"{p['parametro']} {p.get('valor_exigido', '')}".strip())
    return list(por.values())[:MAX_PARTIDAS]


async def proponer(motor_id: str, por: str) -> dict:
    """Rellena las partidas con lo que recomienda la tabla de equivalencias. Lo que una persona ya haya tocado (cantidad, exclusión, partidas a mano) se conserva."""
    motor_id = O._id(motor_id)
    eq = await Q.leer(motor_id)
    if not eq:
        raise ErrorPartida("Primero hace falta la tabla de equivalencias (pulsa «Preparar la oferta» o repite ese paso)")
    nuevas = desde_equivalencia(eq["contenido"])
    if not nuevas:
        raise ErrorPartida("La tabla de equivalencias no recomienda ningún producto verificado: no hay nada que costear")
    async with await O._conectar() as conn:
        async with conn.transaction():
            claves = []
            for n in nuevas:
                k = clave_de(n["producto"])
                claves.append(k)
                await conn.execute(
                    "INSERT INTO ofertas_partidas (motor_id, clave, producto, parametros, origen, por) VALUES (%s,%s,%s,%s,'equivalencia',%s) "
                    "ON CONFLICT (motor_id, clave) DO UPDATE SET parametros = EXCLUDED.parametros, actualizado = now()", [motor_id, k, n["producto"][:160], Jsonb(n["parametros"][:10]), str(por)[:200]])
            await conn.execute("DELETE FROM ofertas_partidas WHERE motor_id = %s AND origen = 'equivalencia' AND cantidad IS NULL AND NOT (clave = ANY(%s))", [motor_id, claves])
    return await listar(motor_id)


async def anadir(motor_id: str, producto: str, cantidad, por: str) -> dict:
    motor_id = O._id(motor_id)
    producto = " ".join(str(producto or "").split())[:160]
    if not clave_de(producto):
        raise ErrorPartida("Indica el producto (marca y referencia)")
    cant = _dec(cantidad)
    async with await O._conectar() as conn:
        cur = await conn.execute("SELECT count(*) AS n FROM ofertas_partidas WHERE motor_id = %s", [motor_id])
        if (await cur.fetchone())["n"] >= MAX_PARTIDAS:
            raise ErrorPartida(f"Hay ya {MAX_PARTIDAS} partidas: es el máximo")
        await conn.execute("INSERT INTO ofertas_partidas (motor_id, clave, producto, cantidad, origen, por) VALUES (%s,%s,%s,%s,'manual',%s) "
                           "ON CONFLICT (motor_id, clave) DO UPDATE SET cantidad = COALESCE(EXCLUDED.cantidad, ofertas_partidas.cantidad), excluida = false, actualizado = now()",
                           [motor_id, clave_de(producto), producto, cant, str(por)[:200]])
    return await listar(motor_id)


async def ajustar(motor_id: str, partida: int, cantidad=..., excluida: bool | None = None, por: str = "") -> dict:
    """Pone la cantidad (o la quita con None) y/o excluye o recupera una partida."""
    motor_id = O._id(motor_id)
    campos, valores = [], []
    if cantidad is not ...:
        campos.append("cantidad = %s")
        valores.append(_dec(cantidad))
    if excluida is not None:
        campos.append("excluida = %s")
        valores.append(bool(excluida))
    if not campos:
        raise ErrorPartida("No hay nada que cambiar")
    async with await O._conectar() as conn:
        cur = await conn.execute(f"UPDATE ofertas_partidas SET {', '.join(campos)}, por = %s, actualizado = now() WHERE id = %s AND motor_id = %s RETURNING id", [*valores, str(por)[:200], partida, motor_id])
        if not await cur.fetchone():
            raise ErrorPartida("No existe esa partida en esta oferta")
    return await listar(motor_id)


async def quitar(motor_id: str, partida: int) -> dict:
    motor_id = O._id(motor_id)
    async with await O._conectar() as conn:
        await conn.execute("DELETE FROM ofertas_partidas WHERE id = %s AND motor_id = %s", [partida, motor_id])
    return await listar(motor_id)


async def texto_para(motor_id: str) -> str:
    """El coste de los equipos como texto para el modelo LOCAL de Costes y de Precio (vacío si no hay partidas o si algo falla). CONFIDENCIAL: no se usa en ningún camino que salga a un modelo externo."""
    try:
        d = await listar(motor_id)
        return texto_de_partidas(d["partidas"], d["totales"])
    except Exception as e:      # noqa: BLE001
        log.warning("partidas de %s: no se ha podido preparar el texto de costes: %s: %s", motor_id, type(e).__name__, e)
        return ""
