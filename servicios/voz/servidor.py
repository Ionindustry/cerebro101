"""Servicio de voz de Jarvis: voz a texto (faster-whisper) y texto a voz (Piper), todo local."""
from __future__ import annotations

import os
import subprocess
import tempfile

from fastapi import FastAPI, UploadFile
from fastapi.responses import Response
from faster_whisper import WhisperModel

MODELO = os.environ.get("WHISPER_MODELO", "large-v3-turbo")
DISPOSITIVO = os.environ.get("WHISPER_DISPOSITIVO", "cuda")
VOCES = {"ca": os.environ.get("PIPER_VOZ_CA", "/voces/ca_ES-upc_ona-medium.onnx"),
         "es": os.environ.get("PIPER_VOZ_ES", "/voces/es_ES-davefx-medium.onnx")}

app = FastAPI(title="Voz de Jarvis")
whisper = WhisperModel(MODELO, device=DISPOSITIVO, compute_type="float16" if DISPOSITIVO == "cuda" else "int8")


@app.post("/transcribir")
async def transcribir(audio: UploadFile):
    with tempfile.NamedTemporaryFile(suffix=".webm") as fh:
        fh.write(await audio.read())
        fh.flush()
        segmentos, info = whisper.transcribe(fh.name, vad_filter=True)
        texto = " ".join(s.text.strip() for s in segmentos)
    return {"texto": texto, "idioma": info.language}


@app.post("/hablar")
async def hablar(datos: dict):
    voz = VOCES.get(datos.get("idioma", "es"), VOCES["es"])
    with tempfile.NamedTemporaryFile(suffix=".wav") as fh:
        subprocess.run(["piper", "--model", voz, "--output_file", fh.name],
                       input=datos["texto"].encode(), check=True)
        return Response(open(fh.name, "rb").read(), media_type="audio/wav")
