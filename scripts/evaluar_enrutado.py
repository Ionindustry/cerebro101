"""Mide el enrutado del Cerebro con la batería de preguntas (evaluacion/bateria_enrutado.yaml).

Llama a POST /jarvis/enrutar (solo elige departamento y agente: no ejecuta nada ni crea aprobaciones).

Uso:  python scripts/evaluar_enrutado.py [--api http://localhost:8000] [--usuario nombre | --token JWT]
                                        [--salida evaluacion/resultados/enrutado.json] [--umbral 0.9]
Termina con código 0 si el acierto de departamento alcanza el umbral (por defecto 90 %), y 1 si no.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parent.parent


def cargar(ruta: Path | None = None) -> list[dict]:
    return yaml.safe_load((ruta or RAIZ / "evaluacion" / "bateria_enrutado.yaml").read_text(encoding="utf-8"))["preguntas"]


def preguntar(api: str, texto: str, cabeceras: dict, timeout: float) -> dict:
    req = urllib.request.Request(f"{api}/jarvis/enrutar", data=json.dumps({"texto": texto}).encode(),
                                 headers={"Content-Type": "application/json", **cabeceras})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def resumen(resultados: list[dict]) -> dict:
    n = len(resultados)
    dep = sum(r["ok_departamento"] for r in resultados)
    ag = sum(r["ok_agente"] for r in resultados)
    por_dep: dict[str, list[int]] = {}
    for r in resultados:
        a = por_dep.setdefault(r["departamento"], [0, 0])
        a[0] += r["ok_departamento"]
        a[1] += 1
    return {"total": n, "aciertos_departamento": dep, "aciertos_agente": ag,
            "acierto_departamento": round(dep / n, 3) if n else 0, "acierto_agente": round(ag / n, 3) if n else 0,
            "por_departamento": {k: f"{a}/{t}" for k, (a, t) in sorted(por_dep.items())}}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--api", default="http://localhost:8000")
    p.add_argument("--usuario", help="modo desarrollo: nombre de usuario en la cabecera X-Usuario")
    p.add_argument("--token", help="JWT de Keycloak")
    p.add_argument("--salida", default=str(RAIZ / "evaluacion" / "resultados" / "enrutado.json"))
    p.add_argument("--umbral", type=float, default=0.9)
    p.add_argument("--timeout", type=float, default=600, help="segundos por pregunta")
    p.add_argument("--solo", type=int, nargs="*", help="ids de preguntas a ejecutar")
    a = p.parse_args()
    cab = {"Authorization": f"Bearer {a.token}"} if a.token else {"X-Usuario": a.usuario or "evaluador",
                                                                  "X-Roles": "direccion"}
    preguntas = [q for q in cargar() if not a.solo or q["id"] in a.solo]
    resultados = []
    for q in preguntas:
        t0 = time.time()
        try:
            r = preguntar(a.api, q["pregunta"], cab, a.timeout)
            dep, ag, error = r.get("departamento"), r.get("agente"), None
        except Exception as e:  # noqa: BLE001 - se registra y se sigue con la siguiente
            dep = ag = None
            error = str(e)
        res = {**q, "departamento_obtenido": dep, "agente_obtenido": ag, "error": error,
               "ok_departamento": dep == q["departamento"], "ok_agente": ag == q["agente"],
               "segundos": round(time.time() - t0, 1)}
        resultados.append(res)
        marca = "✓" if res["ok_departamento"] else "✗"
        print(f"{marca} {q['id']:>2} esperado {q['departamento']}/{q['agente']} · obtenido {dep}/{ag}"
              f"{' · ' + error if error else ''} ({res['segundos']} s)", flush=True)
    r = resumen(resultados)
    Path(a.salida).parent.mkdir(parents=True, exist_ok=True)
    Path(a.salida).write_text(json.dumps({"resumen": r, "resultados": resultados}, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    print(f"\nDepartamento: {r['aciertos_departamento']}/{r['total']} ({r['acierto_departamento']:.0%}) · "
          f"Agente: {r['aciertos_agente']}/{r['total']} ({r['acierto_agente']:.0%}) · umbral {a.umbral:.0%}")
    print(f"Informe: {a.salida}")
    return 0 if r["acierto_departamento"] >= a.umbral else 1


if __name__ == "__main__":
    sys.exit(main())
