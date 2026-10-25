#!/usr/bin/env bash
# Descarga en Ollama los modelos del perfil de hardware elegido (config/modelos.yaml).
set -euo pipefail
cd "$(dirname "$0")/.."
PERFIL="${PERFIL_HARDWARE:-$(grep -E '^PERFIL_HARDWARE=' .env | cut -d= -f2 | cut -d' ' -f1)}"
MODELOS=$(python3 - "$PERFIL" <<'PY'
import sys, yaml
c = yaml.safe_load(open("config/modelos.yaml"))
perfil = c["perfiles"][sys.argv[1] or c["perfil_por_defecto"]]
print(" ".join(sorted({v["modelo"] for v in perfil.values()} | {c["embeddings"]["modelo"]})))
PY
)
for m in $MODELOS; do
  echo "Descargando $m…"
  docker compose exec -T ollama ollama pull "$m" || echo "No se pudo descargar $m: revisa la etiqueta en ollama.com/library"
done
