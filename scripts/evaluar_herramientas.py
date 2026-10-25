"""Mide si el modelo elige bien la herramienta y rellena sus argumentos, con el prompt antiguo y con el esquema exacto.

Para cada petición de evaluacion/herramientas_casos.yaml hace UNA llamada al modelo del agente (sin ejecutar nada) y
comprueba: ¿usa una herramienta de su ficha?, ¿existe la operación?, ¿los argumentos son válidos?, ¿es la correcta?
Hay que ejecutarlo donde esté el modelo (dentro del contenedor de la API):
    docker compose exec -e PYTHONPATH=/app/api api python /app/scripts/evaluar_herramientas.py [--modos antiguo nuevo]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "api"))

import cerebro.herramientas as H  # noqa: E402
from cerebro.grafo.nodos import ESQUEMA_AGENTE, inyectar  # noqa: E402
from cerebro.grafo.prompts import sistema_agente  # noqa: E402
from cerebro.herramientas import base  # noqa: E402
from cerebro.llm import chat  # noqa: E402
from cerebro.registro import registro  # noqa: E402
from cerebro.router_modelos import asignar  # noqa: E402


def clasificar(ficha, d: dict, estado: dict | None = None) -> str:
    """valida | responde | herramienta_inventada | operacion_inventada | argumentos_invalidos"""
    if d.get("tipo") != "herramienta":
        return "responde"
    nombre, op = d.get("herramienta", ""), d.get("operacion", "")
    if nombre not in ficha.herramientas or nombre not in base._REGISTRO:
        return "herramienta_inventada"
    if op not in base._REGISTRO[nombre].operaciones:
        return "operacion_inventada"
    args = inyectar(ficha, estado or {}, nombre, d.get("argumentos") or {})
    return "argumentos_invalidos" if base.validar_llamada(ficha, nombre, op, args) else "valida"


async def una(caso: dict, con_esquema: bool) -> dict:
    ficha = registro().fichas[caso["agente"]]
    mensajes = [{"role": "system", "content": sistema_agente(ficha, H.disponibles_para(ficha), con_esquema)},
                {"role": "user", "content": caso["peticion"]}]
    t0 = time.time()
    try:
        d = await chat(asignar(ficha, "peticion"), mensajes, esquema=ESQUEMA_AGENTE, temperatura=0, timeout=300, max_tokens=500)
    except Exception as e:  # noqa: BLE001
        return {"id": caso["id"], "resultado": "error", "detalle": str(e)[:200], "correcta": False, "segundos": round(time.time() - t0, 1)}
    res = clasificar(ficha, d)
    llamada = f"{d.get('herramienta')}.{d.get('operacion')}"
    return {"id": caso["id"], "resultado": res, "llamada": llamada, "argumentos": d.get("argumentos"),
            "correcta": res == "valida" and llamada in caso["aceptar"], "segundos": round(time.time() - t0, 1)}


async def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--casos", default=str(RAIZ / "evaluacion" / "herramientas_casos.yaml"))
    p.add_argument("--modos", nargs="+", default=["antiguo", "nuevo"], choices=["antiguo", "nuevo"])
    p.add_argument("--salida", default="/tmp/herramientas.json")
    p.add_argument("--solo", nargs="*")
    a = p.parse_args()
    casos = [c for c in yaml.safe_load(Path(a.casos).read_text(encoding="utf-8"))["casos"] if not a.solo or c["id"] in a.solo]
    informe = {}
    for modo in a.modos:
        filas = []
        for c in casos:
            f = await una(c, modo == "nuevo")
            filas.append(f)
            print(f"[{modo:7}] {c['id']} {'✓' if f['correcta'] else '✗'} {f['resultado']:22} {f.get('llamada', '')} ({f['segundos']} s)", flush=True)
        informe[modo] = filas
        n = len(filas)
        cuenta = {k: sum(1 for f in filas if f["resultado"] == k) for k in ("valida", "responde", "herramienta_inventada", "operacion_inventada", "argumentos_invalidos", "error")}
        print(f"=== {modo}: llamadas válidas {cuenta['valida']}/{n} · correctas {sum(f['correcta'] for f in filas)}/{n} · {cuenta}\n", flush=True)
    Path(a.salida).write_text(json.dumps(informe, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
