"""Lectura defensiva de XML de terceros (PLACSP/CODICE, TED/eForms).

Solo biblioteca estándar. Ejecutar siempre con `python3 -I`.
- Rechaza cualquier DOCTYPE/ENTITY (sin DTD, sin entidades: ni XXE ni «billion laughs»).
- Límite de tamaño de fichero y de profundidad.
- Lectura en streaming con iterparse.
"""
import xml.etree.ElementTree as ET

MAX_BYTES = 200 * 1024 * 1024
MAX_DEPTH = 64

# Prefijos para mostrar rutas legibles (los del propio feed).
NS = {
    "http://www.w3.org/2005/Atom": "atom",
    "urn:dgpe:names:draft:codice:schema:xsd:CommonBasicComponents-2": "cbc",
    "urn:dgpe:names:draft:codice:schema:xsd:CommonAggregateComponents-2": "cac",
    "urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonAggregateComponents-2": "cac-place-ext",
    "urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonBasicComponents-2": "cbc-place-ext",
    "http://purl.org/atompub/tombstones/1.0": "at",
    "urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2": "ext",
    # eForms / UBL
    "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2": "cbc",
    "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2": "cac",
    "http://data.europa.eu/p27/eforms-ubl-extensions/1": "efext",
    "http://data.europa.eu/p27/eforms-ubl-extension-basic-components/1": "efbc",
    "http://data.europa.eu/p27/eforms-ubl-extension-aggregate-components/1": "efac",
    "urn:oasis:names:specification:ubl:schema:xsd:ContractNotice-2": "cn",
    "urn:oasis:names:specification:ubl:schema:xsd:ContractAwardNotice-2": "can",
    "urn:oasis:names:specification:ubl:schema:xsd:PriorInformationNotice-2": "pin",
}


class HostileXML(Exception):
    pass


def check_prolog(path, nbytes=65536):
    import os
    size = os.path.getsize(path)
    if size > MAX_BYTES:
        raise HostileXML(f"{path}: {size} bytes > límite {MAX_BYTES}")
    with open(path, "rb") as f:
        head = f.read(nbytes).upper()
    if b"<!DOCTYPE" in head or b"<!ENTITY" in head:
        raise HostileXML(f"{path}: DOCTYPE/ENTITY no permitido")


def short(tag):
    if tag.startswith("{"):
        uri, local = tag[1:].split("}", 1)
        return f"{NS.get(uri, uri)}:{local}"
    return tag


def check_bytes(data, nbytes=65536):
    if len(data) > MAX_BYTES:
        raise HostileXML(f"{len(data)} bytes > límite {MAX_BYTES}")
    head = data[:nbytes].upper()
    if b"<!DOCTYPE" in head or b"<!ENTITY" in head:
        raise HostileXML("DOCTYPE/ENTITY no permitido")


def iterparse_bytes(data, events=("start", "end")):
    """Como iterparse_safe pero sobre bytes en memoria (p. ej. una entrada de ZIP)."""
    import io
    check_bytes(data)
    depth = 0
    for ev, el in ET.iterparse(io.BytesIO(data), events=events):
        if ev == "start":
            depth += 1
            if depth > MAX_DEPTH:
                raise HostileXML(f"profundidad > {MAX_DEPTH}")
        elif ev == "end":
            depth -= 1
        yield ev, el


def iterparse_safe(path, events=("start", "end")):
    """iterparse con comprobación previa del prólogo y límite de profundidad.

    Según XML 1.0 el DOCTYPE solo puede ir antes del elemento raíz, así que
    basta con revisar el prólogo (check_prolog); un DOCTYPE posterior es un
    error de buena formación que expat ya rechaza.
    """
    check_prolog(path)
    depth = 0
    for ev, el in ET.iterparse(path, events=events):
        if ev == "start":
            depth += 1
            if depth > MAX_DEPTH:
                raise HostileXML(f"profundidad > {MAX_DEPTH}")
        elif ev == "end":
            depth -= 1
        yield ev, el
