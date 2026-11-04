#!/usr/bin/env bash
# Copia de seguridad AUTOMÁTICA: la lanza una tarea programada (scripts/windows/autoarranque.ps1 → «Cerebro - copia»), o a mano:  ./scripts/copia_automatica.sh
#
# Hace lo que scripts/copia_seguridad.sh (bases de datos del Cerebro, de Langfuse, del motor de licitaciones y de ERPNext) pero sin las trazas pesadas (COPIA_SIN_TRAZAS=1), y además:
#   · COMPRUEBA la copia: cada .gz se descomprime de prueba, ninguno está vacío y SHA256SUMS coincide;
#   · conserva solo las últimas COPIA_CONSERVAR (7) y borra las más antiguas (solo dentro de copias/auto/);
#   · si COPIA_EXTRA apunta a otra carpeta (otro disco, una unidad de red, un USB: /mnt/d/Copias101), deja ahí una segunda copia: una copia en el mismo disco no te salva de que el disco falle;
#   · deja el resultado en copias/estado.json (fecha, ok, carpeta, tamaño, error);
#   · si algo falla, AVISA por correo a soporte@ (los mismos destinatarios que los fallos del motor) y sale con código 1.
# Una copia no sirve de nada sin probar la restauración: ver docs/SEGURIDAD.md. Y guarda una copia del .env en un gestor de contraseñas (no está en git).
#
# Variables (o en el .env): COPIA_CONSERVAR=7  COPIA_EXTRA=  COPIA_BASE=copias/auto   (para pruebas: COPIA_COMANDO, COPIA_AVISAR)
set -uo pipefail
cd "$(dirname "$0")/.."

CONSERVAR="${COPIA_CONSERVAR:-7}"
BASE="${COPIA_BASE:-copias/auto}"
EXTRA="${COPIA_EXTRA:-}"
[ -z "$EXTRA" ] && [ -f .env ] && EXTRA="$({ grep -E '^COPIA_EXTRA=' .env || true; } | head -1 | cut -d= -f2- | sed 's/[[:space:]]#.*$//')"      # también se puede fijar en el .env
COMANDO="${COPIA_COMANDO:-./scripts/copia_seguridad.sh}"
AVISAR="${COPIA_AVISAR:-docker compose exec -T api python -m cerebro.avisar_soporte}"
ESTADO="$(dirname "$BASE")/estado.json"
CARPETA="$BASE/$(date +%Y-%m-%d_%H%M)"
mkdir -p "$BASE" "$(dirname "$ESTADO")"

estado() {      # ok(true|false) carpeta bytes mensaje
  printf '{"fecha": "%s", "ok": %s, "carpeta": "%s", "bytes": %s, "mensaje": "%s"}\n' "$(date -Is)" "$1" "$2" "${3:-0}" "$(printf '%s' "$4" | tr -d '"\\' | tr '\n' ' ' | cut -c1-300)" > "$ESTADO"
}

fallar() {
  echo "ERROR: $1" >&2
  estado false "$CARPETA" 0 "$1"
  $AVISAR "Copia de seguridad fallida" "La copia de seguridad automática de $(hostname) ha fallado ($(date '+%d/%m/%Y %H:%M')): $1. Mira ./scripts/copia_automatica.sh en el servidor." >/dev/null 2>&1 \
    || echo "Aviso: tampoco se ha podido avisar por correo a soporte@" >&2
  exit 1
}

rm -rf -- "$CARPETA"            # una repetición en el mismo minuto rehace la copia entera, no mezcla ficheros de dos intentos
echo "→ Copia automática en $CARPETA"
COPIA_SIN_TRAZAS=1 $COMANDO "$CARPETA" >/tmp/copia_automatica.log 2>&1 || { tail -5 /tmp/copia_automatica.log >&2; fallar "el script de copia terminó con error (últimas líneas: $(tail -2 /tmp/copia_automatica.log | tr '\n' ' '))"; }
[ -d "$CARPETA" ] || fallar "no se ha creado la carpeta de la copia"

echo "→ Comprobando la copia"
n=0
for f in "$CARPETA"/*.gz; do
  [ -e "$f" ] || break
  n=$((n + 1))
  [ -s "$f" ] || fallar "el fichero $(basename "$f") está vacío"
  gzip -t "$f" 2>/dev/null || fallar "el fichero $(basename "$f") está dañado (no se descomprime)"
done
[ "$n" -ge 1 ] || fallar "la copia no contiene ningún fichero .gz"
[ -f "$CARPETA/cerebro.sql.gz" ] || fallar "falta cerebro.sql.gz: la base de datos principal no se ha copiado"
( cd "$CARPETA" && sha256sum -c SHA256SUMS >/dev/null 2>&1 ) || fallar "SHA256SUMS no coincide con los ficheros de la copia"
BYTES="$(du -sb "$CARPETA" | cut -f1)"

if [ -n "$EXTRA" ]; then
  echo "→ Segunda copia en $EXTRA"
  mkdir -p "$EXTRA" 2>/dev/null && cp -r "$CARPETA" "$EXTRA/" 2>/dev/null && ( cd "$EXTRA/$(basename "$CARPETA")" && sha256sum -c SHA256SUMS >/dev/null 2>&1 ) \
    || fallar "no se ha podido dejar la segunda copia en $EXTRA (¿está conectada la unidad?)"
fi

echo "→ Conservando las últimas $CONSERVAR copias"
# Solo carpetas con el nombre de una copia (AAAA-MM-DD_HHMM) dentro de $BASE: nada más se borra
mapfile -t viejas < <(ls -1d "$BASE"/[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]_[0-9][0-9][0-9][0-9] 2>/dev/null | sort | head -n "-$CONSERVAR")
for d in "${viejas[@]}"; do [ -n "$d" ] && rm -rf -- "$d" && echo "   borrada $d"; done

estado true "$CARPETA" "$BYTES" "copia correcta"
echo "Copia correcta: $CARPETA ($(numfmt --to=iec "$BYTES" 2>/dev/null || echo "$BYTES bytes"))"
