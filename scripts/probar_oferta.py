"""Revisión previa («pre-vuelo») de «Preparar la oferta con los agentes» para una licitación: comprueba, SIN cambiar nada ni llamar a ningún modelo, que están los ingredientes y dice qué falta.
Es la misma revisión que el botón «Revisar antes de preparar la oferta» de la ficha del expediente en Jarvis (cerebro/licitaciones/revision_previa.py).

    docker compose exec api python /app/scripts/probar_oferta.py                  # elige la licitación «en estudio» con mejor encaje
    docker compose exec api python /app/scripts/probar_oferta.py <id del motor>   # una licitación concreta (el UUID de la ficha)

Sale con código 1 si hay algo que BLOQUEA (sin ficha o sin sociedad). Los avisos no bloquean, pero conviene resolverlos antes de lanzar a los agentes. Es de solo lectura.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "api"))

from cerebro.licitaciones import embudo, revision_previa  # noqa: E402

MARCA = {"ok": "✔", "aviso": "!", "bloqueo": "✘"}


async def elegir_licitacion(motor_id: str | None) -> dict | None:
    if motor_id:
        filas = await embudo.listar(motor_id=motor_id, limite=1)
        return filas[0] if filas else {"motor_id": motor_id, "titulo": "(no está en el embudo)", "estado": None, "encaje": None}
    filas = await embudo.listar("en_estudio", None, 200)
    return max(filas, key=lambda f: f.get("encaje") or 0) if filas else None


async def main() -> int:
    motor_id = sys.argv[1] if len(sys.argv) > 1 else None
    try:
        fila = await elegir_licitacion(motor_id)
    except Exception as e:      # noqa: BLE001
        print(f"No se ha podido leer el embudo: {type(e).__name__}: {e}")
        return 1
    if not fila:
        print("No hay ninguna licitación «en estudio» en el embudo: pasa una a «en estudio» desde Jarvis (o indica su id).")
        return 1
    print(f"\nLicitación: {fila.get('titulo')}\n  id del motor: {fila['motor_id']} · estado en el embudo: {fila.get('estado') or 'no está'} · encaje: {fila.get('encaje')}")
    r = await revision_previa.revisar(str(fila["motor_id"]))
    for n, s in enumerate(r["secciones"], 1):
        print(f"\n{n}. {s['titulo']}")
        for i in s["items"]:
            print(f"  {MARCA[i['nivel']]} {i['texto']}")
    print()
    if r["resultado"] == "bloqueada":
        print(f"RESULTADO: hay {r['bloqueos']} cosas que bloquean; arréglalas antes de lanzar a los agentes.")
        return 1
    if r["resultado"] == "con_avisos":
        print(f"RESULTADO: se puede lanzar, pero hay {r['avisos']} avisos: los agentes trabajarán con huecos o con menos información. Resuelve primero los que puedas.")
    else:
        print("RESULTADO: todo listo para lanzar «Preparar la oferta con los agentes».")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
