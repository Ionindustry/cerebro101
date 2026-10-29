"""«Nuevo competidor»: ¿es la primera vez que esta empresa gana algo en este mercado?

Una alerta de competencia con `solo_nuevos` avisa de una adjudicación solo si el adjudicatario NO había ganado antes nada en el mercado de la alerta (sus CPV y su zona; si la
alerta no los fija, los CPV del propio expediente). Se pregunta al motor (`/awards`) por las adjudicaciones anteriores de ese NIF.

Una empresa solo se puede llamar «nueva» si el motor tiene historia suficiente: con unas semanas de datos casi todo adjudicatario lo parecería. Por eso antes se comprueba que
hay adjudicaciones de hace al menos `nuevo_competidor.cobertura_meses` (12 por defecto); si no las hay, no se avisa de nada y se dice por qué. Es una cota de seguridad contra
falsas alarmas, no una garantía: que el motor no conozca una victoria anterior (otra plataforma, antes de su histórico) no es que no exista.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

log = logging.getLogger("cerebro.licitaciones.novedad")
DEFECTO = {"cobertura_meses": 12}


def configuracion(cfg: dict | None = None) -> dict:
    c = {**DEFECTO, **((cfg or {}).get("nuevo_competidor") or {})}
    c["cobertura_meses"] = min(max(int(c["cobertura_meses"]), 1), 120)
    return c


def mercado_de(filtro: dict, item: dict) -> dict:
    """El mercado en el que se compara: los CPV y la zona de la alerta; sin CPV en la alerta, los CPV del expediente recortados a 4 cifras (grupo)."""
    cpv = list(filtro.get("cpv") or []) or sorted({str(c)[:4] for c in (item.get("cpv") or []) if str(c)})[:5]
    nuts = list(filtro.get("nuts") or [])
    return {"cpv": cpv, "nuts": nuts}


def _dia(v) -> date | None:
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def _hace_meses(hoy: date, meses: int) -> date:
    y, m = divmod(hoy.year * 12 + hoy.month - 1 - meses, 12)
    return date(y, m + 1, min(hoy.day, 28))


async def hay_cobertura(consulta, hoy: date, meses: int) -> bool:
    """¿Tiene el motor alguna adjudicación de hace al menos `meses` meses? Si no, su historia es demasiado corta para decir que alguien es nuevo."""
    r = await consulta("/awards", {"adjudicada_hasta": _hace_meses(hoy, meses).isoformat(), "resultado": "adjudicado", "limit": 1})
    return bool(r.get("items"))


async def gano_antes(consulta, nif: str, mercado: dict, fecha: date, licitacion_id: str) -> bool:
    """¿Había ganado ya ese NIF algo en el mercado, en una licitación distinta y antes del día de esta adjudicación?"""
    p = {"adjudicatario": f"nif:{nif}", "resultado": "adjudicado", "adjudicada_hasta": (fecha - timedelta(days=1)).isoformat(), "limit": 5}
    if mercado.get("cpv"):
        p["cpv"] = mercado["cpv"]
    if mercado.get("nuts"):
        p["nuts"] = mercado["nuts"]
    r = await consulta("/awards", p)
    return any(str(x.get("licitacion_id")) != str(licitacion_id) for x in r.get("items", []))


async def solo_los_nuevos(consulta, ganadores: list[dict], filtro: dict, item: dict, ficha: dict, hoy: date, cfg: dict | None = None) -> tuple[list[dict], str]:
    """(los ganadores que son nuevos en el mercado, motivo si no hay ninguno). Cada ganador lleva `_nif`; un adjudicatario sin NIF no se puede comparar y no cuenta."""
    c = configuracion(cfg)
    mercado = mercado_de(filtro, item)
    if not mercado["cpv"] and not mercado["nuts"]:
        return [], "sin mercado: ni la alerta ni el expediente tienen CPV o zona con los que comparar"
    if not await hay_cobertura(consulta, hoy, c["cobertura_meses"]):
        return [], f"el motor aún no tiene histórico de al menos {c['cobertura_meses']} meses: no se puede saber si alguien es nuevo"
    fechas = [_dia(a.get("fecha_adjudicacion")) for a in (ficha.get("adjudicaciones") or []) if a.get("resultado") == "adjudicado"]
    fecha = min((f for f in fechas if f), default=hoy)
    nuevos = []
    for g in ganadores:
        if not g.get("_nif"):
            continue
        if not await gano_antes(consulta, g["_nif"], mercado, fecha, item.get("id") or ""):
            nuevos.append(g)
    return nuevos, "" if nuevos else "los adjudicatarios ya habían ganado antes en ese mercado"
