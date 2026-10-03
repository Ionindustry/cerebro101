"""Envoltorio mínimo de Agent Reach en un contenedor aislado.

Solo expone canales de lectura pública de la lista permitida. No guarda ni usa
cookies de cuentas personales (condición del documento del Cerebro).
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException

app = FastAPI(title="Agent Reach (aislado)")
DOMINIOS_YOUTUBE = {"youtube.com", "www.youtube.com", "youtu.be", "m.youtube.com"}


def _ejecutar(cmd: list[str], timeout: int = 120) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise HTTPException(502, r.stderr[-500:])
    return r.stdout


@app.get("/doctor")
def doctor():
    return json.loads(_ejecutar(["agent-reach", "doctor", "--json"]))


@app.get("/youtube/transcripcion")
def transcripcion(url: str, idioma: str = "es,ca,en"):
    if urlparse(url).netloc not in DOMINIOS_YOUTUBE:
        raise HTTPException(400, "Solo se admiten URL de YouTube")
    with tempfile.TemporaryDirectory() as d:
        _ejecutar(["yt-dlp", "--skip-download", "--write-auto-subs", "--write-subs", "--sub-langs", idioma,
                   "--sub-format", "vtt", "-o", f"{d}/%(id)s.%(ext)s", url], timeout=300)
        textos = [p.read_text(encoding="utf-8", errors="replace") for p in Path(d).glob("*.vtt")]
    lineas = [l for t in textos for l in t.splitlines()
              if l and "-->" not in l and not l.startswith(("WEBVTT", "Kind:", "Language:"))]
    return {"url": url, "texto": " ".join(dict.fromkeys(lineas))[:100_000]}
