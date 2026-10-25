"""Tareas programadas y colas de trabajo.

Jarvis lo atiende la API directamente, sin cola, para que la conversación en directo
nunca espere. Las demás tareas van a dos colas:
  - peticiones: tareas largas pedidas por personas
  - lote:       tareas programadas (Radar, noticias, tarifas…), sobre todo de noche
El calendario se genera a partir del campo «horario» de cada ficha de agente.
"""
from __future__ import annotations

import asyncio
import uuid

from celery import Celery
from celery.schedules import crontab

from ..ajustes import ajustes
from ..llm import ModeloNoDisponible, ModeloOcupado, ModeloTimeout
from ..registro import registro

app = Celery("cerebro", broker=ajustes.redis_url, backend=ajustes.redis_url)
app.conf.timezone = ajustes.zona_horaria
app.conf.task_routes = {"cerebro.tareas.celery_app.ejecutar_programada": {"queue": "lote"},
                        "cerebro.tareas.celery_app.volcar_constancia": {"queue": "peticiones"}}


def _calendario() -> dict:
    tareas = {}
    for f in registro().programados():
        minuto, hora, dia_mes, mes, dia_semana = f.horario.split()
        tareas[f"agente-{f.id}"] = {
            "task": "cerebro.tareas.celery_app.ejecutar_programada",
            "schedule": crontab(minute=minuto, hour=hora, day_of_month=dia_mes,
                                month_of_year=mes, day_of_week=dia_semana),
            "args": (f.id,),
        }
    return tareas


app.conf.beat_schedule = {**_calendario(),
                          "constancia-pendiente": {"task": "cerebro.tareas.celery_app.volcar_constancia", "schedule": 300.0}}


async def _ejecutar(agente_id: str) -> dict:
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    from ..grafo import construir
    from ..observabilidad import callbacks, metadatos
    ficha = registro().fichas[agente_id]
    async with AsyncPostgresSaver.from_conn_string(ajustes.database_url) as cp:
        g = construir(cp)
        hilo = f"programada-{agente_id}-{uuid.uuid4()}"
        return await g.ainvoke({"peticion": f"Tarea programada. Haz tu trabajo periódico: {ficha.tareas}. "
                                            "Resume lo encontrado y propone acciones si hacen falta.",
                                "agente": agente_id, "origen": "programada"},
                               {"configurable": {"thread_id": hilo}, "callbacks": callbacks(),
                                "metadata": metadatos(hilo, f"agente:{agente_id}")})


@app.task(name="cerebro.tareas.celery_app.volcar_constancia")
def volcar_constancia() -> dict:
    """Vuelca a registro_acciones las filas que quedaron en el fichero local cuando la base no respondía."""
    from ..constancia import volcar_pendientes
    return asyncio.run(volcar_pendientes())


@app.task(name="cerebro.tareas.celery_app.ejecutar_programada",
          autoretry_for=(ModeloNoDisponible, ModeloOcupado, ModeloTimeout), retry_backoff=60, retry_backoff_max=900,
          retry_jitter=True, max_retries=4)
def ejecutar_programada(agente_id: str) -> dict:
    estado = asyncio.run(_ejecutar(agente_id))
    return {"agente": agente_id, "respuesta": estado.get("respuesta"),
            "acciones": len(estado.get("acciones", []))}
