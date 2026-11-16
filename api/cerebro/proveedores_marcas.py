"""Qué marcas distribuye cada proveedor: se deduce de sus tarifas cargadas y se guarda, para saber a quién pedir precio o cotización de una marca.

Sale de la columna «marca» de la última tarifa cargada de cada proveedor (sin precios: solo el nombre de la marca y cuántos artículos trae). Las variantes que traen las tarifas («HIKVISION PRO NO CCTV»,
«MOVOK ACCESSORIES»…) se juntan bajo el fabricante de verdad con config/marcas_alias.yaml, y las variantes originales se conservan. Además se pueden añadir a mano marcas que un proveedor distribuye pero
no vienen en su tarifa («fuente manual»: nunca las pisa una recarga de tarifas). Es de SOLO LECTURA sobre las tarifas y confidencial (quién nos vende qué): solo Dirección.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

import psycopg
import yaml
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .ajustes import ajustes

log = logging.getLogger("cerebro.proveedores_marcas")
SIN_MARCA = "(sin marca)"
MAX_MARCA = 60


def _conectar():
    return psycopg.AsyncConnection.connect(ajustes.database_url, row_factory=dict_row)


def plano(t) -> str:
    """Minúsculas, sin tildes ni signos, espacios simples. Pura."""
    s = "".join(c for c in unicodedata.normalize("NFD", str(t or "").lower()) if unicodedata.category(c) != "Mn")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", s).split())


@lru_cache(maxsize=2)
def _alias(ruta: str) -> dict:
    try:
        d = yaml.safe_load(Path(ruta).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        d = {}
    propias = []
    for p in d.get("propias") or []:
        try:
            propias.append((re.compile(str(p["patron"]), re.I), str(p["marca"])))
        except (re.error, KeyError, TypeError):
            continue
    return {"prefijos": sorted(((plano(k), str(v)) for k, v in (d.get("prefijos") or {}).items()), key=lambda kv: -len(kv[0])),
            "exactas": {plano(k): str(v) for k, v in (d.get("exactas") or {}).items()}, "propias": propias, "sin_marca": {plano(x) for x in d.get("sin_marca") or []}}


def alias() -> dict:
    return _alias(str(Path(ajustes.dir_config) / "marcas_alias.yaml"))


def canonica(marca, cfg: dict | None = None) -> tuple[str, str]:
    """(nombre que se enseña, clave para comparar) de una marca tal como la trae la tarifa. Lo vacío o «sin fabricante» → «(sin marca)». Pura sobre `cfg`."""
    cfg = cfg if cfg is not None else alias()
    crudo = str(marca or "").strip()
    p = plano(crudo)
    if not p or p in cfg["sin_marca"]:
        return SIN_MARCA, ""
    if p in cfg["exactas"]:
        nombre = cfg["exactas"][p]
        return nombre, plano(nombre)
    for patron, nombre in cfg["propias"]:
        if patron.match(crudo.strip()) or patron.match(p):
            return nombre, plano(nombre)
    for pref, nombre in cfg["prefijos"]:
        if p == pref or p.startswith(pref + " "):
            return nombre, plano(nombre)
    return crudo[:MAX_MARCA], p


def resumir(lineas: list[dict], cfg: dict | None = None) -> dict[str, dict]:
    """De las líneas de una tarifa: {clave: {marca, articulos, variantes: {texto original: n}}}. Las líneas sin marca se cuentan aparte bajo la clave vacía. Pura."""
    out: dict[str, dict] = {}
    for l in lineas or []:
        if not isinstance(l, dict):
            continue
        nombre, clave = canonica(l.get("marca"), cfg)
        m = out.setdefault(clave, {"marca": nombre, "articulos": 0, "variantes": {}})
        m["articulos"] += 1
        crudo = str(l.get("marca") or "").strip()[:MAX_MARCA]
        if crudo and plano(crudo) != clave:
            m["variantes"][crudo] = m["variantes"].get(crudo, 0) + 1
    return out


async def registrar(proveedor: str, lineas: list[dict], cfg: dict | None = None) -> int:
    """Guarda las marcas de la tarifa de ese proveedor (sustituye lo que había de fuente «tarifa» para él; lo manual no se toca). Devuelve cuántas marcas distintas."""
    marcas = {k: v for k, v in resumir(lineas, cfg).items() if k}
    async with await _conectar() as conn:
        async with conn.transaction():
            await conn.execute("DELETE FROM proveedores_marcas WHERE proveedor = %s AND fuente = 'tarifa'", [proveedor])
            for clave, m in marcas.items():
                await conn.execute("INSERT INTO proveedores_marcas (proveedor, clave, marca, articulos, variantes, fuente, por) VALUES (%s,%s,%s,%s,%s,'tarifa','sistema')",
                                   [proveedor, clave, m["marca"], m["articulos"], Jsonb(m["variantes"])])
    return len(marcas)


async def reconstruir(cfg: dict | None = None) -> dict:
    """Vuelve a calcular las marcas de TODOS los proveedores desde sus tarifas cargadas (la última de cada lista, propuesta o aplicada). Idempotente: sirve para llenar lo que ya estaba cargado."""
    async with await _conectar() as conn:
        cur = await conn.execute("SELECT DISTINCT ON (proveedor->>'nombre', lista) proveedor->>'nombre' AS nombre, lineas FROM importaciones_precios "
                                 "WHERE estado IN ('propuesta', 'aplicada') AND resumen->>'tarifa' = 'true' ORDER BY proveedor->>'nombre', lista, id DESC")
        filas = await cur.fetchall()
    por_proveedor: dict[str, list[dict]] = {}
    for f in filas:
        por_proveedor.setdefault(f["nombre"], []).extend(f["lineas"] or [])
    resultado = {}
    for nombre, lineas in por_proveedor.items():
        resultado[nombre] = await registrar(nombre, lineas, cfg)
    return {"proveedores": len(resultado), "marcas": resultado}


def _normalizar_proveedor(p) -> str:
    p = " ".join(str(p or "").split())
    if not 2 <= len(p) <= 80:
        raise ValueError("El proveedor tiene que tener entre 2 y 80 caracteres")
    return p


async def anadir_manual(proveedor: str, marca: str, por: str, cfg: dict | None = None) -> dict:
    proveedor, marca = _normalizar_proveedor(proveedor), " ".join(str(marca or "").split())
    nombre, clave = canonica(marca, cfg)
    if not clave:
        raise ValueError("Escribe el nombre de la marca")
    async with await _conectar() as conn:
        await conn.execute("INSERT INTO proveedores_marcas (proveedor, clave, marca, articulos, variantes, fuente, por) VALUES (%s,%s,%s,0,'{}','manual',%s) "
                           "ON CONFLICT (proveedor, clave, fuente) DO UPDATE SET marca = EXCLUDED.marca, por = EXCLUDED.por, actualizado = now()", [proveedor, clave, nombre, por[:120]])
    return {"proveedor": proveedor, "marca": nombre}


async def quitar_manual(proveedor: str, marca: str, cfg: dict | None = None) -> bool:
    """Quita una marca puesta a mano (la que viene de una tarifa no se quita: desaparece sola si deja de venir en la tarifa)."""
    _n, clave = canonica(marca, cfg)
    async with await _conectar() as conn:
        cur = await conn.execute("DELETE FROM proveedores_marcas WHERE proveedor = %s AND clave = %s AND fuente = 'manual'", [_normalizar_proveedor(proveedor), clave])
        return cur.rowcount > 0


def agrupar(filas: list[dict]) -> list[dict]:
    """De las filas de la tabla a [{proveedor, articulos, marcas: [{marca, clave, articulos, fuentes, variantes}]}], proveedores por nombre y marcas por artículos. Pura."""
    por_prov: dict[str, dict[str, dict]] = {}
    for f in filas:
        m = por_prov.setdefault(f["proveedor"], {}).setdefault(f["clave"], {"marca": f["marca"], "clave": f["clave"], "articulos": 0, "fuentes": [], "variantes": {}, "actualizado": None})
        m["articulos"] += int(f["articulos"] or 0)
        if f["fuente"] not in m["fuentes"]:
            m["fuentes"].append(f["fuente"])
        for k, v in (f.get("variantes") or {}).items():
            m["variantes"][k] = m["variantes"].get(k, 0) + v
        if f.get("actualizado") and (m["actualizado"] is None or f["actualizado"] > m["actualizado"]):
            m["actualizado"] = f["actualizado"]
    out = []
    for prov in sorted(por_prov, key=str.lower):
        marcas = sorted(por_prov[prov].values(), key=lambda m: (-m["articulos"], m["marca"].lower()))
        for m in marcas:
            m["actualizado"] = m["actualizado"].isoformat() if m["actualizado"] else None
            m["variantes"] = dict(sorted(m["variantes"].items(), key=lambda kv: -kv[1]))
        out.append({"proveedor": prov, "articulos": sum(m["articulos"] for m in marcas), "marcas": marcas})
    return out


async def listar(marca: str = "", cfg: dict | None = None) -> dict:
    """Los proveedores con sus marcas. Con `marca`, solo los proveedores que la distribuyen (y solo esa marca): «¿a quién le pido esta marca?»."""
    async with await _conectar() as conn:
        cur = await conn.execute("SELECT proveedor, clave, marca, articulos, variantes, fuente, actualizado FROM proveedores_marcas ORDER BY proveedor, clave")
        filas = await cur.fetchall()
    _n, clave = canonica(marca, cfg) if marca else ("", "")
    if marca:
        if not clave:
            raise ValueError("Escribe el nombre de la marca")
        filas = [f for f in filas if f["clave"] == clave or clave in f["clave"] or f["clave"] in clave and len(f["clave"]) >= 4]
    return {"proveedores": agrupar(filas), "marca": marca or None}
