"""Mide cuánto detecta la anonimización que precede a Jev (evaluacion/anonimizacion_corpus.yaml).

Uso:  python scripts/evaluar_anonimizacion.py [--corpus ruta] [--detalle] [--umbral-libre 0.8]
Informa de la cobertura por capa (datos con formato, entidades conocidas, nombres libres), de los bloqueos por
categorías especiales y de la utilidad (que lo demás no se estropee). Sale con 1 si la cobertura de datos con
formato, entidades conocidas o bloqueos no es del 100 %, o si los nombres libres no llegan al umbral.
Lo medido vale lo que se parezca el corpus a vuestros textos reales: ampliadlo con casos vuestros.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "api"))

from cerebro import anonimizacion as anon  # noqa: E402


def evaluar(corpus: dict, cfg: dict, detector=None) -> dict:
    ent = anon.Entidades(personas=corpus["entidades"]["personas"], organizaciones=corpus["entidades"]["organizaciones"])
    por_capa: dict[str, list[int]] = {}     # capa -> [ocultados, total]
    fallos, limites, utilidad = [], [], [0, 0]
    bloqueos = [0, 0]
    for c in corpus["casos"]:
        r = anon.anonimizar(c["texto"], ent, detector, cfg)
        salida = anon._palabras(r.texto)
        capa = c["capa"]
        if capa == "bloqueo":
            bloqueos[1] += 1
            if r.apto == c["bloquear"]:       # debía bloquearse y salió apto (o al revés)
                fallos.append(f"{c['id']}: bloqueo incorrecto (apto={r.apto})")
            else:
                bloqueos[0] += 1
            continue
        for dato in c.get("ocultar", []):
            sobrevive = anon._palabras(dato) in salida
            if c.get("limite"):
                if sobrevive:
                    limites.append(f"{c['id']}: «{dato}» no se detecta (limitación conocida)")
                continue
            acum = por_capa.setdefault(capa, [0, 0])
            acum[1] += 1
            if sobrevive:
                fallos.append(f"{c['id']}: sobrevive «{dato}» → {r.texto}")
            else:
                acum[0] += 1
        for trozo in c.get("conservar", []):
            utilidad[1] += 1
            if anon._palabras(trozo) in salida:
                utilidad[0] += 1
            else:
                fallos.append(f"{c['id']}: se estropea «{trozo}» → {r.texto}")
        if capa == "utilidad" and not r.apto:
            fallos.append(f"{c['id']}: texto sin datos personales bloqueado: {r.motivos}")
    return {"capas": {k: (a, t) for k, (a, t) in por_capa.items()}, "bloqueos": tuple(bloqueos),
            "utilidad": tuple(utilidad), "fallos": fallos, "limites": limites}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--corpus", default=str(RAIZ / "evaluacion" / "anonimizacion_corpus.yaml"))
    p.add_argument("--umbral-libre", type=float, default=0.8)
    p.add_argument("--detalle", action="store_true")
    a = p.parse_args()
    cfg = anon.configuracion(str(RAIZ / "config"))
    r = evaluar(yaml.safe_load(Path(a.corpus).read_text(encoding="utf-8")), cfg, anon.detector_heuristico(cfg["no_son_nombres"]))
    ok = True
    for capa, (hecho, total) in sorted(r["capas"].items()):
        minimo = a.umbral_libre if capa == "libre" else 1.0
        bien = total and hecho / total >= minimo
        ok &= bool(bien)
        print(f"{'✓' if bien else '✗'} {capa:8} {hecho}/{total} ({hecho / total:.0%}) · exigido {minimo:.0%}")
    b, bt = r["bloqueos"]
    ok &= b == bt
    print(f"{'✓' if b == bt else '✗'} bloqueo  {b}/{bt} categorías especiales detenidas")
    u, ut = r["utilidad"]
    print(f"  utilidad {u}/{ut} ({u / ut:.0%}) de lo que debía conservarse sigue en el texto")
    if r["limites"]:
        print("Limitaciones conocidas (no cuentan):")
        print("\n".join("  - " + x for x in r["limites"]))
    if r["fallos"] and (a.detalle or not ok):
        print("Fallos:")
        print("\n".join("  - " + x for x in r["fallos"]))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
