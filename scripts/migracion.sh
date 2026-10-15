#!/usr/bin/env bash
# Traslada TODO el stack (datos incluidos) de una máquina a otra: exporta en el origen, importa en el destino.
#
#   ORIGEN :  ./scripts/migracion.sh exportar [carpeta] [--sin-trazas]   → migracion-AAAAMMDD-HHMM.tar.gz (+ .sha256)
#             (--sin-trazas deja fuera ClickHouse y MinIO, que son lo que más pesa; Langfuse conserva su configuración pero no el historial)
#   DESTINO:  git clone … && cd cerebro101
#             scp origen:cerebro101/.env .env                       (las claves van por un canal seguro, NO dentro del paquete)
#             ./scripts/migracion.sh importar migracion-….tar.gz --confirmar
#
# Qué lleva: base del Cerebro (aprobaciones, registro de acciones, conocimiento), Langfuse (base, ClickHouse y MinIO),
# ERPNext (base y ficheros del sitio) y el volumen «datos» (documentos de conocimiento y cola de constancia).
# Qué NO lleva: el .env (secretos: hay que llevarlo aparte y el destino lo necesita IGUAL, porque ERPNext y las bases guardan
# esas contraseñas), los modelos de Ollama (se descargan: scripts/cargar_modelos.sh), las sesiones del panel ni los usuarios
# de Keycloak en modo desarrollo (en producción, Keycloak tiene su propia base: añadidla con --keycloak si existe).
#
# «importar» SOBRESCRIBE las bases y volúmenes del destino con los del paquete: exige --confirmar.
set -euo pipefail
cd "$(dirname "$0")/.."

orden="${1:-}"; [ $# -gt 0 ] && shift || true
PROYECTO="$(docker compose config --format json 2>/dev/null | python3 -c 'import sys,json;print(json.load(sys.stdin)["name"])')"
ERP=(docker compose -f erpnext/docker-compose.yml --env-file .env)
valor() { grep -E "^$1=" .env | head -1 | cut -d= -f2- | sed 's/[[:space:]]#.*$//'; }
paso() { printf '\n\033[1m→ %s\033[0m\n' "$*"; }
esperar() { # descripción comando…
  local d="$1"; shift; for _ in $(seq 1 60); do "$@" >/dev/null 2>&1 && return 0; sleep 3; done; echo "No responde: $d"; exit 1
}
volumen_a_tar() { docker run --rm -v "$1:/d:ro" -v "$2:/c" alpine tar czf "/c/$3" -C /d .; }
tar_a_volumen() { docker run --rm -v "$1:/d" -v "$2:/c:ro" alpine sh -c "find /d -mindepth 1 -delete; tar xzf /c/$3 -C /d"; }

exportar() {
  [ -f .env ] || { echo "Falta .env"; exit 1; }
  local destino="." a; for a in "$@"; do case "$a" in --sin-trazas) export COPIA_SIN_TRAZAS=1;; *) destino="$a";; esac; done
  local marca tmp; marca="$(date +%Y%m%d-%H%M)"; mkdir -p "$destino"; destino="$(cd "$destino" && pwd)"
  tmp="$(mktemp -d "$destino/.migracion.XXXXXX")"; trap "rm -rf '$tmp'" EXIT
  paso "Copia consistente de las bases y volúmenes (se paran Langfuse y ClickHouse unos segundos)"
  ./scripts/copia_seguridad.sh "$tmp/datos-stack" --parar
  paso "Volumen «datos» (documentos de conocimiento, cola de constancia)"
  volumen_a_tar "${PROYECTO}_datos" "$tmp/datos-stack" datos.tar.gz
  {
    echo "fecha=$(date -Is)"; echo "proyecto=$PROYECTO"; echo "commit=$(git rev-parse HEAD 2>/dev/null || echo desconocido)"
    echo "erpnext=$(docker inspect -f '{{.Config.Image}}' erpnext-backend-1 2>/dev/null || echo no)"
    echo "contenido=$(cd "$tmp/datos-stack" && ls *.gz | tr '\n' ' ')"
  } > "$tmp/datos-stack/INFO.txt"
  ( cd "$tmp/datos-stack" && sha256sum *.gz INFO.txt > SHA256SUMS )
  tar czf "$destino/migracion-$marca.tar.gz" -C "$tmp" datos-stack
  ( cd "$destino" && sha256sum "migracion-$marca.tar.gz" > "migracion-$marca.tar.gz.sha256" )
  paso "Listo"; ls -lh "$destino/migracion-$marca.tar.gz"
  cat <<NOTA

Paquete: $destino/migracion-$marca.tar.gz  (suma de control en el .sha256)
Llévalo al destino junto con el .env, que NO está dentro:  scp .env usuario@destino:cerebro101/.env
El paquete contiene datos de la empresa: trátalo como confidencial y bórralo del origen y del destino cuando acabes.
NOTA
}

importar() {
  local paquete="" confirmar=0 a
  for a in "$@"; do case "$a" in --confirmar) confirmar=1;; *) paquete="$a";; esac; done
  [ -f "$paquete" ] || { echo "Uso: $0 importar paquete.tar.gz --confirmar"; exit 2; }
  [ -f .env ] || { echo "Falta .env: cópialo del origen (scp) antes de importar; ERPNext y las bases guardan esas contraseñas."; exit 1; }
  [ "$confirmar" = 1 ] || { echo "Esto SOBRESCRIBE las bases y volúmenes de este equipo con los del paquete. Repite con --confirmar."; exit 2; }
  if [ -f "$paquete.sha256" ]; then ( cd "$(dirname "$paquete")" && sha256sum -c "$(basename "$paquete").sha256" ) || { echo "La suma de control no coincide: el paquete está dañado."; exit 1; }
  else echo "Aviso: no hay $paquete.sha256; no se puede comprobar la integridad."; fi
  local tmp; tmp="$(mktemp -d)"; trap "rm -rf '$tmp'" EXIT
  tar xzf "$paquete" -C "$tmp"; local d="$tmp/datos-stack"
  ( cd "$d" && sha256sum -c SHA256SUMS >/dev/null ) || { echo "Un fichero del paquete no coincide con SHA256SUMS."; exit 1; }
  cat "$d/INFO.txt"

  paso "Parando los servicios que usan los datos"
  for srv in proxy panel api worker beat langfuse langfuse-worker; do    # uno a uno: si falta alguno (p. ej. el proxy sin producción) no impide parar el resto
    docker compose stop "$srv" >/dev/null 2>&1 || true
  done
  docker compose up -d postgres langfuse-db langfuse-clickhouse langfuse-minio >/dev/null
  esperar "PostgreSQL" docker compose exec -T postgres pg_isready -U cerebro -d postgres
  esperar "PostgreSQL de Langfuse" docker compose exec -T langfuse-db pg_isready -U langfuse

  restaurar_pg() { # servicio usuario base fichero
    docker compose exec -T "$1" psql -U "$2" -d postgres -v ON_ERROR_STOP=1 -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$3' AND pid<>pg_backend_pid();" >/dev/null
    docker compose exec -T "$1" psql -U "$2" -d postgres -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS $3;" -c "CREATE DATABASE $3 OWNER $2;" >/dev/null
    gunzip -c "$4" | docker compose exec -T "$1" psql -U "$2" -d "$3" -v ON_ERROR_STOP=1 -q >/dev/null
  }
  paso "Base del Cerebro"; restaurar_pg postgres cerebro cerebro "$d/cerebro.sql.gz"
  paso "Base de Langfuse"; restaurar_pg langfuse-db langfuse langfuse "$d/langfuse.sql.gz"
  paso "Permisos de la base del Cerebro (rol de mínimo privilegio con la clave de este .env)"
  docker compose up --force-recreate migraciones 2>&1 | tail -3

  paso "Trazas de Langfuse (ClickHouse y MinIO)"
  docker compose stop langfuse-clickhouse langfuse-minio >/dev/null
  for v in clickhouse minio; do
    if [ -f "$d/$v.tar.gz" ]; then tar_a_volumen "${PROYECTO}_langfuse-$v" "$d" "$v.tar.gz"
    else echo "  (el paquete no trae $v: se conserva lo que haya en este equipo; el historial de trazas puede no coincidir)"; fi
  done

  paso "Volumen «datos»"
  [ -f "$d/datos.tar.gz" ] && tar_a_volumen "${PROYECTO}_datos" "$d" datos.tar.gz

  if [ -f "$d/erpnext.sql.gz" ]; then
    paso "ERPNext (base y ficheros del sitio)"
    local clave; clave="$(valor ERPNEXT_DB_ROOT_PASSWORD)"
    docker network inspect cerebro >/dev/null 2>&1 || docker network create cerebro >/dev/null
    "${ERP[@]}" stop backend frontend queue-short queue-long scheduler websocket >/dev/null 2>&1 || true
    "${ERP[@]}" up -d db >/dev/null
    esperar "MariaDB de ERPNext" docker exec -e MYSQL_PWD="$clave" erpnext-db-1 mariadb -uroot -e "SELECT 1"
    gunzip -c "$d/erpnext.sql.gz" | docker exec -i -e MYSQL_PWD="$clave" erpnext-db-1 mariadb -uroot
    tar_a_volumen erpnext_sites "$d" erpnext_sitios.tar.gz
    "${ERP[@]}" up -d >/dev/null
  fi

  paso "Arrancando todo"
  docker compose up -d $([ "${MIGRACION_SIN_BUILD:-0}" = 1 ] && echo --no-build)      # SIN_BUILD=1: no reconstruye imágenes (equipos con Docker Hub limitado)
  esperar "la API" curl -fsS -m 5 http://127.0.0.1:8000/salud
  echo; curl -s http://127.0.0.1:8000/salud; echo
  curl -s http://127.0.0.1:8000/salud/constancia; echo
  echo "Importado. Descarga los modelos de Ollama si el destino es nuevo: ./scripts/cargar_modelos.sh"
}

case "$orden" in
  exportar) exportar "$@";;
  importar) importar "$@";;
  *) sed -n '2,19p' "$0" | sed 's/^# \{0,1\}//'; exit 2;;
esac
