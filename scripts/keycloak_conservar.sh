#!/usr/bin/env bash
# Hace que Keycloak (el inicio de sesión de Jarvis) CONSERVE sus usuarios y ajustes cuando se recrea el contenedor.
#
# Hasta ahora Keycloak (modo desarrollo) guardaba sus datos dentro del contenedor: al recrearlo (actualizar la imagen, `docker compose up --force-recreate`…) se perdían los usuarios.
# Ahora tiene un volumen propio (keycloak-datos). Este script lo estrena SIN perder lo que ya hay: para Keycloak, copia sus datos actuales (también quedan en copias/keycloak-FECHA/),
# crea el contenedor nuevo con el volumen, vuelca los datos en él y lo arranca. Se puede ejecutar las veces que haga falta: si ya tiene el volumen, no hace nada.
#
# Uso:  ./scripts/keycloak_conservar.sh
# Lo llaman también iniciar.sh y arrancar.sh antes de levantar los servicios, para que nadie pierda los usuarios por arrancar sin haberlo pasado.
set -euo pipefail
cd "$(dirname "$0")/.."

RUTA=/opt/keycloak/data/h2
ctr="$(docker compose ps -aq keycloak 2>/dev/null | head -1 || true)"

if [ -z "$ctr" ]; then
  echo "Keycloak todavía no existe: se creará ya con su volumen. Nada que conservar."
  exit 0
fi
if docker inspect "$ctr" --format '{{range .Mounts}}{{.Destination}}{{"\n"}}{{end}}' | grep -qx "$RUTA"; then
  echo "Keycloak ya conserva sus datos en un volumen: no hay nada que hacer."
  exit 0
fi

copia="copias/keycloak-$(date +%Y-%m-%d_%H%M)"
volver() {
  echo >&2
  echo "No se ha podido completar el cambio. Arranco Keycloak otra vez como estaba y NO se ha perdido nada." >&2
  [ -d "$copia/h2" ] && echo "Hay una copia de sus datos en: $copia/h2" >&2
  docker compose start keycloak >/dev/null 2>&1 || true
  exit 1
}
trap volver ERR

echo "→ Parando Keycloak (para copiar sus datos enteros)"
docker compose stop keycloak >/dev/null
mkdir -p "$copia"
echo "→ Copia de seguridad de los datos actuales en $copia/h2"
docker cp "$ctr:$RUTA/." "$copia/h2"
[ -n "$(ls -A "$copia/h2")" ] || { echo "La copia está vacía: no sigo." >&2; volver; }

echo "→ Creando Keycloak con su volumen"
docker compose up -d --no-start keycloak >/dev/null
nuevo="$(docker compose ps -aq keycloak | head -1)"
[ -n "$nuevo" ] || { echo "No se ha creado el contenedor nuevo." >&2; volver; }
docker cp -a "$copia/h2/." "$nuevo:$RUTA/"
trap - ERR
docker compose up -d keycloak >/dev/null

echo "→ Esperando a que Keycloak responda"
for _ in $(seq 1 40); do
  if curl -fsS -o /dev/null http://localhost:8080/realms/cerebro 2>/dev/null; then
    echo "Listo: Keycloak responde y ahora conserva sus datos. La copia de seguridad queda en $copia/h2"
    exit 0
  fi
  sleep 3
done
echo "Keycloak tarda en responder. Comprueba con:  docker compose ps keycloak   y   docker compose logs keycloak --tail 30" >&2
echo "Si hubiera perdido los usuarios, la copia está en $copia/h2" >&2
exit 1
