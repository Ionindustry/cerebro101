#!/usr/bin/env bash
# Instala Frappe CRM en el ERPNext de este proyecto. Idempotente.
#
#   ./scripts/erpnext_crm.sh instalar [--ref RAMA_O_ETIQUETA]    construye la imagen, la activa y instala las apps en el sitio
#   ./scripts/erpnext_crm.sh estado                               qué versión hay y si responde
#
# Qué hace: construye cerebro-erpnext-crm (erpnext/Dockerfile.crm: la imagen oficial + las dos apps), pone ERPNEXT_IMAGEN en el .env,
# recrea los contenedores del ERP con esa imagen (los datos están en volúmenes y no se tocan), instala las apps en el sitio,
# migra y enlaza los ficheros estáticos. Hace antes una copia de la base de ERPNext. Frappe CRM queda en  http(s)://<ERP>/crm
# Necesita acceso a github.com y a los registros de npm y PyPI durante la construcción (unos 2 GB de descarga y 5 GB de disco).
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] || { echo "Falta .env"; exit 1; }
ERP=(docker compose -f erpnext/docker-compose.yml --env-file .env)
valor() { { grep -E "^$1=" .env || true; } | head -1 | cut -d= -f2- | sed 's/[[:space:]]#.*$//'; }    # una clave ausente da cadena vacía, no error
fijar() { if grep -qE "^$1=" .env; then sed -i -E "s|^$1=.*|$1=$2|" .env; else printf '%s=%s\n' "$1" "$2" >> .env; fi; }
paso() { printf '\n\033[1m→ %s\033[0m\n' "$*"; }
SITIO="$(valor ERPNEXT_SITE)"; SITIO="${SITIO:-erp.101.cat}"
VERSION="$(valor ERPNEXT_VERSION)"; VERSION="${VERSION:-v16.37.0}"
IMAGEN="cerebro-erpnext-crm:$VERSION"
bench() { docker exec -u frappe -w /home/frappe/frappe-bench erpnext-backend-1 bench "$@"; }

estado() {
  docker exec erpnext-backend-1 bench --site "$SITIO" list-apps 2>/dev/null | tail -6 || echo "ERPNext no está en marcha"
  local c; c="$(curl -s -o /dev/null -m 15 -w '%{http_code}' -H "Host: $SITIO" http://127.0.0.1:8081/crm || true)"
  case "$c" in 200|302|403) echo "CRM: responde ($c; sin sesión es normal que pida iniciar sesión)";; *) echo "CRM: NO responde ($c)";; esac
}

instalar() {
  local ref="${CRM_REF:-v1.87.0}" a; while [ $# -gt 0 ]; do case "$1" in --ref) ref="$2"; shift 2;; *) echo "Opción desconocida: $1"; exit 2;; esac; done
  docker ps --format '{{.Names}}' | grep -qx erpnext-db-1 || { echo "ERPNext no está en marcha: docker compose -f erpnext/docker-compose.yml --env-file .env up -d"; exit 1; }
  paso "Copia de seguridad de la base de ERPNext (por si hubiera que volver atrás)"
  mkdir -p copias; local copia="copias/erpnext-antes-crm-$(date +%Y%m%d-%H%M).sql.gz"
  docker exec -e MYSQL_PWD="$(valor ERPNEXT_DB_ROOT_PASSWORD)" erpnext-db-1 mariadb-dump -uroot --all-databases --single-transaction --routines | gzip > "$copia"
  echo "  $copia"
  paso "Construyendo la imagen $IMAGEN (la primera vez tarda 10-20 minutos)"
  local dockerfile="erpnext/Dockerfile.crm"; [ -f erpnext/Dockerfile.crm.local ] && dockerfile="erpnext/Dockerfile.crm.local"
  docker build ${CRM_BUILD_ARGS:-} --build-arg "ERPNEXT_VERSION=$VERSION" --build-arg "CRM_REF=$ref" -f "$dockerfile" -t "$IMAGEN" erpnext/
  paso "Activando la imagen en el ERP (los datos no se tocan)"
  fijar ERPNEXT_IMAGEN "$IMAGEN"
  "${ERP[@]}" up -d --force-recreate backend frontend queue-short queue-long scheduler websocket configurator
  for _ in $(seq 1 60); do curl -fsS -m 5 -o /dev/null -H "Host: $SITIO" http://127.0.0.1:8081/api/method/ping 2>/dev/null && break; sleep 5; done
  paso "Instalando crm en el sitio $SITIO"
  for app in $(docker exec erpnext-backend-1 ls apps | grep -E "^(whatsapp|crm)$" | sort -r); do   # whatsapp antes que crm si existe
    bench --site "$SITIO" list-apps 2>/dev/null | grep -q "^$app " && echo "  $app ya instalada" || bench --site "$SITIO" install-app "$app"
  done
  bench --site "$SITIO" migrate
  # los ficheros estáticos (JS y CSS) de CRM ya están en la imagen: se compilaron al construirla
  bench --site "$SITIO" clear-cache
  "${ERP[@]}" restart backend frontend queue-short queue-long scheduler websocket >/dev/null
  for _ in $(seq 1 60); do curl -fsS -m 5 -o /dev/null -H "Host: $SITIO" http://127.0.0.1:8081/api/method/ping 2>/dev/null && break; sleep 3; done
  paso "Resultado"; estado
  echo; echo "Entra en http://localhost:8081/crm (usuario Administrator, contraseña ERPNEXT_ADMIN_PASSWORD del .env)."
  echo "Commit de las apps: $(docker exec erpnext-backend-1 cat apps/crm/.commit apps/whatsapp/.commit 2>/dev/null | tr '\n' ' ')"
}

case "${1:-}" in
  instalar) shift; instalar "$@";;
  estado) estado;;
  *) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 2;;
esac
