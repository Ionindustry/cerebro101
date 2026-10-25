"""jeff: sustituto autoalojado de Jev (TypeSafe) con la misma API (`POST /v1/systemone`), servido por el modelo local de Ollama.

Jev da respuestas cerradas —elegir entre opciones, puntuar, sí/no— con una probabilidad. jeff hace lo mismo con el modelo `juez` del perfil de hardware,
sin que ningún dato salga del servidor: por eso se usa siempre con datos sensibles (RR.HH., clientes, económicos) y como respaldo si la nube no está disponible.

Solo se publica en la red interna de Docker. No guarda nada: ni el texto ni las respuestas.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import httpx
import yaml
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

log = logging.getLogger("jeff")
OLLAMA = os.environ.get("OLLAMA_URL", "http://ollama:11434")
PERFIL = os.environ.get("PERFIL_HARDWARE", "pequena")
CONTEXTO = int(os.environ.get("OLLAMA_NUM_CTX") or 8192)
TIMEOUT = float(os.environ.get("JEFF_TIMEOUT") or 120)
MAX_TEXTO = 24_000

app = FastAPI(title="jeff", version="1.0", docs_url=None, redoc_url=None)


def modelo() -> str:
    """El modelo `juez` del perfil activo (config/modelos.yaml). JEFF_MODELO lo fija a mano."""
    if os.environ.get("JEFF_MODELO"):
        return os.environ["JEFF_MODELO"]
    cfg = yaml.safe_load(Path(os.environ.get("CEREBRO_CONFIG", "/app/config"), "modelos.yaml").read_text(encoding="utf-8"))
    return cfg["perfiles"].get(PERFIL, cfg["perfiles"][cfg["perfil_por_defecto"]])["juez"]["modelo"]


class Pregunta(BaseModel):
    type: str
    instructions: str = ""
    criteria: dict | list | None = None


class Peticion(BaseModel):
    model: str | None = None
    state: str
    questions: dict[str, Pregunta]


def esquema(p: Pregunta) -> dict:
    if p.type == "choice":
        opciones = list(p.criteria or [])
        if not opciones:
            raise HTTPException(422, "Una pregunta «choice» necesita criterios (las opciones)")
        return {"type": "object", "required": ["eleccion", "confianza"],
                "properties": {"eleccion": {"type": "string", "enum": opciones}, "confianza": {"type": "number", "minimum": 0, "maximum": 1}}}
    if p.type == "score":
        niveles = list(p.criteria or [])
        if len(niveles) < 2:
            raise HTTPException(422, "Una pregunta «score» necesita al menos dos niveles")
        return {"type": "object", "required": ["nivel", "confianza"],
                "properties": {"nivel": {"type": "integer", "minimum": 0, "maximum": len(niveles) - 1}, "confianza": {"type": "number", "minimum": 0, "maximum": 1}}}
    if p.type == "noul":
        return {"type": "object", "required": ["si", "confianza"], "properties": {"si": {"type": "boolean"}, "confianza": {"type": "number", "minimum": 0, "maximum": 1}}}
    raise HTTPException(422, f"Tipo de pregunta no admitido: {p.type}")


def instruccion(p: Pregunta) -> str:
    if p.type == "choice":
        return f"{p.instructions}\nOpciones: {', '.join(p.criteria)}.\nResponde con la opción elegida y tu confianza de 0 a 1."
    if p.type == "score":
        niveles = "\n".join(f"{i}: {c}" for i, c in enumerate(p.criteria))
        return f"{p.instructions}\nNiveles:\n{niveles}\nResponde con el número del nivel y tu confianza de 0 a 1."
    return f"{p.instructions}\nResponde si es cierto (true/false) y tu confianza de 0 a 1."


def respuesta(p: Pregunta, r: dict) -> dict:
    """Pasa la salida del modelo al formato de Jev: elección/puntuación/probabilidad con su reparto de probabilidades."""
    c = min(1.0, max(0.0, float(r.get("confianza", 0.5))))
    if p.type == "choice":
        ops = list(p.criteria)
        resto = (1 - c) / (len(ops) - 1) if len(ops) > 1 else 0
        return {"choice": r["eleccion"], "confidence": round(c, 3), "probabilities": {o: round(c if o == r["eleccion"] else resto, 3) for o in ops}}
    if p.type == "score":
        n = len(p.criteria)
        resto = (1 - c) / (n - 1)
        return {"score": int(r["nivel"]), "confidence": round(c, 3), "probabilities": [round(c if i == int(r["nivel"]) else resto, 3) for i in range(n)]}
    return {"noul": round(c if r["si"] else 1 - c, 3)}


async def preguntar(cliente: httpx.AsyncClient, estado: str, p: Pregunta) -> dict:
    cuerpo = {"model": modelo(), "stream": False, "think": False, "format": esquema(p), "keep_alive": -1,
              "options": {"temperature": 0, "num_ctx": CONTEXTO, "presence_penalty": 0, "frequency_penalty": 0, "repeat_penalty": 1},   # Qwen trae presence_penalty=1,5: hace derivar a otros idiomas
              "messages": [{"role": "system", "content": "Eres un evaluador preciso. Respondes solo con el JSON pedido, sin explicaciones."},
                           {"role": "user", "content": f"Estado:\n{estado}\n\nPregunta:\n{instruccion(p)}"}]}
    r = await cliente.post(f"{OLLAMA}/api/chat", json=cuerpo)
    r.raise_for_status()
    try:
        return respuesta(p, json.loads(r.json()["message"]["content"]))
    except (KeyError, ValueError, TypeError) as e:
        raise HTTPException(502, "El modelo no ha dado una respuesta válida") from e


@app.post("/v1/systemone")
async def systemone(p: Peticion):
    if not p.state.strip():
        raise HTTPException(422, "El estado está vacío")
    if len(p.state) > MAX_TEXTO:
        raise HTTPException(413, f"El estado es demasiado largo (máximo {MAX_TEXTO} caracteres)")
    if not p.questions or len(p.questions) > 8:
        raise HTTPException(422, "Se admiten de 1 a 8 preguntas")
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        try:
            return {"model": "jeff-" + modelo(), "answers": {k: await preguntar(c, p.state, q) for k, q in p.questions.items()}}
        except httpx.HTTPStatusError as e:
            log.warning("Ollama rechaza la petición: %s %s", e.response.status_code, e.response.text[:200])
            raise HTTPException(502, "El modelo local ha rechazado la petición") from e
        except httpx.HTTPError as e:
            log.warning("Ollama no responde: %s", e)
            raise HTTPException(503, "El modelo local no está disponible") from e


@app.get("/salud")
async def salud():
    """Operativo = responde y el modelo `juez` está descargado en Ollama."""
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(f"{OLLAMA}/api/tags")
        r.raise_for_status()
        etiquetas = {m["name"] for m in r.json().get("models", [])}
    except httpx.HTTPError:
        raise HTTPException(503, "Ollama no responde")
    m = modelo()
    if m not in etiquetas and not (":" not in m and f"{m}:latest" in etiquetas):
        raise HTTPException(503, f"El modelo {m} no está descargado en Ollama")
    return {"estado": "ok", "modelo": m}
