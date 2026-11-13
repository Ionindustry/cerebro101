"""Familias de producto de seguridad y qué datos se comparan en cada una (config/familias_equivalencia.csv) + modelos de ejemplo con ficha oficial (config/fichas_semillas.csv).

Es una GUÍA para la tabla de equivalencias: dice al modelo qué campos suelen decidir si un producto sirve (en vídeo: resolución real, sensor, WDR, ONVIF…; en incendio: EN 54 y protocolo de lazo…).
No añade parámetros que el pliego no pida, no sustituye a la evidencia y no decide nada: el veredicto lo sigue fijando el código con los números de las fichas. Los ficheros son datos
de terceros (se leen como datos). Las «semillas» son referencias de dónde buscar fichas oficiales; no son fichas cargadas ni autorizan ningún dominio.
"""
from __future__ import annotations

import csv
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

from ..ajustes import ajustes

# palabras (sin acentos, minúsculas) que delatan la familia en el texto del pliego
PISTAS = {
    "cctv": ("camara", "videovigilancia", "cctv", "videograbador", "grabador", "nvr", "ip66", "ip67", "megapixel", "resolucion", "ptz"),
    "intrusion": ("intrusion", "alarma", "central de alarma", "en 50131", "en50131", "detector volumetrico", "sirena"),
    "control_acceso": ("control de acceso", "controles de acceso", "controladora", "lector de tarjetas", "credencial", "torno", "osdp", "wiegand", "biometric"),
    "incendio": ("incendio", "en 54", "en54", "detector de humo", "pulsador de alarma", "central de incendios", "lazo"),
    "intercom": ("videoportero", "interfono", "intercomunicador", "portero"),
    "redes_poe": ("switch", "poe", "conmutador", "802.3"),
    "vms": ("vms", "software de gestion de video", "gestion de video", "licencia de canal", "plataforma de video"),
}
MAX_FAMILIAS = 2
MAX_CAMPOS = 14


def _plano(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", str(t).lower()) if unicodedata.category(c) != "Mn")


def _leer_csv(ruta: str) -> list[dict]:
    try:
        with open(ruta, encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    except OSError:
        return []


@lru_cache(maxsize=2)
def _familias(ruta: str) -> dict[str, tuple[tuple[str, str], ...]]:
    out: dict[str, list[tuple[str, str]]] = {}
    for r in _leer_csv(ruta):
        fam, campo = (r.get("familia") or "").strip(), (r.get("campo") or "").strip()
        if fam and campo:
            out.setdefault(fam, []).append((campo, (r.get("descripcion") or "").strip()))
    return {k: tuple(v) for k, v in out.items()}


def familias() -> dict[str, tuple[tuple[str, str], ...]]:
    """familia → ((campo, descripción), …); «comun» son los campos de cualquier familia."""
    return _familias(str(Path(ajustes.dir_config) / "familias_equivalencia.csv"))


def detectar(texto: str, maximo: int = MAX_FAMILIAS) -> list[str]:
    """Familias que parece tratar el texto, de más a menos pistas (solo las que aparecen). Pura."""
    t = _plano(texto)
    puntos = {}
    for fam, pistas in PISTAS.items():
        n = sum(1 for p in pistas if re.search(r"(?<![a-z0-9])" + re.escape(p), t))
        if n:
            puntos[fam] = n
    return sorted(puntos, key=lambda f: (-puntos[f], f))[:maximo]


def guia(texto: str, tabla: dict | None = None) -> str:
    """Texto para el modelo con los campos que suelen decidir en las familias detectadas; vacío si no se detecta ninguna. Pura sobre `tabla`."""
    tabla = tabla if tabla is not None else familias()
    lineas = []
    for fam in detectar(texto):
        campos = tabla.get(fam, ())[:MAX_CAMPOS]
        if campos:
            lineas.append(f"- {fam}: " + "; ".join(f"{c} ({d})" if d else c for c, d in campos))
    if not lineas:
        return ""
    return ("Guía por familia de producto (qué datos suelen decidir). Úsala solo para fijarte en parámetros que el PLIEGO ya pide y para saber qué ficha falta; "
            "no añadas parámetros que el pliego no exija:\n" + "\n".join(lineas))


@lru_cache(maxsize=2)
def _semillas(ruta: str) -> tuple[dict, ...]:
    return tuple({"fabricante": (r.get("fabricante") or "").strip(), "modelo": (r.get("modelo_o_familia") or "").strip(), "categoria": (r.get("categoria") or "").strip(),
                  "url": (r.get("url_fuente") or "").strip(), "acceso": (r.get("estado_acceso") or "").strip()} for r in _leer_csv(ruta) if (r.get("fabricante") or "").strip())


def semillas() -> tuple[dict, ...]:
    """Modelos de ejemplo con su ficha oficial (referencia de dónde buscar), no fichas cargadas."""
    return _semillas(str(Path(ajustes.dir_config) / "fichas_semillas.csv"))
