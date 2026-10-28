"""Resumen diario de licitaciones (decidido por Dirección: lo recibe Dirección a las 16:00 en el panel, con lo publicado desde las 16:00 del día anterior).

Se construye CONSULTANDO la API del motor (ADR 0007 §3), no a partir de eventos: la consulta es idempotente y se puede repetir sin consecuencias. Es
determinista —no usa el modelo de IA—: lista, puntúa (encaje.py) y ordena, y siempre dice lo que no sabe:
  - si el motor no responde, el resumen sale con estado «sin_datos» y el motivo, no vacío;
  - si el motor no está al día, lleva un aviso;
  - si hay más novedades de las que se leen, lo dice.
Se guarda en la tabla licitaciones_resumenes (db/esquema.sql); el panel lo muestra.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import psycopg
import yaml
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ..ajustes import ajustes
from ..herramientas import licitaciones as motor
from . import encaje

log = logging.getLogger("cerebro.licitaciones.resumen")

VERSION = 1
ABIERTAS = encaje.ABIERTAS
RESUELTAS = {"adjudicada", "formalizada", "desierta"}


@lru_cache(maxsize=1)
def config() -> dict:
    return yaml.safe_load((Path(ajustes.dir_config) / "licitaciones.yaml").read_text(encoding="utf-8"))


def ventana(ahora: datetime, zona: str) -> tuple[datetime, datetime]:
    """(desde, hasta): desde la misma hora local del día anterior (a las 16:00, «desde las 16:00 de ayer»; si se pide a otra hora, las últimas 24 h
    de reloj de pared). Con el cambio de hora un día dura 23 o 25 horas: se respeta la hora local, no un número fijo de horas."""
    z = ZoneInfo(zona)
    hasta = ahora.astimezone(z)
    desde = datetime.combine(hasta.date() - timedelta(days=1), hasta.timetz().replace(tzinfo=None), tzinfo=z)
    return desde.astimezone(timezone.utc), hasta.astimezone(timezone.utc)


def prefijos_de_consulta(cfg: dict) -> list[str]:
    """Los CPV de interés como prefijos para la API del motor (cada código cubre sus descendientes), sin repetir y sin pasar del máximo que admite."""
    vistos: list[str] = []
    for c in cfg["cpv"]:
        p = encaje.prefijo(c["codigo"])
        if p not in vistos and not any(p.startswith(q) for q in vistos):     # 72 ya cubre 7226…
            vistos = [q for q in vistos if not q.startswith(p)] + [p]
    return vistos[:20]


def _url(u: str | None) -> str | None:
    p = urlparse(u or "")
    return u if p.scheme in ("http", "https") and p.netloc else None


def _linea(x: dict, p: dict) -> dict:
    c = x.get("comprador") or {}
    imp = x.get("importe") or None
    return {
        "id": x.get("id"), "titulo": motor._corto(x.get("titulo")), "expediente": x.get("expediente"), "comprador": motor._corto(c.get("nombre"), 120) or None,
        "estado": x.get("estado"), "nueva": x.get("version_entidad") == 1, "encaje": p["encaje"], "razones": p["razones"],
        "importe": {"valor": imp.get("valor"), "moneda": imp.get("moneda") or "EUR"} if imp else None,
        "plazo_presentacion": x.get("plazo_presentacion"), "dias_plazo": p["dias_plazo"], "cpv": (x.get("cpv") or [])[:4], "nuts": (x.get("nuts") or [])[:2],
        "url_origen": _url(x.get("url_origen")),
    }


async def _leer(consulta, cfg: dict, desde: datetime) -> tuple[list[dict], bool]:
    """Todas las licitaciones con novedades desde `desde` en los CPV de interés (hasta paginas_max páginas de 100). (items, truncado)."""
    params: dict = {"actualizada_desde": desde.strftime("%Y-%m-%dT%H:%M:%SZ"), "cpv": prefijos_de_consulta(cfg), "orden": "actualizacion", "limit": 100}
    items: list[dict] = []
    for _ in range(cfg["resumen"]["paginas_max"]):
        r = await consulta("/tenders", params)
        items += r.get("items", [])
        if not r.get("siguiente_cursor"):
            return items, False
        params = {**params, "cursor": r["siguiente_cursor"]}
    return items, True


async def _estado_motor(consulta) -> dict:
    try:
        r = await consulta("/ops/status", None)
    except (motor.MotorNoDisponible, ValueError):
        return {"estado": "desconocido", "antiguedad_h": None}
    ages = [f["antiguedad_s"] for f in r.get("fuentes", []) if f.get("antiguedad_s") is not None]
    sin_ingesta = any(f.get("antiguedad_s") is None for f in r.get("fuentes", []))
    return {"estado": r.get("estado", "desconocido"), "antiguedad_h": round(max(ages) / 3600, 1) if ages else None, "sin_ingesta_completa": sin_ingesta}


async def construir(ahora: datetime | None = None, consulta=None, cfg: dict | None = None) -> dict:
    """El resumen del día como documento (ver los campos abajo). No toca la base de datos."""
    ahora = ahora or datetime.now(timezone.utc)
    cfg = cfg or config()
    consulta = consulta or motor._get
    desde, hasta = ventana(ahora, ajustes.zona_horaria)
    out = {
        "version": VERSION, "estado": "ok", "aviso": None, "ventana": {"desde": desde.isoformat(), "hasta": hasta.isoformat()},
        "generado": ahora.astimezone(timezone.utc).isoformat(), "motor": {"estado": "desconocido", "antiguedad_h": None},
        "totales": {"novedades": 0, "oportunidades": 0, "adjudicaciones": 0, "anuladas": 0, "fuera_de_importe": 0, "otras": 0, "truncado": False},
        "oportunidades": [], "adjudicaciones": [], "anuladas": [],
    }
    try:
        items, truncado = await _leer(consulta, cfg, desde)
    except (motor.MotorNoDisponible, ValueError) as e:
        out["estado"] = "sin_datos"
        out["aviso"] = f"No se ha podido consultar el motor de licitaciones: {e}. Este resumen no incluye ninguna licitación; no significa que no haya novedades."
        return out
    out["motor"] = await _estado_motor(consulta)

    avisos = []
    if out["motor"]["estado"] in ("degradado", "caido"):
        h = out["motor"].get("antiguedad_h")
        avisos.append("El motor no está al día" + (f" (última ingesta completa hace {h:g} h)" if h is not None else "") +
                      ": puede faltar lo publicado en las últimas horas.")
    elif out["motor"]["estado"] == "desconocido":
        avisos.append("No se ha podido comprobar si el motor está al día: puede faltar lo publicado en las últimas horas.")
    if truncado:
        avisos.append(f"Hay más de {len(items)} novedades en este periodo: solo se han puntuado las {len(items)} más recientes.")

    t = out["totales"]
    t["novedades"], t["truncado"] = len(items), truncado
    ops, adj, anu = [], [], []
    for x in items:
        p = encaje.puntuar(x, cfg, ahora)
        if p["fuera_de_importe"]:
            t["fuera_de_importe"] += 1
            continue
        estado = x.get("estado")
        if estado in ABIERTAS:
            ops.append((x, p))
        elif estado in RESUELTAS:
            adj.append((x, p))
        elif estado == "anulada":
            anu.append((x, p))
        else:
            t["otras"] += 1
    por_encaje = lambda xp: (-(xp[1]["encaje"] or 0), xp[0].get("plazo_presentacion") or "9999", xp[0].get("id") or "")    # noqa: E731
    r = cfg["resumen"]
    for clave, lista, tope in (("oportunidades", ops, r["oportunidades_max"]), ("adjudicaciones", adj, r["otras_max"]), ("anuladas", anu, r["otras_max"])):
        t[clave] = len(lista)
        out[clave] = [_linea(x, p) for x, p in sorted(lista, key=por_encaje)[:tope]]
    out["aviso"] = " ".join(avisos) or None
    return out


# ---- Almacenamiento (tabla licitaciones_resumenes) ----

async def guardar(resumen: dict, origen: str, zona: str | None = None) -> int:
    fecha = datetime.fromisoformat(resumen["ventana"]["hasta"]).astimezone(ZoneInfo(zona or ajustes.zona_horaria)).date()
    args = (fecha, origen, resumen["ventana"]["desde"], resumen["ventana"]["hasta"], resumen["estado"], Jsonb(resumen))
    async with await psycopg.AsyncConnection.connect(ajustes.database_url, row_factory=dict_row) as conn:
        if origen == "programada":      # repetir el de las 16:00 (reintento, recuperación) lo sustituye en vez de duplicarlo
            cur = await conn.execute(
                """INSERT INTO licitaciones_resumenes (fecha, origen, desde, hasta, estado, contenido) VALUES (%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (fecha) WHERE origen = 'programada'
                   DO UPDATE SET desde = EXCLUDED.desde, hasta = EXCLUDED.hasta, estado = EXCLUDED.estado, contenido = EXCLUDED.contenido, generado = now()
                   RETURNING id""", args)
        else:
            cur = await conn.execute("""INSERT INTO licitaciones_resumenes (fecha, origen, desde, hasta, estado, contenido) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id""", args)
        return (await cur.fetchone())["id"]


async def _manual_reciente(segundos: int = 60) -> dict | None:
    async with await psycopg.AsyncConnection.connect(ajustes.database_url, row_factory=dict_row) as conn:
        cur = await conn.execute(
            """SELECT id, estado, contenido FROM licitaciones_resumenes
               WHERE origen = 'manual' AND generado > now() - make_interval(secs => %s) ORDER BY generado DESC LIMIT 1""", [segundos])
        return await cur.fetchone()


async def generar(origen: str = "programada", ahora: datetime | None = None) -> dict:
    """Construye y guarda el resumen. Devuelve {id, estado, totales}. Un resumen manual pedido menos de un minuto después de otro devuelve ese
    (evita repetir la consulta al motor si alguien pulsa el botón varias veces)."""
    if origen not in ("programada", "manual"):
        raise ValueError("origen debe ser programada o manual")
    if origen == "manual" and ahora is None and (reciente := await _manual_reciente()):
        return {"id": reciente["id"], "estado": reciente["estado"], "totales": reciente["contenido"].get("totales"), "reutilizado": True}
    r = await construir(ahora)
    rid = await guardar(r, origen)
    log.info("resumen de licitaciones %s: estado=%s oportunidades=%s", rid, r["estado"], r["totales"]["oportunidades"])
    return {"id": rid, "estado": r["estado"], "totales": r["totales"]}


def _fila(f: dict, con_contenido: bool) -> dict:
    out = {"id": f["id"], "fecha": f["fecha"].isoformat(), "origen": f["origen"], "estado": f["estado"], "generado": f["generado"].isoformat(),
           "desde": f["desde"].isoformat(), "hasta": f["hasta"].isoformat()}
    c = f["contenido"]
    if con_contenido:
        out["contenido"] = c
    else:
        out["totales"] = c.get("totales")
        out["mejor_encaje"] = max((o["encaje"] for o in c.get("oportunidades", []) if o.get("encaje") is not None), default=None)
        out["aviso"] = bool(c.get("aviso"))
    return out


async def listar(limite: int = 14) -> list[dict]:
    limite = max(1, min(int(limite), 60))
    async with await psycopg.AsyncConnection.connect(ajustes.database_url, row_factory=dict_row) as conn:
        cur = await conn.execute("SELECT * FROM licitaciones_resumenes ORDER BY fecha DESC, generado DESC LIMIT %s", [limite])
        return [_fila(f, False) for f in await cur.fetchall()]


async def leer(rid: int | None = None) -> dict | None:
    """Un resumen completo; sin id, el más reciente."""
    async with await psycopg.AsyncConnection.connect(ajustes.database_url, row_factory=dict_row) as conn:
        if rid is None:
            cur = await conn.execute("SELECT * FROM licitaciones_resumenes ORDER BY fecha DESC, generado DESC LIMIT 1")
        else:
            cur = await conn.execute("SELECT * FROM licitaciones_resumenes WHERE id = %s", [rid])
        f = await cur.fetchone()
    return _fila(f, True) if f else None
