#!/usr/bin/env bash
# Segundo sondeo (solo lectura): muestra la ESTRUCTURA interna de las respuestas ya guardadas de Cataluña, BOE y la UE para poder escribir sus conectores con datos reales.
# Hay que lanzarlo desde la carpeta del proyecto, después de  ./scripts/subvenciones_sondear.sh  (usa las muestras de subvenciones_muestras/). Son datos públicos.
set -uo pipefail
M="subvenciones_muestras"
[ -f "$M/boe_sumario_hoy.txt" ] || { echo "Falta $M/boe_sumario_hoy.txt: ejecuta antes ./scripts/subvenciones_sondear.sh" >&2; exit 1; }
UA="ARES-FundingIntelligence/1.0 (+https://101.cat)"
CAT="https://analisi.transparenciacatalunya.cat/resource/3gku-b36y.json"

echo "=== Cataluña: valores de «estat» y cuántas convocatorias hay desde el 1/10/2026 ==="
curl -sS -m 40 -A "$UA" -G "$CAT" --data-urlencode '$select=estat,count(*) as n' --data-urlencode '$group=estat' --data-urlencode '$order=n DESC' --data-urlencode '$limit=15' | head -c 1500; echo
curl -sS -m 40 -A "$UA" -G "$CAT" --data-urlencode '$select=count(*) as recientes' --data-urlencode "\$where=data_pub >= '2026-10-01T00:00:00'" | head -c 300; echo
echo "--- 3 filas recientes (campos completos) ---"
curl -sS -m 40 -A "$UA" -G "$CAT" --data-urlencode '$order=data_pub DESC' --data-urlencode '$limit=3' | head -c 2500; echo
echo "--- columnas del dataset ---"
curl -sS -m 40 -A "$UA" "https://analisi.transparenciacatalunya.cat/api/views/3gku-b36y.json" | python3 -c 'import sys,json
d=json.load(sys.stdin)
for c in d.get("columns",[]): print(" ", c.get("fieldName"), "-", c.get("dataTypeName"), "-", (c.get("description") or "")[:70])' 2>&1 | head -20

echo; echo "=== BOE: ítems del sumario de hoy que hablan de ayudas o subvenciones ==="
python3 - "$M/boe_sumario_hoy.txt" <<'PY'
import json, re, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
patron = re.compile(r"ayuda|subvenci|bases reguladoras|convocatoria", re.I)
hallados, total = [], 0
def recorre(o, ruta):
    global total
    if isinstance(o, dict):
        if "titulo" in o and "identificador" in o:
            total += 1
            if patron.search(str(o.get("titulo"))):
                hallados.append((ruta, o))
        for k, v in o.items():
            n = o.get("nombre") or o.get("codigo") or ""
            recorre(v, ruta + [f"{k}:{str(n)[:50]}" if k in ("seccion", "departamento", "epigrafe") else k])
    elif isinstance(o, list):
        for x in o: recorre(x, ruta)
recorre(d, [])
print(f"ítems con título: {total}; de ayudas/subvenciones/convocatorias: {len(hallados)}")
for ruta, o in hallados[:4]:
    print("· ruta:", " > ".join(r for r in ruta if ":" in r)[:200])
    print("  ", json.dumps(o, ensure_ascii=False)[:900])
PY

echo; echo "=== UE: campos del primer resultado ==="
python3 - "$M/ue_busqueda.txt" <<'PY'
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
print("totalResults:", d.get("totalResults"), "· claves de nivel superior:", ", ".join(d.keys()))
r = (d.get("results") or [{}])[0]
print("claves del resultado:", ", ".join(r.keys()))
for k in ("reference", "url", "summary", "language"):
    print(f"  {k}: {str(r.get(k))[:140]}")
for k, v in (r.get("metadata") or {}).items():
    print(f"  metadata.{k}: {str(v)[:110]}")
PY
echo; echo "Fin. Pega este resultado completo en el chat (datos públicos)."
