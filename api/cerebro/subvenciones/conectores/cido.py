"""Conector del dataset «Convocatòries de subvencions» de la Generalitat de Catalunya (ES-003; datos de la Diputació de Barcelona y otros entes catalanes, vía el CIDO).

VERIFICADO con respuestas reales el 19/11/2026 (consulta Socrata en formato JSON): campos resum, data_pub, enlla.url, codi_ens, nom_ens, estat. LIMITES DE LOS DATOS: no trae plazo, ni importe, ni
fecha de apertura ni identificador propio (el identificador es el número final del enlace al CIDO). Por eso el estado sale SOLO de lo que declara el campo «estat» (nunca se inventan fechas) y la
confianza es baja: sirve para saber que una convocatoria local existe y abrir su ficha oficial, no para decidir. Licencia del dataset: «ver términos de uso» (atribución al Consorci AOC / CIDO).
Estados declarados vistos: Termini tancat, Resolt, Procés no vigent, Pendent de convocatòria, Termini obert, Pendent de termini.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import AsyncIterator

import httpx

from .. import normalizar as N
from .base import Conector, ErrorRegistro, Pagina
from .http import pedir_json

BASE_POR_DEFECTO = "https://analisi.transparenciacatalunya.cat/resource/3gku-b36y.json"
ESTADOS_VIVOS = ("Termini obert", "Pendent de termini", "Pendent de convocatòria")
# «Procés no vigent» = el proceso ya no está en vigor: se trata como cerrado. «Resolt» = ya se ha resuelto: cerrado.
ESTADO_DECLARADO = {"termini tancat": "CLOSED", "resolt": "CLOSED", "proces no vigent": "CLOSED", "pendent de convocatoria": "OPENING_SOON", "pendent de termini": "OPENING_SOON", "termini obert": "OPEN"}


def _enlace(v) -> str | None:
    u = v.get("url") if isinstance(v, dict) else v
    u = str(u or "").strip()
    return u if u.startswith(("http://", "https://")) else None


class ConectorCIDO(Conector):
    codigo = "cido"

    def __init__(self, fuente: dict, params: dict, cliente=None):
        super().__init__(fuente, params, cliente)
        self.base = (self.ajustes.get("base_url") or fuente.get("api_base_url") or BASE_POR_DEFECTO).rstrip("/")

    def _donde(self, hoy: date) -> str:
        desde = hoy - timedelta(days=30 * int(self.ajustes.get("meses_ventana", 12)))
        vivos = ", ".join("'" + e.replace("'", "''") + "'" for e in ESTADOS_VIVOS)
        return f"data_pub >= '{desde.isoformat()}T00:00:00' OR estat in ({vivos})"

    async def paginas(self, cursor: dict, hoy: date) -> AsyncIterator[Pagina]:
        tam = int(self.ajustes.get("tamano_pagina", 1000))
        maximo = int(self.params.get("paginas_maximas_por_ejecucion", 40))
        pausa = float(self.params.get("pausa_entre_peticiones_s", 0.5))
        salto = int((cursor or {}).get("offset") or 0)
        propio = self.cliente is None
        cliente = self.cliente or httpx.AsyncClient()
        try:
            for _ in range(maximo):
                filas = await pedir_json(cliente, "GET", self.base, {"$where": self._donde(hoy), "$order": ":id", "$limit": tam, "$offset": salto}, self.params, "Dades obertes de Catalunya")
                if not isinstance(filas, list):
                    from .base import ErrorConector
                    raise ErrorConector("El dataset de Cataluña no devuelve una lista (¿cambió el formato?)")
                ultima = len(filas) < tam
                salto += len(filas)
                yield Pagina([f for f in filas if isinstance(f, dict)], {} if ultima else {"offset": salto})
                if ultima:
                    return
                import asyncio
                await asyncio.sleep(pausa)
        finally:
            if propio:
                await cliente.aclose()

    def normalizar(self, crudo: dict, hoy: date) -> dict:
        enlace = _enlace(crudo.get("enlla"))
        m = re.search(r"/subvencions/(\d+)", enlace or "")
        titulo = N.limpiar(crudo.get("resum"), 1000)
        if not m:
            raise ErrorRegistro("la convocatoria no trae un enlace con identificador del CIDO")
        if not titulo:
            raise ErrorRegistro(f"la convocatoria {m.group(1)} no trae título")
        declarado = N.plano(crudo.get("estat"))
        return {
            "title": titulo, "description": None, "program_name": None, "issuing_organization": N.limpiar(crudo.get("nom_ens"), 300),
            "official_url": enlace, "application_url": None, "country": "ES", "region": "Cataluña", "province": None, "municipality": None, "geographic_scope": "local",
            "eligible_beneficiaries": [], "company_sizes": [], "economic_activities": [], "sector": [], "keywords": [], "funding_objectives": None, "funding_type": None,
            "total_budget": None, "minimum_amount": None, "maximum_amount": None, "funding_percentage": None, "currency": "EUR", "cofinancing_required": None,
            "publication_date": N.fecha(crudo.get("data_pub")), "opening_date": None, "deadline": None, "last_official_update": None, "legal_basis_url": None,
            "eligibility_requirements": None, "exclusions": None, "eligible_expenses": None,
            "status": ESTADO_DECLARADO.get(declarado, "UNKNOWN"),
            "_confidence": 0.4, "_external_id": m.group(1), "_refs": {}, "_source_url": enlace, "_documents": [],
        }
