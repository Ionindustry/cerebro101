#!/usr/bin/env bash
# Arranca (o recupera tras una caída) el Cerebro y el ERP ya instalados. No reconstruye imágenes ni descarga modelos:
# para la primera instalación está scripts/iniciar.sh. Es idempotente: se puede lanzar las veces que haga falta.
#
#   ./scripts/arrancar.sh            levanta lo que esté parado y espera a que respondan
#   ./scripts/arrancar.sh estado     solo comprueba (sale con 0 si la API responde, con 1 si no); no arranca nada
#
# Variables: ARRANCAR_ESPERA=300 (segundos máximos esperando a la API), ARRANCAR_SERVICIOS="api postgres …" (solo esos del Cerebro),
#            ARRANCAR_SIN_ERP=1 (no toca ERPNext).
set -uo pipefail
cd "$(dirname "$0")/.."
ESPERA="${ARRANCAR_ESPERA:-300}"
ERP=(docker compose -f erpnext/docker-compose.yml --env-file .env)
# shellcheck disable=SC2206
SERVICIOS=(${ARRANCAR_SERVICIOS:-})
marca() { date '+%F %T'; }
api_ok() { curl -fsS -m 5 http://127.0.0.1:8000/salud >/dev/null 2>&1 && return 0 || return 1; }
erp_ok() { curl -fsS -m 5 http://127.0.0.1:8081/api/method/ping >/dev/null 2>&1 && return 0 || return 1; }

resumen() {
  echo "[$(marca)] API:  $(api_ok && echo responde || echo 'NO responde')"
  if [ -f erpnext/docker-compose.yml ] && [ "${ARRANCAR_SIN_ERP:-0}" != 1 ]; then echo "[$(marca)] ERP:  $(erp_ok && echo responde || echo 'NO responde')"; fi
  local parados="" p
  for p in cerebro-101 erpnext; do        # solo los contenedores de estos dos proyectos, no restos de otros
    parados+="$(docker ps -a --filter "label=com.docker.compose.project=$p" --filter 'status=exited' --filter 'status=restarting' --filter 'status=dead' \
                --format '{{.Names}} ({{.Status}})' 2>/dev/null | grep -v -E 'migraciones|create-site|configurator' || true)"$'\n'
  done
  parados="$(echo "$parados" | sed '/^$/d')"
  [ -n "$parados" ] && { echo "[$(marca)] Contenedores parados o reiniciándose:"; echo "$parados" | sed 's/^/    /'; }
  return 0
}

if [ "${1:-}" = "estado" ]; then resumen; api_ok; exit $?; fi

[ -f .env ] || { echo "Falta .env: este equipo no tiene el Cerebro instalado (scripts/iniciar.sh)"; exit 2; }
docker info >/dev/null 2>&1 || { echo "[$(marca)] Docker no responde: arráncalo y repite"; exit 1; }
docker network inspect cerebro >/dev/null 2>&1 || docker network create cerebro >/dev/null

echo "[$(marca)] Arrancando el Cerebro…"
docker compose up -d --no-build "${SERVICIOS[@]}" || docker compose up -d "${SERVICIOS[@]}" || echo "[$(marca)] AVISO: docker compose up falló (mira docker compose ps)"

if [ -f erpnext/docker-compose.yml ] && [ "${ARRANCAR_SIN_ERP:-0}" != 1 ] && [ -n "$("${ERP[@]}" ps -a -q 2>/dev/null)" ]; then
  echo "[$(marca)] Arrancando ERPNext…"
  "${ERP[@]}" up -d --no-build || echo "[$(marca)] AVISO: ERPNext no arrancó (mira docker compose -f erpnext/docker-compose.yml ps)"
fi

echo "[$(marca)] Esperando a la API (hasta ${ESPERA} s)…"
for _ in $(seq 1 $((ESPERA / 5))); do api_ok && break; sleep 5; done
resumen
api_ok
