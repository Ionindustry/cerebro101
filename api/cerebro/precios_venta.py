"""Lista de precios de VENTA: del mejor coste de cada producto al precio de venta propuesto, y su aplicación en el ERP SOLO cuando Dirección la aprueba.

Cómo funciona (y por qué):
  - Los costes salen de las tarifas ya cargadas en el ERP (`importaciones_precios` aplicadas con `proponer_tarifa`): por cada artículo (marca + referencia) hay una oferta por proveedor. Se elige el mejor coste YA EN EUROS
    (con la logística y el cambio de su canal; con preferencia por los que tienen stock) y se calcula el precio de venta con el margen de la familia y el redondeo (`precios`). Lo calcula el código, no un modelo.
  - Un agente PROPONE: se guarda la propuesta con, para cada artículo, el coste, el precio calculado, el precio que ya tiene la lista «Venta» en el ERP y la variación. No se escribe nada en el ERP.
  - Dirección puede AJUSTAR precios a mano o EXCLUIR artículos de la propuesta. Un coste o un tipo de cambio que cambian NO cambian ningún precio de venta por sí solos: hay que proponer de nuevo y aprobar.
  - Solo entonces `aplicar` da de alta la lista «Venta» y crea o actualiza los precios que han cambiado, con la clave de Operaciones y la política de «maestros» (config/erp_acceso.yaml). Es repetible.
"""
from __future__ import annotations

import logging
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from psycopg.types.json import Jsonb

from . import cambio, listas_precios as LP, precios

log = logging.getLogger("cerebro.precios_venta")
CENT = Decimal("0.01")
TOLERANCIA = Decimal("0.005")
MAX_LINEAS = 20000


class ErrorVenta(ValueError):
    """Lo que la propuesta no admite; el mensaje es para quien la pidió."""


def _dec(v, nombre: str) -> Decimal:
    try:
        d = Decimal(str(v).replace(",", ".")).quantize(CENT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        raise ErrorVenta(f"{nombre}: «{str(v)[:30]}» no es un precio") from None
    if d <= 0 or d >= Decimal("10000000"):
        raise ErrorVenta(f"{nombre}: el precio debe ser mayor que 0 y razonable")
    return d


def _cambio(nuevo: Decimal, actual: Decimal | None) -> tuple[str, str | None]:
    if actual is None:
        return "nuevo", None
    if abs(nuevo - actual) < TOLERANCIA:
        return "igual", "0.0"
    pct = ((nuevo - actual) / actual * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return ("sube" if nuevo > actual else "baja"), str(pct)


async def _ofertas() -> tuple[dict[str, dict[str, dict]], int]:
    """{código: {lista de compra: oferta}} con lo último cargado de cada proveedor, y cuántas importaciones aplicadas no son tarifas (no traen canal ni familia: no sirven)."""
    async with await LP._conectar() as conn:
        cur = await conn.execute("SELECT id, proveedor, moneda, lista, lineas, resumen FROM importaciones_precios WHERE estado = 'aplicada' ORDER BY id")
        filas = await cur.fetchall()
    ofertas: dict[str, dict[str, dict]] = {}
    sin_tarifa = 0
    for f in filas:
        if not (f["resumen"] or {}).get("tarifa"):
            sin_tarifa += 1
            continue
        canal = f["resumen"]["canal"]
        for l in f["lineas"]:
            ofertas.setdefault(l["codigo"], {})[f["lista"]] = {
                "proveedor": f["proveedor"]["nombre"], "lista": f["lista"], "canal": canal, "coste": l["precio"], "moneda": f["moneda"], "stock": l.get("stock"), "ref": l["ref"], "desc": l["desc"],
                "familia": l.get("familia") or "", "marca": l.get("marca") or ""}
    return ofertas, sin_tarifa


def calcular_lineas(ofertas: dict[str, dict[str, dict]], cfg: dict, actuales: dict[str, Decimal], ajustes: dict[str, Decimal] | None = None, excluir: set[str] | None = None) -> tuple[list[dict], list[str]]:
    """Del mejor coste de cada artículo a su línea de propuesta. Pura (sin ERP ni base de datos)."""
    lineas, avisos, sin_precio = [], [], 0
    for codigo in sorted(ofertas):
        mejor = precios.mejor_coste(list(ofertas[codigo].values()), cfg)
        if mejor is None:
            sin_precio += 1
            continue
        c = precios.calcular(mejor["coste"], mejor["moneda"], mejor["canal"], mejor["familia"], cfg)
        calculado = c.venta
        final = (ajustes or {}).get(codigo)
        venta = final if final is not None else calculado
        margen = ((venta - c.coste_eur) / venta).quantize(Decimal("0.0001"))
        av = list(c.avisos) + list(mejor["avisos"])
        av = list(dict.fromkeys(av))
        if final is not None and margen < cfg["margen"]["minimo"]:
            av.append(f"el precio ajustado deja un margen por debajo del mínimo ({cfg['margen']['minimo'] * 100:.0f} %)")
        actual = actuales.get(codigo)
        tipo, pct = _cambio(venta, actual)
        lineas.append({"codigo": codigo, "ref": mejor["ref"], "desc": mejor["desc"][:140], "familia": mejor["familia"], "marca": mejor["marca"], "proveedor": mejor["proveedor"], "canal": mejor["canal"],
                       "coste": str(mejor["coste"]), "moneda": mejor["moneda"], "coste_eur": str(c.coste_eur), "ofertas": len(ofertas[codigo]), "calculado": str(calculado), "venta": str(venta),
                       "ajustado": final is not None, "excluida": codigo in (excluir or set()), "margen": str(margen), "actual": None if actual is None else str(actual), "cambio": tipo, "variacion_pct": pct, "avisos": av})
    if sin_precio:
        avisos.append(f"{sin_precio} artículos sin coste calculable (falta el tipo de cambio o el coste): no entran en la propuesta")
    return lineas, avisos


def resumir(lineas: list[dict]) -> dict:
    vivas = [l for l in lineas if not l["excluida"]]
    cuenta = {k: sum(1 for l in vivas if l["cambio"] == k) for k in ("nuevo", "sube", "baja", "igual")}
    margenes = sorted(Decimal(l["margen"]) for l in vivas)
    provisional = sorted({a for l in vivas for a in l["avisos"] if "provisional" in a or "respaldo" in a})
    return {"articulos": len(lineas), "incluidos": len(vivas), "excluidos": len(lineas) - len(vivas), **cuenta, "ajustados": sum(1 for l in vivas if l["ajustado"]),
            "margen_min": str(margenes[0]) if margenes else None, "margen_max": str(margenes[-1]) if margenes else None,
            "bajo_minimo": sum(1 for l in vivas if any("por debajo del mínimo" in a for a in l["avisos"])), "provisional": provisional}


async def _actuales(departamento: str, lista: str, codigos: list[str], lote: int) -> dict[str, Decimal]:
    """El precio que ya tiene cada artículo en la lista de venta del ERP (los que no estén, no aparecen)."""
    out: dict[str, Decimal] = {}
    for i in range(0, len(codigos), 80):
        trozo = codigos[i:i + 80]
        for r in await LP.erpnext.listar("Item Price", departamento, filtros=[["price_list", "=", lista], ["item_code", "in", trozo]], campos=["name", "item_code", "price_list_rate"], limite=len(trozo) + 20):
            try:
                out[str(r["item_code"])] = Decimal(str(r.get("price_list_rate")))
            except InvalidOperation:
                continue
    return out


async def proponer(agente: str, departamento: str, ajustes: dict | None = None, excluir: list | None = None, solo_marca: str | None = None) -> dict:
    """Propone los precios de venta de TODOS los artículos con coste cargado (o de una marca). No escribe nada en el ERP."""
    cfg_l = LP.configuracion()
    lista = cfg_l["lista_venta"]
    aj = _ajustes(ajustes)
    exc = _excluir(excluir)
    cfg = await cambio.configuracion_de_precios()
    ofertas, sin_tarifa = await _ofertas()
    if solo_marca:
        ofertas = {k: {l: o for l, o in v.items() if o["marca"].lower() == str(solo_marca).lower()} for k, v in ofertas.items()}
        ofertas = {k: v for k, v in ofertas.items() if v}
    if not ofertas:
        raise ErrorVenta("No hay costes cargados: primero hay que importar y aprobar la tarifa de algún proveedor (proponer_tarifa)")
    if len(ofertas) > MAX_LINEAS:
        raise ErrorVenta(f"Hay más de {MAX_LINEAS} artículos: propón por marca (solo_marca)")
    avisos: list[str] = []
    try:
        actuales = await _actuales(departamento, lista, sorted(ofertas), cfg_l["lote"])
    except Exception as e:  # noqa: BLE001 — sin ERP se propone igual: todo saldrá como «nuevo» y se avisa
        log.warning("precios de venta: no se pudo leer la lista del ERP: %s: %s", type(e).__name__, e)
        actuales = {}
        avisos.append("No se ha podido leer la lista de venta del ERP: los cambios no son fiables hasta que se vuelva a proponer")
    lineas, av = calcular_lineas(ofertas, cfg, actuales, aj, exc)
    avisos += av
    if sin_tarifa:
        avisos.append(f"{sin_tarifa} importaciones antiguas no se usan (no son tarifas con canal y familia)")
    desconocidos = (set(aj) | exc) - {l["codigo"] for l in lineas}
    if desconocidos:
        avisos.append("Códigos que no están en la propuesta: " + ", ".join(sorted(desconocidos)[:5]))
    if not lineas:
        raise ErrorVenta("Ningún artículo tiene un coste calculable (revisa el tipo de cambio)")
    resumen = resumir(lineas)
    async with await LP._conectar() as conn:
        cur = await conn.execute("INSERT INTO propuestas_venta (agente, departamento, lista, lineas, avisos, resumen) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
                                 [agente, departamento, lista, Jsonb(lineas), Jsonb(avisos), Jsonb(resumen)])
        pid = (await cur.fetchone())["id"]
    log.info("precios de venta: %s propone la lista %s (%s)", agente, pid, resumen)
    return {"propuesta": pid, "lista": lista, **resumen, "avisos": avisos, "mayores_cambios": _mayores(lineas, 5),
            "siguiente": "Dirección puede ajustar o excluir artículos (ajustar_venta). Si todo es correcto, propón la acción «aplicar_venta»: una persona la aprobará antes de que se escriba nada en el ERP."}


def _ajustes(ajustes) -> dict[str, Decimal]:
    if ajustes in (None, {}):
        return {}
    if not isinstance(ajustes, dict) or len(ajustes) > 5000:
        raise ErrorVenta("ajustes es {código del artículo: precio de venta sin IVA}")
    return {str(k): _dec(v, str(k)) for k, v in ajustes.items()}


def _excluir(excluir) -> set[str]:
    if excluir in (None, []):
        return set()
    if not isinstance(excluir, list) or not all(isinstance(x, str) for x in excluir):
        raise ErrorVenta("excluir es una lista de códigos de artículo")
    return set(excluir)


def _mayores(lineas: list[dict], n: int) -> list[dict]:
    con = [l for l in lineas if not l["excluida"] and l["cambio"] in ("sube", "baja")]
    con.sort(key=lambda l: abs(Decimal(l["variacion_pct"])), reverse=True)
    return [{k: l[k] for k in ("codigo", "actual", "venta", "variacion_pct")} for l in con[:n]]


async def _cargar(pid) -> dict:
    if isinstance(pid, bool) or not isinstance(pid, int):
        raise ErrorVenta("propuesta es el número que devolvió «proponer_venta»")
    async with await LP._conectar() as conn:
        cur = await conn.execute("SELECT * FROM propuestas_venta WHERE id = %s", [pid])
        f = await cur.fetchone()
    if not f:
        raise LP.NoExiste("No existe esa propuesta de precios")
    return f


async def estado(propuesta: int) -> dict:
    f = await _cargar(propuesta)
    return {"propuesta": f["id"], "estado": f["estado"], "lista": f["lista"], **f["resumen"], "resultado": f["resultado"], "avisos": f["avisos"]}


async def ajustar(propuesta: int, ajustes: dict | None = None, excluir: list | None = None, incluir: list | None = None) -> dict:
    """Dirección (o un agente a su petición) corrige precios a mano o saca/mete artículos de una propuesta que aún no se ha aplicado. No escribe en el ERP."""
    aj, exc, inc = _ajustes(ajustes), _excluir(excluir), _excluir(incluir)
    async with await LP._conectar() as conn:
        cur = await conn.execute("SELECT * FROM propuestas_venta WHERE id = %s FOR UPDATE", [propuesta if isinstance(propuesta, int) and not isinstance(propuesta, bool) else -1])
        f = await cur.fetchone()
        if not f:
            raise LP.NoExiste("No existe esa propuesta de precios")
        if f["estado"] not in ("propuesta", "error"):
            raise ErrorVenta(f"Esta propuesta está «{f['estado']}»: ya no se puede ajustar")
        cfg = (await cambio.configuracion_de_precios())
        lineas = f["lineas"]
        por = {l["codigo"]: l for l in lineas}
        desconocidos = (set(aj) | exc | inc) - set(por)
        if desconocidos:
            raise ErrorVenta("No están en la propuesta: " + ", ".join(sorted(desconocidos)[:5]))
        for codigo, precio in aj.items():
            l = por[codigo]
            margen = ((precio - Decimal(l["coste_eur"])) / precio).quantize(Decimal("0.0001"))
            av = [a for a in l["avisos"] if "ajustado deja un margen" not in a]
            if margen < cfg["margen"]["minimo"]:
                av.append(f"el precio ajustado deja un margen por debajo del mínimo ({cfg['margen']['minimo'] * 100:.0f} %)")
            tipo, pct = _cambio(precio, None if l["actual"] is None else Decimal(l["actual"]))
            l.update({"venta": str(precio), "ajustado": True, "margen": str(margen), "cambio": tipo, "variacion_pct": pct, "avisos": av})
        for c in exc:
            por[c]["excluida"] = True
        for c in inc:
            por[c]["excluida"] = False
        resumen = resumir(lineas)
        await conn.execute("UPDATE propuestas_venta SET lineas = %s, resumen = %s WHERE id = %s", [Jsonb(lineas), Jsonb(resumen), propuesta])
    return {"propuesta": propuesta, **resumen}


async def descartar(propuesta: int) -> dict:
    async with await LP._conectar() as conn:
        cur = await conn.execute("UPDATE propuestas_venta SET estado = 'descartada' WHERE id = %s AND estado IN ('propuesta', 'error') RETURNING id", [propuesta])
        if not await cur.fetchone():
            raise ErrorVenta("Solo se puede descartar una propuesta pendiente o con error")
    return {"propuesta": propuesta, "estado": "descartada"}


async def vista_aplicar(propuesta: int, departamento: str) -> dict:
    """Lo que ve Dirección al aprobar: cuántos precios nuevos, suben, bajan, ajustes a mano, márgenes, valores provisionales y los mayores cambios."""
    f = await _cargar(propuesta)
    if f["estado"] not in ("propuesta", "error"):
        raise ErrorVenta(f"Esta propuesta está «{f['estado']}»: no se puede aplicar")
    r = f["resumen"]
    campos = [["Lista de precios", f"{f['lista']} (EUR, sin IVA)"],
              ["Artículos", f"{r['incluidos']} incluidos" + (f" · {r['excluidos']} excluidos" if r["excluidos"] else "")],
              ["Cambios", f"{r['nuevo']} precios nuevos · {r['sube']} suben · {r['baja']} bajan · {r['igual']} sin cambios (no se tocan)" + (f" · {r['ajustados']} ajustados a mano" if r["ajustados"] else "")],
              ["Margen", f"de {float(r['margen_min']) * 100:.1f} % a {float(r['margen_max']) * 100:.1f} % sobre la venta" + (f" · {r['bajo_minimo']} por debajo del mínimo" if r["bajo_minimo"] else "")]
              if r["margen_min"] else ["Margen", "—"]]
    if r["provisional"]:
        campos.append(["Valores provisionales", "\n".join(f"- {a}" for a in r["provisional"][:5])])
    if f["avisos"]:
        campos.append(["Avisos", "\n".join(f"- {a}" for a in f["avisos"][:8])])
    mayores = _mayores(f["lineas"], 8)
    if mayores:
        campos.append(["Mayores cambios", "\n".join(f"{m['codigo']}: {m['actual']} → {m['venta']} ({m['variacion_pct']} %)" for m in mayores)])
    vivas = [l for l in f["lineas"] if not l["excluida"] and l["cambio"] != "igual"][:12]
    campos.append(["Primeras líneas", "\n".join(f"{l['ref']} · {l['desc'][:50]} · coste {l['coste_eur']} € → venta {l['venta']} € ({l['cambio']})" for l in vivas) or "—"])
    return {"titulo": f"Aplicar los precios de venta de la lista «{f['lista']}» en el ERP (propuesta {f['id']})", "campos": campos}


async def aplicar(propuesta: int, departamento: str) -> dict:
    """Crea la lista de venta (si falta) y crea o actualiza en el ERP los precios que han cambiado. Solo se llega aquí tras la aprobación de una persona. Repetible: lo que ya está igual no se toca."""
    cfg = LP.configuracion()
    async with await LP._conectar() as conn:
        cur = await conn.execute("UPDATE propuestas_venta SET estado = 'aplicando' WHERE id = %s AND estado IN ('propuesta', 'error') RETURNING *", [propuesta])
        f = await cur.fetchone()
    if not f:
        e = await _cargar(propuesta)
        raise ErrorVenta(f"Esta propuesta está «{e['estado']}»: no se puede aplicar")
    res = {"lista_creada": False, "precios_nuevos": 0, "precios_actualizados": 0, "sin_cambios": 0, "excluidos": 0, "errores": []}
    try:
        lista = f["lista"]
        if not await LP.erpnext.listar("Price List", departamento, filtros=[["name", "=", lista]], campos=["name"], limite=1):
            await LP.erpnext.crear_maestro("Price List", {"price_list_name": lista, "currency": "EUR", "enabled": 1, "buying": 0, "selling": 1}, departamento)
            res["lista_creada"] = True
        vivas = [l for l in f["lineas"] if not l["excluida"]]
        res["excluidos"] = len(f["lineas"]) - len(vivas)
        existentes: dict[str, tuple[str, Decimal]] = {}
        codigos = [l["codigo"] for l in vivas]
        for i in range(0, len(codigos), 80):
            trozo = codigos[i:i + 80]
            for r in await LP.erpnext.listar("Item Price", departamento, filtros=[["price_list", "=", lista], ["item_code", "in", trozo]], campos=["name", "item_code", "price_list_rate"], limite=len(trozo) + 20):
                existentes[str(r["item_code"])] = (str(r["name"]), Decimal(str(r.get("price_list_rate") or "0")))
        crear = []
        for l in vivas:
            nuevo = Decimal(l["venta"])
            actual = existentes.get(l["codigo"])
            if actual is None:
                crear.append({"item_code": l["codigo"], "price_list": lista, "selling": 1, "buying": 0, "currency": "EUR", "price_list_rate": float(nuevo)})
            elif abs(actual[1] - nuevo) < TOLERANCIA:
                res["sin_cambios"] += 1
            else:
                try:
                    await LP.erpnext.modificar("Item Price", actual[0], {"price_list_rate": float(nuevo)}, departamento)
                    res["precios_actualizados"] += 1
                except Exception as e:  # noqa: BLE001
                    res["errores"].append(f"{l['ref'][:30]}: {type(e).__name__}")
        if crear:
            res["precios_nuevos"] = len(await LP.erpnext.insertar_varios("Item Price", crear, departamento, cfg["lote"]))
    except Exception as e:  # noqa: BLE001 — se guarda lo hecho y el motivo; repetir `aplicar` sigue por donde se quedó
        res["errores"].append(f"{type(e).__name__}: {str(e)[:300]}")
        log.exception("precios de venta: fallo al aplicar la propuesta %s", propuesta)
    final = "error" if res["errores"] else "aplicada"
    async with await LP._conectar() as conn:
        await conn.execute("UPDATE propuestas_venta SET estado = %s, resultado = %s, aplicada_en = CASE WHEN %s = 'aplicada' THEN now() ELSE aplicada_en END WHERE id = %s", [final, Jsonb(res), final, propuesta])
    if final == "error":
        raise ErrorVenta("La aplicación no ha terminado: " + "; ".join(res["errores"][:3]) + f". Se ha guardado lo hecho ({res['precios_nuevos']} precios nuevos y {res['precios_actualizados']} actualizados); se puede repetir sin duplicar.")
    log.info("precios de venta: propuesta %s aplicada: %s", propuesta, res)
    return {"propuesta": propuesta, "estado": "aplicada", **res}
