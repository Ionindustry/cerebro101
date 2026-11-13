#!/usr/bin/env bash
# Deja una tarifa de proveedor (Excel o CSV) en la carpeta que vigila el sistema: /datos/tarifas/<proveedor>/ (en el volumen de datos de Docker).
# A la mañana siguiente (o al pulsar «Comprobar ahora» en Jarvis → Precios) se prepara una propuesta con los cambios; NO se carga nada en el ERP hasta que Dirección lo firma.
#
# Uso:  ./scripts/tarifa_subir.sh <id-del-proveedor> /ruta/a/la_tarifa.xlsx
#   · <id-del-proveedor> es el «id» que pusiste en config/tarifas_auto.yaml (por ejemplo: milesight).
#   · En WSL, los ficheros de Windows están en /mnt/c/Users/TU_USUARIO/Downloads/...
set -euo pipefail
cd "$(dirname "$0")/.."
[ $# -eq 2 ] || { echo "Uso: $0 <id-del-proveedor> /ruta/a/la_tarifa.xlsx" >&2; exit 1; }
id="$1"; fichero="$2"
[[ "$id" =~ ^[a-z0-9][a-z0-9-]{1,39}$ ]] || { echo "El id «$id» no vale: minúsculas, números y guiones." >&2; exit 1; }
[ -f "$fichero" ] || { echo "No encuentro el fichero: $fichero" >&2; exit 1; }
case "${fichero,,}" in *.xlsx|*.csv) ;; *) echo "Solo se admiten tarifas .xlsx o .csv." >&2; exit 1;; esac
nombre="$(date +%Y%m%d-%H%M)-$(basename "$fichero")"
docker compose exec -T api mkdir -p "/datos/tarifas/$id"
docker compose cp "$fichero" "api:/datos/tarifas/$id/$nombre"
echo "Hecho: $fichero → /datos/tarifas/$id/$nombre"
echo "Se mirará en la próxima comprobación diaria; para verlo ya: Jarvis → Precios → Tarifas de proveedores → «Comprobar ahora»."
