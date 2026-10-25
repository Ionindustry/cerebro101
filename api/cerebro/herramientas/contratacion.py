"""Plataformas de contratación pública: lectura de los datos abiertos (ATOM) y preparación
del paquete de oferta.

La presentación NO se automatiza: las ofertas se presentan con la herramienta de la
plataforma y firma electrónica de una persona. El Cerebro deja el paquete preparado
y la lista de comprobación; la firma es siempre humana.

VERIFICAR con un fichero real de la plataforma: los nombres de campo de la
sindicación (formato CODICE) se buscan sin espacio de nombres para tolerar cambios.
"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

from .base import Herramienta, registrar
from .ficheros import _ruta_segura
from .integraciones import config

ATOM = "{http://www.w3.org/2005/Atom}"


def _local(etiqueta: str) -> str:
    return etiqueta.rsplit("}", 1)[-1]


def _primero(elemento: ET.Element, nombres: tuple[str, ...]) -> str | None:
    for e in elemento.iter():
        if _local(e.tag) in nombres and (e.text or "").strip():
            return e.text.strip()
    return None


def leer_feed(xml: str | bytes) -> list[dict]:
    raiz = ET.fromstring(xml)
    licitaciones = []
    for entrada in raiz.iter(f"{ATOM}entry"):
        enlace = entrada.find(f"{ATOM}link")
        cpv = sorted({e.text.strip() for e in entrada.iter()
                      if _local(e.tag) == "ItemClassificationCode" and (e.text or "").strip()})
        importe = _primero(entrada, ("TaxExclusiveAmount", "EstimatedOverallContractAmount", "TotalAmount"))
        licitaciones.append({
            "id": entrada.findtext(f"{ATOM}id"),
            "titulo": (entrada.findtext(f"{ATOM}title") or "").strip(),
            "resumen": (entrada.findtext(f"{ATOM}summary") or "").strip(),
            "enlace": enlace.get("href") if enlace is not None else None,
            "actualizado": entrada.findtext(f"{ATOM}updated"),
            "expediente": _primero(entrada, ("ContractFolderID",)),
            "organismo": _primero(entrada, ("Name",)),
            "cpv": cpv,
            "importe": float(importe) if importe else None,
            "fecha_limite": _primero(entrada, ("EndDate",)),
        })
    return licitaciones


def filtrar(licitaciones: list[dict], prefijos_cpv: list[str], importe_min: float | None = None,
            importe_max: float | None = None) -> list[dict]:
    def encaja(l: dict) -> bool:
        if prefijos_cpv and not any(c.startswith(tuple(prefijos_cpv)) for c in l["cpv"]):
            return False
        if l["importe"] is not None:
            if importe_min is not None and l["importe"] < importe_min:
                return False
            if importe_max is not None and l["importe"] > importe_max:
                return False
        return True
    return [l for l in licitaciones if encaja(l)]


async def novedades(cpv: list[str] | None = None, importe_min: float | None = None,
                    importe_max: float | None = None) -> list[dict]:
    c = config()["contratacion"]
    if not c["feeds"]:
        return [{"error": "No hay fuentes configuradas en config/integraciones.yaml (contratacion.feeds)"}]
    import httpx
    resultado = []
    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as cliente:
        for url in c["feeds"]:
            r = await cliente.get(url)
            r.raise_for_status()
            resultado += leer_feed(r.content)
    return filtrar(resultado, cpv or c["cpv_interes"], importe_min, importe_max)


async def descargar_documento(expediente: str, url: str, nombre: str) -> str:
    destino = _ruta_segura(f"{config()['contratacion']['carpeta_paquetes']}/{expediente}/pliegos/{nombre}")
    destino.parent.mkdir(parents=True, exist_ok=True)
    import httpx
    async with httpx.AsyncClient(timeout=300, follow_redirects=True) as cliente:
        r = await cliente.get(url)
        r.raise_for_status()
    destino.write_bytes(r.content)
    return str(destino)


async def preparar_paquete(expediente: str, sobres: dict[str, list[str]], comprobaciones: list[str]) -> dict:
    """Ordena los documentos ya generados por sobre y deja la lista de comprobación
    para la persona que firmará y presentará la oferta."""
    base = _ruta_segura(f"{config()['contratacion']['carpeta_paquetes']}/{expediente}")
    base.mkdir(parents=True, exist_ok=True)
    indice = {"expediente": expediente, "sobres": sobres, "comprobaciones": comprobaciones,
              "presentacion": "Pendiente: firma y presentación por una persona en la plataforma"}
    (base / "paquete.json").write_text(json.dumps(indice, ensure_ascii=False, indent=2), encoding="utf-8")
    faltan = [d for docs in sobres.values() for d in docs if not (base / d).exists()]
    return {"paquete": str(base / "paquete.json"), "documentos_que_faltan": faltan}


registrar(Herramienta(
    nombre="plataformas_contratacion",
    descripcion="Contratación pública. La presentación de ofertas la firma y hace siempre una persona.",
    operaciones={"novedades": novedades, "descargar_documento": descargar_documento,
                 "preparar_paquete": preparar_paquete},
    ayuda={"novedades": "licitaciones nuevas filtradas por CPV (códigos de 8 cifras, como texto) e importe",
           "descargar_documento": "descarga un pliego u otro documento del expediente",
           "preparar_paquete": "ordena los documentos ya generados por sobre y deja la lista de comprobación"},
    ejemplos={"novedades": {"cpv": ["35125000"], "importe_min": 10000}},
))
