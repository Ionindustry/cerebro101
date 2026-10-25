#!/bin/sh
# Arranque del servicio de voz. Las librerías CUDA 12 (cuBLAS) y cuDNN 9 se instalan con pip (paquetes nvidia-*), que las deja dentro de
# site-packages; CTranslate2 las busca con el cargador del sistema, así que hay que añadir esas carpetas a LD_LIBRARY_PATH ANTES de arrancar Python.
RUTAS=$(python - <<'PY'
import importlib.util
rutas = []
for m in ("nvidia.cublas.lib", "nvidia.cudnn.lib"):
    try:
        espec = importlib.util.find_spec(m)
    except ModuleNotFoundError:
        continue
    if espec is not None:
        rutas += list(espec.submodule_search_locations or [])
print(":".join(rutas))
PY
)
export LD_LIBRARY_PATH="${RUTAS}${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
echo "voz: LD_LIBRARY_PATH=${LD_LIBRARY_PATH:-(vacío)}"
exec uvicorn servidor:app --host 0.0.0.0 --port 8100
