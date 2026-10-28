#!/usr/bin/env bash
# Actualiza el Cerebro y el motor de licitaciones sin escribir los comandos a mano.
#
# Uso:  ./scripts/actualizar.sh [--sin-git]
#   1. Trae el código (git fetch + merge --ff-only origin/main). Con --sin-git no toca git.
#   2. Motor de licitaciones, y después el Cerebro: si el .env define la imagen de GitHub (LIC_IMAGEN, CEREBRO_IMAGEN_API, CEREBRO_IMAGEN_PANEL) la DESCARGA ya
#      construida (ghcr.io; hace falta `docker login ghcr.io` una vez) y este PC no construye nada; si no la define, la construye aquí, como siempre.
#   3. Reinicia solo lo que cambió y enseña el estado.
# Las descargas se reintentan: una capa ya descargada no se vuelve a bajar.
set -euo pipefail
cd "$(dirname "$0")/.."

SIN_GIT=0
for a in "$@"; do
  case "$a" in
    --sin-git) SIN_GIT=1 ;;
    *) echo "Uso: $0 [--sin-git]" >&2; exit 2 ;;
  esac
done

# Valor de una variable del .env (sin comillas ni comentarios al final); vacío si no está.
valor() {
  [ -f .env ] || return 0
  { grep -E "^$1=" .env || true; } | tail -n 1 | cut -d= -f2- | sed -E 's/[[:space:]]+#.*$//; s/^"(.*)"$/\1/; s/^'"'"'(.*)'"'"'$/\1/; s/[[:space:]]+$//'
}

# Repite una orden hasta 4 veces (las descargas y las construcciones fallan a veces en un PC inestable).
reintentar() {
  local i
  for i in 1 2 3 4; do
    "$@" && return 0
    echo "  (intento $i de 4 fallido)" >&2
    sleep "${ESPERA_REINTENTO:-5}"
  done
  return 1
}

MOTOR=(docker compose -f licitaciones/compose.yaml -f licitaciones/compose.cerebro.yaml --env-file .env)
CEREBRO=(docker compose --profile licitaciones)

if [ -d copias ] && ! find copias -mindepth 1 -maxdepth 1 -mtime -7 2>/dev/null | grep -q .; then
  echo "Aviso: no hay ninguna copia de seguridad de los últimos 7 días. Antes de seguir conviene: COPIA_SIN_TRAZAS=1 ./scripts/copia_seguridad.sh"
fi

if [ "$SIN_GIT" = 0 ]; then
  echo "→ Código"
  git fetch origin
  git merge --ff-only origin/main
fi

# Sube un grupo de servicios: descargando su imagen si el .env la define, o construyéndola aquí si no.
subir() {  # subir <nombre> <variable de imagen> <orden compose...> -- <servicios...>
  local nombre="$1" variable="$2"; shift 2
  local orden=() servicios=()
  while [ "$1" != "--" ]; do orden+=("$1"); shift; done
  shift
  servicios=("$@")
  local imagen; imagen="$(valor "$variable")"
  if [ -n "$imagen" ]; then
    echo "→ $nombre: descargando $imagen"
    reintentar "${orden[@]}" pull "${servicios[0]}" || {
      echo "No se ha podido descargar $imagen. ¿Hiciste 'docker login ghcr.io' (token con permiso read:packages)? ¿Ha terminado de construirse en GitHub (pestaña Actions)?" >&2
      return 1
    }
    reintentar "${orden[@]}" up -d --no-build "${servicios[@]}"
  else
    echo "→ $nombre: construyendo en este PC (para descargarla de GitHub define $variable en el .env)"
    reintentar "${orden[@]}" up -d --build "${servicios[@]}"
  fi
}

subir "Motor de licitaciones" LIC_IMAGEN "${MOTOR[@]}" -- api ingestor proyector
subir "Cerebro (API, worker, beat, migraciones, consumidor)" CEREBRO_IMAGEN_API "${CEREBRO[@]}" -- migraciones api worker beat licitaciones-eventos
subir "Panel" CEREBRO_IMAGEN_PANEL "${CEREBRO[@]}" -- panel

echo "→ Estado"
docker compose ps
echo "Listo. Si algo no responde, mira los registros: docker compose logs --tail 30 <servicio>"
