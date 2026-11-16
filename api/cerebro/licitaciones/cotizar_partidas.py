"""Pedir cotización de lo que no tiene precio: de una oferta, prepara de una vez las cotizaciones (en BORRADOR) de todas las partidas sin coste en las tarifas.

Para cada partida SIN coste, con cantidad y sin otra cotización abierta: saca la marca del producto, busca qué proveedores la distribuyen (`proveedores_marcas`, de sus tarifas y de lo añadido a mano) y crea el borrador
con el proveedor que más artículos de esa marca tiene Y correo de contacto. El correo lo redacta el sistema con la plantilla de siempre (solo referencia, cantidad y plazo): aquí no se envía nada.
Lo que no se puede preparar (sin cantidad, sin marca, sin proveedor o sin su correo) se devuelve con el motivo: nada se inventa. Quien decide y envía sigue siendo una persona (Dirección). Pura salvo `preparar`.
"""
from __future__ import annotations

import logging
import re

from .. import cotizaciones as COT
from .. import proveedores_marcas as PM
from . import partidas as P

log = logging.getLogger("cerebro.cotizar_partidas")


def referencia_de(producto: str) -> str:
    """La referencia que se le pide al proveedor (la misma regla que el panel): la palabra con letras y números más larga (mín. 4 caracteres); si no hay, el texto recortado. Pura."""
    palabras = [re.sub(r"^[^A-Za-z0-9]+|[^A-Za-z0-9)]+$", "", p) for p in str(producto or "").split()]
    palabras = [p for p in palabras if len(p) >= 4 and re.search(r"[A-Za-z]", p) and re.search(r"\d", p) and re.fullmatch(r"[A-Za-z0-9._/+()#:-]+", p)]
    if palabras:
        return sorted(palabras, key=len, reverse=True)[0][:80]
    return " ".join(str(producto or "").split())[:80]


def marca_de(producto: str, marcas: list[str], cfg: dict | None = None) -> str | None:
    """De las marcas conocidas (las de las tarifas) la que aparece como palabra en el texto del producto; la más larga si hay varias. None si ninguna. Pura."""
    texto = " " + PM.plano(producto) + " "
    mejor = None
    for m in marcas:
        _n, clave = PM.canonica(m, cfg)
        if len(clave) >= 3 and f" {clave} " in texto and (mejor is None or len(clave) > len(PM.canonica(mejor, cfg)[1])):
            mejor = m
    return mejor


def elegir_proveedor(proveedores: list[dict]) -> tuple[dict | None, str]:
    """(proveedor, motivo): el que más artículos de la marca tiene y correo de contacto. Sin correo en ninguno, dice a quién habría que ponérselo. Pura."""
    if not proveedores:
        return None, "Ningún proveedor de tus tarifas distribuye esa marca (puedes añadirlo en «Proveedores y marcas»)"
    con = sorted((p for p in proveedores if p.get("email")), key=lambda p: -int(p.get("articulos") or 0))
    if con:
        return con[0], ""
    return None, f"Falta el correo de {proveedores[0]['proveedor']}: añádelo en «Contactos de proveedores» de Cotizaciones"


def pendientes(filas: list[dict], abiertas: list[dict]) -> list[dict]:
    """Las partidas que piden cotización: vivas, sin coste, con cantidad y sin otra cotización en borrador o enviada. Pura."""
    con_cotizacion = {c.get("partida") for c in abiertas if c.get("partida") is not None}
    return [f for f in filas if not f.get("excluida") and f.get("coste_unit_eur") is None and f.get("cantidad") not in (None, "") and f["id"] not in con_cotizacion]


def sin_cantidad(filas: list[dict]) -> list[dict]:
    return [f for f in filas if not f.get("excluida") and f.get("coste_unit_eur") is None and f.get("cantidad") in (None, "")]


async def preparar(motor_id: str, por: str, modo: str, plazo_tipo: str, plazo_valor, listar=None, abiertas=None, marcas=None, proveedores=None, crear=None) -> dict:
    """Crea los borradores. {creadas: [{id, producto, proveedor, referencia}], omitidas: [{producto, motivo}]}. Las funciones de lectura/escritura se pueden sustituir (pruebas)."""
    listar, abiertas, crear = listar or P.listar, abiertas or COT.abiertas, crear or COT.crear
    filas = (await listar(motor_id))["partidas"]
    quedan = pendientes(filas, await abiertas())
    todas = marcas if marcas is not None else [m["marca"] for p in (await PM.listar())["proveedores"] for m in p["marcas"]]
    creadas, omitidas = [], [{"producto": f["producto"], "motivo": "Pon la cantidad antes de pedir la cotización"} for f in sin_cantidad(filas)]
    for f in quedan:
        marca = marca_de(f["producto"], todas)
        if not marca:
            omitidas.append({"producto": f["producto"], "motivo": "No reconozco la marca entre las de tus proveedores: pídela a mano en Cotizaciones"})
            continue
        listado = proveedores[marca] if proveedores is not None else (await PM.listar(marca))["proveedores"]
        mails = {c["proveedor"]: c["email"] for c in await COT.contactos()} if proveedores is None else {}
        elegido, motivo = elegir_proveedor([{"proveedor": p["proveedor"], "articulos": p["articulos"], "email": p.get("email") or mails.get(p["proveedor"])} for p in listado])
        if not elegido:
            omitidas.append({"producto": f["producto"], "motivo": motivo})
            continue
        try:
            c = await crear({"referencia": referencia_de(f["producto"]), "cantidad": int(round(float(f["cantidad"]))) or 1, "plazo_tipo": plazo_tipo, "plazo_valor": plazo_valor,
                             "proveedor": elegido["proveedor"], "email": elegido["email"], "modo": modo, "marca": marca, "licitacion": motor_id, "partida": f["id"]}, por)
        except COT.ErrorCotizacion as e:
            omitidas.append({"producto": f["producto"], "motivo": str(e)[:200]})
            continue
        creadas.append({"id": c["id"], "producto": f["producto"], "proveedor": elegido["proveedor"], "referencia": c["referencia"]})
    log.info("cotizar_partidas: %s prepara %s borrador(es) para %s (%s omitidas)", por, len(creadas), motor_id, len(omitidas))
    return {"creadas": creadas, "omitidas": omitidas}
