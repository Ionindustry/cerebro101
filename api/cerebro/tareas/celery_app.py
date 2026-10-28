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
                        "cerebro.tareas.celery_app.resumen_licitaciones": {"queue": "lote"},
                        "cerebro.tareas.celery_app.rastreo_embudo": {"queue": "lote"},
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


def _resumen_licitaciones() -> dict:
    """El resumen diario de licitaciones para Dirección: a la hora de config/licitaciones.yaml (16:00), todos los días."""
    import yaml
    # Se lee el YAML directamente (sin importar el paquete de licitaciones) para que beat arranque ligero; sin el fichero, 16:00.
    try:
        hora, minuto = yaml.safe_load((ajustes.dir_config / "licitaciones.yaml").read_text(encoding="utf-8"))["resumen"]["hora"].split(":")
    except (OSError, KeyError, TypeError, ValueError):
        hora, minuto = "16", "00"
    return {"resumen-licitaciones": {"task": "cerebro.tareas.celery_app.resumen_licitaciones", "schedule": crontab(minute=minuto, hour=hora)}}


def _rastreo_embudo() -> dict:
    """El rastreo diario del embudo (Viabilidad valora las licitaciones detectadas): a la hora de config/licitaciones.yaml (06:30). Como el resumen, se lee el YAML directamente."""
    import yaml
    try:
        hora, minuto = yaml.safe_load((ajustes.dir_config / "licitaciones.yaml").read_text(encoding="utf-8"))["rastreo"]["hora"].split(":")
    except (OSError, KeyError, TypeError, ValueError):
        hora, minuto = "06", "30"
    return {"rastreo-embudo": {"task": "cerebro.tareas.celery_app.rastreo_embudo", "schedule": crontab(minute=minuto, hour=hora)}}


app.conf.beat_schedule = {**_calendario(), **_resumen_licitaciones(), **_rastreo_embudo(),
                          "constancia-pendiente": {"task": "cerebro.tareas.celery_app.volcar_constancia", "schedule": 300.0}}


async def _ejecutar(agente_id: str, peticion: str | None = None) -> dict:
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    from ..grafo import construir
    from ..observabilidad import callbacks, metadatos
    ficha = registro().fichas[agente_id]
    async with AsyncPostgresSaver.from_conn_string(ajustes.database_url) as cp:
        g = construir(cp)
        hilo = f"programada-{agente_id}-{uuid.uuid4()}"
        return await g.ainvoke({"peticion": peticion or f"Tarea programada. Haz tu trabajo periódico: {ficha.tareas}. "
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


def _reintentar_resumen(resultado: dict, reintentos: int, maximo: int) -> bool:
    """Solo se reintenta si el motor no respondió (resumen «sin_datos») y quedan reintentos; con datos, o agotados, se deja lo guardado."""
    return resultado["estado"] == "sin_datos" and reintentos < maximo


@app.task(name="cerebro.tareas.celery_app.resumen_licitaciones", bind=True, max_retries=3)
def resumen_licitaciones(self) -> dict:
    """Genera el resumen de licitaciones de las 16:00. No usa el modelo de IA (consulta el motor, puntúa y ordena). Si el motor no responde, el
    resumen se guarda igualmente diciéndolo (Dirección nunca recibe «nada» sin explicación) y se reintenta cada 15 minutos hasta 3 veces: el
    reintento sustituye al guardado, no lo duplica."""
    from ..licitaciones.resumen import generar
    r = asyncio.run(generar("programada"))
    if _reintentar_resumen(r, self.request.retries, self.max_retries):
        raise self.retry(countdown=900)
    return r


@app.task(name="cerebro.tareas.celery_app.rastreo_embudo",
          autoretry_for=(ModeloNoDisponible, ModeloOcupado, ModeloTimeout), retry_backoff=60, retry_backoff_max=900, retry_jitter=True, max_retries=4)
def rastreo_embudo() -> dict:
    """El Rastreador pide a Viabilidad el informe ir/no ir de las licitaciones detectadas (hasta rastreo.max_por_dia, de más a menos encaje). El informe es consultivo:
    no cambia el estado de nada. Si el modelo no está disponible se reintenta; lo ya valorado se conserva y no se repite (cerebro/licitaciones/rastreo.py)."""
    from ..licitaciones.rastreo import revisar
    return asyncio.run(revisar(_ejecutar))
