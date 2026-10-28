"""API del Cerebro: la usan el panel, Jarvis (voz) y las tareas programadas."""
from __future__ import annotations

import logging
import os
import uuid
from contextlib import asynccontextmanager

import psycopg
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command
from pydantic import BaseModel

from ..ajustes import ajustes
from ..aprobaciones import bandeja, objetivos
from ..aprobaciones.logica import DecisionNoValida
from .. import actividad, constancia, kpis, modelos_externos, oficina
from ..licitaciones import resumen as resumen_licitaciones
from ..cotizador import Solicitud, calcular
from ..grafo import construir, nodos
from ..llm import ErrorModelo, circuito, estado_modelos
from ..observabilidad import callbacks, metadatos
from ..red_instaladores import Oferta, puntuar
from ..registro import registro
from ..router_modelos import modelos_necesarios
from .auth import Usuario, usuario_actual

GRAFO = {}
log = logging.getLogger("cerebro.api")


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    async with AsyncPostgresSaver.from_conn_string(ajustes.database_url) as checkpointer:
        try:
            await checkpointer.setup()
        except psycopg.errors.InsufficientPrivilege:
            # Con el rol de la aplicación (sin permiso para crear tablas) las migraciones las hace el servicio «migraciones»
            log.info("Sin permiso para crear tablas: se usan las que dejó el servicio «migraciones»")
        GRAFO["g"] = construir(checkpointer)
        try:
            await constancia.volcar_pendientes()          # filas que no se pudieron escribir antes de un reinicio
        except Exception:  # noqa: BLE001
            log.exception("No se pudo volcar la constancia pendiente")
        yield


app = FastAPI(title="Cerebro 101.cat", version="0.1.0", lifespan=ciclo_de_vida)


@app.exception_handler(ErrorModelo)
async def error_del_modelo(_, e: ErrorModelo):
    """Un problema del modelo de IA no es un error interno: se explica y se dice cuándo reintentar."""
    log.warning("Modelo de IA: %s (%s)", e.codigo, e)
    cabeceras = {"Retry-After": str(e.reintentar_en)} if e.reintentar_en else {}
    return JSONResponse(status_code=e.http, headers=cabeceras,
                        content={"detail": str(e), "codigo": e.codigo, "reintentar_en": e.reintentar_en})


class Mensaje(BaseModel):
    texto: str
    hilo: str | None = None
    origen: str = "jarvis"
    sensibilidad: str | None = None


class Decision(BaseModel):
    aprobado: bool
    canal: str = "panel"         # panel | voz
    comentario: str = ""


def _salida(estado: dict, hilo: str) -> dict:
    interrupcion = estado.get("__interrupt__")
    return {
        "hilo": hilo,
        "departamento": estado.get("departamento"),
        "agente": estado.get("agente"),
        "respuesta": estado.get("respuesta"),
        "acciones": estado.get("acciones", []),
        "esperando_aprobacion": bool(interrupcion),
    }


@app.get("/salud")
async def salud():
    r = registro()
    return {"estado": "ok", "agentes": len(r.fichas), "departamentos": len(r.departamentos),
            "perfil_hardware": ajustes.perfil_hardware, "modo": os.environ.get("CEREBRO_MODO", "produccion")}


@app.get("/salud/constancia")
async def salud_constancia():
    """503 mientras haya acciones ejecutadas sin constancia en la base (pendientes de volcar o rechazadas por la base y sin revisar): es lo que debe vigilar la monitorización."""
    n, r = constancia.pendientes(), constancia.rechazadas()
    cuerpo = {"pendientes": n, "rechazadas": r, "fallos_desde_el_arranque": constancia.ESTADO["fallos"],
              "ultimo_fallo": constancia.ESTADO["ultimo_fallo"]}
    return JSONResponse(status_code=503 if (n or r) else 200, content=cuerpo)


@app.get("/salud/jev")
async def salud_jev(probar: bool = False):
    """Estado de las vías de decisión (Jev en la nube, jeff autoalojado y modelo local) y cuál usará cada sensibilidad. No devuelve ninguna clave."""
    from ..herramientas import decision
    return await decision.estado(probar)


@app.get("/salud/modelos")
async def salud_modelos():
    """¿Responde Ollama y están descargados los modelos del perfil? (lo usa la verificación del despliegue)"""
    return await estado_modelos(modelos_necesarios())


@app.get("/modelos-externos")
async def ver_modelos_externos(probar: str | None = None, usuario: Usuario = Depends(usuario_actual)):
    """Claude y ChatGPT para consultas complejas: si están conectados, si tienen clave y cuánto se han usado hoy. No devuelve ninguna clave.
    `probar=claude|chatgpt` hace una pregunta de prueba (sin datos de nadie); solo Dirección."""
    if probar:
        _exigir_direccion(usuario)
        if probar not in modelos_externos.CLAVES:
            raise HTTPException(404, "Proveedor desconocido")
    return await modelos_externos.estado(probar)


class Interruptor(BaseModel):
    activo: bool


def _exigir_direccion(usuario: Usuario) -> None:
    if "direccion" not in usuario.roles:
        raise HTTPException(403, "Solo Dirección puede conectar o desconectar los modelos externos")


@app.post("/modelos-externos/{proveedor}")
async def cambiar_modelo_externo(proveedor: str, i: Interruptor, usuario: Usuario = Depends(usuario_actual)):
    """Conecta o desconecta un modelo externo. Solo Dirección, y solo si tiene clave; queda constancia de quién y cuándo."""
    _exigir_direccion(usuario)
    if proveedor not in modelos_externos.CLAVES:
        raise HTTPException(404, "Proveedor desconocido")
    if i.activo and not modelos_externos.clave(proveedor):
        raise HTTPException(409, f"Falta la clave de {proveedor}: ponla con «python3 scripts/modelos_activar.py {proveedor}» y recrea la API")
    try:
        await modelos_externos.poner(proveedor, i.activo, usuario.id)
    except Exception as e:  # noqa: BLE001
        log.exception("No se pudo guardar el estado de %s", proveedor)
        raise HTTPException(503, "No se ha podido guardar el cambio (la base de datos no responde)") from e
    await constancia.dejar_constancia(None, usuario.id, "modelos_externos", "conectar" if i.activo else "desconectar", None,
                                      f"{proveedor} {'conectado' if i.activo else 'desconectado'} por {usuario.id}")
    return await modelos_externos.estado()


@app.post("/jarvis/mensaje")
async def mensaje(m: Mensaje, usuario: Usuario = Depends(usuario_actual)):
    hilo = m.hilo or str(uuid.uuid4())
    config = {"configurable": {"thread_id": hilo}, "callbacks": callbacks(), "metadata": metadatos(hilo, usuario.id)}
    estado = await GRAFO["g"].ainvoke({"peticion": m.texto, "usuario": usuario.id, "origen": m.origen,
                                       "sensibilidad": m.sensibilidad}, config)
    return _salida(estado, hilo)


@app.post("/jarvis/enrutar")
async def enrutar_peticion(m: Mensaje, usuario: Usuario = Depends(usuario_actual)):
    """Solo decide departamento y agente (sin ejecutar nada ni crear aprobaciones); sirve para medir el enrutado."""
    estado = {"peticion": m.texto, "usuario": usuario.id, "origen": m.origen}
    estado.update(await nodos.enrutar(estado))
    estado.update(await nodos.elegir_agente(estado))
    return {"departamento": estado["departamento"], "agente": estado["agente"]}


@app.get("/aprobaciones")
async def ver_aprobaciones(usuario: Usuario = Depends(usuario_actual)):
    deps = None if "direccion" in usuario.roles else usuario.departamentos
    return await bandeja.pendientes(deps)


@app.get("/aprobaciones/historial")
async def ver_historial(decision: str | None = None, q: str | None = None, pagina: int = 0, limite: int = 30,
                        departamento: str | None = None, usuario: Usuario = Depends(usuario_actual)):
    """Aprobaciones ya resueltas (aprobadas y rechazadas): se guardan todas. Dirección las ve todas; el resto, las de sus departamentos.
    `departamento` filtra por uno."""
    deps = None if "direccion" in usuario.roles else usuario.departamentos
    return await bandeja.historial(deps, decision, q, limite, pagina, departamento)


@app.get("/aprobaciones/resumen")
async def resumen_aprobaciones(dias: int = 30, usuario: Usuario = Depends(usuario_actual)):
    """Dashboard de Aprobaciones: pendientes, resueltas, tiempos, por departamento, por día, agentes y acciones más frecuentes."""
    deps = None if "direccion" in usuario.roles else usuario.departamentos
    return await bandeja.resumen(deps, dias)


def _ve_licitaciones(usuario: Usuario) -> bool:
    """El resumen de licitaciones lo ve Dirección y el departamento de Licitaciones."""
    return "direccion" in usuario.roles or "licitaciones" in usuario.departamentos


@app.get("/licitaciones/resumenes")
async def listar_resumenes_licitaciones(limite: int = 14, usuario: Usuario = Depends(usuario_actual)):
    """Los últimos resúmenes diarios de licitaciones (el de las 16:00 y los generados a mano), del más reciente al más antiguo."""
    if not _ve_licitaciones(usuario):
        raise HTTPException(403, "El resumen de licitaciones es para Dirección y el departamento de Licitaciones")
    return await resumen_licitaciones.listar(limite)


@app.get("/licitaciones/resumenes/ultimo")
async def ultimo_resumen_licitaciones(usuario: Usuario = Depends(usuario_actual)):
    if not _ve_licitaciones(usuario):
        raise HTTPException(403, "El resumen de licitaciones es para Dirección y el departamento de Licitaciones")
    r = await resumen_licitaciones.leer()
    if r is None:
        raise HTTPException(404, "Todavía no hay ningún resumen")
    return r


@app.get("/licitaciones/resumenes/{rid}")
async def ver_resumen_licitaciones(rid: int, usuario: Usuario = Depends(usuario_actual)):
    if not _ve_licitaciones(usuario):
        raise HTTPException(403, "El resumen de licitaciones es para Dirección y el departamento de Licitaciones")
    r = await resumen_licitaciones.leer(rid)
    if r is None:
        raise HTTPException(404, "No existe ese resumen")
    return r


@app.post("/licitaciones/resumenes")
async def generar_resumen_licitaciones(usuario: Usuario = Depends(usuario_actual)):
    """Genera ahora un resumen (las últimas 24 horas) sin esperar a las 16:00: p. ej. si el equipo estaba apagado a esa hora. Es de consulta
    (no cambia nada del motor); si ya se generó uno a mano hace menos de un minuto, devuelve ese en vez de repetir la consulta."""
    if not _ve_licitaciones(usuario):
        raise HTTPException(403, "El resumen de licitaciones es para Dirección y el departamento de Licitaciones")
    r = await resumen_licitaciones.generar("manual")
    return await resumen_licitaciones.leer(r["id"])


class ObjetivoNuevo(BaseModel):
    titulo: str
    departamentos: list[str]
    agentes: list[str] = []
    operaciones: list[str]
    max_acciones: int = 20
    dias: float = 7


@app.get("/objetivos")
async def ver_objetivos(usuario: Usuario = Depends(usuario_actual)):
    """Objetivos permanentes (firma que cubre varias peticiones). Solo Dirección."""
    if "direccion" not in usuario.roles:
        raise HTTPException(403, "Solo Dirección gestiona los objetivos permanentes")
    return {"objetivos": await objetivos.listar(), "operaciones": objetivos.operaciones_cubribles(),
            "departamentos": sorted(registro().departamentos),
            "limites": {"max_dias": objetivos.MAX_DIAS, "max_acciones": objetivos.MAX_ACCIONES}}


@app.post("/objetivos")
async def crear_objetivo(o: ObjetivoNuevo, usuario: Usuario = Depends(usuario_actual)):
    if "direccion" not in usuario.roles:
        raise HTTPException(403, "Solo Dirección gestiona los objetivos permanentes")
    try:
        datos = objetivos.validar_nuevo(o.titulo, o.departamentos, o.agentes, o.operaciones, o.max_acciones, o.dias, registro())
    except objetivos.ObjetivoNoValido as e:
        raise HTTPException(422, str(e)) from e
    return {"id": await objetivos.crear(datos, usuario.id)}


@app.post("/objetivos/{oid}/revocar")
async def revocar_objetivo(oid: str, usuario: Usuario = Depends(usuario_actual)):
    if "direccion" not in usuario.roles:
        raise HTTPException(403, "Solo Dirección gestiona los objetivos permanentes")
    if not await objetivos.revocar(oid, usuario.id):
        raise HTTPException(404, "Objetivo no encontrado o ya revocado")
    return {"estado": "revocado"}


@app.post("/aprobaciones/{sid}")
async def decidir(sid: str, d: Decision, usuario: Usuario = Depends(usuario_actual)):
    try:
        s, hilo = await bandeja.registrar_decision(sid, usuario.id, usuario.roles, usuario.departamentos,
                                                   d.aprobado, d.canal, d.comentario)
    except DecisionNoValida as e:
        raise HTTPException(403, str(e)) from e
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    if s.estado == "pendiente":
        return {"estado": "pendiente", "mensaje": "Falta la segunda aprobación"}
    estados = await bandeja.estados_del_hilo(hilo)
    if any(e == "pendiente" for e in estados.values()):
        return {"estado": s.estado, "mensaje": "Decisión guardada; quedan otras acciones de esta petición por decidir"}
    config = {"configurable": {"thread_id": hilo}, "callbacks": callbacks(), "metadata": metadatos(hilo, usuario.id)}
    estado = await GRAFO["g"].ainvoke(Command(resume=estados), config)
    return {"estado": s.estado, **_salida(estado, hilo)}


@app.get("/oficina")
async def ver_oficina(usuario: Usuario = Depends(usuario_actual)):
    """La oficina del panel: departamentos, agentes y qué hace cada uno ahora. Sin base de datos se muestra todo en reposo."""
    try:
        snap = await actividad.instantanea()
    except Exception:  # noqa: BLE001
        log.warning("No se pudo leer la actividad de los agentes", exc_info=True)
        snap = {"actividad": {}, "pendientes": {}, "ultimas": []}
    return oficina.construir(registro(), snap, usuario.roles, usuario.departamentos)


@app.get("/oficina/agentes/{agente}")
async def ver_agente(agente: str, usuario: Usuario = Depends(usuario_actual)):
    """La ficha de un agente y, si es de tu departamento (o eres de dirección), lo que está haciendo y ha hecho."""
    ficha = registro().fichas.get(agente)
    if ficha is None:
        raise HTTPException(404, "Agente no encontrado")
    try:
        snap = await actividad.detalle_agente(agente)
    except Exception:  # noqa: BLE001
        log.warning("No se pudo leer el detalle de %s", agente, exc_info=True)
        snap = {"actividad": None, "pasos": [], "acciones": [], "pendientes": []}
    return oficina.detalle(ficha, snap, usuario.roles, usuario.departamentos)


@app.get("/agentes/{agente}/kpis")
async def kpis_del_agente(agente: str, dias: int = 30, usuario: Usuario = Depends(usuario_actual)):
    """El panel de KPI de un agente: rendimiento y KPI de su cargo (con cifras del ERP/CRM). Solo para dirección y el departamento del agente."""
    ficha = registro().fichas.get(agente)
    if ficha is None:
        raise HTTPException(404, "Agente no encontrado")
    if "direccion" not in usuario.roles and ficha.departamento not in usuario.departamentos:
        raise HTTPException(403, "Los KPI de este agente solo los ven su departamento y la dirección")
    try:
        return await kpis.calcular(ficha, kpis.cargar_config(str(ajustes.dir_config)), dias, kpis.Fuente())
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    except Exception as e:  # noqa: BLE001
        log.warning("No se pudieron calcular los KPI de %s", agente, exc_info=True)
        raise HTTPException(503, "No se han podido calcular los KPI ahora mismo") from e


@app.get("/departamentos/{dep}/kpis")
async def kpis_del_departamento(dep: str, dias: int = 30, usuario: Usuario = Depends(usuario_actual)):
    """Dashboard de un departamento: KPI específicos del ERP/CRM, actividad de todos sus agentes y reparto por agente. Dirección y ese departamento."""
    r = registro()
    if dep not in r.departamentos:
        raise HTTPException(404, "Departamento no encontrado")
    if "direccion" not in usuario.roles and dep not in usuario.departamentos:
        raise HTTPException(403, "El dashboard de este departamento solo lo ven su departamento y la dirección")
    try:
        return await kpis.calcular_departamento(dep, r, kpis.cargar_config(str(ajustes.dir_config)), dias, kpis.Fuente())
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    except Exception as e:  # noqa: BLE001
        log.warning("No se pudieron calcular los KPI del departamento %s", dep, exc_info=True)
        raise HTTPException(503, "No se han podido calcular los KPI ahora mismo") from e


@app.get("/departamentos")
async def departamentos():
    return registro().departamentos


@app.get("/agentes")
async def agentes(departamento: str | None = None):
    r = registro()
    fichas = r.del_departamento(departamento) if departamento else list(r.fichas.values())
    return [f.__dict__ for f in fichas]


@app.post("/cotizaciones/calcular")
async def cotizar(datos: dict, usuario: Usuario = Depends(usuario_actual)):
    try:
        return calcular(Solicitud(**datos)).como_dict()
    except (TypeError, ValueError) as e:
        raise HTTPException(422, str(e)) from e


@app.post("/instaladores/comparar")
async def comparar(datos: dict, usuario: Usuario = Depends(usuario_actual)):
    ofertas = [Oferta(**o) for o in datos.get("ofertas", [])]
    return [p.__dict__ for p in puntuar(ofertas, datos.get("pesos"))]
