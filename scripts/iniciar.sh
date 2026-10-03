#!/usr/bin/env bash
# Arranca el Cerebro 101.cat en el servidor local.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] || { echo "Falta .env: copia .env.example a .env y rellénalo."; exit 1; }
command -v nvidia-smi >/dev/null && nvidia-smi --query-gpu=name,memory.total --format=csv || echo "Aviso: no se detecta tarjeta NVIDIA"
docker compose up -d --build postgres redis ollama
./scripts/cargar_modelos.sh
docker compose up -d --build
echo "Panel de Jarvis:  http://localhost:3000"
echo "API del Cerebro:  http://localhost:8000/docs"
echo "Registro (Langfuse): http://localhost:3001"
