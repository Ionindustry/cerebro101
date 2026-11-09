#!/usr/bin/env bash
# Cambia la contraseña del administrador de Keycloak por una nueva generada al azar.
#
# Cuándo: si la contraseña se ha visto en un chat, una captura o un correo; o cada cierto tiempo. NO hace falta pegarla en ningún sitio: este script la genera, la pone en Keycloak y la guarda en el .env
# (permisos 600). Se muestra UNA vez por pantalla por si quieres anotarla en tu gestor de contraseñas. No la compartas con nadie ni la pegues en un chat.
#
# Uso:  ./scripts/keycloak_clave_admin.sh
# Requiere Keycloak en marcha y que conserve sus datos (./scripts/keycloak_conservar.sh): si no, al recrearlo volvería la contraseña antigua.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] || { echo "Falta el fichero .env" >&2; exit 1; }

RUTA=/opt/keycloak/data/h2
ctr="$(docker compose ps -q keycloak | head -1 || true)"
[ -n "$ctr" ] || { echo "Keycloak no está en marcha: docker compose up -d keycloak" >&2; exit 1; }
if ! docker inspect "$ctr" --format '{{range .Mounts}}{{.Destination}}{{"\n"}}{{end}}' | grep -qx "$RUTA"; then
  echo "Keycloak todavía no conserva sus datos: ejecuta antes  ./scripts/keycloak_conservar.sh" >&2
  exit 1
fi

nueva="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"

echo "→ Cambiando la contraseña en Keycloak"
export NUEVA="$nueva"          # va por el entorno («-e NUEVA» sin valor): así no aparece en la lista de procesos ni en ningún registro de comandos
docker compose exec -T -e NUEVA keycloak bash -c '
  set -e
  KCADM=/opt/keycloak/bin/kcadm.sh
  CFG=$(mktemp)
  trap "rm -f $CFG" EXIT
  $KCADM config credentials --config "$CFG" --server http://localhost:8080 --realm master --user admin --password "$KC_BOOTSTRAP_ADMIN_PASSWORD" >/dev/null
  $KCADM set-password --config "$CFG" -r master --username admin --new-password "$NUEVA"
'

echo "→ Guardándola en .env"
python3 - "$nueva" <<'PY'
import os, re, sys
nueva = sys.argv[1]
ruta = ".env"
t = open(ruta, encoding="utf-8").read()
if re.search(r"^KEYCLOAK_ADMIN_PASSWORD=.*$", t, re.M):
    t = re.sub(r"^KEYCLOAK_ADMIN_PASSWORD=.*$", lambda _: f"KEYCLOAK_ADMIN_PASSWORD={nueva}", t, count=1, flags=re.M)
else:
    t += f"\nKEYCLOAK_ADMIN_PASSWORD={nueva}\n"
tmp = ruta + ".tmp"
open(tmp, "w", encoding="utf-8").write(t)
os.chmod(tmp, 0o600)
os.replace(tmp, ruta)
PY
echo
echo "Hecho. La nueva contraseña del administrador de Keycloak (usuario «admin») es:"
echo "  $nueva"
echo "Anótala ahora en tu gestor de contraseñas: no se vuelve a mostrar (queda en .env). NO la compartas ni la pegues en un chat."
