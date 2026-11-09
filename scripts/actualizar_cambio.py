"""Baja ahora el tipo de cambio del Banco Central Europeo y lo guarda (lo hace solo cada día laborable a las 16:30; esto sirve para la primera vez o para probarlo).

    docker compose exec api python /app/scripts/actualizar_cambio.py

Escribe el último tipo guardado de las monedas que usa config/precios.yaml. Solo necesita internet desde el contenedor de la API.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

from cerebro import cambio  # noqa: E402


async def main() -> int:
    try:
        r = await cambio.actualizar()
    except cambio.ErrorCambio as e:
        print(f"No se ha podido actualizar el tipo de cambio: {e}")
        return 1
    print(f"Tipos del Banco Central Europeo del {r['fecha']}: {r['monedas']} monedas guardadas (1 USD = {r['usd']} EUR)")
    u = await cambio.ultimos(["USD", "GBP"])
    for m, v in sorted(u.items()):
        print(f"  {m}: {v['eur_por_unidad']} EUR por unidad (del {v['fecha']})")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
