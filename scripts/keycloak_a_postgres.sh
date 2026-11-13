#!/usr/bin/env bash
# Pasa Keycloak (el inicio de sesión de Jarvis) del modo desarrollo con base H2 al MODO PRODUCCIÓN con PostgreSQL, SIN perder usuarios, contraseñas ni ajustes.
#
# Qué hace, en este orden, y se detiene SIN CAMBIAR NADA si algo falla:
#   1. Copia de seguridad de los datos actuales (copias/keycloak-postgres-FECHA/h2). Los datos viejos NO se tocan nunca: quedan en su volumen por si hay que volver.
#   2. Exporta el realm «cerebro» CON sus usuarios (copias/keycloak-postgres-FECHA/export) y comprueba que la exportación trae usuarios.
#   3. Crea la contraseña de la base de Keycloak si no hay una (la genera el script; no la tienes que escribir ni ver) y fija la versión exacta de Keycloak.
#   4. Activa despliegue/docker-compose.keycloak-postgres.yml en el .env (COMPOSE_FILE) y arranca Keycloak con PostgreSQL importando esa exportación.
#   5. Comprueba que responde, que el administrador entra y que están los usuarios. Si algo no cuadra, vuelve atrás solo.
#
# Uso:  ./scripts/keycloak_a_postgres.sh            (hacer el cambio)
#       ./scripts/keycloak_a_postgres.sh --deshacer  (volver al modo anterior; los usuarios creados DESPUÉS del cambio no estarán en el volumen viejo)
# Mientras dura (unos 3-5 minutos) nadie puede iniciar sesión en Jarvis. No lo ejecutes mientras «Preparar la oferta» está trabajando: el panel pediría iniciar sesión de nuevo.
set -euo pipefail
cd "$(dirname "$0")/.."

FICHERO="despliegue/docker-compose.keycloak-postgres.yml"
ENV=".env"
RUTA_H2=/opt/keycloak/data/h2
URL="http://localhost:8080"

[ -f "$ENV" ] || { echo "No encuentro el fichero .env en $(pwd): ejecuta el script desde la carpeta del proyecto." >&2; exit 1; }

valor_env() { grep -E "^$1=" "$ENV" | tail -1 | cut -d= -f2- || true; }
poner_env() {                       # poner_env CLAVE VALOR: cambia o añade la línea sin tocar el resto
  local tmp; tmp="$(mktemp)"
  grep -v -E "^$1=" "$ENV" > "$tmp" || true
  printf '%s=%s\n' "$1" "$2" >> "$tmp"
  cat "$tmp" > "$ENV"; rm -f "$tmp"
}
con_fichero() { case ":$(valor_env COMPOSE_FILE):" in *":$FICHERO:"*) return 0;; *) return 1;; esac; }
sin_fichero() {                     # el COMPOSE_FILE de ahora sin el fichero de Postgres
  local c; c="$(valor_env COMPOSE_FILE)"
  printf '%s' "$c" | tr ':' '\n' | grep -v -x -F "$FICHERO" | paste -sd: -
}
esperar() {                         # esperar SEGUNDOS: hasta que el realm responda
  local n=$(( $1 / 3 ))
  for _ in $(seq 1 "$n"); do
    curl -fsS -o /dev/null "$URL/realms/cerebro" 2>/dev/null && return 0
    sleep 3
  done
  return 1
}

if [ "${1:-}" = "--deshacer" ]; then
  con_fichero || { echo "Keycloak no está en el modo con PostgreSQL: no hay nada que deshacer."; exit 0; }
  nuevo="$(sin_fichero)"
  [ -n "$nuevo" ] || nuevo="docker-compose.yml"
  poner_env COMPOSE_FILE "$nuevo"
  echo "→ Volviendo al modo anterior (datos del volumen viejo, los de antes del cambio)"
  docker compose up -d --force-recreate keycloak >/dev/null
  esperar 180 && echo "Hecho: Keycloak responde en el modo anterior. La base PostgreSQL y su volumen siguen ahí por si quieres volver a intentarlo." \
    || { echo "Keycloak tarda en responder: mira  docker compose logs keycloak --tail 30" >&2; exit 1; }
  exit 0
fi

if con_fichero; then
  echo "Keycloak ya funciona en modo producción con PostgreSQL: no hay nada que hacer."
  exit 0
fi
ctr="$(docker compose ps -aq keycloak 2>/dev/null | head -1 || true)"
[ -n "$ctr" ] || { echo "Keycloak todavía no existe. Arranca primero la plataforma con ./scripts/iniciar.sh y vuelve a ejecutar esto." >&2; exit 1; }
docker inspect "$ctr" --format '{{range .Mounts}}{{.Destination}}{{"\n"}}{{end}}' | grep -qx "$RUTA_H2" \
  || { echo "Keycloak aún no conserva sus datos en un volumen: ejecuta antes ./scripts/keycloak_conservar.sh" >&2; exit 1; }

fecha="$(date +%Y-%m-%d_%H%M)"
copia="copias/keycloak-postgres-$fecha"
export_dir="$copia/export"
env_antes="$ENV.antes-keycloak-postgres"
cp -p "$ENV" "$env_antes"

volver() {
  echo >&2
  echo "No se ha podido completar el cambio. Dejo Keycloak como estaba: tus usuarios NO se han perdido." >&2
  cat "$env_antes" > "$ENV"
  docker compose up -d --force-recreate keycloak >/dev/null 2>&1 || docker compose start keycloak >/dev/null 2>&1 || true
  [ -d "$copia" ] && echo "Copia de seguridad: $copia" >&2
  exit 1
}
trap volver ERR

echo "→ Parando Keycloak (para copiar y exportar sus datos enteros)"
docker compose stop keycloak >/dev/null
mkdir -p "$copia/h2" "$export_dir"
echo "→ Copia de seguridad de los datos actuales en $copia/h2"
docker cp "$ctr:$RUTA_H2/." "$copia/h2"
[ -n "$(ls -A "$copia/h2")" ] || { echo "La copia está vacía: no sigo." >&2; volver; }

echo "→ Exportando el realm «cerebro» con sus usuarios"
chmod 777 "$export_dir"
docker compose run --rm --no-deps -v "$(pwd)/$export_dir:/export" keycloak export --dir /export --realm cerebro --users realm_file >/dev/null 2>"$copia/export.log" \
  || { echo "La exportación ha fallado (detalles en $copia/export.log)." >&2; tail -5 "$copia/export.log" >&2; volver; }
fichero_realm="$(ls "$export_dir"/*realm*.json 2>/dev/null | grep -v -- '-users-' | head -1 || true)"
[ -n "$fichero_realm" ] && [ -s "$fichero_realm" ] || { echo "No ha salido el fichero del realm: no sigo." >&2; volver; }
usuarios="$(grep -c '"username"' "$fichero_realm" || true)"
[ "${usuarios:-0}" -ge 1 ] || { echo "La exportación no trae ningún usuario: no sigo." >&2; volver; }
echo "  Exportados $usuarios usuarios (incluidas las cuentas de servicio)."

version="$(docker compose run --rm --no-deps keycloak --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || true)"
if [ -n "$version" ]; then
  poner_env KEYCLOAK_IMAGEN "quay.io/keycloak/keycloak:$version"
  echo "→ Versión de Keycloak fijada a $version (una actualización futura será una decisión tuya)"
else
  echo "  (No he podido leer la versión de Keycloak: se queda en «latest». Conviene fijarla más adelante en KEYCLOAK_IMAGEN del .env.)"
fi

if [ -z "$(valor_env KEYCLOAK_DB_PASSWORD)" ] || [ "$(valor_env KEYCLOAK_DB_PASSWORD)" = "cambia-esto" ]; then
  echo "→ Creando la contraseña de la base de Keycloak (la guarda el script en el .env; no hace falta que la veas)"
  poner_env KEYCLOAK_DB_PASSWORD "$(head -c 32 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 32)"
fi
poner_env KEYCLOAK_IMPORT_DIR "./$export_dir"
actual="$(valor_env COMPOSE_FILE)"
poner_env COMPOSE_FILE "${actual:-docker-compose.yml}:$FICHERO"

echo "→ Arrancando Keycloak en modo producción con PostgreSQL (la primera vez tarda: prepara su arranque optimizado)"
docker compose up -d keycloak-db >/dev/null
docker compose up -d --force-recreate keycloak >/dev/null
esperar 360 || { echo "Keycloak no responde tras el cambio (docker compose logs keycloak --tail 40)." >&2; volver; }

echo "→ Comprobando que el administrador entra y que están los usuarios"
clave="$(valor_env KEYCLOAK_ADMIN_PASSWORD)"
token="$(curl -fsS -d "client_id=admin-cli" -d "username=admin" --data-urlencode "password=$clave" -d "grant_type=password" "$URL/realms/master/protocol/openid-connect/token" 2>/dev/null \
         | sed -n 's/.*"access_token":"\([^"]*\)".*/\1/p' || true)"
if [ -n "$token" ]; then
  cuenta="$(curl -fsS -H "Authorization: Bearer $token" "$URL/admin/realms/cerebro/users/count" 2>/dev/null || echo 0)"
  echo "  Usuarios en el Keycloak nuevo: $cuenta (exportados: $usuarios)"
  [ "${cuenta:-0}" -ge 1 ] || { echo "El Keycloak nuevo no tiene usuarios: vuelvo atrás." >&2; volver; }
else
  echo "  No he podido entrar como administrador (la contraseña del .env puede ser otra): lo compruebo solo con que el realm responde. Entra tú en $URL y mira Usuarios."
fi
trap - ERR
rm -f "$env_antes"
echo
echo "Listo: Keycloak funciona ya en modo producción con PostgreSQL y conserva sus usuarios."
echo "  · Copia de seguridad y exportación: $copia  (contienen contraseñas cifradas: no las compartas)"
echo "  · Los datos viejos siguen en el volumen anterior por si quieres volver:  ./scripts/keycloak_a_postgres.sh --deshacer"
echo "  · Prueba ahora a iniciar sesión en Jarvis."
