"""Batería de calidad de las respuestas: ¿lo que contesta el agente es correcto, honesto y seguro?

Cada caso de evaluacion/calidad_casos.yaml pasa por el agente real (modelo, herramientas y prompt de producción, sin
aprobaciones ni envíos) y se comprueba el contenido con reglas automáticas. Las cifras esperadas las calcula el motor
de cálculo, nunca el modelo. Hay que ejecutarlo donde esté el modelo (dentro del contenedor de la API):
    docker compose exec -e PYTHONPATH=/app/api api python /app/scripts/evaluar_calidad.py [--solo C01 C05] [--tipos cifras]
Sale con código 1 si algún caso falla.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "api"))

from cerebro.cotizador import Solicitud, calcular  # noqa: E402
from cerebro.grafo.nodos import ejecutar_agente  # noqa: E402
from cerebro.herramientas import base  # noqa: E402
from cerebro.red_instaladores import Oferta, puntuar  # noqa: E402
from cerebro.registro import registro  # noqa: E402

PALABRAS = {
    "es": {"el", "la", "los", "las", "de", "que", "y", "en", "un", "una", "para", "con", "por", "su", "es", "no", "se", "le"},
    "ca": {"el", "la", "els", "les", "de", "que", "i", "en", "un", "una", "per", "amb", "seu", "és", "no", "es", "al", "del", "nostre", "servei"},
}
EXCLUSIVAS = {"es": {"los", "las", "para", "con", "por", "su", "es", "le", "una", "se"},
              "ca": {"els", "les", "i", "per", "amb", "seu", "és", "al", "del", "nostre", "servei", "són", "pels"}}


def idioma_de(texto: str) -> str:
    palabras = re.findall(r"[a-zàèéíòóúüçñ·]+", texto.lower())
    pts = {i: sum(1 for p in palabras if p in EXCLUSIVAS[i]) for i in EXCLUSIVAS}
    return max(pts, key=pts.get) if max(pts.values()) else "?"


def numeros(texto: str) -> list[float]:
    """Todos los números del texto, entendiendo 1.234,56 / 1,234.56 / 231,5 / 231."""
    salida = []
    for m in re.findall(r"\d[\d.,]*", texto):
        m = m.rstrip(".,")
        if "," in m and "." in m:
            m = m.replace(".", "").replace(",", ".") if m.rfind(",") > m.rfind(".") else m.replace(",", "")
        elif "," in m:
            m = m.replace(",", ".") if len(m.split(",")[-1]) != 3 or m.count(",") == 1 and len(m.split(",")[0]) > 3 else m.replace(",", "")
        elif m.count(".") > 1 or (m.count(".") == 1 and len(m.split(".")[-1]) == 3):
            m = m.replace(".", "")
        try:
            salida.append(float(m))
        except ValueError:
            pass
    return salida


def comprobar(caso: dict, d: dict) -> list[str]:
    """Devuelve la lista de motivos de fallo (vacía = correcto)."""
    texto = d.get("respuesta") or ""
    bajo = texto.lower()
    fallos = []
    if not texto.strip():
        return ["respuesta vacía"]
    if "idioma" in caso and idioma_de(texto) != caso["idioma"]:
        fallos.append(f"idioma: esperaba {caso['idioma']} y parece {idioma_de(texto)}")
    if "max_palabras" in caso and len(texto.split()) > caso["max_palabras"]:
        fallos.append(f"demasiado larga: {len(texto.split())} palabras (máx. {caso['max_palabras']})")
    for r in caso.get("todos", []):
        if not re.search(r, texto, re.I):
            fallos.append(f"falta «{r}»")
    if caso.get("alguno") and not any(re.search(r, texto, re.I) for r in caso["alguno"]):
        fallos.append(f"no aparece ninguna de {caso['alguno']}")
    for r in caso.get("prohibido", []):
        if m := re.search(r, texto, re.I):
            fallos.append(f"contiene lo prohibido «{m.group(0)}»")
    if "importe" in caso:
        c = caso["importe"]
        r = calcular(Solicitud(**c["argumentos"])).como_dict()
        esperados = {round(r["precio_definitivo"], 2), round(r["venta_total"], 2)}
        if not any(abs(n - e) <= 0.51 for n in numeros(texto) for e in esperados):
            fallos.append(f"el importe no coincide con el del motor ({' o '.join(f'{e:g}' for e in sorted(esperados))} €); "
                          f"cifras en la respuesta: {numeros(texto)[:6]}")
    if "ganador" in caso:
        orden = puntuar([Oferta(**o) for o in caso["ganador"]["ofertas"]])
        ganador = orden[0].instalador
        if ganador.lower() not in bajo:
            fallos.append(f"no menciona al ganador que calcula el comparador: {ganador}")
        else:
            otros = [o.instalador for o in orden[1:] if o.instalador.lower() in bajo]
            primero = min(bajo.find(x.lower()) for x in [ganador, *otros])
            if otros and bajo.find(ganador.lower()) != primero and not re.search(r"recomiend|mejor|elij|opción", bajo):
                fallos.append("no queda claro que recomienda al ganador")
    if "accion" in caso:
        hay = bool(d.get("acciones"))
        if hay != caso["accion"]:
            fallos.append("debía proponer una acción para aprobar" if caso["accion"] else "no debía proponer acciones")
    if caso.get("sin_ejecutar"):
        for p in d.get("pasos", []):
            h = base._REGISTRO.get(p.get("herramienta") or "")
            if h and p.get("operacion") in h.externas and p.get("ok"):
                fallos.append(f"ejecutó {p['herramienta']}.{p['operacion']} sin pasar por la bandeja")
    return fallos


async def una(caso: dict) -> dict:
    t0 = time.time()
    try:
        d = await asyncio.wait_for(ejecutar_agente({"agente": caso["agente"], "peticion": caso["peticion"], "origen": "peticion"}), 600)
    except Exception as e:  # noqa: BLE001
        return {"id": caso["id"], "tipo": caso["tipo"], "ok": False, "fallos": [f"error: {type(e).__name__}: {str(e)[:160]}"],
                "segundos": round(time.time() - t0, 1)}
    fallos = comprobar(caso, d)
    return {"id": caso["id"], "tipo": caso["tipo"], "ok": not fallos, "fallos": fallos, "respuesta": d.get("respuesta"),
            "acciones": d.get("acciones"), "pasos": d.get("pasos"), "segundos": round(time.time() - t0, 1)}


async def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--casos", default=str(RAIZ / "evaluacion" / "calidad_casos.yaml"))
    p.add_argument("--salida", default="/tmp/calidad.json")
    p.add_argument("--solo", nargs="*")
    p.add_argument("--tipos", nargs="*")
    a = p.parse_args()
    casos = [c for c in yaml.safe_load(Path(a.casos).read_text(encoding="utf-8"))["casos"]
             if (not a.solo or c["id"] in a.solo) and (not a.tipos or c["tipo"] in a.tipos)]
    for c in casos:
        assert c["agente"] in registro().fichas, f"{c['id']}: el agente {c['agente']} no existe"
    filas = []
    for c in casos:
        f = await una(c)
        filas.append(f)
        print(f"{c['id']} {'✓' if f['ok'] else '✗'} {c['tipo']:11} {f['segundos']:6} s  {'; '.join(f['fallos'])}", flush=True)
    por_tipo: dict[str, list[bool]] = {}
    for f in filas:
        por_tipo.setdefault(f["tipo"], []).append(f["ok"])
    print("\n=== " + " · ".join(f"{t} {sum(v)}/{len(v)}" for t, v in por_tipo.items()) +
          f" · TOTAL {sum(f['ok'] for f in filas)}/{len(filas)}")
    Path(a.salida).write_text(json.dumps(filas, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if all(f["ok"] for f in filas) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
