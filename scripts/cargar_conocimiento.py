"""Indexa en la base de conocimiento los documentos de una carpeta (txt, md).

Uso:  docker compose exec api python /app/scripts/cargar_conocimiento.py /datos/conocimiento comun media
La estructura recomendada es una subcarpeta por departamento.
"""
import asyncio
import sys
from pathlib import Path

from cerebro.herramientas.conocimiento import indexar


async def main(carpeta: str, departamento: str = "comun", sensibilidad: str = "media") -> None:
    total = 0
    for ruta in sorted(Path(carpeta).rglob("*")):
        if ruta.suffix.lower() in {".txt", ".md"}:
            total += await indexar(ruta.stem, ruta.read_text(encoding="utf-8", errors="replace"),
                                   str(ruta), departamento, sensibilidad)
            print(f"Indexado {ruta}")
    print(f"{total} fragmentos indexados")


if __name__ == "__main__":
    asyncio.run(main(*sys.argv[1:]))
