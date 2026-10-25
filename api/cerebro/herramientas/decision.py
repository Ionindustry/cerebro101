"""Decisiones de elegir, puntuar o responder sí/no.

Tres implementaciones intercambiables con la misma interfaz:
  - `local`: el modelo local con salida estructurada (funciona desde el primer día).
  - `jeff`:  sustituto autoalojado compatible con la API de Jev.
  - `jev`:   Jev en la nube de TypeSafe (solo datos de sensibilidad baja, o media con
             retención cero y anonimización).

Jev y jeff hablan la misma API (`POST /v1/systemone`, https://docs.typesafe.ai/api): un `state`
y un mapa de preguntas tipadas (noul / choice / score) y devuelven respuestas con probabilidades.
Si la llamada falla (sin clave, red caída, límite de uso), se usa el modelo `local`.
"""
from __future__ import annotations

import json
import logging
import os
from functools import lru_cache

import httpx

from .. import anonimizacion as anon
from ..ajustes import ajustes
from ..entidades import cargar_entidades
from ..observabilidad import anotar, generacion
from ..llm import chat
from ..registro import registro
from ..router_modelos import asignar
from .base import Herramienta, registrar

log = logging.getLogger("cerebro.decision")


async def _local(texto: str, tipo: str, opciones: list[str] | None, rubrica: str | None) -> dict:
    ficha = registro().fichas["director-general"]  # el modelo rápido basta para decidir
    if tipo == "eleccion":
        esquema = {"type": "object", "properties": {
            "eleccion": {"type": "string", "enum": opciones}, "confianza": {"type": "number"},
            "motivo": {"type": "string"}}, "required": ["eleccion", "confianza", "motivo"]}
        pregunta = f"Elige una opción de {opciones} para el texto."
    elif tipo == "puntuacion":
        esquema = {"type": "object", "properties": {
            "puntuacion": {"type": "number", "minimum": 0, "maximum": 10}, "motivo": {"type": "string"}},
            "required": ["puntuacion", "motivo"]}
        pregunta = f"Puntúa de 0 a 10 según esta rúbrica: {rubrica}"
    else:
        esquema = {"type": "object", "properties": {
            "si": {"type": "boolean"}, "confianza": {"type": "number"}, "motivo": {"type": "string"}},
            "required": ["si", "confianza", "motivo"]}
        pregunta = "Responde sí o no."
    mensajes = [{"role": "system", "content": "Eres un clasificador preciso. Responde solo con el JSON pedido."},
                {"role": "user", "content": f"{pregunta}\n\nTexto:\n{texto}"}]
    return await chat(asignar(ficha), mensajes, esquema=esquema, temperatura=0)


URL_JEV = "https://api.typesafe.ai"
ESPERA_JEFF = 120         # jeff usa el modelo local: la primera llamada tras un rato puede tener que cargarlo en la tarjeta
NIVELES_PUNTUACION = 10   # Jev admite como máximo 10 niveles (0..9); se reescala a 0..10, como el modelo local


def _pregunta(tipo: str, opciones: list[str] | None, rubrica: str | None) -> dict:
    if tipo == "eleccion":
        return {"type": "choice", "instructions": "Elige la opción que mejor encaja con el estado.",
                "criteria": {o: None for o in opciones or []}}
    if tipo == "puntuacion":
        ultimo = NIVELES_PUNTUACION - 1
        return {"type": "score", "instructions": f"Puntúa según esta rúbrica: {rubrica}",
                "criteria": [f"Nivel {i} de {ultimo}" + (" (mínimo)" if i == 0 else " (máximo)" if i == ultimo else "")
                             for i in range(NIVELES_PUNTUACION)]}
    return {"type": "noul", "instructions": "¿Es cierto lo que se pregunta o se afirma en el estado?"}


def _traducir(tipo: str, respuesta: dict) -> dict:
    """Pasa la respuesta de Jev al mismo formato que devuelve `_local`."""
    if tipo == "eleccion":
        return {"eleccion": respuesta["choice"], "confianza": respuesta["confidence"],
                "motivo": f"Jev: probabilidades {respuesta['probabilities']}"}
    if tipo == "puntuacion":
        return {"puntuacion": round(respuesta["score"] * 10 / (NIVELES_PUNTUACION - 1), 2), "confianza": respuesta["confidence"],
                "motivo": f"Jev: probabilidades {respuesta['probabilities']}"}
    p = respuesta["noul"]
    return {"si": p >= 0.5, "confianza": round(max(p, 1 - p), 3), "motivo": f"Jev: probabilidad de sí {p}"}


async def _llamar_api(base_url: str, clave: str, texto: str, tipo: str, opciones, rubrica,
                      transporte: httpx.AsyncBaseTransport | None = None, espera: float = 30) -> dict:
    if tipo == "eleccion" and not opciones:
        raise ValueError("La elección necesita opciones")
    cuerpo = {"model": "jev-latest", "state": texto, "questions": {"q": _pregunta(tipo, opciones, rubrica)}}
    cabeceras = {"Authorization": f"Bearer {clave}"} if clave else {}
    async with httpx.AsyncClient(base_url=base_url or URL_JEV, timeout=espera, transport=transporte) as c:
        r = await c.post("/v1/systemone", json=cuerpo, headers=cabeceras)
    r.raise_for_status()
    return _traducir(tipo, r.json()["answers"]["q"])


@lru_cache(maxsize=1)
def _detector():
    """ANONIMIZACION_NER=spacy usa spaCy (si está instalado con su modelo); por defecto, el detector heurístico."""
    cfg = anon.configuracion(str(ajustes.dir_config))
    if os.environ.get("ANONIMIZACION_NER", "heuristico").lower() == "spacy":
        d = anon.detector_spacy(os.environ.get("ANONIMIZACION_MODELO_SPACY", "es_core_news_md"))
        if d:
            return d
        log.warning("ANONIMIZACION_NER=spacy pero spaCy o su modelo no están instalados: se usa el heurístico")
    return anon.detector_heuristico(cfg.get("no_son_nombres", []))


async def preparar_para_la_nube(texto: str, opciones, rubrica) -> tuple[anon.Resultado, str | None, list[str]]:
    """Anonimiza lo que va a salir. Devuelve (resultado del texto, rúbrica anonimizada, motivos de bloqueo)."""
    cfg = anon.configuracion(str(ajustes.dir_config))
    ent = await cargar_entidades(cfg)
    res = anon.anonimizar(texto, ent, _detector(), cfg)
    motivos = list(res.motivos)
    rub = None
    if rubrica:
        r2 = anon.anonimizar(rubrica, ent, _detector(), cfg)
        rub, motivos = r2.texto, motivos + r2.motivos
    for o in opciones or []:       # las opciones las fija el código, pero no pueden llevar datos personales
        if anon.detectar_con_formato(o) or anon.detectar_entidades(o, ent):
            motivos.append("las opciones contienen datos personales")
            break
    return res, rub, motivos


async def _respaldo(texto: str, tipo: str, opciones, rubrica, motivo: str) -> dict:
    """Cuando Jev no puede o no debe usarse: primero jeff (misma API, en el servidor, sin que salga ningún dato) y, si tampoco está, el modelo local."""
    try:
        r = await _llamar_api(ajustes.jeff_url, "", texto, tipo, opciones, rubrica, espera=ESPERA_JEFF)
        return {**r, "via": f"jeff ({motivo})"}
    except (httpx.HTTPError, KeyError, ValueError) as e:
        log.warning("jeff no disponible (%s): se usa el modelo local", e)
        return {**await _local(texto, tipo, opciones, rubrica), "via": f"local ({motivo}; jeff no disponible)"}


def _crear(proveedor: str):
    async def decidir(texto: str, tipo: str = "si_no", opciones: list[str] | None = None,
                      rubrica: str | None = None) -> dict:
        if proveedor == "jev" and not ajustes.usar_jev_nube:
            log.info("Jev en la nube desactivado (USAR_JEV_NUBE=false): decide jeff")
            return await _respaldo(texto, tipo, opciones, rubrica, "Jev desactivado")
        url, clave = (ajustes.jev_url, ajustes.jev_api_key) if proveedor == "jev" else (ajustes.jeff_url, "")
        if proveedor == "jev" and not clave:
            log.warning("Falta JEV_API_KEY: decide jeff")
            return await _respaldo(texto, tipo, opciones, rubrica, "sin clave de Jev")
        if proveedor == "jev":
            # Nada sale a la nube sin anonimizar; si no se puede garantizar, decide jeff (en el servidor)
            res, rub, motivos = await preparar_para_la_nube(texto, opciones, rubrica)
            if motivos:
                log.info("Jev no recibe esta petición (%s): decide jeff", "; ".join(motivos))
                with generacion("jev.decidir:bloqueado", None, "[no enviado]", tipo="tool",
                                **{**res.resumen(), "apto": False, "motivos": motivos}):
                    pass
                return await _respaldo(texto, tipo, opciones, rubrica, "no apto para la nube")
            texto, rubrica = res.texto, rub
            extra = {"via": "jev (anonimizado)"}
            audit = res.resumen()
        else:
            extra, audit = {"via": "jeff"}, {}
        try:
            with generacion("jev.decidir" if proveedor == "jev" else "jeff.decidir", "jev-latest", texto,
                            tipo="generation", tipo_decision=tipo, **audit) as obs:
                r = await _llamar_api(url, clave, texto, tipo, opciones, rubrica, espera=30 if proveedor == "jev" else ESPERA_JEFF)
                anotar(obs, output=json.dumps(r, ensure_ascii=False))
                return {**r, **extra}
        except (httpx.HTTPError, KeyError, ValueError) as e:
            if proveedor == "jev":
                log.warning("Jev no disponible (%s): decide jeff", e)
                return await _respaldo(texto, tipo, opciones, rubrica, "Jev no disponible")
            log.warning("jeff no disponible (%s): se usa el modelo local", e)
            return {**await _local(texto, tipo, opciones, rubrica), "via": "local (jeff no disponible)"}
    return decidir


for _p, _desc in (("jev", "Jev en la nube (solo datos públicos o anonimizados)"),
                  ("jeff", "Sustituto local de Jev")):
    registrar(Herramienta(
        nombre=_p,
        descripcion=f"{_desc}. Para decisiones cerradas: elegir entre opciones, puntuar de 0 a 10 o responder sí/no.",
        operaciones={"decidir": _crear(_p)},
        ayuda={"decidir": "tipo «eleccion» necesita opciones; «puntuacion» necesita rubrica; «si_no» es una afirmación o pregunta en texto"},
        ejemplos={"decidir": {"texto": "El grabador lleva tres días sin grabar", "tipo": "eleccion", "opciones": ["soporte", "ventas"]}},
    ))


# --- Estado de Jev / jeff / modelo local (para el panel y el diagnóstico) -------------------------------------------------------------

import time as _tiempo

_CACHE: dict = {"cuando": 0.0, "datos": None}
PRUEBA = "Prueba de funcionamiento: el sol sale por el este."          # sin datos de nadie: es lo único que puede salir a la nube


async def _probar(url: str, clave: str, transporte=None) -> tuple[bool, float, str]:
    t0 = _tiempo.monotonic()
    try:
        r = await _llamar_api(url, clave, PRUEBA, "si_no", None, None, transporte, espera=30 if clave else ESPERA_JEFF)
        return True, round(_tiempo.monotonic() - t0, 2), f"respondió «{'sí' if r['si'] else 'no'}»"
    except httpx.HTTPStatusError as e:
        return False, 0, {401: "la clave es incorrecta o ha caducado", 403: "la clave no tiene permiso", 429: "se ha superado el límite de uso"}.get(
            e.response.status_code, f"responde con error {e.response.status_code}")
    except (httpx.HTTPError, KeyError, ValueError) as e:
        return False, 0, f"no responde ({type(e).__name__})"


async def estado(probar: bool = False, transporte_nube=None, transporte_jeff=None, transporte_ollama=None) -> dict:
    """¿Qué vía de decisiones cerradas está operativa y cuál usará cada nivel de sensibilidad?

    Sin `probar` solo se hacen comprobaciones ligeras (¿responde jeff y tiene su modelo?, ¿están la clave y la activación de Jev?) y se reutiliza el resultado
    de hace menos de un minuto. Antes se hacía siempre una pregunta real a jeff (un modelo de lenguaje) y a Jev: el panel la repetía cada minuto, tardaba
    hasta 15 s (o 2 min con el modelo cargándose) y competía con las respuestas de Jarvis. `probar` hace esa pregunta de prueba, sin datos de nadie."""
    if not probar and _CACHE["datos"] and _tiempo.monotonic() - _CACHE["cuando"] < 60:
        return _CACHE["datos"]
    from ..llm import estado_modelos
    from ..router_modelos import modelos_necesarios

    # Nube (Jev)
    if not ajustes.usar_jev_nube:
        nube = {"estado": "desactivado", "detalle": "USAR_JEV_NUBE no está en «true»: las decisiones se hacen en local"}
    elif not ajustes.jev_api_key:
        nube = {"estado": "sin_clave", "detalle": "falta la clave de Jev (JEV_API_KEY): se activa con scripts/jev_activar.py"}
    elif probar:
        ok, seg, det = await _probar(ajustes.jev_url, ajustes.jev_api_key, transporte_nube)
        nube = {"estado": "operativo" if ok else "caido", "detalle": det, "segundos": seg}
    else:
        nube = {"estado": "configurado", "detalle": "la clave y la activación están puestas; «Comprobar ahora» le hace una pregunta de prueba (no se pregunta sola, para no gastar uso)"}
    # jeff (autoalojado)
    try:
        async with httpx.AsyncClient(base_url=ajustes.jeff_url, timeout=5, transport=transporte_jeff) as c:
            r = await c.get("/salud")
        if r.status_code == 200 and not probar:
            jeff = {"estado": "operativo", "detalle": "responde y tiene su modelo; «Comprobar ahora» le hace una pregunta de prueba", "modelo": r.json().get("modelo")}
        elif r.status_code == 200:
            ok, seg, det = await _probar(ajustes.jeff_url, "", transporte_jeff)
            jeff = {"estado": "operativo" if ok else "caido", "detalle": det, "segundos": seg, "modelo": r.json().get("modelo")}
        else:
            jeff = {"estado": "caido", "detalle": r.json().get("detail", f"responde {r.status_code}") if r.headers.get("content-type", "").startswith("application/json") else f"responde {r.status_code}"}
    except httpx.HTTPError:
        jeff = {"estado": "no_desplegado", "detalle": "el servicio jeff no responde: arráncalo con «docker compose up -d jeff»"}
    # modelo local
    m = await estado_modelos(modelos_necesarios(), transporte_ollama)
    local = {"estado": "operativo" if m.get("ollama") == "ok" and not m.get("faltan") else "caido",
             "detalle": "Ollama responde" if m.get("ollama") == "ok" and not m.get("faltan") else (f"faltan modelos: {', '.join(m.get('faltan', []))}" if m.get("ollama") == "ok" else "Ollama no responde")}

    def via(sensibilidad: str) -> str:
        if sensibilidad != "alta" and nube["estado"] in ("operativo", "configurado"):
            return "jev"
        if jeff["estado"] == "operativo":
            return "jeff"
        return "local" if local["estado"] == "operativo" else "ninguna"
    datos = {"nube": nube, "jeff": jeff, "local": local, "se_usara": {n: via(n) for n in ("baja", "media", "alta")},
             "operativo": nube["estado"] in ("operativo", "configurado") or jeff["estado"] == "operativo",
             "resumen": ("Jev operativo" if nube["estado"] == "operativo" else
                         "Jev configurado; decide Jev (sin probar)" if nube["estado"] == "configurado" else
                         "Jev no activo; decide jeff (local)" if jeff["estado"] == "operativo" else
                         "Solo el modelo local" if local["estado"] == "operativo" else "Sin motor de decisiones")}
    _CACHE.update(cuando=_tiempo.monotonic(), datos=datos)
    return datos
