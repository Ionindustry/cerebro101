"""Nodos del grafo de orquestación."""
from __future__ import annotations

import json
import logging

from langgraph.types import interrupt

from .. import herramientas as H
from ..aprobaciones import bandeja
from ..llm import ErrorModelo, chat
from ..politicas import AccionProhibida, nivel_para
from ..registro import registro
from ..router_modelos import asignar
from .estado import Estado
from .prompts import sistema_agente, sistema_director_departamento, sistema_director_general

log = logging.getLogger("cerebro.grafo")
MAX_PASOS = 5
INYECTAR_DEPARTAMENTO = {"erpnext", "conocimiento", "correo", "calendario"}

def inyectar(ficha, estado: dict, herramienta: str, args: dict) -> dict:
    """Lo que decide el sistema (no el modelo): el departamento y la sensibilidad. Si el modelo los pasa, se pisan."""
    args = {k: v for k, v in args.items() if k != "sensibilidad"}    # la sensibilidad la fija `usar()`
    if herramienta in INYECTAR_DEPARTAMENTO:
        args["departamento"] = ficha.departamento
    return args


ESQUEMA_AGENTE = {
    "type": "object",
    "properties": {
        "tipo": {"type": "string", "enum": ["herramienta", "respuesta"]},
        "herramienta": {"type": "string"},
        "operacion": {"type": "string"},
        "argumentos": {"type": "object"},
        "respuesta": {"type": "string"},
        "acciones": {"type": "array", "items": {"type": "object", "properties": {
            "accion": {"type": "string"}, "herramienta": {"type": "string"}, "operacion": {"type": "string"},
            "argumentos": {"type": "object"}, "resumen": {"type": "string"}},
            "required": ["accion", "herramienta", "operacion", "resumen"]}},
    },
    "required": ["tipo"],
}


async def enrutar(estado: Estado) -> Estado:
    if estado.get("agente"):
        return {"departamento": registro().fichas[estado["agente"]].departamento}
    r = registro()
    ficha = r.fichas["director-general"]
    esquema = {"type": "object", "properties": {
        "departamento": {"type": "string", "enum": list(r.departamentos)}, "motivo": {"type": "string"}},
        "required": ["departamento", "motivo"]}
    mensajes = [{"role": "system", "content": sistema_director_general(
                    r.departamentos, {k: [f.nombre for f in r.del_departamento(k)] for k in r.departamentos})},
                {"role": "user", "content": estado["peticion"]}]
    try:
        d = await chat(asignar(ficha, estado.get("origen", "peticion")), mensajes, esquema=esquema, temperatura=0)
    except ErrorModelo:
        d = await chat(asignar(ficha, estado.get("origen", "peticion"), dificil=True), mensajes,
                       esquema=esquema, temperatura=0)
    return {"departamento": d["departamento"]}


async def elegir_agente(estado: Estado) -> Estado:
    if estado.get("agente"):
        return {}
    r = registro()
    dep = estado["departamento"]
    fichas = r.del_departamento(dep)
    director = r.director_de(dep)
    esquema = {"type": "object", "properties": {
        "agente": {"type": "string", "enum": [f.id for f in fichas]}, "motivo": {"type": "string"}},
        "required": ["agente", "motivo"]}
    mensajes = [{"role": "system", "content": sistema_director_departamento(r.departamentos[dep]["nombre"], fichas)},
                {"role": "user", "content": estado["peticion"]}]
    d = await chat(asignar(director, estado.get("origen", "peticion"), dificil=True), mensajes,
                   esquema=esquema, temperatura=0)
    return {"agente": d["agente"]}


async def ejecutar_agente(estado: Estado) -> Estado:
    ficha = registro().fichas[estado["agente"]]
    disponibles = H.disponibles_para(ficha)
    mensajes = [{"role": "system", "content": sistema_agente(ficha, disponibles)},
                {"role": "user", "content": estado["peticion"]}]
    pasos: list[dict] = []
    for _ in range(MAX_PASOS):
        try:
            d = await chat(asignar(ficha, estado.get("origen", "peticion")), mensajes, esquema=ESQUEMA_AGENTE)
        except ErrorModelo:
            d = await chat(asignar(ficha, estado.get("origen", "peticion"), dificil=True), mensajes,
                           esquema=ESQUEMA_AGENTE)
        if d["tipo"] == "respuesta":
            acciones = [{**a, "argumentos": a.get("argumentos", {}), "estado": "propuesta"}
                        for a in d.get("acciones", [])]
            return {"respuesta": d.get("respuesta", ""), "acciones": acciones, "pasos": pasos}
        args = inyectar(ficha, estado, d.get("herramienta", ""), d.get("argumentos") or {})
        try:
            resultado = await H.usar(ficha, d.get("herramienta", ""), d.get("operacion", ""),
                                     sensibilidad=estado.get("sensibilidad"), **args)
        except Exception as e:  # el error vuelve al modelo para que corrija o cambie de plan
            resultado = {"error": str(e)}
        pasos.append({"herramienta": d.get("herramienta"), "operacion": d.get("operacion"),
                      "ok": not (isinstance(resultado, dict) and "error" in resultado)})
        mensajes += [{"role": "assistant", "content": json.dumps(d, ensure_ascii=False)},
                     {"role": "user", "content": "Resultado: " + json.dumps(resultado, ensure_ascii=False,
                                                                            default=str)[:12000]}]
    return {"respuesta": "No he podido terminar la tarea en el número máximo de pasos.", "pasos": pasos,
            "acciones": []}


async def registrar_aprobaciones(estado: Estado, config) -> Estado:
    ficha = registro().fichas[estado["agente"]]
    hilo = config["configurable"]["thread_id"]
    acciones = []
    for a in estado.get("acciones", []):
        if a.get("solicitud_id"):
            acciones.append(a)
            continue
        try:
            d = nivel_para(ficha, a["accion"])
        except AccionProhibida as e:
            acciones.append({**a, "estado": "error", "resultado": str(e)})
            continue
        if a.get("herramienta") and a.get("operacion"):       # no se pide aprobar algo que va a fallar al ejecutarse
            motivo = H.validar_llamada(ficha, a["herramienta"], a["operacion"], a.get("argumentos") or {}, estado.get("sensibilidad"))
            if motivo:
                acciones.append({**a, "estado": "error", "resultado": f"Acción no válida, no se envía a aprobación: {motivo}"})
                continue
        if not d.requiere:
            acciones.append({**a, "estado": "aprobada"})
            continue
        sid = await bandeja.crear(hilo, ficha.id, ficha.departamento, a["accion"], d.nivel,
                                  d.aprobadores, d.voz_permitida,
                                  {"resumen": a["resumen"], "argumentos": a.get("argumentos", {})})
        acciones.append({**a, "solicitud_id": sid, "estado": "pendiente"})
    return {"acciones": acciones}


def esperar_aprobaciones(estado: Estado) -> Estado:
    pendientes = [a for a in estado.get("acciones", []) if a.get("estado") == "pendiente"]
    if not pendientes:
        return {}
    # El grafo se detiene aquí hasta que la API lo reanude con las decisiones:
    # {"<solicitud_id>": "aprobada" | "rechazada", ...}
    decisiones = interrupt({"pendientes": [{"id": a["solicitud_id"], "resumen": a["resumen"]} for a in pendientes]})
    return {"acciones": [{**a, "estado": decisiones.get(a.get("solicitud_id"), a["estado"])}
                         for a in estado["acciones"]]}


async def _dejar_constancia(hilo: str, ficha, a: dict, resultado: str) -> None:
    """Escribe en registro_acciones. Si falla, se grita en el log pero no se pierde el resultado de la acción."""
    try:
        await bandeja.registrar_accion(hilo, ficha.id, a["herramienta"], a["operacion"],
                                       a.get("solicitud_id"), resultado)
    except Exception:  # noqa: BLE001
        log.exception("NO SE PUDO REGISTRAR la acción ejecutada %s.%s (aprobación %s)",
                      a["herramienta"], a["operacion"], a.get("solicitud_id"))


async def ejecutar_acciones(estado: Estado, config) -> Estado:
    ficha = registro().fichas[estado["agente"]]
    hilo = config["configurable"]["thread_id"]
    resultado = []
    for a in estado.get("acciones", []):
        if a.get("estado") != "aprobada":
            resultado.append(a)
            continue
        args = inyectar(ficha, estado, a["herramienta"], a.get("argumentos") or {})
        try:
            r = await H.usar(ficha, a["herramienta"], a["operacion"], sensibilidad=estado.get("sensibilidad"),
                             aprobada=True, **args)
            resultado.append({**a, "estado": "ejecutada", "resultado": r})
            await _dejar_constancia(hilo, ficha, a, "OK: " + json.dumps(r, ensure_ascii=False, default=str))
        except Exception as e:
            resultado.append({**a, "estado": "error", "resultado": str(e)})
            await _dejar_constancia(hilo, ficha, a, f"ERROR: {type(e).__name__}: {e}")
    return {"acciones": resultado}
