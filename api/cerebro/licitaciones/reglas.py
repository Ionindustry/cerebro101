"""Reglas de puntuación del precio de una licitación, anotadas por una PERSONA a partir del pliego, y las fórmulas que las aplican.

El simulador de ofertas supone, sin más información, que gana la mejor oferta económica. Los pliegos puntúan el precio con una fórmula y le dan un peso (p. ej. 51 de 100 puntos);
con esas dos cosas se calculan los puntos de precio de cada oferta y se ve cuánto pesa el precio en la decisión. Las fórmulas son código determinista; la IA no calcula puntos.
Con b = baja de la oferta (fracción del presupuesto base) y r = baja de la mejor oferta rival:

  inversa            puntos = P × (1 − r) / (1 − b)   si la oferta no es la más baja (la más baja se lleva P); es la «proporcionalidad inversa» de muchos pliegos
  proporcional_baja  puntos = P × b / r               si la oferta no es la que más baja (la que más baja se lleva P)
  lineal_umbral      puntos = P × min(b, T) / T       con T = baja a partir de la cual no se puntúa más (no depende de las demás ofertas)

Las reglas las anota una persona (leyendo el pliego, con la ayuda de los requisitos que el Analista de Pliegos haya extraído); el agente no las puede tocar.
"""
from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation

import psycopg
from psycopg.rows import dict_row

from ..ajustes import ajustes
from ..herramientas import licitaciones as motor

log = logging.getLogger("cerebro.licitaciones.reglas")
FORMULAS = ("inversa", "proporcional_baja", "lineal_umbral")
NOTA_MAX = 500


class ErrorReglas(ValueError):
    """Lo que no se puede guardar; el mensaje es para la persona."""


def _num(v, nombre: str, minimo: float, maximo: float, obligatorio: bool = False) -> float | None:
    if v is None or (isinstance(v, str) and not v.strip()):
        if obligatorio:
            raise ErrorReglas(f"Falta {nombre}")
        return None
    if isinstance(v, bool):
        raise ErrorReglas(f"{nombre} debe ser un número")
    try:
        x = float(Decimal(str(v).strip().replace(",", ".")))
    except (InvalidOperation, ValueError):
        raise ErrorReglas(f"{nombre} debe ser un número") from None
    if not (minimo < x <= maximo) or x != x:
        raise ErrorReglas(f"{nombre} debe estar entre {minimo:g} (sin incluir) y {maximo:g}")
    return x


def validar(datos: dict) -> dict:
    """Normaliza y comprueba lo que escribe la persona; lanza ErrorReglas con un mensaje claro."""
    formula = str(datos.get("formula") or "")
    if formula not in FORMULAS:
        raise ErrorReglas("formula debe ser una de: " + ", ".join(FORMULAS))
    puntos = _num(datos.get("puntos_precio"), "los puntos del precio", 0, 1000, True)
    total = _num(datos.get("puntos_total"), "los puntos totales", 0, 1000) or 100.0
    if puntos > total:
        raise ErrorReglas("Los puntos del precio no pueden superar los puntos totales")
    tope = _num(datos.get("baja_tope_pct"), "la baja tope (%)", 0, 100)
    if formula == "lineal_umbral" and tope is None:
        raise ErrorReglas("Esta fórmula necesita la baja tope (%): la baja a partir de la cual no se puntúa más")
    anormal = _num(datos.get("baja_anormal_pct"), "el umbral de baja anormal (%)", 0, 100)
    nota = " ".join(str(datos.get("nota") or "").split())[:NOTA_MAX]
    return {"formula": formula, "puntos_precio": puntos, "puntos_total": total, "baja_tope_pct": tope if formula == "lineal_umbral" else None,
            "baja_anormal_pct": anormal, "nota": nota}


# ---- Fórmulas (puras) ----

def puntos_precio(regla: dict, b: float, r: float | None) -> float | None:
    """Puntos de precio de una oferta con baja b (fracción) frente a la mejor oferta rival con baja r (fracción; None si no se sabe). None si la fórmula necesita r y no lo hay."""
    P = float(regla["puntos_precio"])
    f = regla["formula"]
    if f == "lineal_umbral":
        t = float(regla["baja_tope_pct"]) / 100
        return P * min(max(b, 0.0), t) / t
    if r is None:
        return None
    if f == "inversa":
        if b >= 1:
            return P
        return P if b >= r else P * (1 - r) / (1 - b)
    if f == "proporcional_baja":
        if b >= r or r <= 0:
            return P
        return P * max(b, 0.0) / r
    return None


# ---- Base de datos ----

def _conectar():
    return psycopg.AsyncConnection.connect(ajustes.database_url, row_factory=dict_row)


def _comprobar_id(motor_id: str) -> None:
    if not isinstance(motor_id, str) or not motor._UUID.match(motor_id.strip()):
        raise ErrorReglas("licitacion debe ser el identificador (UUID) de la licitación")


def _salida(f: dict) -> dict:
    return {"motor_id": str(f["motor_id"]), "formula": f["formula"], "puntos_precio": float(f["puntos_precio"]), "puntos_total": float(f["puntos_total"]),
            "baja_tope_pct": None if f["baja_tope_pct"] is None else float(f["baja_tope_pct"]),
            "baja_anormal_pct": None if f["baja_anormal_pct"] is None else float(f["baja_anormal_pct"]),
            "nota": f["nota"], "por": f["por"], "actualizado": f["actualizado"].isoformat()}


async def leer(motor_id: str) -> dict | None:
    """Las reglas anotadas de la licitación, o None si nadie las ha anotado."""
    _comprobar_id(motor_id)
    async with await _conectar() as conn:
        cur = await conn.execute("SELECT * FROM licitaciones_reglas_precio WHERE motor_id = %s", [motor_id.strip().lower()])
        f = await cur.fetchone()
    return _salida(f) if f else None


async def guardar(motor_id: str, datos: dict, usuario: str) -> dict:
    _comprobar_id(motor_id)
    v = validar(datos)
    async with await _conectar() as conn:
        cur = await conn.execute(
            """INSERT INTO licitaciones_reglas_precio (motor_id, formula, puntos_precio, puntos_total, baja_tope_pct, baja_anormal_pct, nota, por)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (motor_id) DO UPDATE SET formula = EXCLUDED.formula, puntos_precio = EXCLUDED.puntos_precio, puntos_total = EXCLUDED.puntos_total,
                 baja_tope_pct = EXCLUDED.baja_tope_pct, baja_anormal_pct = EXCLUDED.baja_anormal_pct, nota = EXCLUDED.nota, por = EXCLUDED.por, actualizado = now()
               RETURNING *""",
            [motor_id.strip().lower(), v["formula"], v["puntos_precio"], v["puntos_total"], v["baja_tope_pct"], v["baja_anormal_pct"], v["nota"], str(usuario)[:200]])
        f = await cur.fetchone()
    log.info("reglas de precio: %s anota %s (%s)", usuario, motor_id, v["formula"])
    return _salida(f)


async def borrar(motor_id: str) -> bool:
    _comprobar_id(motor_id)
    async with await _conectar() as conn:
        cur = await conn.execute("DELETE FROM licitaciones_reglas_precio WHERE motor_id = %s", [motor_id.strip().lower()])
        return cur.rowcount > 0
