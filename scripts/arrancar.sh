#!/usr/bin/env bash
# Arranca (o recupera tras una caída) el Cerebro y el ERP ya instalados. No reconstruye imágenes ni descarga modelos:
# para la primera instalación está scripts/iniciar.sh. Es idempotente: se puede lanzar las veces que haga falta.
#
#   ./scripts/arrancar.sh            levanta lo que esté parado y espera a que respondan
#   ./scripts/arrancar.sh estado     solo comprueba (sale con 0 si la API responde, con 1 si no); no arranca nada
#   ./scripts/arrancar.sh reparar-erp  reinicia los servicios del ERP en el orden correcto (backend y websocket, luego el frontend)
#
# Variables: ARRANCAR_ESPERA=300 (segundos máximos esperando a la API), ARRANCAR_SERVICIOS="api postgres ..." (solo esos del Cerebro),
#            ARRANCAR_SIN_ERP=1 (no toca ERPNext), ARRANCAR_SIN_MOTOR=1 (no toca el motor de licitaciones).
set -uo pipefail
cd "$(dirname "$0")/.."
ESPERA="${ARRANCAR_ESPERA:-300}"
ERP=(docker compose -f erpnext/docker-compose.yml --env-file .env)
# shellcheck disable=SC2206
SERVICIOS=(${ARRANCAR_SERVICIOS:-})
marca() { date '+%F %T'; }
api_ok() { curl -fsS -m 5 http://127.0.0.1:8000/salud >/dev/null 2>&1 && return 0 || return 1; }
panel_ok() { curl -sS -m 5 -o /dev/null http://127.0.0.1:3000/ >/dev/null 2>&1; }       # basta que el puerto responda (con cualquier código): lo que falla tras reiniciar Docker es que el puerto no esté publicado
MOTOR=(docker compose -f licitaciones/compose.yaml -f licitaciones/compose.cerebro.yaml --env-file .env)
erp_ok() { curl -fsS -m 5 http://127.0.0.1:8081/api/method/ping >/dev/null 2>&1 && return 0 || return 1; }

resumen() {
  echo "[$(marca)] API:  $(api_ok && echo responde || echo 'NO responde')"
  echo "[$(marca)] Panel: $(panel_ok && echo responde || echo 'NO responde')"
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

# Tras reiniciar Docker, todo arranca a la vez y el frontend (nginx) puede caerse porque aun no existe el websocket
# ("host not found in upstream"). Reiniciarlo cuando los demas ya estan en pie lo arregla.
reparar_erp() {
  echo "[$(marca)] Reparando el ERP: se reinician backend y websocket y despues el frontend..."
  "${ERP[@]}" --progress quiet restart backend websocket >/dev/null 2>&1
  sleep 20
  "${ERP[@]}" --progress quiet restart frontend >/dev/null 2>&1
  for _ in $(seq 1 24); do erp_ok && return 0; sleep 5; done
  return 1
}

# Tras reiniciar Docker puede pasar que los contenedores de la API o del panel estén «Up» pero con sus puertos sin publicar en este equipo
# (localhost:3000 y :8000 caídos). Recrearlos (sin tocar datos ni dependencias) lo arregla.
reparar_puertos() {
  echo "[$(marca)] La API o el panel no responden en este equipo aunque estén en marcha: se recrean api y panel (los datos no se tocan)..."
  docker compose --progress quiet up -d --no-build --force-recreate --no-deps api panel >/dev/null 2>&1 || echo "[$(marca)] AVISO: no se pudieron recrear api y panel"
}

if [ "${1:-}" = "estado" ]; then resumen; api_ok && panel_ok; exit $?; fi
if [ "${1:-}" = "reparar-erp" ]; then reparar_erp && echo "[$(marca)] ERP: responde" || echo "[$(marca)] ERP: sigue sin responder"; exit 0; fi

[ -f .env ] || { echo "Falta .env: este equipo no tiene el Cerebro instalado (scripts/iniciar.sh)"; exit 2; }
docker info >/dev/null 2>&1 || { echo "[$(marca)] Docker no responde: arráncalo y repite"; exit 1; }
docker network inspect cerebro >/dev/null 2>&1 || docker network create cerebro >/dev/null

echo "[$(marca)] Arrancando el Cerebro..."
docker compose --progress quiet up -d --no-build "${SERVICIOS[@]}" || docker compose --progress quiet up -d "${SERVICIOS[@]}" || echo "[$(marca)] AVISO: docker compose up falló (mira docker compose ps)"

if [ -f erpnext/docker-compose.yml ] && [ "${ARRANCAR_SIN_ERP:-0}" != 1 ] && [ -n "$("${ERP[@]}" ps -a -q 2>/dev/null)" ]; then
  echo "[$(marca)] Arrancando ERPNext..."
  "${ERP[@]}" --progress quiet up -d --no-build || echo "[$(marca)] AVISO: ERPNext no arrancó (mira docker compose -f erpnext/docker-compose.yml ps)"
fi

# El motor de licitaciones es otro proyecto de Docker (licitaciones/compose.yaml): se levanta aparte, sin reconstruir (la imagen la construye actualizar.sh)
if [ -f licitaciones/compose.yaml ] && [ -f licitaciones/compose.cerebro.yaml ] && [ "${ARRANCAR_SIN_MOTOR:-0}" != 1 ] && [ -n "$("${MOTOR[@]}" ps -a -q 2>/dev/null)" ]; then
  echo "[$(marca)] Arrancando el motor de licitaciones..."
  "${MOTOR[@]}" --progress quiet up -d --no-build || echo "[$(marca)] AVISO: el motor de licitaciones no arrancó (mira docker compose -f licitaciones/compose.yaml -f licitaciones/compose.cerebro.yaml --env-file .env ps)"
fi

usa_erp=0; if [ -f erpnext/docker-compose.yml ] && [ "${ARRANCAR_SIN_ERP:-0}" != 1 ] && [ -n "$("${ERP[@]}" ps -a -q 2>/dev/null)" ]; then usa_erp=1; fi
echo "[$(marca)] Esperando a la API$([ "$usa_erp" = 1 ] && echo ' y al ERP') (hasta ${ESPERA} s)..."
espera_servicios() {   # segundos maximos
  local i; for i in $(seq 1 $(($1 / 5))); do
    if api_ok && panel_ok && { [ "$usa_erp" = 0 ] || erp_ok; }; then return 0; fi
    sleep 5
  done
  return 1
}
PRIMERA=$(( ESPERA < 90 ? ESPERA : 90 ))
if ! espera_servicios "$PRIMERA"; then
  if ! api_ok || ! panel_ok; then
    reparar_puertos
  fi
  if [ "$usa_erp" = 1 ] && ! erp_ok; then
    reparar_erp || true
  fi
  espera_servicios $(( ESPERA - PRIMERA > 30 ? ESPERA - PRIMERA : 30 )) || true
fi
resumen
api_ok && panel_ok
