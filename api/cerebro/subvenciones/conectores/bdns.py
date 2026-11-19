"""Conector de la Base de Datos Nacional de Subvenciones (BDNS, ES-001).

ESTADO: PENDIENTE DE VERIFICAR contra el servicio real. Los nombres de endpoints y campos de abajo son los que documenta el catálogo de fuentes de ARES
(GET /convocatorias/busqueda, /convocatorias/ultimas, /convocatorias, /convocatorias/documentos, /convocatorias/exportar) y los que se conocen de uso público de la API,
pero NO se han podido comprobar con respuestas reales desde el entorno de desarrollo (sin acceso de red al portal). Por eso:
  - todo lo que depende de la forma de la respuesta es configurable (`settings` de la fuente: endpoints, nombres de parámetros y `campos`) sin tocar el código;
  - la fuente nace en PENDING_VERIFICATION y no se sincroniza sola hasta que una persona de Dirección la habilite tras comprobar datos reales;
  - `scripts/subvenciones_verificar.sh` guarda respuestas reales del servidor para ajustar los nombres.
Nunca se inventan datos: lo que la respuesta no trae queda en null.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from typing import AsyncIterator

import httpx

from .. import normalizar as N
from .base import Conector, ErrorConector, ErrorRegistro, Pagina

log = logging.getLogger("cerebro.subvenciones.bdns")

BASE_POR_DEFECTO = "https://www.infosubvenciones.es/bdnstrans/api"
PORTAL = "https://www.infosubvenciones.es/bdnstrans/"

# Dónde mirar cada dato en el registro crudo {"resumen": …lista de búsqueda…, "detalle": …detalle de la convocatoria…}. Se prueban en orden; el primero que existe gana.
CAMPOS_POR_DEFECTO = {
    "external_id": ["resumen.numeroConvocatoria", "detalle.codigoBDNS", "detalle.numeroConvocatoria"],
    "title": ["detalle.descripcion", "resumen.descripcion"],
    "title_ca": ["detalle.descripcionLeng", "resumen.descripcionLeng"],
    "nivel1": ["detalle.organo.nivel1", "resumen.nivel1"],
    "nivel2": ["detalle.organo.nivel2", "resumen.nivel2"],
    "nivel3": ["detalle.organo.nivel3", "resumen.nivel3"],
    "publication_date": ["detalle.fechaRecepcion", "resumen.fechaRecepcion"],
    "opening_date": ["detalle.fechaInicioSolicitud"],
    "deadline": ["detalle.fechaFinSolicitud"],
    "total_budget": ["detalle.presupuestoTotal"],
    "application_url": ["detalle.sedeElectronica"],
    "legal_basis_url": ["detalle.urlBasesReguladoras"],
    "abierto": ["detalle.abierto"],
    "beneficiarios": ["detalle.tiposBeneficiarios"],
    "sectores": ["detalle.sectores"],
    "regiones": ["detalle.regiones"],
    "instrumentos": ["detalle.instrumentos"],
    "objetivo": ["detalle.finalidad.descripcion", "detalle.finalidad"],
    "documentos": ["detalle.documentos"],
    "ultima_modificacion": ["detalle.fechaModificacion"],
}
AMBITO = {"estado": "nacional", "autonomica": "autonomico", "local": "local", "otros": "otro"}


def _buscar(crudo: dict, ruta: str):
    v = crudo
    for parte in ruta.split("."):
        if not isinstance(v, dict) or parte not in v:
            return None
        v = v[parte]
    return v


def _valor(crudo: dict, campos: dict, nombre: str):
    for ruta in campos.get(nombre, []):
        v = _buscar(crudo, ruta)
        if v not in (None, "", []):
            return v
    return None


def _descripciones(v) -> list[str]:
    """Una lista de {descripcion: …} (o de textos) como lista de textos sin repetir."""
    out = []
    for x in v if isinstance(v, list) else ([] if v in (None, "") else [v]):
        t = N.limpiar(x.get("descripcion") or x.get("nombre") if isinstance(x, dict) else x, 300)
        if t and t not in out:
            out.append(t)
    return out


class ConectorBDNS(Conector):
    codigo = "bdns"

    def __init__(self, fuente: dict, params: dict, cliente=None):
        super().__init__(fuente, params, cliente)
        self.base = (self.ajustes.get("base_url") or fuente.get("api_base_url") or BASE_POR_DEFECTO).rstrip("/")
        self.campos = {**CAMPOS_POR_DEFECTO, **(self.ajustes.get("campos") or {})}

    # ---- HTTP con reintentos, backoff y pausa de cortesía ----
    async def _get(self, cliente: httpx.AsyncClient, ruta: str, parametros: dict):
        reintentos = int(self.params.get("reintentos", 3))
        for intento in range(reintentos + 1):
            try:
                r = await cliente.get(f"{self.base}{ruta}", params=parametros, timeout=float(self.params.get("timeout_s", 30)),
                                      headers={"Accept": "application/json", "User-Agent": "ARES-FundingIntelligence/1.0 (+https://101.cat)"})
                if r.status_code in (429, 500, 502, 503, 504) and intento < reintentos:
                    await asyncio.sleep(min(2 ** intento * 2, 60))
                    continue
                if r.status_code >= 400:
                    raise ErrorConector(f"BDNS respondió {r.status_code} en {ruta}")
                try:
                    return r.json()
                except ValueError:
                    raise ErrorConector(f"BDNS no devolvió JSON en {ruta}") from None
            except httpx.HTTPError as e:
                if intento >= reintentos:
                    raise ErrorConector(f"BDNS no responde ({type(e).__name__})") from None
                await asyncio.sleep(min(2 ** intento * 2, 60))
        raise ErrorConector("BDNS no responde")     # pragma: no cover

    async def paginas(self, cursor: dict, hoy: date) -> AsyncIterator[Pagina]:
        a = self.ajustes
        tam = int(a.get("tamano_pagina") or self.params.get("tamano_pagina", 50))
        maximo = int(self.params.get("paginas_maximas_por_ejecucion", 40))
        pausa = float(self.params.get("pausa_entre_peticiones_s", 0.5))
        formato = a.get("formato_fecha", "%d/%m/%Y")
        desde = N.fecha((cursor or {}).get("desde")) or (hoy - timedelta(days=int(a.get("dias_primera_carga", 7))))
        pagina = int((cursor or {}).get("pagina") or 0)
        propio = self.cliente is None
        cliente = self.cliente or httpx.AsyncClient()
        try:
            for _ in range(maximo):
                parametros = {a.get("param_pagina", "page"): pagina, a.get("param_tamano", "pageSize"): tam, a.get("param_desde", "fechaDesde"): desde.strftime(formato)}
                if a.get("vpd", "GE"):
                    parametros["vpd"] = a.get("vpd", "GE")
                datos = await self._get(cliente, a.get("endpoint_busqueda", "/convocatorias/busqueda"), parametros)
                filas = datos.get("content") if isinstance(datos, dict) else datos
                if not isinstance(filas, list):
                    raise ErrorConector("La búsqueda de BDNS no devuelve una lista de convocatorias (¿cambió el formato? ajusta endpoints y campos en la fuente)")
                registros, fallos = [], 0
                for fila in filas:
                    if not isinstance(fila, dict):
                        continue
                    detalle = None
                    if a.get("con_detalle", True):
                        numero = _valor({"resumen": fila}, {"n": ["resumen.numeroConvocatoria"]}, "n")
                        if numero:
                            await asyncio.sleep(pausa)
                            try:
                                detalle = await self._get(cliente, a.get("endpoint_detalle", "/convocatorias"), {a.get("param_detalle", "numConv"): numero})
                            except ErrorConector as e:
                                fallos += 1
                                log.warning("BDNS: sin detalle de %s (%s); se guarda solo el resumen", numero, e)
                    registros.append({"resumen": fila, "detalle": detalle if isinstance(detalle, dict) else None})
                if filas and fallos > len(filas) / 2:
                    raise ErrorConector("BDNS: falla el detalle de más de la mitad de las convocatorias de la página")
                ultima = bool(filas == [] or (isinstance(datos, dict) and datos.get("last") is True) or len(filas) < tam)
                pagina += 1
                yield Pagina(registros, {"desde": (hoy - timedelta(days=2)).isoformat(), "pagina": 0} if ultima else {"desde": desde.isoformat(), "pagina": pagina})
                if ultima:
                    return
                await asyncio.sleep(pausa)
        finally:
            if propio:
                await cliente.aclose()

    def normalizar(self, crudo: dict, hoy: date) -> dict:
        v = lambda n: _valor(crudo, self.campos, n)      # noqa: E731
        externo = N.limpiar(v("external_id"), 60)
        titulo = N.limpiar(v("title"), 1000)
        if not externo:
            raise ErrorRegistro("la convocatoria no trae identificador")
        if not titulo:
            raise ErrorRegistro(f"la convocatoria {externo} no trae título")
        n1, n2, n3 = (N.limpiar(v(k), 300) for k in ("nivel1", "nivel2", "nivel3"))
        regiones = _descripciones(v("regiones"))
        instrumentos = _descripciones(v("instrumentos"))
        detalle = crudo.get("detalle")
        apertura, limite = N.fecha(v("opening_date")), N.fecha(v("deadline"))
        abierto = v("abierto")
        opp = {
            "title": titulo,
            "description": N.limpiar(v("objetivo"), 6000),
            "program_name": None,
            "issuing_organization": " · ".join(x for x in (n2 or n1, n3) if x) or None,
            "official_url": (self.ajustes.get("ficha_url") or "").format(numero=externo) or PORTAL,
            "application_url": N.limpiar(v("application_url"), 1000),
            "country": "ES",
            "region": regiones[0] if len(regiones) == 1 else None,
            "province": None, "municipality": None,
            "geographic_scope": AMBITO.get(N.plano(n1)),
            "eligible_beneficiaries": _descripciones(v("beneficiarios")),
            "company_sizes": [], "economic_activities": [],
            "sector": _descripciones(v("sectores")),
            "keywords": [],
            "funding_objectives": None,
            "funding_type": next((t for t in (N.instrumento(i) for i in instrumentos) if t), None),
            "total_budget": N.importe(v("total_budget")),
            "minimum_amount": None, "maximum_amount": None, "funding_percentage": None,
            "currency": "EUR", "cofinancing_required": None,
            "publication_date": N.fecha(v("publication_date")), "opening_date": apertura, "deadline": limite,
            "last_official_update": None,
            "legal_basis_url": N.limpiar(v("legal_basis_url"), 1000),
            "eligibility_requirements": None, "exclusions": None, "eligible_expenses": None,
            "status": N.estado(apertura, limite, hoy, abierta_declarada=abierto if isinstance(abierto, bool) else None),
            # Con solo el resumen (sin detalle) se sabe poco: confianza baja, y se completa cuando llegue el detalle
            "_confidence": 0.9 if detalle else 0.4,
            "_external_id": externo, "_refs": {}, "_source_url": PORTAL,
            "_documents": [{"title": N.limpiar(d.get("nombre") or d.get("descripcion"), 300), "url": d.get("url"), "doc_type": N.limpiar(d.get("tipo"), 60)}
                           for d in (v("documentos") or []) if isinstance(d, dict) and str(d.get("url") or "").startswith("http")],
        }
        if v("title_ca") and not opp["description"]:
            opp["description"] = N.limpiar(v("title_ca"), 2000)
        return opp
