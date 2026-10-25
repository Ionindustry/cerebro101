"""Descarga las voces de Piper (voz de salida de Jarvis) en servicios/voz/voces/: castellano (davefx) y catalán (upc_ona).

    python3 scripts/voces_descargar.py            # las dos
    python3 scripts/voces_descargar.py --solo es  # solo castellano

Vienen de https://huggingface.co/rhasspy/piper-voices (licencia abierta de cada voz en su carpeta). Cada una son dos ficheros: el modelo (.onnx, unos
60 MB) y su configuración (.onnx.json). Si ya están descargadas no se vuelven a bajar. Después: docker compose restart voz
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

DESTINO = Path(__file__).resolve().parent.parent / "servicios" / "voz" / "voces"
BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main"
VOCES = {
    "es": "es/es_ES/davefx/medium/es_ES-davefx-medium",
    "ca": "ca/ca_ES/upc_ona/medium/ca_ES-upc_ona-medium",
}
MINIMO_ONNX = 5_000_000       # un modelo de voz pesa decenas de MB; menos es una página de error


def descargar(url: str, destino: Path) -> int:
    tmp = destino.with_suffix(destino.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "Cerebro101-voces/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        hecho = 0
        while True:
            trozo = r.read(1 << 20)
            if not trozo:
                break
            f.write(trozo)
            hecho += len(trozo)
            if total:
                print(f"\r  {destino.name}: {hecho * 100 // total} %", end="", flush=True)
    tmp.replace(destino)
    print(f"\r  {destino.name}: {hecho / 1e6:.1f} MB        ")
    return hecho


def bajar_voz(idioma: str) -> bool:
    ruta = VOCES[idioma]
    nombre = ruta.rsplit("/", 1)[1]
    onnx, config = DESTINO / f"{nombre}.onnx", DESTINO / f"{nombre}.onnx.json"
    if onnx.exists() and onnx.stat().st_size >= MINIMO_ONNX and config.exists():
        print(f"{idioma}: ya está ({nombre})")
        return True
    print(f"{idioma}: descargando {nombre}…")
    try:
        descargar(f"{BASE}/{ruta}.onnx.json", config)
        json.loads(config.read_text(encoding="utf-8"))            # que sea un JSON de verdad
        if descargar(f"{BASE}/{ruta}.onnx", onnx) < MINIMO_ONNX:
            raise ValueError("el modelo descargado es demasiado pequeño")
    except (urllib.error.URLError, OSError, ValueError) as e:
        print(f"  FALLA: {e}")
        for f in (onnx, config):
            f.unlink(missing_ok=True)
        return False
    return True


def main() -> int:
    a = argparse.ArgumentParser()
    a.add_argument("--solo", choices=sorted(VOCES), help="descargar solo esta voz")
    r = a.parse_args()
    DESTINO.mkdir(parents=True, exist_ok=True)
    ok = [bajar_voz(i) for i in ([r.solo] if r.solo else sorted(VOCES))]
    print("\nListo. Reinicia la voz: docker compose restart voz" if all(ok) else "\nAlguna voz no se ha podido descargar: revisa la conexión y repite.")
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(main())
