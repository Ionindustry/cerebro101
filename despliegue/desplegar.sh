#!/usr/bin/env bash
# Instala y mantiene el Cerebro 101.cat en un servidor, con HTTPS.
#
#   ./despliegue/desplegar.sh requisitos
#   ./despliegue/desplegar.sh instalar --dominio 101.cat --correo it@101.cat [opciones]
#   ./despliegue/desplegar.sh estado | actualizar | copia
#
# Opciones de «instalar»:
#   --dominio D        el Cerebro queda en cerebro.D, auth.D, erp.D y trazas.D (deben apuntar a este servidor)
#   --correo C         avisos de certificados y administrador de Langfuse
#   --tls MODO         letsencrypt (por defecto: DNS público y puertos 80/443 abiertos) | interno (intranet)
#   --empresa N --abreviatura XX   completa el asistente de ERPNext (razón social y 2-5 letras)
#   --director E [--nombre N]      primer usuario de dirección (contraseña temporal que se muestra una vez)
#   --sin-gpu          instala sin tarjeta NVIDIA (los modelos irán en CPU: muy lento)
#   --sin-modelos      no descarga los modelos de IA (hacedlo luego con scripts/cargar_modelos.sh)
#   --sin-erp          no instala ERPNext
#   --simular          muestra lo que haría sin hacerlo
#
# Es idempotente: se puede repetir. No sobrescribe contraseñas ya generadas del .env.
set -euo pipefail
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$RAIZ"

# DESPLIEGUE_COMPOSE_EXTRA="-f otro.yml" añade ficheros de compose (pruebas); DESPLIEGUE_SIN_BUILD=1 no reconstruye imágenes
# shellcheck disable=SC2206
EXTRA=(${DESPLIEGUE_COMPOSE_EXTRA:-})
COMPOSE=(docker compose --env-file .env -f docker-compose.yml -f despliegue/docker-compose.produccion.yml "${EXTRA[@]}")
ERP=(docker compose -f erpnext/docker-compose.yml --env-file .env)
BUILD=(--build); [ "${DESPLIEGUE_SIN_BUILD:-0}" = 1 ] && BUILD=(--no-build)

DOMINIO=""; CORREO=""; TLS="letsencrypt"; EMPRESA=""; ABREV=""; DIRECTOR=""; NOMBRE="Dirección General"
SIN_GPU=0; SIN_MODELOS=0; SIN_ERP=0; SIMULAR=0

bien() { printf '  \033[32m✓\033[0m %s\n' "$*"; }
aviso() { printf '  \033[33m!\033[0m %s\n' "$*"; }
falla() { printf '  \033[31m✗\033[0m %s\n' "$*"; }
paso() { printf '\n\033[1m[%s] %s\033[0m\n' "$1" "$2"; }
run() { if [ "$SIMULAR" = 1 ]; then echo "  + $*"; else "$@"; fi; }
valor() { grep -E "^$1=" .env 2>/dev/null | head -1 | cut -d= -f2- | sed 's/[[:space:]]#.*$//'; }

esperar_http() { # url intentos [curl opciones...]
  local url="$1" n="$2"; shift 2
  for _ in $(seq 1 "$n"); do curl -fsS -m 10 -o /dev/null "$@" "$url" 2>/dev/null && return 0; sleep 5; done; return 1
}

requisitos() {
  local fallos=0
  paso "0" "Requisitos del servidor"
  if command -v docker >/dev/null && docker compose version >/dev/null 2>&1; then bien "Docker $(docker version --format '{{.Server.Version}}' 2>/dev/null || echo '?') y Compose v2"; else falla "Hace falta Docker con el plugin Compose v2"; fallos=1; fi
  for c in python3 curl; do command -v "$c" >/dev/null && bien "$c" || { falla "Falta $c"; fallos=1; }; done
  python3 -c "import yaml" 2>/dev/null && bien "python3-yaml (lo usa scripts/cargar_modelos.sh)" || { falla "Falta python3-yaml (apt install python3-yaml)"; fallos=1; }
  local ram_gb disco_gb
  ram_gb=$(awk '/MemTotal/{printf "%d", $2/1048576}' /proc/meminfo); disco_gb=$(df -BG --output=avail "$RAIZ" | tail -1 | tr -dc 0-9)
  [ "$ram_gb" -ge 32 ] && bien "Memoria: ${ram_gb} GB" || aviso "Memoria: ${ram_gb} GB (recomendado 64 GB; con menos, usad el perfil de modelos «pequena»)"
  [ "$disco_gb" -ge 100 ] && bien "Disco libre: ${disco_gb} GB" || aviso "Disco libre: ${disco_gb} GB (recomendado 500 GB o más: modelos, base de datos y copias)"
  if command -v nvidia-smi >/dev/null && nvidia-smi >/dev/null 2>&1; then
    bien "GPU: $(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader | head -1)"
    docker info 2>/dev/null | grep -qi nvidia && bien "Docker con soporte NVIDIA" || { aviso "Docker no muestra el runtime NVIDIA: instalad nvidia-container-toolkit"; [ "$SIN_GPU" = 1 ] || fallos=1; }
  else
    [ "$SIN_GPU" = 1 ] && aviso "Sin GPU (--sin-gpu): los modelos irán en CPU y tardarán minutos por respuesta" || { falla "No se detecta tarjeta NVIDIA (usad --sin-gpu solo para pruebas)"; fallos=1; }
  fi
  for puerto in 80 443; do
    if ss -ltn 2>/dev/null | awk '{print $4}' | grep -qE "[:.]${puerto}$"; then aviso "El puerto $puerto ya está en uso (si es el proxy del Cerebro de una instalación anterior, es normal)"; else bien "Puerto $puerto libre"; fi
  done
  if [ -n "$DOMINIO" ]; then
    local ip_local; ip_local=$(hostname -I 2>/dev/null | awk '{print $1}')
    for h in cerebro auth erp trazas; do
      ip=$(getent hosts "$h.$DOMINIO" 2>/dev/null | awk '{print $1}' | head -1)
      if [ -z "$ip" ]; then [ "$TLS" = letsencrypt ] && { falla "$h.$DOMINIO no resuelve: crea el registro DNS (con TLS letsencrypt es imprescindible)"; fallos=1; } || aviso "$h.$DOMINIO no resuelve (en intranet, añadidlo al DNS interno)"
      else bien "$h.$DOMINIO → $ip${ip_local:+ (este servidor: $ip_local)}"; fi
    done
  fi
  return $fallos
}

verificar() {
  paso "7" "Verificación"
  local k="" ; [ "$TLS" = interno ] && k="-k"
  # shellcheck disable=SC2086
  code() { curl -sS -m 20 -o /dev/null -w '%{http_code}' $k "$@" 2>/dev/null || echo 000; }
  local p; p=$(code "https://$(valor DOM_PANEL)/")
  case "$p" in 200|302|307) bien "Panel https://$(valor DOM_PANEL) responde ($p)";; *) falla "Panel: HTTP $p";; esac
  local iss; iss=$(curl -sS -m 20 $k "https://$(valor DOM_AUTH)/realms/$(valor KEYCLOAK_REALM)/.well-known/openid-configuration" 2>/dev/null | python3 -c "import sys,json;print(json.load(sys.stdin).get('issuer',''))" 2>/dev/null || true)
  [ "$iss" = "https://$(valor DOM_AUTH)/realms/$(valor KEYCLOAK_REALM)" ] && bien "Keycloak: emisor correcto ($iss)" || falla "Keycloak: emisor inesperado «$iss»"
  [ "$(code "https://$(valor DOM_AUTH)/admin/master/console/")" = 403 ] && bien "Consola de administración de Keycloak restringida a IPS_ADMIN desde fuera" || aviso "La consola de Keycloak responde desde aquí (normal si estás dentro de IPS_ADMIN)"
  [ "$(code "https://$(valor DOM_TRAZAS)/api/public/health")" = 200 ] && bien "Langfuse https://$(valor DOM_TRAZAS)" || falla "Langfuse no responde"
  if [ "$SIN_ERP" = 0 ]; then [ "$(code "https://$(valor DOM_ERP)/api/method/ping")" = 200 ] && bien "ERPNext https://$(valor DOM_ERP)" || falla "ERPNext no responde"; fi
  "${COMPOSE[@]}" exec -T api python -c "import json,urllib.request as u;print(json.load(u.urlopen('http://localhost:8000/salud')))" 2>/dev/null | sed 's/^/  API: /' || falla "La API no responde"
  "${COMPOSE[@]}" exec -T api python -c "
import json, urllib.request as u
d = json.load(u.urlopen('http://localhost:8000/salud/modelos', timeout=15))
print('Modelos de IA:', 'todos descargados' if d['ollama'] == 'ok' and not d['faltan'] else ('faltan ' + ', '.join(d['faltan']) + ' (docker compose exec ollama ollama pull …)' if d['ollama'] == 'ok' else 'Ollama no responde'))" 2>/dev/null | sed 's/^/  /' || aviso "No se pudo comprobar los modelos de IA"
  "${COMPOSE[@]}" exec -T api python -c "
import json, urllib.request as u, urllib.error as e
try:
    u.urlopen('http://localhost:8000/salud/constancia', timeout=10); print('Registro de acciones: sin filas pendientes')
except e.HTTPError as x:
    print('✗ Registro de acciones: ' + str(json.load(x)['pendientes']) + ' fila(s) sin volcar a la base (revisa los logs de la API)')" 2>/dev/null | sed 's/^/  /' || aviso "No se pudo comprobar la constancia de acciones"
  "${COMPOSE[@]}" exec -T api python /app/scripts/comprobar_permisos.py 2>/dev/null | tail -1 | sed 's/^/  Base de datos: /' || aviso "No se pudo ejecutar comprobar_permisos.py"
}

instalar() {
  [ -n "$DOMINIO" ] && [ -n "$CORREO" ] || { echo "Faltan --dominio y --correo"; exit 2; }
  if [ -n "$EMPRESA" ] && [ -z "$ABREV" ]; then echo "--empresa necesita también --abreviatura"; exit 2; fi
  requisitos || { echo; falla "Corregid los requisitos marcados con ✗ y repetid."; exit 1; }
  if [ "$SIMULAR" = 1 ]; then
    paso "→" "Simulación: esto es lo que se haría"
    for s in "1 Generar/completar .env con contraseñas aleatorias y las direcciones de $DOMINIO (permisos 600)" \
             "2 Levantar Postgres, Redis y Ollama; descargar los modelos de IA" \
             "3 Levantar API, worker, panel, Langfuse (v3), Keycloak (producción, con su base de datos) y migraciones" \
             "4 ERPNext: instalar${EMPRESA:+, asistente de «$EMPRESA»}, usuarios técnicos y blindaje" \
             "5 Keycloak: direcciones de $DOMINIO${DIRECTOR:+ y primer usuario $DIRECTOR}" \
             "6 Proxy Caddy con HTTPS ($TLS) en 80/443" "7 Verificación"; do echo "  ${s%% *}. ${s#* }"; done
    exit 0
  fi

  paso "1" "Configuración (.env)"
  python3 despliegue/preparar_env.py --dominio "$DOMINIO" --correo "$CORREO" --tls "$TLS" | tail -3

  paso "2" "Base y modelos de IA"
  "${COMPOSE[@]}" up -d "${BUILD[@]}" postgres redis ollama
  [ "$SIN_MODELOS" = 1 ] && aviso "Modelos omitidos (--sin-modelos): ejecutad scripts/cargar_modelos.sh después" || ./scripts/cargar_modelos.sh

  paso "3" "Servicios del Cerebro (sin el proxy todavía)"
  "${COMPOSE[@]}" up -d "${BUILD[@]}" --scale proxy=0
  esperar_http "http://127.0.0.1:8000/salud" 60 && bien "API en marcha" || { falla "La API no arranca: docker compose logs api"; exit 1; }

  if [ "$SIN_ERP" = 0 ]; then
    paso "4" "ERPNext"
    "${ERP[@]}" up -d
    esperar_http "http://127.0.0.1:8081/api/method/ping" 120 && bien "ERPNext responde" || { falla "ERPNext no responde tras 10 minutos: ${ERP[*]} logs create-site"; exit 1; }
    [ -n "$EMPRESA" ] && python3 scripts/erpnext_asistente.py --empresa "$EMPRESA" --abreviatura "$ABREV" || aviso "Asistente de ERPNext pendiente: hacedlo en https://$(valor DOM_ERP) o con scripts/erpnext_asistente.py"
    python3 scripts/erpnext_usuario_tecnico.py --departamento direccion --roles "Sales User,Purchase User,HR User"
    python3 scripts/erpnext_usuario_tecnico.py --departamento finanzas --roles "Accounts User"
    python3 scripts/erpnext_blindar.py
    "${ERP[@]}" restart backend queue-short queue-long >/dev/null
    "${ERP[@]}" exec -T backend bench --site "$(valor ERPNEXT_SITE)" set-config host_name "https://$(valor DOM_ERP)" >/dev/null
    "${COMPOSE[@]}" up -d --no-build --force-recreate --no-deps --scale proxy=0 api worker beat   # leen las claves nuevas
  else
    paso "4" "ERPNext omitido (--sin-erp)"
  fi

  paso "5" "Keycloak"
  esperar_http "http://127.0.0.1:8080/realms/master" 60 && bien "Keycloak responde" || { falla "Keycloak no arranca: docker compose logs keycloak"; exit 1; }
  python3 despliegue/configurar_keycloak.py ${DIRECTOR:+--director "$DIRECTOR" --nombre "$NOMBRE"}

  paso "6" "Proxy con HTTPS ($TLS)"
  "${COMPOSE[@]}" up -d --no-build proxy
  if [ "$TLS" = interno ]; then
    sleep 8; "${COMPOSE[@]}" cp proxy:/data/caddy/pki/authorities/local/root.crt ./caddy-raiz.crt 2>/dev/null \
      && aviso "Certificado raíz de Caddy en ./caddy-raiz.crt: instalad ese fichero como autoridad de confianza en los equipos que usen el Cerebro"
  else
    aviso "Let's Encrypt emite los certificados en el primer acceso; si tarda, mirad: docker compose logs proxy"
  fi
  sleep 10
  verificar

  cat <<RESUMEN

Listo.
  Panel de Jarvis ........ https://$(valor DOM_PANEL)
  Inicio de sesión ....... https://$(valor DOM_AUTH)   (consola de administración: solo desde $(valor IPS_ADMIN))
  ERPNext ................ https://$(valor DOM_ERP)     (usuario Administrator; contraseña: ERPNEXT_ADMIN_PASSWORD en .env)
  Registro de decisiones . https://$(valor DOM_TRAZAS)  (usuario $(valor LANGFUSE_INIT_USER_EMAIL); contraseña: LANGFUSE_INIT_USER_PASSWORD en .env)

Pendiente, a mano:
  1. Firewall: dejad abiertos solo SSH, 80 y 443 (Docker ignora ufw para los puertos publicados; aquí solo se publican 80 y 443):
       ufw allow OpenSSH && ufw allow 80,443/tcp && ufw allow 443/udp && ufw enable
  2. Copias de seguridad cada noche:  0 3 * * *  cd $RAIZ && ./scripts/copia_seguridad.sh --parar   (y llevad la carpeta copias/ fuera del servidor)
  3. Guardad una copia del .env en un gestor de contraseñas: no está en git y sin él no se pueden restaurar los datos.
  4. Claves externas (Jev, Grok, correo…) en el .env; después: docker compose -f docker-compose.yml -f despliegue/docker-compose.produccion.yml up -d api worker beat
RESUMEN
}

orden="${1:-}"; [ $# -gt 0 ] && shift || true
while [ $# -gt 0 ]; do
  case "$1" in
    --dominio) DOMINIO="$2"; shift 2;; --correo) CORREO="$2"; shift 2;; --tls) TLS="$2"; shift 2;;
    --empresa) EMPRESA="$2"; shift 2;; --abreviatura) ABREV="$2"; shift 2;;
    --director) DIRECTOR="$2"; shift 2;; --nombre) NOMBRE="$2"; shift 2;;
    --sin-gpu) SIN_GPU=1; shift;; --sin-modelos) SIN_MODELOS=1; shift;; --sin-erp) SIN_ERP=1; shift;; --simular) SIMULAR=1; shift;;
    *) echo "Opción desconocida: $1"; exit 2;;
  esac
done

case "$orden" in
  requisitos) [ -z "$DOMINIO" ] && [ -f .env ] && DOMINIO="$(valor DOMINIO)" && TLS="$(valor TLS_MODO)"; requisitos;;
  instalar) instalar;;
  estado) [ -f .env ] || { echo "No hay .env: ¿se ha instalado?"; exit 1; }; TLS="$(valor TLS_MODO)"; SIN_ERP=0; "${COMPOSE[@]}" ps; verificar;;
  actualizar) git pull --ff-only; "${COMPOSE[@]}" up -d "${BUILD[@]}"; "${ERP[@]}" up -d; echo "Actualizado. Las migraciones de la base de datos se aplican solas al arrancar.";;
  copia) ./scripts/copia_seguridad.sh "$@";;
  *) sed -n '2,23p' "$0" | sed 's/^# \{0,1\}//'; exit 2;;
esac
