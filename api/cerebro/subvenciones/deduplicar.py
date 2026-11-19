"""Identificador canónico y resolución de coincidencias entre fuentes. Código puro.

Orden de resolución de un registro nuevo (de más a menos seguro; nunca se fusiona por parecido):
  1. el mismo registro de la misma fuente (fuente + id externo): es una actualización, no una oportunidad nueva
  2. un identificador de OTRA fuente que el propio registro cita (p. ej. un extracto del BOE que dice «código BDNS 123456») → la oportunidad con ese identificador
  3. su propio identificador canónico (BDNS:123456, EU:HORIZON-…)
  4. sin identificador oficial: huella de organismo + título + fechas + territorio (coincidencia exacta tras normalizar)
Si nada coincide, es una oportunidad nueva. La similitud por significado (embeddings) queda como ayuda para revisar posibles duplicados, nunca para fusionar solos.
"""
from __future__ import annotations

import hashlib

from .normalizar import plano

# Prefijo del identificador canónico por fuente: las fuentes que hablan de lo mismo (BDNS, BOE, autonómicas) comparten el del identificador oficial
PREFIJOS = {"ES-001": "BDNS", "EU-001": "EU"}


def prefijo(codigo_fuente: str) -> str:
    return PREFIJOS.get(codigo_fuente, codigo_fuente)


def canonico(codigo_fuente: str, external_id: str | None) -> str | None:
    e = " ".join(str(external_id or "").split())
    return f"{prefijo(codigo_fuente)}:{e}" if e else None


def referencias_canonicas(refs: dict | None) -> list[str]:
    """Los identificadores canónicos que un registro cita de otras fuentes ({"BDNS": "123456"} → ["BDNS:123456"])."""
    return [f"{str(k).strip().upper()}:{' '.join(str(v).split())}" for k, v in (refs or {}).items() if str(v or "").strip()]


def huella_fuente_sin_id(opp: dict) -> str:
    """Identificador para registros sin identificador oficial: huella exacta del organismo, el título, las fechas y el territorio normalizados."""
    base = "|".join([plano(opp.get("issuing_organization")), plano(opp.get("title")), str(opp.get("opening_date") or ""), str(opp.get("deadline") or ""),
                     plano(opp.get("region")), plano(opp.get("country"))])
    return "FP:" + hashlib.sha256(base.encode("utf-8")).hexdigest()[:24]


def id_canonico(codigo_fuente: str, opp: dict, external_id: str | None) -> str:
    return canonico(codigo_fuente, external_id) or huella_fuente_sin_id(opp)
