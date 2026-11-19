#!/usr/bin/env bash
# Tercer sondeo (solo lectura): cómo cita el BOE las convocatorias de ayudas y si trae el número de la BDNS, para poder enlazarlas con la BDNS en vez de duplicarlas.
# Usa el sumario de hoy ya guardado por ./scripts/subvenciones_sondear.sh y descarga el texto (XML) de 2-3 ítems del propio BOE. Son datos públicos; no usa claves.
# Desde la carpeta del proyecto:  ./scripts/subvenciones_sondear_boe.sh
set -uo pipefail
M="subvenciones_muestras"
[ -f "$M/boe_sumario_hoy.txt" ] || { echo "Falta $M/boe_sumario_hoy.txt: ejecuta antes ./scripts/subvenciones_sondear.sh" >&2; exit 1; }
python3 - "$M/boe_sumario_hoy.txt" <<'PY'
import json, re, sys, urllib.request
d = json.load(open(sys.argv[1], encoding="utf-8"))
items = []
# recorrido con nombre de sección
for sec in [s for dia in d["data"]["sumario"]["diario"] for s in dia["seccion"]]:
    codigo = sec.get("codigo")
    for dep in sec.get("departamento", []):
        for epi in (dep.get("epigrafe") or [{"item": dep.get("item")}]):
            its = epi.get("item") or []
            for it in (its if isinstance(its, list) else [its]):
                if isinstance(it, dict) and "titulo" in it:
                    items.append((codigo, dep.get("nombre", "")[:40], it))
print(f"ítems totales: {len(items)}")
por = {}
for s, _, _ in items: por[s] = por.get(s, 0) + 1
print("por sección:", dict(sorted(por.items(), key=lambda x: str(x[0]))))
pat = re.compile(r"extracto|subvenci|ayudas?\b|bases reguladoras", re.I)
cand = [(s, dep, it) for s, dep, it in items if pat.search(it["titulo"]) and str(s) not in ("2", "2A", "2B")]
print(f"candidatos (fuera de la sección II de personal): {len(cand)}")
for s, dep, it in cand[:10]:
    print(f"  [{s}] {dep} | {it['identificador']} | {it['titulo'][:150]}")
print()
for s, dep, it in [c for c in cand if re.search(r"extracto", c[2]["titulo"], re.I)][:2] or cand[:2]:
    url = it.get("url_xml")
    if not (url and url.startswith("https://www.boe.es/")):
        continue
    print("── texto de", it["identificador"], "(", url, ")")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ARES-FundingIntelligence/1.0 (+https://101.cat)"})
        xml = urllib.request.urlopen(req, timeout=40).read().decode("utf-8", "replace")
    except Exception as e:
        print("  no se pudo descargar:", type(e).__name__); continue
    print("  bytes:", len(xml))
    print("  inicio:", re.sub(r"\s+", " ", xml[:900]))
    for m in list(re.finditer(r"BDNS", xml))[:2]:
        print("  contexto BDNS:", re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", xml[max(0, m.start()-200): m.end()+200])))
    print()
PY
echo "Fin. Pega este resultado completo en el chat (datos públicos)."
