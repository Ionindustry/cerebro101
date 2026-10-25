"""Modelos de IA externos (Claude y ChatGPT) para las consultas más complejas, con interruptor por proveedor.

Reglas, de más a menos importante:
  1. Nunca se usan por defecto: cada proveedor está «desconectado» hasta que Dirección lo conecta en el panel, y necesita su clave en el .env.
  2. Solo sale lo que pasa la anonimización local; si no se puede garantizar, la consulta se queda en el modelo local.
  3. Los agentes de sensibilidad por encima de `sensibilidad_maxima` (config/modelos_externos.yaml) no los usan nunca.
  4. Hay un tope de llamadas al día por proveedor (gasto) y, si el proveedor falla, se pasa al siguiente y al final al modelo local.
La respuesta vuelve con los datos reales: el modelo externo solo ha visto etiquetas ([PERSONA_1]…) y se deshacen aquí, en memoria
(la tabla de equivalencias no se guarda, no se registra y no sale del servidor).
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from functools import lru_cache
from pathlib import Path

import httpx
import psycopg
import yaml

from . import actividad
from . import anonimizacion as anon
from .ajustes import ajustes
from .entidades import cargar_entidades
from .llm import RespuestaInvalida
from .observabilidad import anotar, generacion

log = logging.getLogger("cerebro.modelos_externos")
NIVELES = ("baja", "media", "alta")
CLAVES = {"claude": "ANTHROPIC_API_KEY", "chatgpt": "OPENAI_API_KEY"}
MODELOS = {"claude": "CLAUDE_MODELO", "chatgpt": "CHATGPT_MODELO"}
ESQUEMA_PRUEBA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}


class ErrorExterno(RuntimeError):
    """El proveedor no ha podido responder; el texto lo puede leer la persona."""


@lru_cache(maxsize=1)
def _configuracion(dir_config: str) -> dict:
    with open(Path(dir_config) / "modelos_externos.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def configuracion() -> dict:
    return _configuracion(str(ajustes.dir_config))


def clave(proveedor: str) -> str:
    return os.environ.get(CLAVES[proveedor], "").strip()


def modelo(proveedor: str) -> str:
    return os.environ.get(MODELOS[proveedor], "").strip() or configuracion()["proveedores"][proveedor]["modelo"]


# --------------------------------------------------------------------------- interruptores (en la base: sobreviven a reinicios y valen para la API y el worker)
async def _conectar() -> psycopg.AsyncConnection:
    return await psycopg.AsyncConnection.connect(ajustes.database_url, connect_timeout=3)


async def activos() -> dict[str, bool]:
    """Qué proveedores están conectados. Si la base no responde, ninguno: ante la duda no sale nada."""
    try:
        async with await _conectar() as c:
            cur = await c.execute("SELECT proveedor, activo FROM modelos_externos")
            filas = await cur.fetchall()
        return {p: bool(a) for p, a in filas}
    except Exception as e:  # noqa: BLE001
        log.warning("No se pudo leer qué modelos externos están conectados (se consideran desconectados): %s", e)
        return {}


async def poner(proveedor: str, activo: bool, quien: str) -> None:
    async with await _conectar() as c:
        await c.execute(
            """INSERT INTO modelos_externos (proveedor, activo, cambiado_por, cambiado) VALUES (%s, %s, %s, now())
               ON CONFLICT (proveedor) DO UPDATE SET activo = EXCLUDED.activo, cambiado_por = EXCLUDED.cambiado_por, cambiado = now()""",
            (proveedor, activo, quien[:120]))
    log.info("Modelo externo %s %s por %s", proveedor, "conectado" if activo else "desconectado", quien)


async def usadas_hoy(proveedor: str) -> int:
    try:
        async with await _conectar() as c:
            cur = await c.execute("SELECT COALESCE(SUM(n), 0) FROM kpi_uso WHERE clave = %s AND dia = (now() AT TIME ZONE 'Europe/Madrid')::date",
                                  (f"modelo_externo:{proveedor}",))
            return int((await cur.fetchone())[0])
    except Exception as e:  # noqa: BLE001
        log.warning("No se pudo leer el uso de hoy de %s: %s", proveedor, e)
        return 10 ** 9           # sin contador no hay tope que vigilar: mejor no gastar


# --------------------------------------------------------------------------- qué consultas son complejas y quién puede usar la nube
def _norm(t: str) -> str:
    return re.sub(r"\s+", " ", anon.normalizar(t)).strip()


def es_compleja(peticion: str) -> bool:
    c = configuracion()["complejidad"]
    if len(peticion) >= c["caracteres"]:
        return True
    texto = _norm(peticion)
    for palabra in c["palabras"]:
        raiz = _norm(palabra)
        patron = r"\b" + re.escape(raiz[:-1]) if raiz.endswith("*") else r"\b" + re.escape(raiz) + r"\b"
        if re.search(patron, texto):
            return True
    return False


def permitido_para(sensibilidad_ficha: str, sensibilidad_peticion: str | None = None) -> bool:
    maxima = NIVELES.index(configuracion()["sensibilidad_maxima"])
    nivel = max(NIVELES.index(sensibilidad_ficha), NIVELES.index(sensibilidad_peticion) if sensibilidad_peticion in NIVELES else 0)
    return nivel <= maxima


async def _preparar(mensajes: list[dict]) -> tuple[list[dict], dict, list[str]]:
    """Anonimiza lo que dicen la persona, el agente y las herramientas (los mensajes del sistema los escribe el código: no llevan datos de nadie)."""
    from .herramientas.decision import _detector       # el mismo detector que usa Jev
    cfg = anon.configuracion(str(ajustes.dir_config))
    ent = await cargar_entidades(cfg)
    sesion: dict = {}
    limpios, motivos = [], []
    for m in mensajes:
        if m["role"] == "system":
            limpios.append(m)
            continue
        r = anon.anonimizar(m["content"], ent, _detector(), cfg, sesion)
        motivos += r.motivos
        limpios.append({**m, "content": r.texto})
    return limpios, sesion, list(dict.fromkeys(motivos))


# --------------------------------------------------------------------------- proveedores
def _alternar(mensajes: list[dict]) -> list[dict]:
    """Claude exige que los mensajes empiecen por el usuario y alternen: se unen los consecutivos del mismo rol."""
    salida: list[dict] = []
    for m in mensajes:
        rol = "assistant" if m["role"] == "assistant" else "user"
        if salida and salida[-1]["role"] == rol:
            salida[-1] = {"role": rol, "content": salida[-1]["content"] + "\n\n" + m["content"]}
        else:
            salida.append({"role": rol, "content": m["content"]})
    if not salida or salida[0]["role"] != "user":
        salida.insert(0, {"role": "user", "content": "(continúa)"})
    return salida


def _error_http(nombre: str, r: httpx.Response) -> ErrorExterno:
    motivo = {401: "la clave es incorrecta o ha caducado", 403: "la clave no tiene permiso", 429: "se ha superado el límite de uso o de saldo",
              400: "la petición no es válida", 404: "el modelo no existe o no está disponible para esta clave"}.get(r.status_code, f"error {r.status_code}")
    try:                                   # el proveedor explica el motivo (nunca lleva la clave ni nuestros datos)
        detalle = (r.json().get("error") or {}).get("message", "")
    except ValueError:
        detalle = ""
    return ErrorExterno(f"{nombre}: {motivo}" + (f" — {detalle[:240]}" if detalle else ""))


async def _claude(cfg: dict, modelo_: str, sistema: str, mensajes: list[dict], esquema: dict, transporte) -> dict:
    cuerpo = {"model": modelo_, "max_tokens": cfg["max_tokens"], "system": sistema, "messages": _alternar(mensajes),
              "tools": [{"name": "responder", "description": "Entrega la respuesta con el formato pedido.", "input_schema": esquema}],
              "tool_choice": {"type": "tool", "name": "responder"}}
    cabeceras = {"x-api-key": clave("claude"), "anthropic-version": "2023-06-01"}
    async with httpx.AsyncClient(base_url=cfg["proveedores"]["claude"]["url"], timeout=cfg["timeout_segundos"], transport=transporte) as c:
        r = await c.post("/v1/messages", json=cuerpo, headers=cabeceras)
        if r.status_code == 400:
            # Algunos modelos no admiten forzar la herramienta (p. ej. con razonamiento activado): se le pide que la use, sin forzarla
            cuerpo = {**cuerpo, "tool_choice": {"type": "auto"}, "system": cuerpo["system"] + "\n\nResponde SIEMPRE llamando a la herramienta «responder»."}
            r = await c.post("/v1/messages", json=cuerpo, headers=cabeceras)
    if r.status_code != 200:
        raise _error_http("Claude", r)
    for bloque in r.json().get("content", []):
        if bloque.get("type") == "tool_use" and isinstance(bloque.get("input"), dict):
            return bloque["input"]
    raise RespuestaInvalida("Claude no devolvió la respuesta en el formato pedido")


async def _chatgpt(cfg: dict, modelo_: str, sistema: str, mensajes: list[dict], esquema: dict, transporte) -> dict:
    formato = f"{sistema}\n\nResponde SOLO con un objeto JSON que cumpla este esquema:\n{json.dumps(esquema, ensure_ascii=False)}"
    cuerpo = {"model": modelo_, "messages": [{"role": "system", "content": formato}, *({"role": m["role"], "content": m["content"]} for m in mensajes if m["role"] != "system")],
              "response_format": {"type": "json_object"}, "max_completion_tokens": cfg["max_tokens"]}
    async with httpx.AsyncClient(base_url=cfg["proveedores"]["chatgpt"]["url"], timeout=cfg["timeout_segundos"], transport=transporte) as c:
        r = await c.post("/v1/chat/completions", json=cuerpo, headers={"Authorization": f"Bearer {clave('chatgpt')}"})
    if r.status_code != 200:
        raise _error_http("ChatGPT", r)
    try:
        datos = json.loads(r.json()["choices"][0]["message"]["content"])
    except (KeyError, IndexError, ValueError) as e:
        raise RespuestaInvalida("ChatGPT no devolvió JSON válido") from e
    if not isinstance(datos, dict):
        raise RespuestaInvalida("ChatGPT no devolvió un objeto JSON")
    return datos


LLAMADAS = {"claude": _claude, "chatgpt": _chatgpt}


async def _llamar(proveedor: str, mensajes: list[dict], esquema: dict, transporte=None) -> dict:
    cfg = configuracion()
    sistema = "\n\n".join(m["content"] for m in mensajes if m["role"] == "system")
    datos = await LLAMADAS[proveedor](cfg, modelo(proveedor), sistema, [m for m in mensajes if m["role"] != "system"], esquema, transporte)
    faltan = [k for k in esquema.get("required", []) if k not in datos]
    if faltan:
        raise RespuestaInvalida(f"Faltan campos en la respuesta: {faltan}")
    return datos


# --------------------------------------------------------------------------- uso desde el grafo
async def consultar(ficha, mensajes: list[dict], esquema: dict, sensibilidad: str | None = None, transporte=None) -> dict | None:
    """Una consulta a Claude o ChatGPT, o `None` si no procede (desconectados, sin clave, agente sensible, datos que no se pueden
    anonimizar, tope diario o fallo): el llamador sigue entonces con el modelo local."""
    cfg = configuracion()
    if not permitido_para(ficha.sensibilidad, sensibilidad):
        return None
    con_clave = [p for p in cfg["orden"] if clave(p)]
    if not con_clave:
        return None
    conectados = await activos()
    candidatos = [p for p in con_clave if conectados.get(p)]
    if not candidatos:
        return None
    limpios, sesion, motivos = await _preparar(mensajes)
    if motivos:
        log.info("Consulta de %s no apta para modelos externos (%s): se queda en local", ficha.id, "; ".join(motivos))
        with generacion("externo:bloqueado", None, "[no enviado]", tipo="tool", agente=ficha.id, apto=False, motivos=motivos):
            pass
        return None
    for p in candidatos:
        if await usadas_hoy(p) >= cfg["limite_diario"]:
            log.warning("%s ha llegado al tope diario de %d llamadas", p, cfg["limite_diario"])
            continue
        nombre = cfg["proveedores"][p]["nombre"]
        await actividad.marcar(ficha.id, f"Consultando a {nombre} (datos anonimizados)")
        try:
            with generacion(f"externo.{p}", modelo(p), limpios, tipo="generation", agente=ficha.id) as obs:
                inicio = time.monotonic()
                datos = await _llamar(p, limpios, esquema, transporte)
                anotar(obs, output=json.dumps(datos, ensure_ascii=False), metadata={"segundos": round(time.monotonic() - inicio, 2)})
        except (ErrorExterno, RespuestaInvalida, httpx.HTTPError) as e:
            log.warning("%s no ha podido responder (%s): se prueba con el siguiente o con el modelo local", p, e)
            continue
        await actividad.contar(ficha.id, f"modelo_externo:{p}")
        return anon.desanonimizar(datos, sesion)
    return None


# --------------------------------------------------------------------------- estado para el panel (nunca devuelve una clave)
async def estado(probar_proveedor: str | None = None, transporte=None) -> dict:
    cfg = configuracion()
    conectados = await activos()
    lista = []
    for p in cfg["orden"]:
        tiene = bool(clave(p))
        on = bool(conectados.get(p))
        item = {"id": p, "nombre": cfg["proveedores"][p]["nombre"], "modelo": modelo(p), "tiene_clave": tiene, "activo": on,
                "estado": "sin_clave" if not tiene else "conectado" if on else "desconectado",
                "usadas_hoy": await usadas_hoy(p) if tiene else 0, "limite_diario": cfg["limite_diario"]}
        if item["usadas_hoy"] >= 10 ** 9:
            item["usadas_hoy"] = None
        if probar_proveedor == p and tiene:
            item.update(await probar(p, transporte))
        lista.append(item)
    return {"proveedores": lista, "sensibilidad_maxima": cfg["sensibilidad_maxima"],
            "ayuda": "Python: python3 scripts/modelos_activar.py claude  (o chatgpt) para poner la clave"}


async def probar(proveedor: str, transporte=None) -> dict:
    """Una pregunta sin datos de nadie para comprobar que la clave y el modelo funcionan."""
    t0 = time.monotonic()
    try:
        await _llamar(proveedor, [{"role": "system", "content": "Responde con el formato pedido."},
                                  {"role": "user", "content": "Prueba de funcionamiento: responde ok=true."}], ESQUEMA_PRUEBA, transporte)
        return {"prueba": {"ok": True, "segundos": round(time.monotonic() - t0, 2), "detalle": "responde correctamente"}}
    except (ErrorExterno, RespuestaInvalida) as e:
        return {"prueba": {"ok": False, "segundos": 0, "detalle": str(e)}}
    except httpx.HTTPError as e:
        return {"prueba": {"ok": False, "segundos": 0, "detalle": f"no se ha podido conectar ({type(e).__name__})"}}
