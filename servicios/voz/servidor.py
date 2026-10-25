"""Servicio de voz de Jarvis: voz a texto (faster-whisper) y texto a voz (Piper), todo local.

Whisper usa la tarjeta gráfica (WHISPER_DISPOSITIVO=cuda) si puede. Si las librerías de NVIDIA no están o la tarjeta falla al transcribir
(«libcublas.so.12 is not found»), el servicio pasa solo a la CPU con un modelo más pequeño (WHISPER_MODELO_CPU, por defecto «small») y lo dice en el log:
transcribe más despacio, pero transcribe.
"""
from __future__ import annotations

import logging
import os
import subprocess
import tempfile
import threading
from pathlib import Path

from fastapi import FastAPI, UploadFile
from fastapi.responses import JSONResponse, Response

log = logging.getLogger("voz")
MODELO = os.environ.get("WHISPER_MODELO") or "large-v3-turbo"
DISPOSITIVO = os.environ.get("WHISPER_DISPOSITIVO") or "cuda"
MODELO_CPU = os.environ.get("WHISPER_MODELO_CPU") or "small"
VOCES = {"ca": os.environ.get("PIPER_VOZ_CA", "/voces/ca_ES-upc_ona-medium.onnx"),
         "es": os.environ.get("PIPER_VOZ_ES", "/voces/es_ES-davefx-medium.onnx")}

_estado = {"modelo": MODELO, "dispositivo": DISPOSITIVO, "whisper": None, "alternativa": None}
_cerrojo = threading.Lock()


def _cargar(nombre: str, dispositivo: str):
    from faster_whisper import WhisperModel          # aquí y no arriba: así el servicio arranca (y se prueba) sin el modelo cargado
    return WhisperModel(nombre, device=dispositivo, compute_type="float16" if dispositivo == "cuda" else "int8")


def _es_fallo_de_gpu(e: Exception) -> bool:
    t = str(e).lower()
    return any(p in t for p in ("cublas", "cudnn", "cuda", "cudart", "nvrtc"))


def _a_cpu(motivo: Exception) -> None:
    log.warning("La tarjeta gráfica no sirve para Whisper (%s): se usa la CPU con el modelo «%s». Para usar la tarjeta hacen falta las "
                "librerías CUDA 12 y cuDNN 9 en la imagen de voz.", motivo, MODELO_CPU)
    _estado.update(modelo=MODELO_CPU, dispositivo="cpu", whisper=_cargar(MODELO_CPU, "cpu"), alternativa=str(motivo)[:200])


def modelo():
    with _cerrojo:
        if _estado["whisper"] is None:
            try:
                _estado["whisper"] = _cargar(_estado["modelo"], _estado["dispositivo"])
            except Exception as e:  # noqa: BLE001
                if _estado["dispositivo"] != "cuda" or not _es_fallo_de_gpu(e):
                    raise
                _a_cpu(e)
        return _estado["whisper"]


def _transcribir_fichero(ruta: str) -> tuple[str, str]:
    """Una transcripción. Si falla por la tarjeta gráfica, se cambia a CPU y se repite una vez."""
    for intento in (1, 2):
        try:
            segmentos, info = modelo().transcribe(ruta, vad_filter=True)
            return " ".join(s.text.strip() for s in segmentos), info.language     # los segmentos se calculan al recorrerlos: el fallo también puede salir aquí
        except Exception as e:  # noqa: BLE001
            with _cerrojo:
                if intento == 1 and _estado["dispositivo"] == "cuda" and _es_fallo_de_gpu(e):
                    _a_cpu(e)
                    continue
            raise
    raise RuntimeError("inalcanzable")


async def _arranque(_app):
    try:
        modelo()
    except Exception:  # noqa: BLE001
        log.exception("No se pudo cargar el modelo de Whisper; se reintentará con la primera petición")
    yield


app = FastAPI(title="Voz de Jarvis", lifespan=_arranque)


@app.get("/salud")
async def salud():
    return {"modelo": _estado["modelo"], "dispositivo": _estado["dispositivo"], "cargado": _estado["whisper"] is not None,
            "alternativa_por": _estado["alternativa"], "voces": {k: os.path.exists(v) for k, v in VOCES.items()}}


@app.post("/transcribir")
async def transcribir(audio: UploadFile):
    with tempfile.NamedTemporaryFile(suffix=".webm") as fh:
        fh.write(await audio.read())
        fh.flush()
        texto, idioma = _transcribir_fichero(fh.name)
    return {"texto": texto, "idioma": idioma}


MAX_TEXTO_HABLADO = 1500


@app.post("/hablar")
async def hablar(datos: dict):
    """Texto a voz con Piper. Devuelve un WAV; si falta la voz o Piper falla, un error que se entiende (no un 500 mudo)."""
    idioma = datos.get("idioma", "es")
    voz = VOCES.get(idioma, VOCES["es"])
    texto = str(datos.get("texto", "")).strip()[:MAX_TEXTO_HABLADO]
    if not texto:
        return JSONResponse({"error": "No hay texto que decir"}, status_code=422)
    if not os.path.exists(voz) or not os.path.exists(voz + ".json"):
        return JSONResponse({"error": f"Falta la voz {os.path.basename(voz)}. Descárgala en el servidor con: python3 scripts/voces_descargar.py"},
                            status_code=503)
    with tempfile.NamedTemporaryFile(suffix=".wav") as fh:
        try:
            subprocess.run(["piper", "--model", voz, "--output_file", fh.name], input=texto.encode(), check=True,
                           capture_output=True, timeout=90)
        except subprocess.CalledProcessError as e:
            log.error("Piper ha fallado: %s", e.stderr.decode("utf-8", "replace")[-400:])
            return JSONResponse({"error": "La síntesis de voz ha fallado (mira el log del servicio de voz)"}, status_code=500)
        except subprocess.TimeoutExpired:
            return JSONResponse({"error": "La síntesis de voz ha tardado demasiado"}, status_code=504)
        return Response(Path(fh.name).read_bytes(), media_type="audio/wav")
