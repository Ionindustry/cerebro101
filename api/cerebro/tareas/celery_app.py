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
                        "cerebro.tareas.celery_app.enviar_avisos_correo": {"queue": "lote"},
                        "cerebro.tareas.celery_app.vigilar_motor": {"queue": "lote"},
                        "cerebro.tareas.celery_app.purgar_subidas": {"queue": "lote"},
                        "cerebro.tareas.celery_app.pedir_viabilidad": {"queue": "peticiones"},
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
                          "avisos-por-correo": {"task": "cerebro.tareas.celery_app.enviar_avisos_correo", "schedule": 300.0},
                          "vigilante-motor": {"task": "cerebro.tareas.celery_app.vigilar_motor", "schedule": 900.0},
                          "purgar-subidas": {"task": "cerebro.tareas.celery_app.purgar_subidas", "schedule": crontab(minute="17", hour="3")},
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


@app.task(name="cerebro.tareas.celery_app.pedir_viabilidad", bind=True, max_retries=3)
def pedir_viabilidad(self, lid: int) -> dict:
    """Una persona ha pedido el informe de viabilidad de una licitación del embudo (botón «Pedir informe de viabilidad»). Si el modelo no está disponible se reintenta hasta 3
    veces con espera creciente; si no hay manera, o falla de otro modo, la petición queda anotada como error para que el panel lo diga. Consultivo: no cambia estado ni decisión."""
    import logging
    from ..licitaciones import embudo, rastreo
    try:
        informe = asyncio.run(rastreo.valorar(lid, _ejecutar, reemplazar=True))
    except rastreo.FALLOS_DEL_MODELO:
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=min(60 * 2 ** self.request.retries, 900))
        asyncio.run(embudo.cerrar_peticion_viabilidad(lid, "El modelo de IA no está disponible ahora: inténtalo de nuevo en unos minutos"))
        return {"estado": "error", "motivo": "modelo no disponible"}
    except Exception as e:      # noqa: BLE001 — cualquier otro fallo deja la petición como error, no «en curso» para siempre
        logging.getLogger("cerebro.tareas").warning("pedir_viabilidad %s: %s: %s", lid, type(e).__name__, e)
        asyncio.run(embudo.cerrar_peticion_viabilidad(lid, "No se ha podido generar el informe: inténtalo de nuevo"))
        return {"estado": "error", "motivo": type(e).__name__}
    return {"estado": "ok", "recomendacion": informe["recomendacion"]}


@app.task(name="cerebro.tareas.celery_app.redactar_oferta", bind=True, max_retries=4)
def redactar_oferta(self, ejecucion_id: int) -> dict:
    """Una persona ha pulsado «Preparar la oferta»: los agentes de Licitaciones redactan el borrador, uno detrás de otro (cerebro/licitaciones/redaccion.py). Si el modelo no está
    disponible se reintenta con espera creciente SIN repetir los pasos ya hechos; si no hay manera, la ejecución se cierra con lo que haya y lo escrito se conserva."""
    import logging
    from ..licitaciones import redaccion
    try:
        return asyncio.run(redaccion.ejecutar(ejecucion_id, _ejecutar))
    except redaccion.FALLOS_DEL_MODELO:
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=min(60 * 2 ** self.request.retries, 900))
        return asyncio.run(redaccion.cerrar(ejecucion_id, "El modelo de IA no está disponible ahora: lo hecho se conserva; vuelve a pulsar el botón en unos minutos"))
    except Exception as e:      # noqa: BLE001 — la ejecución no puede quedarse «en curso» para siempre
        logging.getLogger("cerebro.tareas").warning("redactar_oferta %s: %s: %s", ejecucion_id, type(e).__name__, e)
        return asyncio.run(redaccion.cerrar(ejecucion_id, f"No se ha podido terminar la redacción ({type(e).__name__})"))


@app.task(name="cerebro.tareas.celery_app.purgar_subidas")
def purgar_subidas() -> dict:
    """Cada noche borra los documentos subidos al chat que pasan de `subidas.retencion_dias` (config/integraciones.yaml): el fichero y su texto."""
    from ..subidas import purgar
    return asyncio.run(purgar())


@app.task(name="cerebro.tareas.celery_app.vigilar_motor")
def vigilar_motor() -> dict:
    """Cada 15 minutos mira si la ingesta del motor de licitaciones está atascada y avisa por correo interno: al empezar, cada 24 h mientras siga y al arreglarse
    (cerebro/licitaciones/vigilante.py). No usa el modelo de IA."""
    from ..licitaciones.vigilante import vigilar
    return asyncio.run(vigilar())


@app.task(name="cerebro.tareas.celery_app.enviar_avisos_correo")
def enviar_avisos_correo() -> dict:
    """Envía por correo los avisos pendientes de las alertas con canal «correo» (cada 5 minutos). Correo interno, solo a direcciones de la empresa;
    lo que falla se reintenta en el siguiente ciclo (cerebro/licitaciones/avisos_correo.py)."""
    from ..licitaciones.avisos_correo import enviar_pendientes
    return asyncio.run(enviar_pendientes())
