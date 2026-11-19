#!/usr/bin/env bash
# Sondea, con el servidor REAL, las fuentes de ayudas que aún no tienen conector (UE, BOE, Cataluña) para poder escribir sus conectores con datos reales y no con suposiciones.
# SOLO LECTURA: peticiones públicas (GET, y un POST de búsqueda a la UE), sin claves tuyas ni datos de la empresa. Las direcciones son CANDIDATAS: que alguna falle es información útil.
#
# Uso:  ./scripts/subvenciones_sondear.sh
# Resultado: un resumen con el código HTTP de cada prueba y el comienzo de cada respuesta (datos públicos), y los ficheros completos en  subvenciones_muestras/
# Copia y pega ese resumen (solo eso) para que se ajusten los conectores.
set -uo pipefail
cd "$(dirname "$0")/.."
SALIDA="subvenciones_muestras"
mkdir -p "$SALIDA"
UA="ARES-FundingIntelligence/1.0 (+https://101.cat)"
HOY=$(date +%Y%m%d)
AYER=$(date -d 'yesterday' +%Y%m%d 2>/dev/null || date -v-1d +%Y%m%d)

resumen() {   # nombre, fichero, código
  local n="$1" f="$2" c="$3"
  echo "── $n → HTTP $c · $(wc -c <"$f") bytes"
  head -c 1200 "$f" | tr '\n' ' ' | sed 's/  */ /g'
  echo; echo
}

get() {   # nombre, url, [cabecera Accept]
  local f="$SALIDA/$1.txt" c
  c=$(curl -sS -m 40 -A "$UA" -H "Accept: ${3:-application/json}" -o "$f" -w "%{http_code}" "$2" 2>"$f.err") || c="sin_respuesta"
  resumen "$1" "$f" "$c"
}

echo "=== Cataluña: datos abiertos (dataset candidato 3gku-b36y) ==="
get cat_dataset "https://analisi.transparenciacatalunya.cat/resource/3gku-b36y.json?\$limit=2"
get cat_metadatos "https://analisi.transparenciacatalunya.cat/api/views/3gku-b36y.json"

echo "=== BOE: sumario del día (datos abiertos) ==="
get boe_sumario_hoy "https://www.boe.es/datosabiertos/api/boe/sumario/$HOY"
get boe_sumario_ayer "https://www.boe.es/datosabiertos/api/boe/sumario/$AYER"

echo "=== UE: Funding & Tenders, búsqueda de convocatorias (2 resultados) ==="
f="$SALIDA/ue_busqueda.txt"
c=$(curl -sS -m 40 -A "$UA" -X POST "https://api.tech.ec.europa.eu/search-api/prod/rest/search?apiKey=SEDIA&text=***&pageSize=2&pageNumber=1" \
     -F 'query={"bool":{"must":[{"terms":{"type":["1","2","8"]}},{"terms":{"status":["31094501","31094502"]}}]}};type=application/json' \
     -F 'languages=["es","en"];type=application/json' -o "$f" -w "%{http_code}" 2>"$f.err") || c="sin_respuesta"
resumen ue_busqueda "$f" "$c"

echo "Muestras completas en $(pwd)/$SALIDA/. Pega solo este resumen en el chat (son datos públicos)."
