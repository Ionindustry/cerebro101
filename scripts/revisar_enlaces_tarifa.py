#!/usr/bin/env python3
"""Mira un CSV de tarifas de proveedor y dice qué columnas traen enlaces (http/https): fichas técnicas, páginas de producto, imágenes…

    python3 scripts/revisar_enlaces_tarifa.py /ruta/a/la_tarifa.csv

Se ejecuta en TU equipo, con el fichero donde esté: no lo sube a ninguna parte ni lo guarda. Solo imprime los nombres de las columnas, cuántas celdas de cada una parecen un enlace y,
de los enlaces, el dominio y el tipo de fichero (nunca precios ni el resto del contenido). Solo CSV: si es un Excel, expórtalo antes a CSV (Archivo → Guardar como → CSV).
"""
from __future__ import annotations

import csv
import re
import sys
from collections import Counter
from urllib.parse import urlparse

URL = re.compile(r"^https?://\S+$", re.I)
CODIFICACIONES = ("utf-8-sig", "utf-8", "cp1252", "latin-1")


def leer(ruta: str) -> list[list[str]]:
    for cod in CODIFICACIONES:
        try:
            with open(ruta, newline="", encoding=cod) as fh:
                muestra = fh.read(8192)
                fh.seek(0)
                try:
                    dialecto = csv.Sniffer().sniff(muestra, delimiters=",;\t|")
                except csv.Error:
                    dialecto = csv.excel
                return [fila for fila in csv.reader(fh, dialecto)]
        except UnicodeDecodeError:
            continue
    raise SystemExit("No he podido leer el fichero: ¿es un CSV de texto?")


def tipo(url: str) -> str:
    ruta = urlparse(url).path.lower()
    for ext in (".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".zip", ".xlsx", ".docx"):
        if ruta.endswith(ext):
            return ext[1:].upper()
    return "página web"


def analizar(filas: list[list[str]]) -> list[dict]:
    if not filas:
        return []
    cab = filas[0]
    cols = []
    for i, nombre in enumerate(cab):
        celdas = [f[i].strip() for f in filas[1:] if i < len(f) and f[i].strip()]
        enlaces = [c for c in celdas if URL.match(c)]
        if not enlaces:
            continue
        cols.append({"columna": nombre.strip() or f"(columna {i + 1} sin nombre)", "enlaces": len(enlaces), "de": len(filas) - 1,
                     "dominios": Counter(urlparse(u).netloc.lower() for u in enlaces).most_common(3), "tipos": Counter(tipo(u) for u in enlaces).most_common(3)})
    return cols


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    filas = leer(argv[1])
    print(f"Filas de datos: {max(len(filas) - 1, 0)}; columnas: {len(filas[0]) if filas else 0}")
    print("Columnas: " + " | ".join(c.strip() for c in (filas[0] if filas else [])))
    cols = analizar(filas)
    if not cols:
        print("\nNingún enlace (http/https) en este fichero.")
        return 0
    print("\nColumnas con enlaces:")
    for c in cols:
        print(f"- «{c['columna']}»: {c['enlaces']} de {c['de']} filas. Dominios: " + ", ".join(f"{d} ({n})" for d, n in c["dominios"]) + ". Tipos: " + ", ".join(f"{t} ({n})" for t, n in c["tipos"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
