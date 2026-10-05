"""Nombres de clientes, proveedores y empleados que hay que ocultar antes de enviar texto a la nube.

Se leen de ERPNext (con caché) y de config/anonimizacion.yaml. Si ERPNext está configurado y no se puede leer, se
devuelve `disponible=False` y el anonimizador bloquea el envío: sin esa lista falta la protección principal.
"""
from __future__ import annotations

import logging
import os
import time

from .anonimizacion import Entidades
from .ajustes import ajustes

log = logging.getLogger("cerebro.entidades")
_cache: dict[str, tuple[float, Entidades]] = {}
CADUCIDAD_MAXIMA = 24 * 3600       # una lista vieja protege mejor que ninguna


def erpnext_configurado() -> bool:
    return bool(os.environ.get("ERPNEXT_TOKEN_DIRECCION") or os.environ.get("ERPNEXT_TOKEN"))


async def _leer_erp(cfg: dict) -> tuple[list[str], list[str]]:
    from .herramientas import erpnext
    personas, organizaciones = [], []
    for doctype, datos in (cfg.get("erpnext") or {}).items():
        filas = await erpnext.listar(doctype, "direccion", campos=[datos["campo"]], limite=100000)
        destino = personas if datos.get("tipo") == "personas" else organizaciones
        destino += [f[datos["campo"]] for f in filas if f.get(datos["campo"])]
    return personas, organizaciones


async def cargar_entidades(cfg: dict, leer=_leer_erp) -> Entidades:
    extra = cfg.get("entidades_extra") or {}
    base = Entidades(personas=list(extra.get("personas") or []), organizaciones=list(extra.get("organizaciones") or []),
                     conservar=list(cfg.get("conservar") or []))
    if not erpnext_configurado():
        return base
    clave, ahora = ajustes.erpnext_url, time.time()
    en_cache = _cache.get(clave)
    if en_cache and ahora - en_cache[0] < cfg.get("caducidad_lista_segundos", 600):
        return en_cache[1]
    try:
        personas, organizaciones = await leer(cfg)
    except Exception as e:  # noqa: BLE001
        log.warning("No se pudo leer la lista de entidades de ERPNext: %s", e)
        if en_cache and ahora - en_cache[0] < CADUCIDAD_MAXIMA:
            return en_cache[1]
        return Entidades(personas=base.personas, organizaciones=base.organizaciones, conservar=base.conservar,
                         disponible=False, origen="erpnext")
    ent = Entidades(personas=base.personas + personas, organizaciones=base.organizaciones + organizaciones,
                    conservar=base.conservar, origen="erpnext")
    _cache[clave] = (ahora, ent)
    return ent
