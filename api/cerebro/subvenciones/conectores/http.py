"""Petición HTTP con reintentos y backoff, común a los conectores nuevos (el de la BDNS lleva la suya). Solo lectura; User-Agent identificado; sin credenciales de la empresa."""
from __future__ import annotations

import asyncio

import httpx

from .base import ErrorConector

USER_AGENT = "ARES-FundingIntelligence/1.0 (+https://101.cat)"


async def pedir_json(cliente: httpx.AsyncClient, metodo: str, url: str, params: dict, ajustes: dict, nombre: str, texto: bool = False, aceptar: str = "application/json", **kw):
    """JSON de la respuesta (o su texto si `texto`), o ErrorConector si la fuente no responde o no devuelve JSON. Un 404 devuelve None (no hay documento). Reintenta los 429/5xx y los fallos de red."""
    reintentos = int(ajustes.get("reintentos", 3))
    for intento in range(reintentos + 1):
        try:
            r = await cliente.request(metodo, url, params=params or None, timeout=float(ajustes.get("timeout_s", 30)), headers={"Accept": aceptar, "User-Agent": USER_AGENT}, **kw)
            if r.status_code in (429, 500, 502, 503, 504) and intento < reintentos:
                await asyncio.sleep(min(2 ** intento * 2, 60))
                continue
            if r.status_code == 404:
                return None
            if r.status_code >= 400:
                raise ErrorConector(f"{nombre} respondió {r.status_code}")
            if texto:
                return r.text
            try:
                return r.json()
            except ValueError:
                raise ErrorConector(f"{nombre} no devolvió JSON") from None
        except httpx.HTTPError as e:
            if intento >= reintentos:
                raise ErrorConector(f"{nombre} no responde ({type(e).__name__})") from None
            await asyncio.sleep(min(2 ** intento * 2, 60))
    raise ErrorConector(f"{nombre} no responde")      # pragma: no cover
