#!/usr/bin/env python3
"""Autoriza dominios para descargar fichas técnicas (la lista `hosts` de config/fichas.yaml), con el directorio de fabricantes delante.

Solo se descargan fichas de los dominios de esa lista (https; también sus subdominios): autorizar uno es decidir que te fías de lo que publica. Por eso el script te dice, para cada dominio, a qué
fabricante corresponde según config/fabricantes_seguridad.csv y si el directorio lo ha COMPROBADO («propuesto» no es comprobado). Un dominio que no está comprobado o no está en el directorio solo se
añade con --forzar, después de que lo hayas abierto y confirmado que es el oficial.

Uso (ventana Ubuntu, desde la carpeta del proyecto; no necesita Docker ni dependencias):
    python3 scripts/fichas_autorizar.py 2n.com paxton-access.com        # añade los que están comprobados
    python3 scripts/fichas_autorizar.py milesight.com --forzar            # añade uno no comprobado (tras confirmarlo tú)
    python3 scripts/fichas_autorizar.py --comprobados                     # añade TODOS los comprobados del directorio (decisión grande: mira antes la lista con --listar)
    python3 scripts/fichas_autorizar.py --listar                          # qué hay autorizado y qué dominios comprobados hay en el directorio
    python3 scripts/fichas_autorizar.py 2n.com --quitar                   # deja de autorizarlo
El cambio vale al momento (la API lee el fichero cada vez); no hace falta reiniciar nada.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

RAIZ = Path(__file__).resolve().parent.parent
FICHERO = RAIZ / "config" / "fichas.yaml"
DIRECTORIO = RAIZ / "config" / "fabricantes_seguridad.csv"
COMPROBADOS = ("DOMINIO_PROPUESTO_PORTAL_DOCUMENTAL_VERIFICADO", "DOMINIO_REVISADO_EN_FUENTE_DEL_FABRICANTE")
RE_DOMINIO = re.compile(r"^(?=.{4,100}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}$")
RE_HOSTS = re.compile(r"^hosts:\s*\[(.*)\]\s*(#.*)?$", re.M)


def dominio_de(t: str) -> str:
    t = str(t or "").strip().lower()
    host = (urlparse(t).hostname if "://" in t else t.split("/")[0]) or ""
    host = host.strip(".")
    host = host[4:] if host.startswith("www.") else host
    return host if RE_DOMINIO.match(host) else ""


def leer_directorio(ruta: Path = DIRECTORIO) -> list[dict]:
    out = []
    try:
        with open(ruta, encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                ds = sorted({d for d in (dominio_de(r.get("web_oficial_candidata", "")), dominio_de(r.get("documentacion_oficial_encontrada", ""))) if d})
                if ds:
                    out.append({"fabricante": r.get("fabricante", ""), "dominios": ds, "comprobado": r.get("estado_verificacion_web") in COMPROBADOS,
                                "acceso": r.get("estado_acceso_documentacion", ""), "login": r.get("login_area_documental", "")})
    except OSError:
        pass
    return out


def buscar(dominio: str, directorio: list[dict]) -> dict | None:
    return next((f for f in directorio if any(dominio == d or dominio.endswith("." + d) for d in f["dominios"])), None)


def hosts_actuales(texto: str) -> list[str]:
    m = RE_HOSTS.search(texto)
    if not m:
        raise SystemExit("No encuentro la línea «hosts: [...]» en config/fichas.yaml (debe ir en una sola línea, como viene de serie). No la toco.")
    return [h.strip().strip("'\"") for h in m.group(1).split(",") if h.strip()]


def con_hosts(texto: str, hosts: list[str]) -> str:
    nueva = "hosts: [" + ", ".join(sorted(set(hosts))) + "]"
    return RE_HOSTS.sub(lambda m: nueva + (f"  {m.group(2)}" if m.group(2) else ""), texto, count=1)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Autoriza dominios para descargar fichas técnicas.")
    ap.add_argument("dominios", nargs="*")
    ap.add_argument("--forzar", action="store_true", help="añade también dominios no comprobados o que no están en el directorio (después de confirmarlos tú)")
    ap.add_argument("--comprobados", action="store_true", help="añade todos los dominios comprobados del directorio")
    ap.add_argument("--quitar", action="store_true", help="quita los dominios indicados de la lista")
    ap.add_argument("--listar", action="store_true", help="enseña lo autorizado y los comprobados disponibles")
    a = ap.parse_args(argv)
    texto = FICHERO.read_text(encoding="utf-8")
    actuales = hosts_actuales(texto)
    directorio = leer_directorio()
    comprobados = sorted({d for f in directorio if f["comprobado"] for d in f["dominios"]})

    if a.listar:
        print(f"Autorizados ({len(actuales)}): {', '.join(actuales) or 'ninguno'}")
        print(f"Comprobados en el directorio ({len(comprobados)}), aún sin autorizar: {', '.join(d for d in comprobados if d not in actuales)}")
        return 0
    pedidos = [dominio_de(d) for d in a.dominios]
    if any(not d for d in pedidos):
        malos = [x for x, d in zip(a.dominios, pedidos) if not d]
        print(f"No son dominios válidos: {', '.join(malos)} (escribe solo el dominio, por ejemplo 2n.com)", file=sys.stderr)
        return 2
    if a.quitar:
        nuevos = [h for h in actuales if h not in pedidos]
        FICHERO.write_text(con_hosts(texto, nuevos), encoding="utf-8")
        print(f"Quitados: {', '.join(d for d in pedidos if d in actuales) or 'ninguno (no estaban)'}")
        return 0
    if a.comprobados:
        pedidos = sorted(set(pedidos) | set(comprobados))
    if not pedidos:
        ap.print_help()
        return 2
    anadir, rechazados = [], []
    for d in pedidos:
        f = buscar(d, directorio)
        estado = "comprobado" if f and f["comprobado"] else ("propuesto, NO comprobado" if f else "no está en el directorio")
        extra = f" · {f['fabricante']} · documentación: {f['acceso']} · login en el área documental: {f['login']}" if f else ""
        if d in actuales:
            print(f"  = {d}: ya estaba autorizado")
        elif f and f["comprobado"] or a.forzar:
            anadir.append(d)
            print(f"  + {d}: {estado}{extra}")
        else:
            rechazados.append(d)
            print(f"  ✗ {d}: {estado}{extra}")
    if rechazados:
        print("\nNo añadidos (no están comprobados). Ábrelos, confirma que son los oficiales del fabricante y repite con --forzar:\n  " + ", ".join(rechazados), file=sys.stderr)
    if anadir:
        FICHERO.write_text(con_hosts(texto, actuales + anadir), encoding="utf-8")
        print(f"\nAutorizados ahora: {len(actuales) + len(anadir)} dominios. Vale al momento.")
    return 1 if rechazados else 0


if __name__ == "__main__":
    sys.exit(main())
