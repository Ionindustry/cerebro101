"""Conversión de modelos en Word antiguo y OpenDocument (.doc, .odt, .rtf) a .docx, para poder rellenarlos como cualquier otra plantilla.

LibreOffice NO corre dentro de la API: corre en el servicio `conversor` (servicios/conversor), un contenedor aparte, sin salida a internet, sin acceso a la base de datos ni al ERP y
con el sistema de ficheros de solo lectura. La API le manda el documento (CONVERSOR_URL) y recibe el .docx, que valida igual que si lo hubiera hecho ella. Sin CONVERSOR_URL (un equipo de
desarrollo) se usa un LibreOffice local si lo hay (conversion_local.py).
"""
from __future__ import annotations

import os
import zipfile
from pathlib import Path

import httpx

from . import conversion_local as L
from .formularios import ErrorFormulario

CONVERTIBLES = L.CONVERTIBLES
PLAZO = L.PLAZO + 30


def _servicio() -> str:
    return os.environ.get("CONVERSOR_URL", "").strip().rstrip("/")


def _por_servicio(url: str, origen: Path, destino: Path, formato: str) -> Path:
    datos = origen.read_bytes()
    if len(datos) > L.MAX_SALIDA:
        raise ErrorFormulario("El documento es demasiado grande para convertirlo a Word")
    try:
        r = httpx.post(f"{url}/convertir", params={"formato": formato}, content=datos, headers={"Content-Type": "application/octet-stream"}, timeout=PLAZO)
    except httpx.HTTPError:
        raise ErrorFormulario(f"El servicio de conversión a Word no responde: el modelo en formato {formato} hay que rellenarlo a mano o pedir la versión en Word") from None
    if r.status_code != 200:
        try:
            motivo = str(r.json().get("error") or "")[:200]
        except ValueError:
            motivo = ""
        raise ErrorFormulario(motivo or f"No se ha podido convertir el documento ({formato}) a Word: hay que rellenarlo a mano o pedir la versión en Word")
    destino.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    destino.write_bytes(r.content)
    os.chmod(destino, 0o600)
    if not L.es_docx(destino):          # no se fía de lo que vuelva por la red: tiene que ser un Word de verdad
        destino.unlink(missing_ok=True)
        raise ErrorFormulario(f"La conversión del documento ({formato}) no ha dado un Word válido")
    return destino


def a_docx(origen: Path, destino: Path, formato: str) -> Path:
    """Convierte `origen` (doc, odt o rtf) en el .docx `destino`. ErrorFormulario, con un mensaje para la persona, si no se puede."""
    if formato not in CONVERTIBLES:
        raise ErrorFormulario(f"El formato {formato} no se convierte a Word")
    url = _servicio()
    if url:
        return _por_servicio(url, origen, destino, formato)
    if not L.disponible():
        raise ErrorFormulario(f"Este documento está en formato {formato} y la conversión a Word no está disponible en este servidor: hay que rellenarlo a mano o pedir la versión en Word")
    try:
        return L.convertir(origen, destino, formato)
    except L.ErrorConversion as e:
        raise ErrorFormulario(f"{e}: hay que rellenarlo a mano o pedir la versión en Word") from None
