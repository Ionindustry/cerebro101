#!/usr/bin/env bash
# Comprueba, con el servidor REAL, las direcciones y los campos que el conector de la BDNS (ES-001) da por supuestos, y guarda las respuestas de muestra.
# Es SOLO LECTURA (peticiones GET públicas, sin claves) y no cambia nada en ARES. Sirve para decidir si el conector funciona tal cual o hay que ajustar
# `settings` de la fuente (config/subvenciones.yaml o panel › Subvenciones › Conectores) antes de activarla.
#
# Uso:  ./scripts/subvenciones_verificar.sh
# Resultado: carpeta  subvenciones_muestras/  con un fichero por prueba y un resumen en pantalla. NO pegues en ningún chat nada que no sea ese resumen.
set -uo pipefail
cd "$(dirname "$0")/.."
BASE="${BDNS_BASE_URL:-https://www.infosubvenciones.es/bdnstrans/api}"
SALIDA="subvenciones_muestras"
mkdir -p "$SALIDA"
UA="ARES-FundingIntelligence/1.0 (+https://101.cat)"
ok=0; mal=0

probar() {   # nombre, ruta (con query)
  local nombre="$1" ruta="$2" fichero="$SALIDA/$1.txt" codigo tipo
  codigo=$(curl -sS -m 40 -A "$UA" -H "Accept: application/json" -o "$fichero" -w "%{http_code} %{content_type}" "$BASE$ruta" 2>"$fichero.err") || codigo="sin_respuesta"
  tipo="$codigo"
  if [[ "$codigo" == 200* ]]; then ok=$((ok+1)); printf "  ✔ %-28s %s  (%s bytes)\n" "$nombre" "$tipo" "$(wc -c <"$fichero")"
  else mal=$((mal+1)); printf "  ✘ %-28s %s  %s\n" "$nombre" "$tipo" "$(head -c 120 "$fichero.err" 2>/dev/null)"; fi
}

echo "Base consultada: $BASE"
echo "1) Documentación del servicio (para confirmar nombres de endpoints)"
for r in /v3/api-docs /v2/api-docs /swagger.json /openapi.json; do probar "doc$(echo "$r" | tr '/.' '__')" "$r"; done
echo "2) Búsqueda de convocatorias (la que usa el conector por defecto)"
DESDE=$(date -d '7 days ago' +%d/%m/%Y 2>/dev/null || date -v-7d +%d/%m/%Y)
probar "busqueda_pagina0" "/convocatorias/busqueda?page=0&pageSize=5&fechaDesde=$(printf %s "$DESDE" | sed 's#/#%2F#g')&vpd=GE"
echo "3) Detalle de una convocatoria de la muestra"
NUM=$(python3 - "$SALIDA/busqueda_pagina0.txt" <<'PY' 2>/dev/null
import json, sys
try:
    d = json.load(open(sys.argv[1], encoding="utf-8"))
    filas = d.get("content") if isinstance(d, dict) else d
    print((filas or [{}])[0].get("numeroConvocatoria") or "")
except Exception:
    print("")
PY
)
if [ -n "${NUM:-}" ]; then probar "detalle_${NUM}" "/convocatorias?numConv=$NUM"; else echo "  (sin número de convocatoria en la búsqueda: no se puede probar el detalle; mira $SALIDA/busqueda_pagina0.txt)"; fi

echo
echo "Campos que el conector espera encontrar en la búsqueda / el detalle (✔ = está en la muestra):"
python3 - "$SALIDA" "${NUM:-}" <<'PY' 2>/dev/null
import json, sys
from pathlib import Path
d = Path(sys.argv[1]); num = sys.argv[2]
def cargar(n):
    try: return json.loads((d / n).read_text(encoding="utf-8"))
    except Exception: return None
b = cargar("busqueda_pagina0.txt"); det = cargar(f"detalle_{num}.txt") if num else None
fila = ((b.get("content") if isinstance(b, dict) else b) or [{}])[0] if b else {}
def tiene(o, ruta):
    for p in ruta.split("."):
        if not isinstance(o, dict) or p not in o: return False
        o = o[p]
    return o not in (None, "", [])
try:        # se lee la lista del código fuente sin importarlo (el Python del servidor no tiene las dependencias de la API)
    import ast
    arbol = ast.parse(Path("api/cerebro/subvenciones/conectores/bdns.py").read_text(encoding="utf-8"))
    C = next(ast.literal_eval(n.value) for n in arbol.body if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "CAMPOS_POR_DEFECTO")
except Exception as e:
    print("  (no se pudo leer la lista de campos del conector:", e, ")"); sys.exit(0)
crudo = {"resumen": fila, "detalle": det}
for campo, rutas in C.items():
    hallado = next((r for r in rutas if tiene(crudo, r)), None)
    print(f"  {'✔' if hallado else '✘'} {campo:<22} {hallado or 'no aparece (candidatas: ' + ', '.join(rutas) + ')'}")
PY
echo
echo "Resumen: $ok pruebas correctas, $mal fallidas. Muestras guardadas en $(pwd)/$SALIDA/"
echo "Si hay ✘ en campos o endpoints: NO actives la fuente; ajusta «campos»/endpoints en los ajustes de ES-001 y repite este script y una sincronización manual."
