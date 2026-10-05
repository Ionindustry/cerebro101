"""Cliente de los modelos locales (Ollama), pensado para que un fallo del modelo nunca sea un 500 sin explicación.

Siempre se pide salida estructurada (JSON con esquema) cuando el agente tiene que decidir algo: así los modelos
pequeños responden en un formato que el código puede validar, y si fallan se reintenta con el modelo principal.

Qué pasa cuando algo va mal (cada caso tiene su error, con un mensaje que puede leer la persona):
  · Ollama caído, reiniciándose o sin memoria → se reintenta con espera creciente (solo fallos transitorios) y, si sigue
    mal, `ModeloNoDisponible`. Tras varios fallos seguidos un cortacircuitos responde al instante durante unos segundos
    en vez de hacer esperar a cada petición.
  · El modelo tarda demasiado (CPU saturada, texto larguísimo) → `ModeloTimeout`, sin reintento: repetir una llamada de
    minutos solo empeora la cola.
  · Demasiadas peticiones a la vez → se limitan las llamadas simultáneas; si la espera supera el máximo, `ModeloOcupado`.
  · El modelo no está descargado → `ModeloNoEncontrado`, con el comando para descargarlo.
  · Respuesta que no es JSON válido, incompleta o cortada por el límite de tokens → `RespuestaInvalida`.
Todo se controla con variables de entorno OLLAMA_* (ver .env.example).
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import math
import os
import time
import weakref
from typing import Any

import httpx

from .ajustes import ajustes
from .observabilidad import anotar, generacion
from .router_modelos import Asignacion

log = logging.getLogger("cerebro.llm")


# --------------------------------------------------------------------------- errores
class ErrorModelo(RuntimeError):
    """Base. El texto del error está pensado para la persona; `http` y `codigo` para la API."""
    codigo = "error_modelo"
    http = 502

    def __init__(self, mensaje: str, reintentar_en: int | None = None):
        super().__init__(mensaje)
        self.reintentar_en = reintentar_en


class ModeloNoDisponible(ErrorModelo):
    codigo, http = "modelo_no_disponible", 503


class ModeloOcupado(ErrorModelo):
    codigo, http = "modelo_ocupado", 503


class ModeloTimeout(ErrorModelo):
    codigo, http = "modelo_timeout", 504


class ModeloNoEncontrado(ErrorModelo):
    codigo, http = "modelo_no_encontrado", 503


class RespuestaInvalida(ErrorModelo):
    codigo, http = "respuesta_invalida", 502


# --------------------------------------------------------------------------- ajustes (se leen al usarlos: se pueden cambiar sin reiniciar pruebas)
def _num(nombre: str, defecto: float) -> float:
    try:
        return float(os.environ.get(nombre, defecto))
    except ValueError:
        return float(defecto)


_reloj = time.monotonic          # sustituibles en las pruebas
_dormir = asyncio.sleep


class _Circuito:
    """Tras `OLLAMA_FALLOS_CIRCUITO` fallos de conexión seguidos, responde al instante durante `OLLAMA_ENFRIAMIENTO` s."""

    def __init__(self):
        self.fallos = 0
        self.abierto_hasta = 0.0

    def reiniciar(self):
        self.fallos, self.abierto_hasta = 0, 0.0

    def comprobar(self):
        resto = self.abierto_hasta - _reloj()
        if resto > 0:
            raise ModeloNoDisponible("El modelo de IA no responde (Ollama parece caído o reiniciándose). "
                                     "Inténtalo de nuevo en unos segundos.", reintentar_en=math.ceil(resto))
        if self.abierto_hasta:                       # se acabó el enfriamiento: una prueba, y si falla se vuelve a abrir
            self.abierto_hasta, self.fallos = 0.0, int(_num("OLLAMA_FALLOS_CIRCUITO", 3)) - 1

    def fallo(self):
        self.fallos += 1
        if self.fallos >= _num("OLLAMA_FALLOS_CIRCUITO", 3):
            self.abierto_hasta = _reloj() + _num("OLLAMA_ENFRIAMIENTO", 20)
            log.warning("Cortacircuitos de Ollama abierto durante %s s", _num("OLLAMA_ENFRIAMIENTO", 20))

    def exito(self):
        self.fallos = 0


circuito = _Circuito()
_semaforos: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore]" = weakref.WeakKeyDictionary()


@contextlib.asynccontextmanager
async def _turno():
    """Limita las llamadas simultáneas a Ollama (OLLAMA_CONCURRENCIA) para que no se amontonen y caduquen todas."""
    bucle = asyncio.get_running_loop()
    if bucle not in _semaforos:
        _semaforos[bucle] = asyncio.Semaphore(max(1, int(_num("OLLAMA_CONCURRENCIA", 2))))
    sem = _semaforos[bucle]
    espera = _num("OLLAMA_ESPERA_MAX", 120)
    try:
        await asyncio.wait_for(sem.acquire(), espera)
    except asyncio.TimeoutError:
        raise ModeloOcupado(f"Hay demasiadas peticiones en curso y el modelo no ha podido atenderte en {espera:.0f} s. "
                            "Inténtalo de nuevo en un momento.", reintentar_en=15) from None
    try:
        yield
    finally:
        sem.release()


# --------------------------------------------------------------------------- llamada con reintentos
_TRANSITORIOS = (httpx.ConnectError, httpx.ConnectTimeout, httpx.RemoteProtocolError, httpx.ReadError, httpx.WriteError)


async def _post(ruta: str, cuerpo: dict, timeout: float, modelo: str, transporte=None) -> httpx.Response:
    reintentos = int(_num("OLLAMA_REINTENTOS", 2))
    ultimo: ErrorModelo | None = None
    for intento in range(reintentos + 1):
        circuito.comprobar()
        try:
            async with httpx.AsyncClient(base_url=ajustes.ollama_url, transport=transporte,
                                         timeout=httpx.Timeout(timeout, connect=_num("OLLAMA_TIMEOUT_CONEXION", 10))) as c:
                r = await c.post(ruta, json=cuerpo)
        except _TRANSITORIOS as e:
            circuito.fallo()
            ultimo = ModeloNoDisponible("El modelo de IA no responde (Ollama parece caído o reiniciándose). "
                                        "Inténtalo de nuevo en unos segundos.", reintentar_en=30)
            log.warning("Ollama: %s (intento %d de %d)", type(e).__name__, intento + 1, reintentos + 1)
        except httpx.TimeoutException:
            raise ModeloTimeout(f"El modelo ha tardado más de {timeout:.0f} s en responder. Suele ser sobrecarga: "
                                "inténtalo de nuevo en un minuto o haz una petición más corta.", reintentar_en=60) from None
        else:
            if r.status_code == 404 and "not found" in r.text.lower():
                raise ModeloNoEncontrado(f"El modelo «{modelo}» no está descargado en Ollama. Descárgalo con: "
                                         f"docker compose exec ollama ollama pull {modelo}")
            if r.status_code >= 500:                           # runner caído, sin memoria…: suele ser transitorio
                circuito.fallo()
                ultimo = ErrorModelo(f"Ollama ha fallado ({r.status_code}). Inténtalo de nuevo en unos segundos.", reintentar_en=15)
                log.warning("Ollama devolvió %s: %s", r.status_code, r.text[:200])
            elif r.status_code != 200:
                raise ErrorModelo(f"Ollama rechazó la petición ({r.status_code}): {r.text[:200]}")
            else:
                circuito.exito()
                return r
        if intento < reintentos:
            await _dormir(min(2 ** intento, 10))                # 1 s, 2 s, 4 s…
    assert ultimo is not None
    raise ultimo


# --------------------------------------------------------------------------- API
async def chat(asignacion: Asignacion, mensajes: list[dict], esquema: dict | None = None,
               imagenes: list[str] | None = None, temperatura: float = 0.2,
               timeout: float | None = None, max_tokens: int | None = None, transporte=None) -> str | dict:
    """Llama a /api/chat de Ollama. Con `esquema`, devuelve el JSON ya validado como dict.

    `timeout`: segundos máximos esperando respuesta (por defecto OLLAMA_TIMEOUT). `max_tokens`: tope de salida
    (por defecto OLLAMA_MAX_TOKENS: sin él, un modelo en bucle genera hasta agotar el tiempo).
    """
    timeout = timeout or _num("OLLAMA_TIMEOUT", 300)
    max_tokens = max_tokens or int(_num("OLLAMA_MAX_TOKENS", 4096))
    if imagenes:
        mensajes = [*mensajes[:-1], {**mensajes[-1], "images": imagenes}]
    cuerpo: dict[str, Any] = {
        "model": asignacion.modelo,
        "messages": mensajes,
        "stream": False,
        # Ollama rechaza "-1" como texto: sin unidad debe ir como número
        "keep_alive": int(asignacion.mantener_cargado) if asignacion.mantener_cargado.lstrip("-").isdigit() else asignacion.mantener_cargado,
        "options": {"temperature": temperatura, "num_predict": max_tokens},
    }
    if esquema:
        cuerpo["format"] = esquema
    # Cada llamada al modelo queda registrada (evidencia ISO 27001: qué modelo, con qué entrada y qué respondió)
    meta = {"clase": asignacion.clase, "prioridad": asignacion.prioridad, "salida_estructurada": bool(esquema)}
    with generacion(f"ollama.chat:{asignacion.clase}", asignacion.modelo, mensajes,
                    parametros={"temperature": temperatura}, **meta) as obs:
        async with _turno():
            r = await _post("/api/chat", cuerpo, timeout, asignacion.modelo, transporte)
        resp = r.json()
        contenido = resp["message"]["content"]
        anotar(obs, output=contenido, usage_details={"input": resp.get("prompt_eval_count", 0),
                                                     "output": resp.get("eval_count", 0)},
               metadata={**meta, "duracion_total_ms": round(resp.get("total_duration", 0) / 1e6),
                         "fin": resp.get("done_reason")})
        cortada = resp.get("done_reason") == "length"
        if not esquema:
            if cortada:
                log.warning("Respuesta de %s cortada por el límite de %d tokens", asignacion.modelo, max_tokens)
            return contenido
        if cortada:
            raise RespuestaInvalida(f"La respuesta del modelo {asignacion.modelo} se cortó al llegar al límite de {max_tokens} tokens.")
        try:
            datos = json.loads(contenido)
        except json.JSONDecodeError as e:
            raise RespuestaInvalida(f"El modelo {asignacion.modelo} no devolvió JSON válido") from e
        if not isinstance(datos, dict):
            raise RespuestaInvalida(f"El modelo {asignacion.modelo} devolvió {type(datos).__name__} en vez de un objeto")
        faltan = [k for k in esquema.get("required", []) if k not in datos]
        if faltan:
            raise RespuestaInvalida(f"Faltan campos en la respuesta: {faltan}")
        return datos


async def embeddings(textos: list[str], modelo: str = "bge-m3", transporte=None) -> list[list[float]]:
    with generacion("ollama.embed", modelo, f"{len(textos)} fragmentos", tipo="embedding") as obs:
        async with _turno():
            r = await _post("/api/embed", {"model": modelo, "input": textos}, _num("OLLAMA_TIMEOUT_EMBEDDINGS", 120), modelo, transporte)
        resp = r.json()
        anotar(obs, usage_details={"input": resp.get("prompt_eval_count", 0)})
        return resp["embeddings"]


async def estado_modelos(necesarios: list[str], transporte=None) -> dict:
    """Para el diagnóstico: ¿responde Ollama y están descargados los modelos que usa el Cerebro?"""
    try:
        async with httpx.AsyncClient(base_url=ajustes.ollama_url, timeout=httpx.Timeout(5.0), transport=transporte) as c:
            r = await c.get("/api/tags")
        r.raise_for_status()
        instalados = {m["name"] for m in r.json().get("models", [])}
    except Exception as e:  # noqa: BLE001 - cualquier fallo significa «no se puede usar»
        return {"ollama": "caido", "error": type(e).__name__, "circuito_abierto": circuito.abierto_hasta > _reloj()}
    circuito.reiniciar()          # Ollama acaba de contestar: no hay motivo para seguir respondiendo «caído»
    faltan = sorted({m for m in necesarios if m not in instalados and f"{m}:latest" not in instalados})
    return {"ollama": "ok", "instalados": sorted(instalados), "faltan": faltan, "circuito_abierto": False}
