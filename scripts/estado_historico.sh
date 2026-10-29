#!/usr/bin/env bash
# Estado de la carga del histórico del motor de licitaciones. SOLO LEE: no cambia nada. Se puede repetir las veces que haga falta mientras carga.
#   ./scripts/estado_historico.sh
# Enseña: carga y disco del PC, qué ZIP del histórico ya están cargados, cuántos eventos faltan por llegar al modelo de lectura, cuántos expedientes hay y las
# últimas líneas del ingestor y del proyector. Guía completa: docs/CARGAR_HISTORICO.md
set -euo pipefail

DB="${LIC_CONTENEDOR_DB:-licitaciones-lic-db-1}"
ING="${LIC_CONTENEDOR_INGESTOR:-licitaciones-ingestor-1}"
PROY="${LIC_CONTENEDOR_PROYECTOR:-licitaciones-proyector-1}"

if ! docker ps --format '{{.Names}}' | grep -qx "$DB"; then
  echo "El motor de licitaciones no está en marcha (no encuentro $DB)." >&2
  exit 1
fi
sql() { docker exec "$DB" psql -U lic -d licitaciones -tA -F ' · ' -c "$1"; }

echo "== PC =="
echo "carga (1/5/15 min): $(cut -d' ' -f1-3 /proc/loadavg) · hilos: $(nproc)"
df -h / | awk 'NR==2 {print "disco: " $4 " libres de " $2 " (" $5 " usado)"}'
echo

echo "== Almacén de originales (RustFS) =="
RUSTFS="${LIC_CONTENEDOR_RUSTFS:-licitaciones-rustfs-1}"
docker stats --no-stream --format "memoria: {{.MemUsage}} ({{.MemPerc}}) · CPU {{.CPUPerc}}" "$RUSTFS" 2>/dev/null || echo "(no encuentro $RUSTFS)"
# El entrypoint relanza el proceso si se cae: cada «Starting» extra en el registro es una caída (casi siempre, falta de memoria).
echo "arranques del proceso en el registro: $(docker logs "$RUSTFS" 2>&1 | grep -c '^Starting:' || true) (1 = nunca se ha caído; muchos = se está cayendo)"
echo

echo "== ZIP del histórico cargados =="
sql "SELECT url FROM paginas_ingeridas WHERE url ~ '^zip:[0-9]{4,6}\$' ORDER BY url DESC" | sed 's/^zip://' | sed 's/^/  /'
echo "  (ficheros .atom ya ingeridos de todos los ZIP: $(sql "SELECT count(*) FROM paginas_ingeridas WHERE url LIKE 'zip:%/%'"))"
echo

echo "== Eventos y modelo de lectura =="
echo "eventos esperando a publicarse (outbox): $(sql "SELECT count(*) || ' (' || count(*) FILTER (WHERE historico) || ' del histórico, el más viejo lleva ' || COALESCE(round(EXTRACT(EPOCH FROM clock_timestamp() - min(creado)))::text, '0') || ' s)' FROM outbox")"
echo "expedientes proyectados: $(sql 'SELECT count(*) FROM expedientes')"
echo "adjudicaciones: $(sql 'SELECT count(*) FROM adjudicaciones')"
echo "vistas (expedientes que ha visto el ingestor): $(sql 'SELECT count(*) FROM vistas')"
echo "  → cuando «outbox» llega a 0 y «expedientes» deja de crecer entre dos ejecuciones, el proyector ha terminado."
echo

echo "== Últimas líneas =="
echo "-- ingestor:"
docker logs --tail 4 "$ING" 2>&1 | cut -c1-220 | sed 's/^/  /' || true
echo "-- proyector:"
docker logs --tail 3 "$PROY" 2>&1 | cut -c1-220 | sed 's/^/  /' || true
