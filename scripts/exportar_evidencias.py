"""Exporta las evidencias de un periodo para una auditoría (ENS / ISO 27001) y comprueba su integridad.

Genera una carpeta con:
  trazas.jsonl, observaciones.jsonl   Langfuse: pasos del grafo, llamadas a modelos y herramientas (con errores)
  aprobaciones.jsonl                  quién aprobó qué, cuándo y por qué canal
  registro_acciones.jsonl             acciones ejecutadas
  manifiesto.json, SHA256SUMS         qué contiene, cuántos registros y la huella SHA-256 de cada fichero

Uso:
  python scripts/exportar_evidencias.py --desde 2026-10-01 --hasta 2026-10-31 [--salida evidencias/2026-10]
                                        [--solo-errores] [--sin-bd]
  python scripts/exportar_evidencias.py --verificar evidencias/2026-10

Variables: LANGFUSE_HOST (o --langfuse), LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, DATABASE_URL.
Desde fuera de Docker, apuntad a los puertos publicados (p. ej. --langfuse http://localhost:3001).
La huella demuestra que los ficheros no han cambiado desde la exportación; guardad el manifiesto en un lugar
distinto (correo firmado, gestor documental) para poder demostrarlo.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterator

FICHEROS = ("trazas.jsonl", "observaciones.jsonl", "aprobaciones.jsonl", "registro_acciones.jsonl")


def paginar(pedir: Callable[[int], dict], limite_paginas: int = 100000) -> Iterator[dict]:
    """Recorre una API paginada de Langfuse: `pedir(pagina)` devuelve {'data': [...], 'meta': {'totalPages': n}}."""
    pagina = 1
    while pagina <= limite_paginas:
        r = pedir(pagina)
        yield from r.get("data", [])
        if pagina >= r.get("meta", {}).get("totalPages", 1):
            return
        pagina += 1


def sha256(ruta: Path) -> str:
    h = hashlib.sha256()
    with ruta.open("rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def escribir_jsonl(ruta: Path, filas: Iterator[dict]) -> int:
    n = 0
    with ruta.open("w", encoding="utf-8") as f:
        for fila in filas:
            f.write(json.dumps(fila, ensure_ascii=False, sort_keys=True, default=str) + "\n")
            n += 1
    return n


def escribir_manifiesto(carpeta: Path, datos: dict, conteos: dict[str, int]) -> dict:
    ficheros = {n: {"registros": c, "sha256": sha256(carpeta / n)} for n, c in conteos.items()}
    manifiesto = {**datos, "generado": datetime.now(timezone.utc).isoformat(timespec="seconds"), "ficheros": ficheros}
    (carpeta / "manifiesto.json").write_text(json.dumps(manifiesto, ensure_ascii=False, indent=2), encoding="utf-8")
    sumas = "".join(f"{v['sha256']}  {n}\n" for n, v in ficheros.items())
    sumas += f"{sha256(carpeta / 'manifiesto.json')}  manifiesto.json\n"
    (carpeta / "SHA256SUMS").write_text(sumas, encoding="utf-8")
    return manifiesto


def verificar(carpeta: Path) -> list[str]:
    """Devuelve la lista de problemas (vacía si todo coincide con SHA256SUMS y el manifiesto)."""
    problemas = []
    sumas = carpeta / "SHA256SUMS"
    if not sumas.exists():
        return ["Falta SHA256SUMS"]
    for linea in sumas.read_text(encoding="utf-8").splitlines():
        esperada, _, nombre = linea.partition("  ")
        ruta = carpeta / nombre
        if not ruta.exists():
            problemas.append(f"Falta {nombre}")
        elif sha256(ruta) != esperada:
            problemas.append(f"{nombre}: la huella no coincide (el fichero ha cambiado)")
    man = carpeta / "manifiesto.json"
    if man.exists():
        for nombre, info in json.loads(man.read_text(encoding="utf-8")).get("ficheros", {}).items():
            ruta = carpeta / nombre
            if ruta.exists():
                n = sum(1 for _ in ruta.open(encoding="utf-8"))
                if n != info["registros"]:
                    problemas.append(f"{nombre}: {n} registros, el manifiesto dice {info['registros']}")
    return problemas


def _iso(d: date, fin: bool = False) -> str:
    """Límites del periodo en UTC: el día `hasta` entra entero."""
    t = datetime.combine(d + timedelta(days=1) if fin else d, time.min, tzinfo=timezone.utc)
    return t.isoformat().replace("+00:00", "Z")


def _api(base: str, clave: tuple[str, str], ruta: str, **params) -> dict:
    q = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    req = urllib.request.Request(f"{base.rstrip('/')}{ruta}?{q}")
    req.add_header("Authorization", "Basic " + base64.b64encode(f"{clave[0]}:{clave[1]}".encode()).decode())
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def _filas_bd(url: str, consulta: str, params: tuple) -> Iterator[dict]:
    import psycopg
    from psycopg.rows import dict_row
    with psycopg.connect(url, row_factory=dict_row) as conn:
        yield from conn.execute(consulta, params)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--desde", type=date.fromisoformat)
    p.add_argument("--hasta", type=date.fromisoformat, help="último día incluido")
    p.add_argument("--salida")
    p.add_argument("--langfuse", default=os.environ.get("LANGFUSE_HOST", "http://localhost:3001"))
    p.add_argument("--solo-errores", action="store_true", help="en Langfuse, solo observaciones con nivel ERROR")
    p.add_argument("--sin-bd", action="store_true", help="no exportar aprobaciones ni registro_acciones")
    p.add_argument("--verificar", metavar="CARPETA", help="comprobar la integridad de una exportación anterior")
    a = p.parse_args()

    if a.verificar:
        problemas = verificar(Path(a.verificar))
        print("\n".join(problemas) if problemas else "Integridad correcta: todos los ficheros coinciden.")
        return 1 if problemas else 0
    if not (a.desde and a.hasta):
        p.error("indica --desde y --hasta (o --verificar)")
    clave = (os.environ.get("LANGFUSE_PUBLIC_KEY", ""), os.environ.get("LANGFUSE_SECRET_KEY", ""))
    if not all(clave):
        p.error("faltan LANGFUSE_PUBLIC_KEY y LANGFUSE_SECRET_KEY")
    ini, fin = _iso(a.desde), _iso(a.hasta, fin=True)
    carpeta = Path(a.salida or f"evidencias/{a.desde}_{a.hasta}")
    carpeta.mkdir(parents=True, exist_ok=True)
    conteos = {}
    conteos["trazas.jsonl"] = escribir_jsonl(carpeta / "trazas.jsonl", paginar(
        lambda pg: _api(a.langfuse, clave, "/api/public/traces", page=pg, limit=100, fromTimestamp=ini, toTimestamp=fin)))
    conteos["observaciones.jsonl"] = escribir_jsonl(carpeta / "observaciones.jsonl", paginar(
        lambda pg: _api(a.langfuse, clave, "/api/public/observations", page=pg, limit=100, fromStartTime=ini,
                        toStartTime=fin, level="ERROR" if a.solo_errores else None)))
    if not a.sin_bd:
        url = os.environ.get("DATABASE_URL")
        if not url:
            p.error("falta DATABASE_URL (o usa --sin-bd)")
        conteos["aprobaciones.jsonl"] = escribir_jsonl(carpeta / "aprobaciones.jsonl", _filas_bd(
            url, "SELECT * FROM aprobaciones WHERE creado >= %s AND creado < %s ORDER BY creado", (ini, fin)))
        conteos["registro_acciones.jsonl"] = escribir_jsonl(carpeta / "registro_acciones.jsonl", _filas_bd(
            url, "SELECT * FROM registro_acciones WHERE creado >= %s AND creado < %s ORDER BY id", (ini, fin)))
    man = escribir_manifiesto(carpeta, {"desde": str(a.desde), "hasta": str(a.hasta), "langfuse": a.langfuse,
                                        "solo_errores": a.solo_errores}, conteos)
    for n, v in man["ficheros"].items():
        print(f"{n}: {v['registros']} registros · sha256 {v['sha256'][:16]}…")
    print(f"Exportado en {carpeta}. Comprobar más tarde con: --verificar {carpeta}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
