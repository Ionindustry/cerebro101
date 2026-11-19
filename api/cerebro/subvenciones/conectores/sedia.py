"""Conector del Funding & Tenders Portal de la Comisión Europea (EU-001), por su servicio público de búsqueda (SEDIA).

VERIFICADO con una respuesta real el 19/11/2026: POST a /search-api/prod/rest/search?apiKey=SEDIA&text=***&pageSize=&pageNumber= con el formulario `query` (JSON) y `languages`. «SEDIA» es la clave PÚBLICA
que usa el propio portal (no es un secreto de la empresa). Cada resultado trae `metadata` con listas de valores: identifier, title, callTitle, type, status, startDate, deadlineDate, budget, description (HTML).
Solo se importan los anuncios de TIPO 8 (los «topics» de subvención que se ven en la respuesta verificada). Los tipos 1 y 2 NO están verificados (podrían ser licitaciones): no se importan salvo que Dirección los
añada en `tipos` de los ajustes tras comprobarlos. Estados de la consulta: 31094501 = próximamente, 31094502 = abierto (31094503 = cerrado: no se importa).
Se consulta en inglés (idioma original de los anuncios) y se descartan las copias por idioma (campo `reference` acaba en el código de idioma), que antes se leían varias veces y se marcaban como modificadas.
Si la fuente declara «abierto» pero el plazo ya pasó, manda la fecha (el estado se calcula con el calendario, igual que en la BDNS).
"""
from __future__ import annotations

import asyncio
import json
from datetime import date
from typing import AsyncIterator

import httpx

from .. import normalizar as N
from .base import Conector, ErrorConector, ErrorRegistro, Pagina
from .http import pedir_json

BASE_POR_DEFECTO = "https://api.tech.ec.europa.eu/search-api/prod/rest/search"
ESTADO_DECLARADO = {"31094501": "OPENING_SOON", "31094502": "OPEN", "31094503": "CLOSED"}


def _uno(meta: dict, clave: str):
    v = (meta or {}).get(clave)
    if isinstance(v, list):
        v = v[0] if v else None
    return v if v not in ("", []) else None


def _fechas(meta: dict, clave: str) -> list[date]:
    v = (meta or {}).get(clave)
    return sorted({d for d in (N.fecha(x) for x in (v if isinstance(v, list) else [v])) if d})


def _plazo(fechas: list[date], hoy: date) -> date | None:
    """Con varios cortes, el próximo que aún no ha pasado; si todos pasaron, el último."""
    futuras = [f for f in fechas if f >= hoy]
    return futuras[0] if futuras else (fechas[-1] if fechas else None)


def _url_ue(u) -> str | None:
    u = str(u or "").strip()
    return u if u.startswith("https://ec.europa.eu/") else None


class ConectorSEDIA(Conector):
    codigo = "sedia"

    def __init__(self, fuente: dict, params: dict, cliente=None):
        super().__init__(fuente, params, cliente)
        self.base = (self.ajustes.get("base_url") or fuente.get("api_base_url") or BASE_POR_DEFECTO).rstrip("/")

    def _formulario(self) -> dict:
        consulta = {"bool": {"must": [{"terms": {"type": [str(t) for t in self.ajustes.get("tipos", ["8"])]}},
                                      {"terms": {"status": [str(e) for e in self.ajustes.get("estados", ["31094501", "31094502"])]}}]}}
        return {"query": (None, json.dumps(consulta), "application/json"), "languages": (None, json.dumps(self.ajustes.get("idiomas", ["en"])), "application/json")}

    async def paginas(self, cursor: dict, hoy: date) -> AsyncIterator[Pagina]:
        tam = int(self.ajustes.get("tamano_pagina", 50))
        maximo = int(self.params.get("paginas_maximas_por_ejecucion", 40))
        pausa = float(self.params.get("pausa_entre_peticiones_s", 0.5))
        pagina = max(1, int((cursor or {}).get("pagina") or 1))
        vistos: set[str] = set()                        # la UE devuelve una copia por idioma del mismo anuncio: solo se toma la primera de cada identificador
        propio = self.cliente is None
        cliente = self.cliente or httpx.AsyncClient()
        try:
            for _ in range(maximo):
                datos = await pedir_json(cliente, "POST", self.base, {"apiKey": self.ajustes.get("api_key", "SEDIA"), "text": "***", "pageSize": tam, "pageNumber": pagina}, self.params,
                                         "Funding & Tenders (UE)", files=self._formulario())
                filas = datos.get("results") if isinstance(datos, dict) else None
                if not isinstance(filas, list):
                    raise ErrorConector("La búsqueda de la UE no devuelve `results` (¿cambió el formato? ajusta los ajustes de la fuente)")
                total = int(datos.get("totalResults") or 0)
                ultima = len(filas) < tam or pagina * tam >= total
                pagina += 1
                utiles = []
                for f in filas:
                    if not isinstance(f, dict):
                        continue
                    ident = str(_uno(f.get("metadata") or {}, "identifier") or f.get("reference") or "")
                    if ident and ident in vistos:
                        continue
                    vistos.add(ident)
                    utiles.append(f)
                yield Pagina(utiles, {} if ultima else {"pagina": pagina})
                if ultima:
                    return
                await asyncio.sleep(pausa)
        finally:
            if propio:
                await cliente.aclose()

    def normalizar(self, crudo: dict, hoy: date) -> dict:
        meta = crudo.get("metadata") or {}
        externo = N.limpiar(_uno(meta, "identifier") or _uno(meta, "ccm2Id"), 120)
        titulo = N.limpiar(_uno(meta, "title") or crudo.get("summary"), 1000)
        if not externo:
            raise ErrorRegistro("el anuncio de la UE no trae identificador")
        if not titulo:
            raise ErrorRegistro(f"el anuncio {externo} no trae título")
        apertura = (_fechas(meta, "startDate") or [None])[0]
        limite = _plazo(_fechas(meta, "deadlineDate"), hoy)
        estado = N.estado(apertura, limite, hoy)
        if estado == "UNKNOWN":
            estado = ESTADO_DECLARADO.get(str(_uno(meta, "status")), "UNKNOWN")
        llamada = N.limpiar(_uno(meta, "callTitle"), 300)
        enlace = _url_ue(crudo.get("url")) or _url_ue(_uno(meta, "url"))
        return {
            "title": titulo, "description": N.texto_de_html(_uno(meta, "description"), 6000), "program_name": llamada if llamada != titulo else None,
            "issuing_organization": "Comisión Europea", "official_url": enlace, "application_url": enlace, "country": "EU", "region": None, "province": None, "municipality": None,
            "geographic_scope": "europeo", "eligible_beneficiaries": [], "company_sizes": [], "economic_activities": [], "sector": [], "keywords": [], "funding_objectives": None,
            "funding_type": "subvencion", "total_budget": N.importe(_uno(meta, "budget")), "minimum_amount": None, "maximum_amount": None, "funding_percentage": None,
            "currency": "EUR", "cofinancing_required": None, "publication_date": None, "opening_date": apertura, "deadline": limite, "last_official_update": None,
            "legal_basis_url": None, "eligibility_requirements": None, "exclusions": None, "eligible_expenses": None, "status": estado,
            "_confidence": 0.9, "_external_id": externo, "_refs": {}, "_source_url": enlace, "_documents": [],
        }
