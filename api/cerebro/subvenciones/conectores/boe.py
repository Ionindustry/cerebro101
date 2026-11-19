"""Conector del BOE (ES-002): enlaza los «Extractos» de convocatoria de la sección 5B con su convocatoria de la BDNS. NO crea oportunidades propias.

VERIFICADO con respuestas reales el 19/11/2026: el sumario diario JSON (`/datosabiertos/api/boe/sumario/AAAAMMDD`) trae los ítems con identificador, titulo, url_pdf.texto, url_html y url_xml; los extractos de
convocatoria van en la sección «5B» con título «Extracto de la orden/Resolución … por la que se convocan …» y su XML contiene «BDNS(Identif.):NNNNNN» (el identificador de la convocatoria en la BDNS).
Por eso cada extracto es un registro SOLO-ENLACE: si la convocatoria ya está en la BDNS, se le añade la procedencia «BOE» y un documento (el extracto, con su PDF) sin tocar su estado ni sus datos; si todavía
no está, se omite (la ventana de días se relee en cada ejecución y se enlazará cuando llegue). Un extracto sin número BDNS no se importa (no se puede enlazar sin duplicar).
Por defecto solo se miran los extractos de la sección 5B; Dirección puede ampliar `secciones` y `patron_titulo` en los ajustes.
"""
from __future__ import annotations

import asyncio
import re
from datetime import date, timedelta
from typing import AsyncIterator

import httpx

from .. import normalizar as N
from .base import Conector, ErrorConector, ErrorRegistro, Pagina
from .http import pedir_json

BASE_POR_DEFECTO = "https://www.boe.es/datosabiertos/api/boe/sumario"
BDNS = re.compile(r"BDNS\s*\(\s*Identif\.\s*\)\s*:?\s*(\d{4,})", re.I)


def _https_boe(u) -> str | None:
    u = str(u or "").strip()
    return u if u.startswith("https://www.boe.es/") else None


def _lista(x) -> list:
    """El JSON del BOE (convertido desde XML) da un objeto suelto cuando solo hay uno y una lista cuando hay varios."""
    if x is None:
        return []
    return [e for e in (x if isinstance(x, list) else [x]) if isinstance(e, dict)]


def _items(sumario: dict) -> list[tuple[str, str, dict]]:
    """[(sección, departamento, ítem)] del sumario del día."""
    salida = []
    data = sumario.get("data") if isinstance(sumario.get("data"), dict) else {}
    cuerpo = data.get("sumario") if isinstance(data.get("sumario"), dict) else {}
    for dia in _lista(cuerpo.get("diario")):
        for sec in _lista(dia.get("seccion")):
            for dep in _lista(sec.get("departamento")):
                epigrafes = _lista(dep.get("epigrafe")) or [{"item": dep.get("item")}]
                for epi in epigrafes:
                    for it in _lista(epi.get("item")):
                        if it.get("identificador") and it.get("titulo"):
                            salida.append((str(sec.get("codigo") or ""), str(dep.get("nombre") or ""), it))
    return salida


class ConectorBOE(Conector):
    codigo = "boe"

    def __init__(self, fuente: dict, params: dict, cliente=None):
        super().__init__(fuente, params, cliente)
        self.base = (self.ajustes.get("base_url") or fuente.get("api_base_url") or BASE_POR_DEFECTO).rstrip("/")
        self.secciones = {str(s) for s in self.ajustes.get("secciones", ["5B"])}
        self.patron = re.compile(self.ajustes.get("patron_titulo", r"^\s*extracto\b.*\bconvoca"), re.I)

    async def paginas(self, cursor: dict, hoy: date) -> AsyncIterator[Pagina]:
        dias = max(1, min(int(self.ajustes.get("dias_ventana", 7)), 31))
        pausa = float(self.params.get("pausa_entre_peticiones_s", 0.5))
        dia = N.fecha((cursor or {}).get("dia")) or (hoy - timedelta(days=dias - 1))
        dia = max(dia, hoy - timedelta(days=dias - 1))
        propio = self.cliente is None
        cliente = self.cliente or httpx.AsyncClient()
        try:
            while dia <= hoy:
                sumario = await pedir_json(cliente, "GET", f"{self.base}/{dia.strftime('%Y%m%d')}", {}, self.params, "BOE")
                registros = []
                if isinstance(sumario, dict):           # None = ese día no hay sumario (domingos, festivos)
                    for seccion, departamento, it in _items(sumario):
                        if seccion not in self.secciones or not self.patron.search(it["titulo"]):
                            continue
                        bdns = None
                        xml = _https_boe(it.get("url_xml"))
                        if xml:
                            await asyncio.sleep(pausa)
                            try:
                                m = BDNS.search(await pedir_json(cliente, "GET", xml, {}, self.params, "BOE (extracto)", texto=True, aceptar="application/xml") or "")
                                bdns = m.group(1) if m else None
                            except ErrorConector:
                                bdns = None
                        registros.append({"item": it, "departamento": departamento, "seccion": seccion, "bdns": bdns, "fecha": dia.isoformat()})
                elif sumario is not None:
                    raise ErrorConector("El sumario del BOE no es un objeto JSON (¿cambió el formato?)")
                dia += timedelta(days=1)
                yield Pagina(registros, {} if dia > hoy else {"dia": dia.isoformat()})
                if dia <= hoy:
                    await asyncio.sleep(pausa)
        finally:
            if propio:
                await cliente.aclose()

    def normalizar(self, crudo: dict, hoy: date) -> dict:
        it = crudo.get("item") or {}
        externo = N.limpiar(it.get("identificador"), 60)
        titulo = N.limpiar(it.get("titulo"), 1000)
        if not externo or not titulo:
            raise ErrorRegistro("el ítem del BOE no trae identificador o título")
        if not crudo.get("bdns"):
            raise ErrorRegistro(f"el extracto {externo} no cita un número de la BDNS: no se puede enlazar sin duplicar")
        html = _https_boe(it.get("url_html"))
        bruto_pdf = it.get("url_pdf")
        pdf = _https_boe(bruto_pdf.get("texto") if isinstance(bruto_pdf, dict) else bruto_pdf)
        return {
            "title": titulo, "description": None, "program_name": None, "issuing_organization": N.limpiar(crudo.get("departamento"), 300), "official_url": html, "application_url": None,
            "country": "ES", "region": None, "province": None, "municipality": None, "geographic_scope": None, "eligible_beneficiaries": [], "company_sizes": [], "economic_activities": [],
            "sector": [], "keywords": [], "funding_objectives": None, "funding_type": None, "total_budget": None, "minimum_amount": None, "maximum_amount": None, "funding_percentage": None,
            "currency": "EUR", "cofinancing_required": None, "publication_date": N.fecha(crudo.get("fecha")), "opening_date": None, "deadline": None, "last_official_update": None,
            "legal_basis_url": None, "eligibility_requirements": None, "exclusions": None, "eligible_expenses": None, "status": "UNKNOWN",
            "_confidence": 0.4, "_external_id": externo, "_refs": {"BDNS": crudo["bdns"]}, "_source_url": html, "_solo_enlazar": True,
            "_documents": [{"title": "Extracto en el BOE", "url": pdf or html, "doc_type": "extracto_boe"}] if (pdf or html) else [],
        }
