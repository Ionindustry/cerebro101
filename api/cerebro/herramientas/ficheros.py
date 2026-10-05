"""Ficheros de la empresa en el servidor (carpeta montada en /datos)."""
from __future__ import annotations

from pathlib import Path

from .base import Herramienta, registrar

RAIZ = Path("/datos")


def _ruta_segura(relativa: str) -> Path:
    ruta = (RAIZ / relativa).resolve()
    if RAIZ.resolve() not in ruta.parents and ruta != RAIZ.resolve():
        raise PermissionError("Ruta fuera de la carpeta de datos")
    return ruta


async def listar(carpeta: str = "") -> list[str]:
    return sorted(str(p.relative_to(RAIZ)) for p in _ruta_segura(carpeta).iterdir())


async def leer_texto(ruta: str, max_caracteres: int = 200_000) -> str:
    return _ruta_segura(ruta).read_text(encoding="utf-8", errors="replace")[:max_caracteres]


async def guardar_borrador(ruta: str, contenido: str) -> str:
    destino = _ruta_segura(f"borradores/{ruta}")
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(contenido, encoding="utf-8")
    return str(destino.relative_to(RAIZ))


registrar(Herramienta(
    nombre="ficheros",
    descripcion="Documentos de la empresa. Solo escribe en /datos/borradores.",
    operaciones={"listar": listar, "leer_texto": leer_texto, "guardar_borrador": guardar_borrador},
    ayuda={"listar": "ficheros de una carpeta", "leer_texto": "contenido de un fichero de texto",
           "guardar_borrador": "guarda un borrador (ruta relativa a /datos/borradores)"},
    ejemplos={"listar": {"carpeta": ""}},
))
