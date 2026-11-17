"""Fichas técnicas de TODOS los productos de un fabricante que vendes, sin buscarlas una a una.

La idea: tus tarifas ya dicen exactamente qué referencias de cada marca existen. Para cada una (reducida a su modelo base: «DS-2CD1143G0-I(2.8mm)(C)» es «DS-2CD1143G0-I») se busca el PDF oficial
en el dominio autorizado del fabricante (SearXNG con `site:`) y se descarga por la misma tubería de siempre (`fichas.desde_url`: dominio autorizado, anti-SSRF, tamaño, antivirus, lectura aislada, índice).

Honradez, comprobada en código:
  · solo se descarga un PDF de un dominio autorizado en config/fichas.yaml y solo si su dirección, su título o su resumen nombran el modelo buscado (no se cuela la ficha de otro producto);
  · una página de producto sin PDF no se da por buena: queda «sin enlace» y se dice;
  · lo ya cargado no se repite, lo no encontrado no se vuelve a buscar hasta pasados REINTENTO_DIAS, y el tope diario de descargas de fichas.yaml se respeta: la carga es reanudable (cada pulsación sigue donde lo dejó).
"""
from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

from psycopg.types.json import Jsonb

from ..herramientas import web
from . import fichas as F
from . import pliegos

log = logging.getLogger("cerebro.fichas_marca")
MAX_POR_EJECUCION = 40
REINTENTO_DIAS = 14
MINUTOS_EN_CURSO = 30
MAX_RESULTADOS = 8
RE_OPCIONES = re.compile(r"\([^)]*\)")


def _alnum(t) -> str:
    return re.sub(r"[^a-z0-9]", "", str(t or "").casefold())


def modelo_base(ref: str) -> str:
    """El modelo sin las opciones de lente, color o variante: «DS-2CD1143G0-I(2.8mm)(C)» → «DS-2CD1143G0-I»; «MS-CQ4431-HYPG1/2.8mm» → «MS-CQ4431-HYPG1». Vacío si no parece un modelo (sin cifras o muy corto). Pura."""
    t = RE_OPCIONES.sub("", str(ref or "")).strip()
    t = re.split(r"[\s/,;]", t)[0].strip("-._") if t else ""
    return t if len(_alnum(t)) >= 5 and any(c.isdigit() for c in t) else ""


def dominios_de_marca(marca: str, hosts: list[str]) -> list[str]:
    """Los dominios autorizados que llevan el nombre de la marca («hikvision.com» para «Hikvision»). Pura."""
    m = _alnum(marca)
    return [h for h in hosts if m and m in _alnum(h.split(".")[0])]


def elegir_enlace(modelo: str, resultados: list[dict], hosts: list[str]) -> tuple[str | None, str]:
    """El mejor enlace a un PDF entre los resultados de búsqueda: dominio autorizado, https, y el modelo nombrado en la dirección, el título o el resumen. (url, motivo si no hay). Pura."""
    m = _alnum(modelo)
    mejor, puntos, vio_pagina = None, 0, False
    for r in resultados:
        url = str(r.get("url") or "")
        if not url.startswith("https://") or not pliegos.host_permitido(url, hosts):
            continue
        if m not in _alnum(url + " " + str(r.get("titulo") or "") + " " + str(r.get("resumen") or "")):
            continue
        es_pdf = urlparse(url).path.lower().endswith(".pdf")
        if not es_pdf:
            vio_pagina = True
            continue
        p = 2 + (3 if m in _alnum(url) else 0) + (1 if re.search(r"data\s*-?sheet|ficha|spec", url + str(r.get("titulo") or ""), re.I) else 0)
        if p > puntos:
            mejor, puntos = url, p
    if mejor:
        return mejor, ""
    return None, ("solo hay página de producto, sin PDF directo" if vio_pagina else "no aparece en los dominios autorizados del fabricante")


async def referencias_de_marca(marca: str) -> list[dict]:
    """Los modelos base de la marca en las últimas tarifas de cada proveedor: [{modelo, ref, nombre}], sin repetir. Es lo que se vende de verdad."""
    async with await F._conectar() as conn:
        cur = await conn.execute(
            "SELECT DISTINCT l->>'ref' AS ref, l->>'desc' AS nombre FROM (SELECT DISTINCT ON (proveedor->>'nombre', lista) lineas FROM importaciones_precios "
            "WHERE estado IN ('propuesta', 'aplicada') ORDER BY proveedor->>'nombre', lista, id DESC) t, jsonb_array_elements(t.lineas) l "
            "WHERE lower(coalesce(l->>'marca', '')) LIKE %s ORDER BY 1", [f"%{marca.casefold()}%"])
        filas = await cur.fetchall()
    out: dict[str, dict] = {}
    for f in filas:
        m = modelo_base(f["ref"])
        if m and _alnum(m) not in out:
            out[_alnum(m)] = {"modelo": m, "ref": f["ref"], "nombre": (f["nombre"] or "")[:120]}
    return list(out.values())


async def _con_ficha(marca: str) -> list[str]:
    async with await F._conectar() as conn:
        cur = await conn.execute("SELECT referencia FROM fichas_tecnicas WHERE estado = ANY(%s) AND (lower(marca) LIKE %s OR lower(nombre) LIKE %s)", [list(F.ESTADOS_BUENOS), f"%{marca.casefold()}%", f"%{marca.casefold()}%"])
        return [_alnum(f["referencia"]) for f in await cur.fetchall()]


async def _recientes(marca: str) -> dict[str, str]:
    async with await F._conectar() as conn:
        cur = await conn.execute("SELECT modelo, estado FROM fichas_marca_intentos WHERE marca = %s AND (estado IN ('cargada', 'repetida') OR intentada > now() - make_interval(days => %s))", [marca, REINTENTO_DIAS])
        return {_alnum(f["modelo"]): f["estado"] for f in await cur.fetchall()}


async def _anotar(marca: str, modelo: str, estado: str, motivo: str = "") -> None:
    async with await F._conectar() as conn:
        await conn.execute("INSERT INTO fichas_marca_intentos (marca, modelo, estado, motivo) VALUES (%s,%s,%s,%s) ON CONFLICT (marca, modelo) DO UPDATE SET estado = EXCLUDED.estado, motivo = EXCLUDED.motivo, intentada = now()",
                           [marca, modelo, estado, motivo[:300]])


async def pendientes(marca: str, refs: list[dict] | None = None) -> list[dict]:
    """Los modelos de la marca que aún no tienen ficha ni se han buscado hace poco."""
    refs = refs if refs is not None else await referencias_de_marca(marca)
    con, hechos = await _con_ficha(marca), await _recientes(marca.casefold())
    return [r for r in refs if _alnum(r["modelo"]) not in hechos and not any(_alnum(r["modelo"]) in c for c in con)]


async def estado(marca: str) -> dict:
    """Lo que se ve en el panel: cuántos modelos tiene la marca en tus tarifas, cuántos tienen ficha, cuántos no se han encontrado y el informe de la última carga (una «en curso» de hace más de MINUTOS_EN_CURSO se da por perdida)."""
    k = marca.casefold().strip()
    refs = await referencias_de_marca(k)
    con, hechos = await _con_ficha(k), await _recientes(k)
    sin = [r for r in refs if not any(_alnum(r["modelo"]) in c for c in con)]
    async with await F._conectar() as conn:
        cur = await conn.execute("SELECT estado, informe, actualizada, (estado = 'en_curso' AND actualizada < now() - make_interval(mins => %s)) AS caducada FROM fichas_marca_cargas WHERE marca = %s", [MINUTOS_EN_CURSO, k])
        c = await cur.fetchone()
    carga = None
    if c:
        carga = {"estado": "error" if c["caducada"] else c["estado"], "informe": c["informe"], "actualizada": c["actualizada"].isoformat()}
        if c["caducada"]:
            carga["informe"] = {**(c["informe"] or {}), "error": "La carga se interrumpió. Puedes volver a lanzarla: sigue donde lo dejó."}
    return {"marca": marca, "modelos": len(refs), "con_ficha": len(refs) - len(sin), "sin_ficha": len(sin),
            "no_encontradas": sum(1 for r in sin if hechos.get(_alnum(r["modelo"])) in ("sin_enlace", "error")), "carga": carga}


async def iniciar(marca: str, por: str) -> None:
    k = marca.casefold().strip()
    if len(k) < 2:
        raise F.ErrorFicha("Indica la marca")
    async with await F._conectar() as conn:
        cur = await conn.execute("SELECT 1 FROM fichas_marca_cargas WHERE marca = %s AND estado = 'en_curso' AND actualizada > now() - make_interval(mins => %s)", [k, MINUTOS_EN_CURSO])
        if await cur.fetchone():
            raise F.ErrorFicha("Ya hay una carga en curso de esa marca")
        await conn.execute("INSERT INTO fichas_marca_cargas (marca, estado, por) VALUES (%s, 'en_curso', %s) ON CONFLICT (marca) DO UPDATE SET estado = 'en_curso', informe = '{}', por = EXCLUDED.por, actualizada = now()", [k, por[:200]])


async def _cerrar(marca: str, estado_: str, informe: dict) -> None:
    async with await F._conectar() as conn:
        await conn.execute("UPDATE fichas_marca_cargas SET estado = %s, informe = %s, actualizada = now() WHERE marca = %s", [estado_, Jsonb(informe), marca])


async def ejecutar(marca: str, por: str = "", maximo: int = MAX_POR_EJECUCION, buscar=None, cfg: dict | None = None, refs: list[dict] | None = None, **kw) -> dict:
    """Busca y carga las fichas de hasta `maximo` modelos pendientes de la marca. Nunca lanza: deja el informe en la fila. `kw` va a `fichas.desde_url` (descargar, analizar, extraer, indexar)."""
    k = marca.casefold().strip()
    inf = {"intentados": 0, "cargadas": 0, "repetidas": 0, "sin_enlace": 0, "errores": [], "tope_diario": False}
    try:
        cfg = cfg or F.configuracion()
        hosts = dominios_de_marca(k, cfg["hosts"])
        if not hosts:
            await _cerrar(k, "error", {**inf, "error": f"No hay ningún dominio de «{marca}» autorizado en config/fichas.yaml: autorízalo primero (así se evita bajar PDF de cualquier sitio)."})
            return {"estado": "error"}
        for r in (await pendientes(k, refs))[:maximo]:
            inf["intentados"] += 1
            try:
                res = []
                for q in [f"{r['modelo']} datasheet site:{h}" for h in hosts[:2]] + [f"{marca} {r['modelo']} datasheet pdf"]:
                    try:
                        res += (await (buscar or web.buscar)(q, max_resultados=MAX_RESULTADOS)).get("resultados") or []
                    except (PermissionError, ValueError, RuntimeError) as e:
                        log.info("fichas_marca: no se ha podido buscar «%s»: %s", q[:80], e)
                    url, motivo = elegir_enlace(r["modelo"], res, cfg["hosts"])
                    if url:
                        break
                if not url:
                    inf["sin_enlace"] += 1
                    await _anotar(k, r["modelo"], "sin_enlace", motivo)
                    continue
                f = await F.desde_url(url, marca, r["modelo"], "web", por, cfg=cfg, **kw)
                if f["estado"] in F.ESTADOS_BUENOS:
                    inf["repetidas" if f.get("repetida") else "cargadas"] += 1
                    await _anotar(k, r["modelo"], "repetida" if f.get("repetida") else "cargada")
                else:
                    inf["errores"].append(f"{r['modelo']}: {f.get('motivo') or f['estado']}"[:160])
                    await _anotar(k, r["modelo"], "error", f.get("motivo") or f["estado"])
            except F.ErrorFicha as e:
                if "máximo" in str(e):
                    inf["tope_diario"] = True
                    inf["intentados"] -= 1
                    break
                inf["errores"].append(f"{r['modelo']}: {e}"[:160])
                await _anotar(k, r["modelo"], "error", str(e))
        inf["errores"] = inf["errores"][:15]
        await _cerrar(k, "terminada", inf)
        return {"estado": "terminada", **inf}
    except Exception as e:      # noqa: BLE001 — la fila no puede quedarse «en curso»
        log.warning("fichas_marca %s: %s: %s", marca, type(e).__name__, e)
        await _cerrar(k, "error", {**inf, "error": f"Fallo interno ({type(e).__name__})"})
        return {"estado": "error"}
