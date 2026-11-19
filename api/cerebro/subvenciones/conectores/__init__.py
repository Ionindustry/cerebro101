"""Conectores disponibles por nombre. Un conector nuevo se añade aquí sin tocar el núcleo."""
from __future__ import annotations

from .base import Conector, ErrorConector, ErrorRegistro, Pagina  # noqa: F401


def cargar(nombre: str):
    """La clase del conector con ese nombre, o None si no existe (la fuente se queda pendiente: nunca se inventa un conector)."""
    if nombre == "bdns":
        from .bdns import ConectorBDNS
        return ConectorBDNS
    return None
