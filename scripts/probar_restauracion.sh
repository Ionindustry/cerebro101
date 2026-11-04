#!/usr/bin/env bash
# Prueba que una copia de seguridad SE PUEDE RESTAURAR, sin tocar tus datos: restaura cada volcado de PostgreSQL en una base de datos TEMPORAL (que se borra al terminar) y comprueba que se lee.
#
# Uso:  ./scripts/probar_restauracion.sh [carpeta_de_la_copia]       (por defecto, la última de copias/auto/ o, si no hay, de copias/)
#
# Comprueba, para cada copia:
#   · SHA256SUMS coincide y cada .gz se descomprime;
#   · cerebro.sql.gz, langfuse.sql.gz y licitaciones.sql.gz (los que haya): se restauran en una base temporal, tienen tablas y se cuentan sus filas;
#   · erpnext.sql.gz (MariaDB): NO se restaura (el volcado «todas las bases» recrearía las de verdad y pisaría el ERP): se comprueba que está completo (termina con «Dump completed») y trae tablas y datos.
# Una copia que nunca se ha restaurado puede estar rota sin que lo sepas: prueba esto de vez en cuando (y tras cambiar algo importante). Deja el resultado en copias/restauracion.json y, si está
# el Cerebro en marcha, lo anota para la tarjeta «Copias de seguridad» de Jarvis. Sale con código 1 si algo falla.
#
# Variables (para pruebas): RESTAURAR_PG_CEREBRO, RESTAURAR_PG_LANGFUSE, RESTAURAR_PG_LIC = comando psql (sin -d) de cada servidor; RESTAURAR_REGISTRAR = comando que anota el resultado.
set -uo pipefail
cd "$(dirname "$0")/.."

DEST="${1:-}"
if [ -z "$DEST" ]; then
  DEST="$(ls -1d copias/auto/[0-9]*_[0-9]* 2>/dev/null | sort | tail -1)"
  [ -n "$DEST" ] || DEST="$(ls -1d copias/[0-9]*_[0-9]* 2>/dev/null | sort | tail -1)"
fi
[ -n "$DEST" ] && [ -d "$DEST" ] || { echo "No hay ninguna copia que probar (carpeta copias/). Haz una con ./scripts/copia_automatica.sh" >&2; exit 2; }
DEST="$(cd "$DEST" && pwd)"
RAIZ_COPIAS="$(dirname "$DEST")"; case "$RAIZ_COPIAS" in */auto) RAIZ_COPIAS="$(dirname "$RAIZ_COPIAS")";; esac        # la carpeta «copias/»
PG_CEREBRO="${RESTAURAR_PG_CEREBRO:-docker compose exec -T postgres psql -U cerebro}"
PG_LANGFUSE="${RESTAURAR_PG_LANGFUSE:-docker compose exec -T langfuse-db psql -U langfuse}"
PG_LIC="${RESTAURAR_PG_LIC:-docker exec -i licitaciones-lic-db-1 psql -U lic}"
REGISTRAR="${RESTAURAR_REGISTRAR:-docker compose exec -T api python -m cerebro.copias registrar restauracion}"
TEMPORAL="restauracion_prueba_$$_$(date +%s)"
FALLOS=(); RESUMEN=()
ok() { echo "  ✔ $*"; }
mal() { echo "  ✘ $*"; FALLOS+=("$*"); }

echo "Probando la copia: $DEST"
echo "→ Sumas de control y ficheros"
if [ -f "$DEST/SHA256SUMS" ]; then
  ( cd "$DEST" && sha256sum -c SHA256SUMS >/dev/null 2>&1 ) && ok "SHA256SUMS coincide" || mal "SHA256SUMS no coincide con los ficheros"
else
  mal "falta SHA256SUMS"
fi
for f in "$DEST"/*.gz; do
  [ -e "$f" ] || { mal "la copia no tiene ningún .gz"; break; }
  { [ -s "$f" ] && gzip -t "$f" 2>/dev/null; } || mal "$(basename "$f") está vacío o dañado"
done

restaurar_pg() {      # fichero comando_psql minimo_de_tablas
  local fichero="$1" psql="$2" minimo="$3" nombre; nombre="$(basename "$fichero")"
  [ -f "$fichero" ] || return 0
  echo "→ Restaurando $nombre en una base temporal"
  $psql -d postgres -qAt -c "CREATE DATABASE \"$TEMPORAL\"" >/dev/null 2>&1 || { mal "$nombre: no se ha podido crear la base temporal (¿el servicio está en marcha?)"; return 0; }
  if gunzip -c "$fichero" | $psql -d "$TEMPORAL" -qAt -v ON_ERROR_STOP=1 >/dev/null 2>"$DEST/.restauracion_error.tmp"; then
    local tablas filas
    tablas="$($psql -d "$TEMPORAL" -qAt -c "SELECT count(*) FROM information_schema.tables WHERE table_schema NOT IN ('pg_catalog','information_schema') AND table_type='BASE TABLE'" 2>/dev/null | tr -d '[:space:]')"
    filas="$($psql -d "$TEMPORAL" -qAt -c "SELECT coalesce(sum((xpath('/row/c/text()', query_to_xml(format('select count(*) as c from %I.%I', table_schema, table_name), false, true, '')))[1]::text::bigint), 0) FROM information_schema.tables WHERE table_schema NOT IN ('pg_catalog','information_schema') AND table_type='BASE TABLE'" 2>/dev/null | tr -d '[:space:]')"
    if [ "${tablas:-0}" -ge "$minimo" ] 2>/dev/null; then ok "$nombre: restaurado; ${tablas} tablas y ${filas:-0} filas"; RESUMEN+=("$nombre: ${tablas} tablas, ${filas:-0} filas")
    else mal "$nombre: se restaura pero tiene solo ${tablas:-0} tablas (se esperaban al menos $minimo)"; fi
  else
    mal "$nombre: NO se restaura ($(head -c 200 "$DEST/.restauracion_error.tmp" | tr '\n' ' '))"
  fi
  rm -f "$DEST/.restauracion_error.tmp"
  $psql -d postgres -qAt -c "DROP DATABASE IF EXISTS \"$TEMPORAL\"" >/dev/null 2>&1 || mal "$nombre: no se ha podido borrar la base temporal $TEMPORAL (bórrala a mano)"
}
restaurar_pg "$DEST/cerebro.sql.gz" "$PG_CEREBRO" 5
restaurar_pg "$DEST/langfuse.sql.gz" "$PG_LANGFUSE" 1
restaurar_pg "$DEST/licitaciones.sql.gz" "$PG_LIC" 1

if [ -f "$DEST/erpnext.sql.gz" ]; then
  echo "→ ERPNext (solo se comprueba que el volcado está completo: no se restaura para no pisar el ERP)"
  if gunzip -c "$DEST/erpnext.sql.gz" | tail -c 400 | grep -q "Dump completed"; then ok "erpnext.sql.gz termina con «Dump completed»"; else mal "erpnext.sql.gz no está completo (no termina con «Dump completed»)"; fi
  t="$(gunzip -c "$DEST/erpnext.sql.gz" | grep -c '^CREATE TABLE')"; i="$(gunzip -c "$DEST/erpnext.sql.gz" | grep -c '^INSERT INTO')"
  { [ "$t" -gt 50 ] && [ "$i" -gt 0 ]; } && { ok "erpnext.sql.gz: $t tablas y datos"; RESUMEN+=("erpnext.sql.gz: $t tablas"); } || mal "erpnext.sql.gz trae $t tablas y $i bloques de datos: parece incompleto"
fi

MENSAJE="$(IFS='; '; echo "${RESUMEN[*]:-sin detalle}")"
if [ "${#FALLOS[@]}" -eq 0 ]; then
  echo "RESULTADO: la copia se puede restaurar. ($MENSAJE)"
  OK=true; MSG="Restauración probada: $MENSAJE"
else
  echo "RESULTADO: la copia tiene ${#FALLOS[@]} problemas; NO te fíes de ella."
  OK=false; MSG="${FALLOS[*]}"
fi
printf '{"fecha": "%s", "ok": %s, "carpeta": "%s", "mensaje": "%s"}\n' "$(date -Is)" "$OK" "$DEST" "$(printf '%s' "$MSG" | tr -d '"\\' | tr '\n' ' ' | cut -c1-400)" > "$RAIZ_COPIAS/restauracion.json" 2>/dev/null || true
$REGISTRAR "$OK" "$DEST" "$(printf '%s' "$MSG" | cut -c1-400)" >/dev/null 2>&1 || echo "Aviso: no se ha podido anotar el resultado en Jarvis (el Cerebro no responde)" >&2
[ "$OK" = true ]
