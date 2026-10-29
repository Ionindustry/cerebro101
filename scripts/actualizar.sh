#!/usr/bin/env bash
# Actualiza el servidor: trae el código, pone al día el motor de licitaciones y DESCARGA las imágenes del Cerebro que construye GitHub
# (.github/workflows/imagenes.yml), en vez de construirlas aquí. Después reinicia lo que ha cambiado.
#
# Uso:  ./scripts/actualizar.sh             descarga las imágenes ya construidas en GitHub (lo normal)
#       ./scripts/actualizar.sh --construir las construye en este equipo (si GitHub no las tiene o no hay acceso)
#
# La primera vez hay que entrar en el registro de GitHub (las imágenes son privadas): docker login ghcr.io -u TU_USUARIO_DE_GITHUB
# y, cuando pida la contraseña, escribir (o pegar) un token «classic» de GitHub con el permiso read:packages. El token NO se comparte con nadie ni se pega en un chat.
set -euo pipefail
cd "$(dirname "$0")/.."

CONSTRUIR=0
case "${1:-}" in
  "") ;;
  --construir) CONSTRUIR=1 ;;
  *) echo "Uso: $0 [--construir]" >&2; exit 2 ;;
esac
[ -f .env ] || { echo "Falta el fichero .env en $(pwd): sin él no se puede arrancar nada." >&2; exit 1; }
MOTOR=(-f licitaciones/compose.yaml -f licitaciones/compose.cerebro.yaml --env-file .env)

echo "→ Código (git pull)"
git pull --ff-only

echo "→ Motor de licitaciones (ingestor, proyector, vectorizador y API; una imagen pequeña que se construye aquí)"
docker compose "${MOTOR[@]}" up -d --build ingestor proyector vectorizador api

echo "→ Cerebro: imágenes de la API y del panel"
if [ "$CONSTRUIR" = 1 ]; then
  docker compose build api panel
elif ! docker compose pull api panel; then
  cat >&2 <<'AYUDA'

No se han podido descargar las imágenes del Cerebro. Causas habituales:
  · «unauthorized» o «denied»: falta entrar en el registro. Una vez:  docker login ghcr.io -u TU_USUARIO_DE_GITHUB
    (la contraseña es un token «classic» de GitHub con el permiso read:packages).
  · «manifest unknown» o «not found»: GitHub aún no ha terminado de construirlas. Mira la pestaña «Actions» del repositorio, flujo «Imágenes», y espera a que salga en verde.
  · Si no hay otra salida:  ./scripts/actualizar.sh --construir   (construye aquí; más lento).
AYUDA
  exit 1
fi

echo "→ Cerebro: reiniciando con las imágenes nuevas"
docker compose up -d --no-build api worker beat panel licitaciones-eventos
docker compose ps --format "table {{.Name}}\t{{.Status}}" | head -30
echo "Listo. Versión del código: $(git rev-parse --short HEAD)"
