"""API del Cerebro: la usan el panel, Jarvis (voz) y las tareas programadas."""
from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command
from pydantic import BaseModel

from ..ajustes import ajustes
from ..aprobaciones import bandeja
from ..aprobaciones.logica import DecisionNoValida
from ..cotizador import Solicitud, calcular
from ..grafo import construir
from ..observabilidad import callbacks
from ..red_instaladores import Oferta, puntuar
from ..registro import registro
from .auth import Usuario, usuario_actual

GRAFO = {}


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    async with AsyncPostgresSaver.from_conn_string(ajustes.database_url) as checkpointer:
        await checkpointer.setup()
        GRAFO["g"] = construir(checkpointer)
        yield


app = FastAPI(title="Cerebro 101.cat", version="0.1.0", lifespan=ciclo_de_vida)


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


@app.post("/jarvis/mensaje")
async def mensaje(m: Mensaje, usuario: Usuario = Depends(usuario_actual)):
    hilo = m.hilo or str(uuid.uuid4())
    config = {"configurable": {"thread_id": hilo}, "callbacks": callbacks()}
    estado = await GRAFO["g"].ainvoke({"peticion": m.texto, "usuario": usuario.id, "origen": m.origen,
                                       "sensibilidad": m.sensibilidad}, config)
    return _salida(estado, hilo)


@app.get("/aprobaciones")
async def ver_aprobaciones(usuario: Usuario = Depends(usuario_actual)):
    deps = None if "direccion" in usuario.roles else usuario.departamentos
    return await bandeja.pendientes(deps)


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
    config = {"configurable": {"thread_id": hilo}, "callbacks": callbacks()}
    estado = await GRAFO["g"].ainvoke(Command(resume=estados), config)
    return {"estado": s.estado, **_salida(estado, hilo)}


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
