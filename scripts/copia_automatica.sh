#!/usr/bin/env bash
# Copia de seguridad AUTOMÁTICA: la lanza una tarea programada (scripts/windows/autoarranque.ps1 → «Cerebro - copia»), o a mano:  ./scripts/copia_automatica.sh
#
# Hace lo que scripts/copia_seguridad.sh (bases de datos del Cerebro, de Langfuse, del motor de licitaciones y de ERPNext) pero sin las trazas pesadas (COPIA_SIN_TRAZAS=1), y además:
#   · COMPRUEBA la copia: cada .gz se descomprime de prueba, ninguno está vacío y SHA256SUMS coincide;
#   · conserva solo las últimas COPIA_CONSERVAR (7) y borra las más antiguas (solo dentro de copias/auto/);
#   · si COPIA_EXTRA apunta a otra carpeta (otro disco, una unidad de red, un USB: /mnt/d/Copias101), deja ahí una segunda copia: una copia en el mismo disco no te salva de que el disco falle;
#   · deja el resultado en copias/estado.json (fecha, ok, carpeta, tamaño, error) y lo anota para la tarjeta «Copias de seguridad» de Jarvis (y el vigilante que avisa si pasan 3 días sin una buena);
#   · si algo falla, AVISA por correo a soporte@ (los mismos destinatarios que los fallos del motor) y sale con código 1.
# Una copia no sirve de nada sin probar la restauración: ver docs/SEGURIDAD.md. Y guarda una copia del .env en un gestor de contraseñas (no está en git).
#
#   · COPIA INCREMENTAL (opcional): con COPIA_RESTIC_REPO (una carpeta) y COPIA_RESTIC_CLAVE (el fichero con la contraseña del repositorio) deja además la copia en un repositorio de restic, que guarda
#     cada día SOLO lo que ha cambiado (deduplicado y cifrado) y conserva 7 diarias, 8 semanales y 12 mensuales. Las copias completas de arriba siguen haciéndose igual. Ver docs/SEGURIDAD.md.
#
# Variables (o en el .env): COPIA_CONSERVAR=7  COPIA_EXTRA=  COPIA_BASE=copias/auto  COPIA_RESTIC_REPO=  COPIA_RESTIC_CLAVE=   (para pruebas: COPIA_COMANDO, COPIA_AVISAR, COPIA_RESTIC, COPIA_RESTIC_SIN_VALIDAR)
set -uo pipefail
umask 077          # las copias llevan datos sensibles: solo las lee quien las hace
cd "$(dirname "$0")/.."
REGISTRO="$(mktemp "${TMPDIR:-/tmp}/copia_automatica.XXXXXX")"; trap 'rm -f "$REGISTRO"' EXIT

CONSERVAR="${COPIA_CONSERVAR:-7}"
BASE="${COPIA_BASE:-copias/auto}"
EXTRA="${COPIA_EXTRA:-}"
[ -z "$EXTRA" ] && [ -f .env ] && EXTRA="$({ grep -E '^COPIA_EXTRA=' .env || true; } | head -1 | cut -d= -f2- | sed 's/[[:space:]]#.*$//')"      # también se puede fijar en el .env
CONSERVAR_EXTRA="${COPIA_CONSERVAR_EXTRA:-0}"        # 0 = en la segunda ubicación no se borra nunca (como siempre)
# Lo que se haya fijado en Jarvis (botón «Configurar» de Copias de seguridad) manda sobre el .env; sin nada fijado (o con la API parada) se queda como arriba. Solo se aceptan valores con la forma esperada.
CONFIG="$(${COPIA_CONFIG:-docker compose exec -T api python -m cerebro.copias config} 2>/dev/null || true)"
ajuste() { printf '%s\n' "$CONFIG" | sed -n "s/^$1=//p" | head -1 | tr -d '\r'; }
v="$(ajuste conservar)"; [[ "$v" =~ ^[0-9]{1,2}$ ]] && [ "$v" -ge 1 ] && CONSERVAR="$v"
v="$(ajuste conservar_extra)"; [[ "$v" =~ ^[0-9]{1,3}$ ]] && CONSERVAR_EXTRA="$v"
if printf '%s\n' "$CONFIG" | grep -q '^extra='; then
  v="$(ajuste extra)"
  if [ -z "$v" ]; then EXTRA=""
  elif [[ "$v" =~ ^/(mnt/[a-z]|media/[A-Za-z0-9._-]+|srv|home/[A-Za-z0-9._-]+)/[A-Za-z0-9._/-]+$ ]] && [[ "$v" != *..* ]]; then EXTRA="$v"
  fi
fi
leer_env() { [ -f .env ] && { grep -E "^$1=" .env || true; } | head -1 | cut -d= -f2- | sed 's/[[:space:]]#.*$//' | tr -d '\r"'"'"; }
RESTIC_REPO="${COPIA_RESTIC_REPO:-$(leer_env COPIA_RESTIC_REPO)}"
RESTIC_CLAVE="${COPIA_RESTIC_CLAVE:-$(leer_env COPIA_RESTIC_CLAVE)}"
RESTIC="${COPIA_RESTIC:-restic}"
COMANDO="${COPIA_COMANDO:-./scripts/copia_seguridad.sh}"
AVISAR="${COPIA_AVISAR:-docker compose exec -T api python -m cerebro.avisar_soporte}"
REGISTRAR="${COPIA_REGISTRAR:-docker compose exec -T api python -m cerebro.copias registrar copia}"      # anota el resultado para la tarjeta de Jarvis y el vigilante de copias
ESTADO="$(dirname "$BASE")/estado.json"
CARPETA="$BASE/$(date +%Y-%m-%d_%H%M)"
mkdir -p "$BASE" "$(dirname "$ESTADO")"

estado() {      # ok(true|false) carpeta bytes mensaje
  printf '{"fecha": "%s", "ok": %s, "carpeta": "%s", "bytes": %s, "mensaje": "%s"}\n' "$(date -Is)" "$1" "$2" "${3:-0}" "$(printf '%s' "$4" | tr -d '"\\' | tr '\n' ' ' | cut -c1-300)" > "$ESTADO"
}

fallar() {
  echo "ERROR: $1" >&2
  estado false "$CARPETA" 0 "$1"
  $REGISTRAR false "$CARPETA" "$1" >/dev/null 2>&1 || true
  $AVISAR "Copia de seguridad fallida" "La copia de seguridad automática de $(hostname) ha fallado ($(date '+%d/%m/%Y %H:%M')): $1. Mira ./scripts/copia_automatica.sh en el servidor." >/dev/null 2>&1 \
    || echo "Aviso: tampoco se ha podido avisar por correo a soporte@" >&2
  exit 1
}

rm -rf -- "$CARPETA"            # una repetición en el mismo minuto rehace la copia entera, no mezcla ficheros de dos intentos
echo "→ Copia automática en $CARPETA"
COPIA_SIN_TRAZAS=1 $COMANDO "$CARPETA" >"$REGISTRO" 2>&1 || { tail -5 "$REGISTRO" >&2; fallar "el script de copia terminó con error (últimas líneas: $(tail -2 "$REGISTRO" | tr '\n' ' '))"; }
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

if [ -n "$RESTIC_REPO" ]; then
  echo "→ Copia incremental (restic) en $RESTIC_REPO"
  RUTA_OK='^/(mnt/[a-z]|media/[A-Za-z0-9._-]+|srv|home/[A-Za-z0-9._-]+)/[A-Za-z0-9._/-]+$'
  [ "${COPIA_RESTIC_SIN_VALIDAR:-0}" = 1 ] || { [[ "$RESTIC_REPO" =~ $RUTA_OK ]] && [[ "$RESTIC_REPO" != *..* ]]; } || fallar "COPIA_RESTIC_REPO tiene que ser una carpeta local (/mnt/d/..., /home/...): $RESTIC_REPO"
  [ -n "$RESTIC_CLAVE" ] && [ -s "$RESTIC_CLAVE" ] || fallar "falta el fichero con la contraseña del repositorio restic (COPIA_RESTIC_CLAVE): sin ella no se puede cifrar ni recuperar la copia"
  command -v "$RESTIC" >/dev/null 2>&1 || fallar "restic no está instalado (sudo apt install restic)"
  export RESTIC_REPOSITORY="$RESTIC_REPO" RESTIC_PASSWORD_FILE="$RESTIC_CLAVE"
  mkdir -p "$RESTIC_REPO" 2>/dev/null || fallar "no se puede crear $RESTIC_REPO (¿está conectada la unidad?)"
  if ! "$RESTIC" cat config >/dev/null 2>&1; then
    "$RESTIC" init >"$REGISTRO" 2>&1 || fallar "no se ha podido crear el repositorio restic en $RESTIC_REPO ($(tail -1 "$REGISTRO"))"
  fi
  "$RESTIC" backup "$CARPETA" --tag cerebro --host cerebro --quiet >"$REGISTRO" 2>&1 || fallar "restic no ha podido hacer la copia incremental ($(tail -1 "$REGISTRO"))"
  "$RESTIC" forget --tag cerebro --keep-daily 7 --keep-weekly 8 --keep-monthly 12 --prune --quiet >"$REGISTRO" 2>&1 || fallar "restic no ha podido limpiar las copias antiguas ($(tail -1 "$REGISTRO"))"
fi

if [ -n "$EXTRA" ] && [ "$CONSERVAR_EXTRA" -gt 0 ]; then
  echo "→ Conservando las últimas $CONSERVAR_EXTRA copias en $EXTRA"
  mapfile -t viejas_extra < <(ls -1d "$EXTRA"/[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]_[0-9][0-9][0-9][0-9] 2>/dev/null | sort | head -n "-$CONSERVAR_EXTRA")
  for d in "${viejas_extra[@]}"; do [ -n "$d" ] && rm -rf -- "$d" && echo "   borrada $d"; done
fi

echo "→ Conservando las últimas $CONSERVAR copias"
# Solo carpetas con el nombre de una copia (AAAA-MM-DD_HHMM) dentro de $BASE: nada más se borra
mapfile -t viejas < <(ls -1d "$BASE"/[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]_[0-9][0-9][0-9][0-9] 2>/dev/null | sort | head -n "-$CONSERVAR")
for d in "${viejas[@]}"; do [ -n "$d" ] && rm -rf -- "$d" && echo "   borrada $d"; done

estado true "$CARPETA" "$BYTES" "copia correcta"
$REGISTRAR true "$CARPETA" "copia correcta" "$BYTES" >/dev/null 2>&1 || echo "Aviso: no se ha podido anotar la copia en Jarvis (el Cerebro no responde)" >&2
echo "Copia correcta: $CARPETA ($(numfmt --to=iec "$BYTES" 2>/dev/null || echo "$BYTES bytes"))"
