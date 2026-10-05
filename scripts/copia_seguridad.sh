#!/usr/bin/env bash
# Copia de seguridad de los datos del Cerebro y de las evidencias (ISO 27001, control 8.13).
#
# Uso:  ./scripts/copia_seguridad.sh [carpeta_destino] [--parar]
#   Sin --parar: copia en caliente. PostgreSQL (volcado) es consistente; ClickHouse y MinIO (Langfuse) se
#                copian como ficheros y pueden quedar a medias. Para esos usad --parar o exportar_evidencias.py.
#   --parar:     detiene Langfuse y ClickHouse unos segundos para copiarlos de forma consistente y los vuelve a arrancar.
#
# Guarda: cerebro.sql.gz (aprobaciones, registro de acciones, conocimiento…), langfuse.sql.gz,
#         clickhouse.tar.gz y minio.tar.gz (trazas), y SHA256SUMS. Llevad la carpeta a un almacenamiento
# externo y probad la restauración de vez en cuando (docs/SEGURIDAD.md).
set -euo pipefail
cd "$(dirname "$0")/.."

PARAR=0; DESTINO=""
for a in "$@"; do [ "$a" = "--parar" ] && PARAR=1 || DESTINO="$a"; done
DESTINO="${DESTINO:-copias/$(date +%Y-%m-%d_%H%M)}"
PROYECTO="$(docker compose config --format json | python3 -c 'import sys,json;print(json.load(sys.stdin)["name"])')"
mkdir -p "$DESTINO"; DESTINO="$(cd "$DESTINO" && pwd)"

echo "→ PostgreSQL del Cerebro (aprobaciones, registro de acciones, conocimiento)"
docker compose exec -T postgres pg_dump -U cerebro --no-owner cerebro | gzip > "$DESTINO/cerebro.sql.gz"
echo "→ PostgreSQL de Langfuse"
docker compose exec -T langfuse-db pg_dump -U langfuse --no-owner langfuse | gzip > "$DESTINO/langfuse.sql.gz"

if [ "$PARAR" = 1 ]; then
  echo "→ Deteniendo Langfuse y ClickHouse un momento"
  docker compose stop langfuse langfuse-worker langfuse-clickhouse langfuse-minio >/dev/null
  trap 'docker compose start langfuse-db langfuse-redis langfuse-clickhouse langfuse-minio langfuse-worker langfuse >/dev/null' EXIT
else
  echo "Aviso: copia en caliente; ClickHouse y MinIO pueden quedar inconsistentes (usad --parar para una copia exacta)."
fi
for volumen in clickhouse minio; do
  echo "→ Volumen langfuse-$volumen"
  docker run --rm -v "${PROYECTO}_langfuse-${volumen}:/datos:ro" -v "$DESTINO:/copia" alpine \
    tar czf "/copia/${volumen}.tar.gz" -C /datos .
done

( cd "$DESTINO" && sha256sum *.gz > SHA256SUMS )
echo "Copia en $DESTINO"; ls -lh "$DESTINO"
