"""Nodos del grafo de orquestación."""
from __future__ import annotations

import json
import logging
import os
import re

from langgraph.types import interrupt

from .. import herramientas as H
from .. import actividad, modelos_externos
from ..aprobaciones import bandeja, objetivos
from ..constancia import dejar_constancia
from ..llm import ContextoLleno, RespuestaInvalida, chat
from .contexto import limite_resultado, recortar
from ..politicas import AccionProhibida, nivel_para
from ..registro import registro
from ..router_modelos import asignar
from .estado import Estado
from .prompts import sistema_agente, sistema_director_departamento, sistema_director_general

log = logging.getLogger("cerebro.grafo")
MAX_PASOS = 5
# Los agentes que trabajan sobre un documento largo necesitan más vueltas: el Analista de Pliegos busca la licitación, lista y baja los documentos, busca y lee páginas
# y anota cada requisito con una llamada. Con 5 pasos no pasaba de buscar. Lo que anota queda guardado aunque la tarea se corte.
MAX_PASOS_AGENTE = {"analista-pliegos": 25}
INYECTAR_DEPARTAMENTO = {"erpnext", "conocimiento", "correo", "calendario", "cuaderno"}
PIDE_CUADERNO = re.compile(r"\bcuadern|\bquadern|notebook\s*lm", re.I)


def con_cuadernos(fichas) -> list:
    return [f for f in fichas if "cuaderno" in f.herramientas]


def corregir_por_cuaderno(peticion: str, departamento: str, agente: str | None = None) -> tuple[str, str | None]:
    """Si la petición pide un cuaderno de investigación y el departamento (o el agente) elegido no tiene cuadernos, lo
    corrige hacia quien sí los tiene. El modelo rápido que enruta confunde «cuaderno» con la base de conocimiento."""
    if not PIDE_CUADERNO.search(peticion):
        return departamento, agente
    r = registro()
    if not con_cuadernos(r.del_departamento(departamento)):
        departamento, agente = "direccion", None
    if agente is not None and "cuaderno" not in r.fichas[agente].herramientas:
        agente = con_cuadernos(r.del_departamento(departamento))[0].id
    return departamento, agente

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
    await actividad.marcar(ficha.id, "Decidiendo qué departamento atiende la petición")
    esquema = {"type": "object", "properties": {
        "departamento": {"type": "string", "enum": list(r.departamentos)}, "motivo": {"type": "string"}},
        "required": ["departamento", "motivo"]}
    mensajes = [{"role": "system", "content": sistema_director_general(
                    r.departamentos, {k: [f.nombre for f in r.del_departamento(k)] for k in r.departamentos})},
                {"role": "user", "content": estado["peticion"]}]
    try:
        try:
            d = await chat(asignar(ficha, estado.get("origen", "peticion")), mensajes, esquema=esquema, temperatura=0, max_tokens=400)
        except ContextoLleno:
            raise
        except RespuestaInvalida:
            d = await chat(asignar(ficha, estado.get("origen", "peticion"), dificil=True), mensajes,
                           esquema=esquema, temperatura=0, max_tokens=400)
    finally:
        await actividad.reposo(ficha.id)
    return {"departamento": corregir_por_cuaderno(estado["peticion"], d["departamento"])[0]}


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
    await actividad.marcar(director.id, "Eligiendo qué agente atiende la petición")
    try:
        d = await chat(asignar(director, estado.get("origen", "peticion"), dificil=True), mensajes,
                       esquema=esquema, temperatura=0, max_tokens=400)
    finally:
        await actividad.reposo(director.id)
    return {"agente": corregir_por_cuaderno(estado["peticion"], dep, d["agente"])[1]}


PASO_MAX_TOKENS = 1500          # un paso del agente es una llamada a herramienta o una respuesta: no necesita más


def _paso_valido(d: dict | None) -> bool:
    """¿Sirve la respuesta de un modelo externo? Una llamada a herramienta con nombre, o una respuesta con texto: si viene vacía, se usa el modelo local."""
    if not d:
        return False
    if d.get("tipo") == "herramienta":
        return bool(d.get("herramienta"))
    return d.get("tipo") == "respuesta" and bool(str(d.get("respuesta") or "").strip())


async def _paso_del_agente(ficha, estado: dict, mensajes: list[dict]) -> dict:
    """Una llamada al modelo con el contexto bajo control: recorta lo antiguo si no cabe y, si aun así el modelo dice que no
    cabe, lo recorta más y reintenta una vez. Si el modelo no da una respuesta válida, sube al modelo principal."""
    ctx = int(os.environ.get("OLLAMA_NUM_CTX") or 8192)
    presupuesto = ctx - PASO_MAX_TOKENS - 300
    origen = estado.get("origen", "peticion")
    entrada = recortar(mensajes, presupuesto)
    # Consulta compleja: si Dirección ha conectado Claude o ChatGPT (y los datos se pueden anonimizar), responde un modelo externo
    if modelos_externos.es_compleja(estado["peticion"]):
        d = await modelos_externos.consultar(ficha, entrada, ESQUEMA_AGENTE, estado.get("sensibilidad"))
        if _paso_valido(d):
            return d
    try:
        try:
            return await chat(asignar(ficha, origen), entrada, esquema=ESQUEMA_AGENTE, max_tokens=PASO_MAX_TOKENS)
        except ContextoLleno:
            return await chat(asignar(ficha, origen), recortar(mensajes, presupuesto // 2, minimo=500),
                              esquema=ESQUEMA_AGENTE, max_tokens=PASO_MAX_TOKENS)
    except ContextoLleno:
        raise
    except RespuestaInvalida:
        try:
            return await chat(asignar(ficha, origen, dificil=True), entrada, esquema=ESQUEMA_AGENTE, max_tokens=PASO_MAX_TOKENS)
        except RespuestaInvalida:
            # Ni el modelo principal local ha dado una respuesta válida: último recurso, un modelo externo (si procede)
            d = await modelos_externos.consultar(ficha, entrada, ESQUEMA_AGENTE, estado.get("sensibilidad"))
            if _paso_valido(d):
                return d
            raise


async def _ejecutar_agente(estado: Estado, ficha) -> Estado:
    disponibles = H.disponibles_para(ficha)
    mensajes = [{"role": "system", "content": sistema_agente(ficha, disponibles)},
                {"role": "user", "content": estado["peticion"]}]
    pasos: list[dict] = []
    for _ in range(MAX_PASOS_AGENTE.get(ficha.id, MAX_PASOS)):
        await actividad.marcar(ficha.id, "Pensando")
        d = await _paso_del_agente(ficha, estado, mensajes)
        if d["tipo"] == "respuesta":
            acciones = [{**a, "argumentos": a.get("argumentos", {}), "estado": "propuesta"}
                        for a in d.get("acciones", [])]
            return {"respuesta": d.get("respuesta", ""), "acciones": acciones, "pasos": pasos}
        args = inyectar(ficha, estado, d.get("herramienta", ""), d.get("argumentos") or {})
        await actividad.marcar(ficha.id, f"Usando {d.get('herramienta', '?')} · {d.get('operacion', '?')}")
        try:
            resultado = await H.usar(ficha, d.get("herramienta", ""), d.get("operacion", ""),
                                     sensibilidad=estado.get("sensibilidad"), **args)
        except Exception as e:  # el error vuelve al modelo para que corrija o cambie de plan
            resultado = {"error": str(e)}
        clave = f"{d.get('herramienta', '?')}.{d.get('operacion', '?')}"
        await actividad.contar(ficha.id, ("error:" if isinstance(resultado, dict) and "error" in resultado else "uso:") + clave)
        pasos.append({"herramienta": d.get("herramienta"), "operacion": d.get("operacion"),
                      "ok": not (isinstance(resultado, dict) and "error" in resultado)})
        mensajes += [{"role": "assistant", "content": json.dumps(d, ensure_ascii=False)},
                     {"role": "user", "content": "Resultado: " + json.dumps(resultado, ensure_ascii=False,
                                                                            default=str)[:limite_resultado()]}]
    return {"respuesta": "No he podido terminar la tarea en el número máximo de pasos.", "pasos": pasos,
            "acciones": []}


async def ejecutar_agente(estado: Estado, config=None) -> Estado:
    ficha = registro().fichas[estado["agente"]]
    hilo = (config or {}).get("configurable", {}).get("thread_id") if config else None
    await actividad.marcar(ficha.id, "Empieza a trabajar", hilo)
    await actividad.contar(ficha.id, "peticion")
    try:
        r = await _ejecutar_agente(estado, ficha)
    except BaseException:
        await actividad.reposo(ficha.id, "Terminó con error")
        raise
    ultimo = (r.get("pasos") or [{}])[-1]
    await actividad.reposo(ficha.id, f"Usó {ultimo['herramienta']} · {ultimo['operacion']}" if ultimo.get("herramienta") else "Atendió una petición")
    return r


async def registrar_aprobaciones(estado: Estado, config) -> Estado:
    """Decide qué acciones necesitan firma (ver politicas.clase_de) y las lleva a la bandeja.

    - Estándar (lecturas, borradores, propuestas…): se ejecutan sin firma.
    - Supervisadas (lo que sale de la empresa): una sola solicitud por petición. Si el objetivo se compone de varias acciones, se firma el objetivo una vez y
      no cada subtarea; la solicitud lleva la lista completa para revisarla antes de firmar.
    - Reservadas (compromisos económicos o legales): una solicitud por acción, siempre individual."""
    ficha = registro().fichas[estado["agente"]]
    hilo = config["configurable"]["thread_id"]
    acciones: list[dict] = []
    lote: list[tuple[int, dict, object, dict]] = []             # (posición, acción, decisión, datos) de las supervisadas
    for a in estado.get("acciones", []):
        if a.get("solicitud_id"):
            acciones.append(a)
            continue
        herramienta, operacion = a.get("herramienta", ""), a.get("operacion", "")
        try:
            d = nivel_para(ficha, a["accion"], externa=H.es_externa(herramienta, operacion), herramienta=herramienta, operacion=operacion)
        except AccionProhibida as e:
            acciones.append({**a, "estado": "error", "resultado": str(e)})
            continue
        if herramienta and operacion:       # no se pide aprobar algo que va a fallar al ejecutarse
            motivo = H.validar_llamada(ficha, herramienta, operacion, a.get("argumentos") or {}, estado.get("sensibilidad"))
            if motivo:
                acciones.append({**a, "estado": "error", "resultado": f"Acción no válida, no se envía a aprobación: {motivo}"})
                continue
        if not d.requiere:
            acciones.append({**a, "estado": "aprobada"})
            continue
        if d.clase == "supervisada" and herramienta and operacion:      # un objetivo permanente vigente ya la cubre: sin nueva firma
            try:
                oid = await objetivos.consumir(ficha.departamento, ficha.id, herramienta, operacion)
            except Exception:  # noqa: BLE001 — si no se puede comprobar, se pide la firma como siempre
                log.warning("No se pudo comprobar los objetivos permanentes", exc_info=True)
                oid = None
            if oid:
                acciones.append({**a, "estado": "aprobada", "objetivo_id": oid})
                await actividad.evento(ficha.id, f"«{a['accion']}» cubierta por un objetivo permanente", hilo)
                continue
        datos = {"resumen": a["resumen"], "argumentos": a.get("argumentos", {})}
        if herramienta and operacion:
            try:
                vista = await H.vista_previa(ficha, herramienta, operacion, a.get("argumentos") or {}, estado.get("sensibilidad"))
            except Exception as e:  # noqa: BLE001
                acciones.append({**a, "estado": "error", "resultado": f"No se puede preparar para aprobación: {e}"})
                continue
            if vista:
                datos["vista"] = vista
        if d.clase == "supervisada":
            lote.append((len(acciones), a, d, datos))
            acciones.append({**a, "estado": "pendiente"})
            continue
        sid = await bandeja.crear(hilo, ficha.id, ficha.departamento, a["accion"], d.nivel, d.aprobadores, d.voz_permitida, datos)
        acciones.append({**a, "solicitud_id": sid, "estado": "pendiente"})
        await actividad.evento(ficha.id, f"Propone «{a['accion']}» y espera aprobación", hilo)
        await actividad.contar(ficha.id, f"propuesta:{herramienta or '?'}.{operacion or '?'}")
    if lote:
        if len(lote) == 1:
            _, a, d, datos = lote[0]
            sid = await bandeja.crear(hilo, ficha.id, ficha.departamento, a["accion"], d.nivel, d.aprobadores, d.voz_permitida, datos)
        else:
            objetivo = " ".join(str(estado.get("peticion") or "").split())[:300]
            nivel = "doble" if any(d.nivel == "doble" for _, _, d, _ in lote) else "simple"
            decision = next(d for _, _, d, _ in lote if d.nivel == nivel)
            datos = {"resumen": f"Objetivo con {len(lote)} acciones" + (f": {objetivo[:120]}" if objetivo else ""), "objetivo": objetivo,
                     "acciones": [{"accion": a["accion"], "herramienta": a.get("herramienta"), "operacion": a.get("operacion"),
                                   "resumen": a["resumen"], "argumentos": dt.get("argumentos", {}), **({"vista": dt["vista"]} if "vista" in dt else {})}
                                  for _, a, _, dt in lote]}
            sid = await bandeja.crear(hilo, ficha.id, ficha.departamento, "objetivo", nivel, decision.aprobadores,
                                      all(d.voz_permitida for _, _, d, _ in lote), datos)
        for pos, a, _, _ in lote:
            acciones[pos] = {**acciones[pos], "solicitud_id": sid}
            await actividad.contar(ficha.id, f"propuesta:{a.get('herramienta') or '?'}.{a.get('operacion') or '?'}")
        await actividad.evento(ficha.id, f"Propone un objetivo con {len(lote)} acciones y espera aprobación" if len(lote) > 1
                               else f"Propone «{lote[0][1]['accion']}» y espera aprobación", hilo)
    return {"acciones": acciones}


def esperar_aprobaciones(estado: Estado) -> Estado:
    pendientes = [a for a in estado.get("acciones", []) if a.get("estado") == "pendiente"]
    if not pendientes:
        return {}
    # El grafo se detiene aquí hasta que la API lo reanude con las decisiones:
    # {"<solicitud_id>": "aprobada" | "rechazada", ...}
    unicas = {a["solicitud_id"]: a["resumen"] for a in reversed(pendientes)}          # un objetivo con varias acciones es una sola solicitud
    decisiones = interrupt({"pendientes": [{"id": sid, "resumen": r} for sid, r in unicas.items()]})
    return {"acciones": [{**a, "estado": decisiones.get(a.get("solicitud_id"), a["estado"])}
                         for a in estado["acciones"]]}


async def _dejar_constancia(hilo: str, ficha, a: dict, resultado: str) -> dict:
    if a.get("objetivo_id"):
        resultado = f"[objetivo {a['objetivo_id']}] {resultado}"
    """Escribe en registro_acciones con reintentos y cola local (ver constancia.py). Si no queda constancia en la base,
    devuelve un aviso para la persona; la acción ya se ejecutó y su resultado no se pierde."""
    estado = await dejar_constancia(hilo, ficha.id, a["herramienta"], a["operacion"], a.get("solicitud_id"), resultado)
    if estado == "ok":
        return {}
    return {"aviso": "La acción se ha ejecutado pero no ha podido quedar registrada en el registro de acciones" +
                     (" (queda en cola y se volcará sola)." if estado == "en_cola" else " y no se ha podido guardar: avisa a un administrador.")}


async def ejecutar_acciones(estado: Estado, config) -> Estado:
    ficha = registro().fichas[estado["agente"]]
    hilo = config["configurable"]["thread_id"]
    resultado = []
    for a in estado.get("acciones", []):
        if a.get("estado") != "aprobada":
            resultado.append(a)
            continue
        args = inyectar(ficha, estado, a["herramienta"], a.get("argumentos") or {})
        await actividad.marcar(ficha.id, f"Ejecuta {a['herramienta']} · {a['operacion']} (aprobada)", hilo)
        try:
            r = await H.usar(ficha, a["herramienta"], a["operacion"], sensibilidad=estado.get("sensibilidad"),
                             aprobada=True, **args)
            aviso = await _dejar_constancia(hilo, ficha, a, "OK: " + json.dumps(r, ensure_ascii=False, default=str))
            resultado.append({**a, "estado": "ejecutada", "resultado": r, **aviso})
        except Exception as e:
            aviso = await _dejar_constancia(hilo, ficha, a, f"ERROR: {type(e).__name__}: {e}")
            resultado.append({**a, "estado": "error", "resultado": str(e), **aviso})
    if any(a.get("estado") in ("ejecutada", "error") and a.get("solicitud_id") for a in resultado):
        await actividad.reposo(ficha.id, "Ejecutó una acción aprobada")
    return {"acciones": resultado}
