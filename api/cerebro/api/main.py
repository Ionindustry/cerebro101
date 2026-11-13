"""API del Cerebro: la usan el panel, Jarvis (voz) y las tareas programadas."""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import re
import time
import uuid
from contextlib import asynccontextmanager

import psycopg
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse, Response
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command
from pydantic import BaseModel, Field

from .. import subidas
from ..ajustes import ajustes
from ..aprobaciones import bandeja, objetivos
from ..aprobaciones.logica import DecisionNoValida
from .. import actividad, antivirus, constancia, copias, hoy, kpis, modelos_externos, oficina
from ..herramientas import licitaciones as motor_lic
from ..herramientas.licitaciones import MotorNoDisponible
from ..licitaciones import alertas as alertas_licitaciones
from ..licitaciones import calendario_plazos
from ..licitaciones import crm as crm_licitaciones
from ..licitaciones import frescura as frescura_licitaciones
from ..licitaciones import analisis_pliego, aptitud, revision_previa
from ..licitaciones import pliegos as pliegos_licitaciones
from ..licitaciones import fabricantes as fabricantes_dir
from ..licitaciones import ofertas as ofertas_licitaciones
from ..licitaciones import empresa as empresa_erp
from ..licitaciones import plantillas as plantillas_ofertas
from ..licitaciones import redaccion as redaccion_ofertas
from ..licitaciones import redaccion_externa as redaccion_externa_ofertas
from ..licitaciones import encargos as encargos_ofertas
from ..licitaciones import comparativa as comparativa_ofertas
from ..licitaciones import equivalencia as equivalencia_ofertas
from .. import precios_venta as precios_venta_pantalla
from .. import ranking_ventas
from .. import tarifas_auto as tarifas_automaticas
from .. import listas_precios as listas_precios_mod
from ..licitaciones import partidas as partidas_ofertas
from ..licitaciones import descubrimiento as descubrimiento_ofertas
from ..licitaciones import fichas as fichas_tecnicas
from ..licitaciones import reglas as reglas_licitaciones
from ..licitaciones import simulador as simulador_licitaciones
from ..licitaciones import embudo as embudo_licitaciones
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
    documentos: list[str] = []          # ids de documentos que la persona ha subido (POST /documentos/subir) y adjunta a este mensaje


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


_CACHE_HOY: dict = {}
CACHE_HOY_S = 30         # Jarvis pide «Hoy» cada minuto desde cada pestaña abierta: la misma lista (mismos permisos) se reutiliza 30 s para no repetir las consultas al ERP, al motor y al antivirus


@app.get("/hoy")
async def que_hacer_hoy(usuario: Usuario = Depends(usuario_actual)):
    """«Qué hacer hoy»: lo que necesita atención de quien abre Jarvis, ordenado por urgencia: aprobaciones pendientes de sus departamentos, plazos de licitaciones y requisitos por revisar (Dirección y Licitaciones) y el estado
    del sistema (Dirección y Tecnología). Solo lee. La lista depende SOLO de los permisos (roles y departamentos), no de quién eres: por eso se puede reutilizar entre pestañas con los mismos permisos."""
    datos = await _hoy_de(usuario)
    try:
        return hoy.sin_archivados(datos, await hoy.claves_archivadas(usuario.id))
    except Exception:  # noqa: BLE001 — si el archivo falla, la lista sale entera: mejor ver de más que no ver nada
        return {**datos, "archivados": 0}


async def _hoy_de(usuario: Usuario) -> dict:
    clave = (frozenset(usuario.roles), frozenset(usuario.departamentos))
    ahora = time.monotonic()
    guardada = _CACHE_HOY.get(clave)
    if guardada and ahora - guardada[0] < CACHE_HOY_S:
        return guardada[1]
    datos = await hoy.construir(set(usuario.roles), set(usuario.departamentos))
    if len(_CACHE_HOY) > 200:
        _CACHE_HOY.clear()
    _CACHE_HOY[clave] = (ahora, datos)
    return datos


class ClaveHoy(BaseModel):
    clave: str


@app.get("/hoy/archivo")
async def archivo_de_hoy(usuario: Usuario = Depends(usuario_actual)):
    """Lo vencido que esta persona ha archivado, lo último primero."""
    return {"items": await hoy.archivo(usuario.id)}


@app.post("/hoy/archivar")
async def archivar_en_hoy(c: ClaveHoy, usuario: Usuario = Depends(usuario_actual)):
    """Archiva un elemento vencido de la lista de esta persona. El texto lo pone el servidor desde la lista que ella ve, no el navegador."""
    item = next((i for i in (await _hoy_de(usuario))["items"] if i.get("clave") == c.clave), None)
    if not item:
        raise HTTPException(404, "Ese elemento ya no está en la lista de hoy")
    try:
        await hoy.archivar(usuario.id, item)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    return {"ok": True}


@app.post("/hoy/desarchivar")
async def desarchivar_en_hoy(c: ClaveHoy, usuario: Usuario = Depends(usuario_actual)):
    if not await hoy.desarchivar(usuario.id, c.clave):
        raise HTTPException(404, "Ese elemento no estaba archivado")
    return {"ok": True}


@app.get("/salud/antivirus")
async def salud_antivirus(usuario: Usuario = Depends(usuario_actual)):
    """El estado del antivirus para Jarvis: si responde y de cuándo son sus firmas (los documentos se rechazan con firmas de más de 48 horas)."""
    return await antivirus.estado()


@app.get("/salud/copias")
async def salud_copias(usuario: Usuario = Depends(usuario_actual)):
    """La tarjeta «Copias de seguridad» de Jarvis: la última copia (fecha, tamaño, si salió bien), la última correcta, si se ha probado la restauración y si hay que preocuparse (más de 3 días sin una buena).
    Sin rutas del servidor."""
    return await copias.estado()


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


class ElegirModelo(BaseModel):
    modelo: str = "auto"              # uno de los permitidos del proveedor, o «auto» para volver al de por defecto


@app.post("/modelos-externos/{proveedor}/modelo")
async def elegir_modelo_externo(proveedor: str, e: ElegirModelo, usuario: Usuario = Depends(usuario_actual)):
    """Dirección elige qué modelo usa un proveedor (p. ej. Claude Opus o Sonnet). Solo entre los permitidos en config/modelos_externos.yaml; queda constancia de quién y cuándo."""
    _exigir_direccion(usuario)
    if proveedor not in modelos_externos.CLAVES:
        raise HTTPException(404, "Proveedor desconocido")
    try:
        await modelos_externos.poner_modelo(proveedor, e.modelo, usuario.id)
    except ValueError as err:
        raise HTTPException(422, str(err)) from None
    except Exception as err:  # noqa: BLE001
        log.exception("No se pudo guardar el modelo de %s", proveedor)
        raise HTTPException(503, "No se ha podido guardar el cambio (la base de datos no responde)") from err
    await constancia.dejar_constancia(None, usuario.id, "modelos_externos", "elegir_modelo", None, f"{proveedor}: modelo {e.modelo[:60]} elegido por {usuario.id}")
    return await modelos_externos.estado()


@app.post("/jarvis/mensaje")
async def mensaje(m: Mensaje, usuario: Usuario = Depends(usuario_actual)):
    hilo = m.hilo or str(uuid.uuid4())
    peticion = m.texto
    if m.documentos:
        try:
            peticion += await subidas.para_chat(usuario.id, m.documentos)          # lo añade el sistema, solo con documentos de esta persona que han pasado el antivirus
        except subidas.ErrorSubida as e:
            raise HTTPException(422, str(e)) from None
    config = {"configurable": {"thread_id": hilo}, "callbacks": callbacks(), "metadata": metadatos(hilo, usuario.id)}
    # El estado del hilo se conserva entre mensajes: sin reiniciar «agente» y «departamento», el primer agente que atendió la conversación se quedaba con todo lo que se pidiera después
    # (el DEUC acababa en Infraestructura aunque el sistema lo enruta al Administrativo). Cada mensaje se enruta de nuevo.
    estado = await GRAFO["g"].ainvoke({"peticion": peticion, "usuario": usuario.id, "origen": m.origen, "sensibilidad": m.sensibilidad,
                                       "agente": None, "departamento": None}, config)
    return _salida(estado, hilo)


class DocumentoEntrada(BaseModel):
    nombre: str
    base64: str


@app.post("/documentos/subir")
async def subir_documento(entrada: DocumentoEntrada, usuario: Usuario = Depends(usuario_actual)):
    """Sube un documento al chat de Jarvis (JSON con el fichero en base64: la pasarela del panel solo lleva JSON). Pasa por cuarentena y antivirus; el agente solo recibirá su texto."""
    cfg = subidas.configuracion()
    if len(entrada.base64) > cfg["max_mb"] * 1_400_000:
        raise HTTPException(413, f"El documento pesa más de {cfg['max_mb']} MB")
    try:
        datos = base64.b64decode(entrada.base64, validate=True)
        r = await subidas.subir(usuario.id, entrada.nombre, datos, cfg=cfg)
    except (ValueError, subidas.ErrorSubida) as e:            # binascii.Error es un ValueError
        raise HTTPException(422, str(e) if isinstance(e, subidas.ErrorSubida) else "El documento no se ha recibido bien") from None
    log.info("subidas: %s sube «%s» (%s, %s)", usuario.id, r["nombre"], r["formato"], r["estado"])
    return r


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


# ---- Embudo propio (ADR 0007 §3-4): lo que 101.cat estudia, presenta, gana o pierde. Lo ven y lo cambian Dirección y el departamento de Licitaciones ----


class EstudiarEntrada(BaseModel):
    motor_id: str


class CambioEstadoEntrada(BaseModel):
    estado: str
    motivo_perdida: str | None = None


def _exige_licitaciones(usuario: Usuario) -> None:
    if not _ve_licitaciones(usuario):
        raise HTTPException(403, "El embudo de licitaciones es para Dirección y el departamento de Licitaciones")


@app.post("/licitaciones/motor/comprobar")
async def comprobar_actualizacion_de_licitaciones(usuario: Usuario = Depends(usuario_actual)):
    """Lo lanza el panel cada vez que se abre la aplicación: si lo último ingerido es viejo, pide al motor que actualice YA (el ingestor empieza en segundos, no espera a su intervalo).
    Para cualquier persona con sesión (es lo mismo que mirar el estado del motor): solo pide una vuelta, nunca ingiere nada ni cambia datos. Devuelve {estado, antiguedad_s, solicitada}."""
    return await frescura_licitaciones.comprobar(usuario.id)


@app.get("/licitaciones/embudo/resumen")
async def resumen_embudo_licitaciones(dias: int = 30, usuario: Usuario = Depends(usuario_actual)):
    """Dashboard de Licitaciones, bloque «Embudo propio»: foto por estado, lo ocurrido en el periodo, tasa de éxito y motivos de pérdida."""
    _exige_licitaciones(usuario)
    try:
        return await embudo_licitaciones.resumen(dias)
    except embudo_licitaciones.ErrorEmbudo as e:
        raise HTTPException(422, str(e)) from None


@app.get("/licitaciones/embudo")
async def listar_embudo_licitaciones(estado: str | None = None, motor_id: str | None = None, limite: int = 200,
                                     usuario: Usuario = Depends(usuario_actual)):
    _exige_licitaciones(usuario)
    try:
        return {"items": await embudo_licitaciones.listar(estado, motor_id, limite), "motivos_perdida": embudo_licitaciones.MOTIVOS_PERDIDA,
                "crm_url": crm_licitaciones.configuracion()["url_publica"],
                "transiciones": {k: sorted(v) for k, v in embudo_licitaciones.TRANSICIONES.items()}}
    except embudo_licitaciones.ErrorEmbudo as e:
        raise HTTPException(422, str(e)) from None


@app.post("/licitaciones/embudo/estudiar")
async def estudiar_licitacion(entrada: EstudiarEntrada, usuario: Usuario = Depends(usuario_actual)):
    """«Estudiar»: pasa un expediente del motor al embudo. Los datos se piden al motor desde el servidor."""
    _exige_licitaciones(usuario)
    try:
        fila = await embudo_licitaciones.estudiar(entrada.motor_id)
    except embudo_licitaciones.ErrorEmbudo as e:
        raise HTTPException(422, str(e)) from None
    except LookupError:
        raise HTTPException(404, "No existe ese expediente en el motor de licitaciones") from None
    except (MotorNoDisponible, ValueError) as e:
        raise HTTPException(503, f"No se ha podido consultar el motor de licitaciones: {e}") from None
    log.info("embudo: %s estudia %s (estado %s)", usuario.id, fila["motor_id"], fila["estado"])
    if fila.get("id"):
        await crm_licitaciones.anotar(fila["id"], "")      # el trato del CRM (si procede); nunca falla
        if fila.get("estado") == "en_estudio":
            _encolar_analisis_pliegos(fila["id"])          # los pliegos se descargan y se extraen sus requisitos solos (en borrador)
    return fila


def _encolar_analisis_pliegos(lid: int, forzar: bool = False) -> bool:
    """Encola el análisis automático de los pliegos de una licitación en estudio (cerebro/licitaciones/analisis_pliego.py). Es comodidad: si no hay cola, lo que hizo la persona ya está guardado."""
    try:
        from ..tareas.celery_app import app as celery
        celery.send_task("cerebro.tareas.celery_app.analizar_pliegos", args=[lid, forzar], queue="peticiones")
        return True
    except Exception as e:      # noqa: BLE001
        log.warning("embudo: no se ha podido encolar el análisis de los pliegos de %s: %s: %s", lid, type(e).__name__, e)
        return False


class ViabilidadEntrada(BaseModel):
    reemplazar: bool = False          # volver a pedirlo aunque ya haya informe (se sustituye)


@app.post("/licitaciones/embudo/{lid}/viabilidad", status_code=202)
async def pedir_viabilidad_licitacion(lid: int, entrada: ViabilidadEntrada | None = None, usuario: Usuario = Depends(usuario_actual)):
    """«Pedir informe de viabilidad»: encola que Viabilidad valore esta licitación (tarda: es un modelo de IA). Responde 202 con la petición en curso; el panel consulta el embudo
    hasta que aparece el informe. Es consultivo: no cambia el estado ni la decisión."""
    _exige_licitaciones(usuario)
    entrada = entrada or ViabilidadEntrada()
    try:
        peticion = await embudo_licitaciones.reservar_peticion_viabilidad(lid, usuario.id, entrada.reemplazar)
    except embudo_licitaciones.NoExiste as e:
        raise HTTPException(404, str(e)) from None
    except embudo_licitaciones.Conflicto as e:
        raise HTTPException(409, str(e)) from None
    except embudo_licitaciones.ErrorEmbudo as e:
        raise HTTPException(422, str(e)) from None
    try:
        from ..tareas.celery_app import app as celery
        celery.send_task("cerebro.tareas.celery_app.pedir_viabilidad", args=[lid], queue="peticiones")
    except Exception as e:      # noqa: BLE001 — sin cola no hay trabajo: se deshace la reserva para poder volver a pedirlo
        log.error("embudo: no se ha podido encolar la viabilidad de %s: %s: %s", lid, type(e).__name__, e)
        await embudo_licitaciones.cerrar_peticion_viabilidad(lid, "No se ha podido encolar la petición: inténtalo de nuevo")
        raise HTTPException(503, "No se ha podido encolar la petición") from None
    log.info("embudo: %s pide el informe de viabilidad de la licitación %s", usuario.id, lid)
    return {"id": lid, "viabilidad_peticion": peticion}


@app.post("/licitaciones/embudo/{lid}/crm")
async def enviar_licitacion_al_crm(lid: int, usuario: Usuario = Depends(usuario_actual)):
    """«Seguir en el CRM»: crea (o pone al día) el trato de la licitación en el CRM, con su nota de alta. Sirve para las que ya se estudiaban antes de conectar el CRM."""
    _exige_licitaciones(usuario)
    fila = await embudo_licitaciones.obtener(lid)
    if not fila:
        raise HTTPException(404, "No existe esa licitación en el embudo")
    if fila["estado"] in ("detectada", "descartada") and not (fila.get("crm") or {}).get("trato"):
        raise HTTPException(422, "Solo se sigue en el CRM una licitación que se estudia, se presenta o ya se ha resuelto")
    try:
        trato = await asyncio.wait_for(crm_licitaciones.asegurar_trato(lid), crm_licitaciones.configuracion()["limite_s"])
    except Exception as e:      # noqa: BLE001 — el CRM falla de muchas maneras: se dice sin ruido y se anota
        log.warning("embudo: no se ha podido llevar la licitación %s al CRM: %s: %s", lid, type(e).__name__, e)
        raise HTTPException(503, "No se ha podido escribir en el CRM. Inténtalo en unos minutos.") from None
    log.info("embudo: %s sigue la licitación %s en el CRM (trato %s)", usuario.id, lid, trato)
    return await embudo_licitaciones.obtener(lid)


@app.post("/licitaciones/embudo/{lid}/calendario")
async def poner_plazo_en_el_calendario(lid: int, usuario: Usuario = Depends(usuario_actual)):
    """«Añadir el plazo al calendario»: crea (o actualiza) un evento con el plazo de presentación en el calendario de la empresa, sin invitados. Lo hace una persona al pulsar."""
    _exige_licitaciones(usuario)
    try:
        fila = await calendario_plazos.poner(lid)
    except embudo_licitaciones.NoExiste as e:
        raise HTTPException(404, str(e)) from None
    except embudo_licitaciones.ErrorEmbudo as e:
        raise HTTPException(422, str(e)) from None
    except calendario_plazos.ErrorCalendario as e:
        raise HTTPException(503, str(e)) from None
    log.info("embudo: %s pone en el calendario el plazo de la licitación %s", usuario.id, lid)
    return fila


@app.post("/licitaciones/embudo/{lid}/calendario/quitar")
async def quitar_plazo_del_calendario(lid: int, usuario: Usuario = Depends(usuario_actual)):
    """«Quitar del calendario»: borra el evento del plazo (si estaba)."""
    _exige_licitaciones(usuario)
    try:
        fila = await calendario_plazos.quitar(lid)
    except embudo_licitaciones.NoExiste as e:
        raise HTTPException(404, str(e)) from None
    except calendario_plazos.ErrorCalendario as e:
        raise HTTPException(503, str(e)) from None
    log.info("embudo: %s quita del calendario el plazo de la licitación %s", usuario.id, lid)
    return fila


# ---- Pliegos de una licitación (cerebro/licitaciones/pliegos.py): documentos, texto y requisitos con cita. Solo Dirección y Licitaciones; nadie recibe el fichero ----

def _error_pliegos(e: Exception) -> HTTPException:
    if isinstance(e, pliegos_licitaciones.SinPermisoDescarga):
        return HTTPException(403, str(e))
    if isinstance(e, pliegos_licitaciones.ErrorPliego):
        return HTTPException(422, str(e))
    if isinstance(e, (pliegos_licitaciones.NoExiste, LookupError)):
        return HTTPException(404, str(e) or "No existe")
    return HTTPException(503, f"No se ha podido consultar el motor de licitaciones: {e}")


class DescargaPliego(BaseModel):
    n: int


class SubidaPliego(BaseModel):
    n: int
    base64: str                         # el fichero en base64 (la pasarela del panel solo lleva JSON)


class RevisionRequisito(BaseModel):
    estado: str                         # confirmado | rechazado | borrador


class CumplimientoRequisito(BaseModel):
    estado: str                         # pendiente | cumple | parcial | no_cumple | no_aplica
    nota: str = ""


@app.get("/licitaciones/pliegos/{motor_id}")
async def pliegos_de_la_licitacion(motor_id: str, usuario: Usuario = Depends(usuario_actual)):
    """Los documentos de la licitación (con su estado de descarga y antivirus) y los requisitos anotados."""
    _exige_licitaciones(usuario)
    try:
        reqs = aptitud.con_sugerencias((await pliegos_licitaciones.requisitos(motor_id))["requisitos"])      # + una orientación por requisito con el perfil de la empresa (no es el cumplimiento)
        return {**await pliegos_licitaciones.documentos(motor_id, con_enlace=True), "requisitos": reqs, "aptitud": aptitud.resumen(reqs), "analisis": await _analisis_de(motor_id)}
    except (pliegos_licitaciones.ErrorPliego, LookupError, MotorNoDisponible) as e:
        raise _error_pliegos(e) from None


async def _analisis_de(motor_id: str) -> dict | None:
    """El estado del análisis automático de los pliegos de esa licitación (si está en el embudo y se ha lanzado); nunca rompe la consulta."""
    try:
        filas = await embudo_licitaciones.listar(motor_id=motor_id, limite=1)
        return await analisis_pliego.leer(filas[0]["id"]) if filas else None
    except Exception as e:      # noqa: BLE001
        log.warning("pliegos: no se ha podido leer el análisis de %s: %s: %s", motor_id, type(e).__name__, e)
        return None


@app.get("/licitaciones/pliegos/{motor_id}/documentos/{n}/fichero")
async def fichero_del_pliego(motor_id: str, n: int, usuario: Usuario = Depends(usuario_actual)):
    """El fichero original de un documento del pliego, para descargarlo desde el panel (solo personas de Dirección y Licitaciones; los agentes nunca lo reciben). Solo si pasó el antivirus."""
    _exige_licitaciones(usuario)
    try:
        datos, nombre, tipo = await pliegos_licitaciones.fichero(motor_id, n)
    except (pliegos_licitaciones.ErrorPliego, LookupError) as e:
        raise _error_pliegos(e) from None
    log.info("pliegos: %s descarga el documento %s de %s (%d bytes)", usuario.id, n, motor_id, len(datos))
    from urllib.parse import quote
    return Response(content=datos, media_type=tipo, headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(nombre)}", "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store",
        "Content-Security-Policy": "default-src 'none'; sandbox"})


@app.post("/licitaciones/pliegos/{motor_id}/analizar", status_code=202)
async def analizar_pliegos_de_la_licitacion(motor_id: str, usuario: Usuario = Depends(usuario_actual)):
    """«Analizar los pliegos»: repite (o lanza) el análisis automático: se descargan los pliegos y el Analista anota los requisitos en borrador. Solo licitaciones en estudio. Tarda: es un modelo de IA."""
    _exige_licitaciones(usuario)
    try:
        filas = await embudo_licitaciones.listar(motor_id=motor_id, limite=1)
    except embudo_licitaciones.ErrorEmbudo as e:
        raise HTTPException(422, str(e)) from None
    if not filas:
        raise HTTPException(404, "Esa licitación no está en el embudo: pásala primero a «en estudio»")
    if filas[0]["estado"] != "en_estudio":
        raise HTTPException(422, "Solo se analizan los pliegos de las licitaciones en estudio")
    if not _encolar_analisis_pliegos(filas[0]["id"], forzar=True):
        raise HTTPException(503, "No se ha podido encolar el análisis")
    log.info("pliegos: %s pide analizar los pliegos de %s", usuario.id, motor_id)
    return {"licitacion": motor_id, "encolado": True}


@app.post("/licitaciones/pliegos/{motor_id}/descargar")
async def descargar_pliego(motor_id: str, entrada: DescargaPliego, usuario: Usuario = Depends(usuario_actual)):
    """«Descargar y analizar»: baja el documento nº n a cuarentena, lo pasa por el antivirus y lee su texto. Tarda unos segundos."""
    _exige_licitaciones(usuario)
    try:
        r = await pliegos_licitaciones.obtener(motor_id, entrada.n)
    except (pliegos_licitaciones.ErrorPliego, pliegos_licitaciones.SinPermisoDescarga, LookupError, MotorNoDisponible) as e:
        raise _error_pliegos(e) from None
    log.info("pliegos: %s baja el documento %s de %s (%s)", usuario.id, entrada.n, motor_id, r["estado"])
    return r


@app.post("/licitaciones/pliegos/{motor_id}/subir")
async def subir_pliego(motor_id: str, entrada: SubidaPliego, usuario: Usuario = Depends(usuario_actual)):
    """«Subir el pliego»: el documento nº n que una persona ha bajado de la plataforma con su navegador (la plataforma rechaza las descargas automáticas). Cuarentena, antivirus y lectura del texto, como los bajados."""
    _exige_licitaciones(usuario)
    cfg = pliegos_licitaciones.configuracion()
    if len(entrada.base64) > cfg["max_mb"] * 1_400_000:
        raise HTTPException(413, f"El documento pesa más de {cfg['max_mb']} MB")
    try:
        datos = base64.b64decode(entrada.base64, validate=True)
    except ValueError:                                  # binascii.Error es un ValueError
        raise HTTPException(422, "El documento no se ha recibido bien") from None
    try:
        r = await pliegos_licitaciones.subir(motor_id, entrada.n, datos, cfg=cfg)
    except (pliegos_licitaciones.ErrorPliego, LookupError, MotorNoDisponible) as e:
        raise _error_pliegos(e) from None
    log.info("pliegos: %s sube a mano el documento %s de %s (%s)", usuario.id, entrada.n, motor_id, r["estado"])
    return r


@app.get("/licitaciones/pliegos/{motor_id}/documentos/{n}/paginas/{pagina}")
async def pagina_de_un_pliego(motor_id: str, n: int, pagina: int, usuario: Usuario = Depends(usuario_actual)):
    """El texto de una página del documento (para comprobar una cita). Es texto de terceros."""
    _exige_licitaciones(usuario)
    try:
        return await pliegos_licitaciones.leer(motor_id, n, pagina)
    except pliegos_licitaciones.ErrorPliego as e:
        raise _error_pliegos(e) from None


@app.post("/licitaciones/pliegos/requisitos/{rid}/revisar")
async def revisar_requisito_de_pliego(rid: int, entrada: RevisionRequisito, usuario: Usuario = Depends(usuario_actual)):
    """Una persona confirma o rechaza un requisito que anotó el Analista de Pliegos. Queda registrado quién y cuándo."""
    _exige_licitaciones(usuario)
    try:
        f = await pliegos_licitaciones.revisar_requisito(rid, entrada.estado, usuario.id)
    except (pliegos_licitaciones.ErrorPliego, pliegos_licitaciones.NoExiste) as e:
        raise _error_pliegos(e) from None
    log.info("pliegos: %s marca el requisito %s como %s", usuario.id, rid, f["estado"])
    return f


@app.get("/licitaciones/pliegos/{motor_id}/matriz")
async def matriz_de_cumplimiento(motor_id: str, usuario: Usuario = Depends(usuario_actual)):
    """La matriz de cumplimiento: los requisitos confirmados con su cita y si 101.cat los cumple, con un resumen."""
    _exige_licitaciones(usuario)
    try:
        return await pliegos_licitaciones.matriz(motor_id)
    except (pliegos_licitaciones.ErrorPliego, LookupError) as e:
        raise _error_pliegos(e) from None


@app.post("/licitaciones/pliegos/requisitos/{rid}/cumplimiento")
async def marcar_cumplimiento_de_requisito(rid: int, entrada: CumplimientoRequisito, usuario: Usuario = Depends(usuario_actual)):
    """Una persona anota si 101.cat cumple un requisito confirmado (con el porqué si es parcial o no). Queda registrado quién y cuándo."""
    _exige_licitaciones(usuario)
    try:
        f = await pliegos_licitaciones.marcar_cumplimiento(rid, entrada.estado, entrada.nota, usuario.id)
    except (pliegos_licitaciones.ErrorPliego, pliegos_licitaciones.NoExiste) as e:
        raise _error_pliegos(e) from None
    log.info("pliegos: %s anota el cumplimiento del requisito %s: %s", usuario.id, rid, f["cumplimiento"])
    return f


class SimulacionEntrada(BaseModel):
    motor_id: str
    coste: float | None = None          # coste estimado sin IVA, en euros (opcional)
    presupuesto_erp: str | None = None  # o el código de un presupuesto (Quotation) del ERP, del que se saca el coste (opcional)


@app.post("/licitaciones/simulador")
async def simular_oferta(entrada: SimulacionEntrada, usuario: Usuario = Depends(usuario_actual)):
    """Simulador de ofertas: con qué baja se ha ganado en concursos parecidos y qué probabilidad y margen daría cada precio. Orientativo: el precio lo decide una persona."""
    _exige_licitaciones(usuario)
    try:
        r = await simulador_licitaciones.simular_completo(entrada.motor_id, entrada.coste, entrada.presupuesto_erp, cfg=resumen_licitaciones.config())
    except simulador_licitaciones.ErrorSimulador as e:
        raise HTTPException(422, str(e)) from None
    except MotorNoDisponible as e:
        raise HTTPException(503, f"No se ha podido consultar el motor de licitaciones: {e}") from None
    except LookupError as e:
        raise HTTPException(404, str(e) or "No existe esa licitación") from None
    log.info("simulador: %s simula %s (muestra %s, apto %s)", usuario.id, entrada.motor_id, r["muestra"]["n"], r["apto_para_decidir"])
    return r


class ReglasPrecioEntrada(BaseModel):
    motor_id: str
    formula: str
    puntos_precio: float
    puntos_total: float | None = None
    baja_tope_pct: float | None = None
    baja_anormal_pct: float | None = None
    nota: str = ""


@app.get("/licitaciones/reglas-precio/{motor_id}")
async def leer_reglas_precio(motor_id: str, usuario: Usuario = Depends(usuario_actual)):
    """Las reglas de puntuación del precio que una persona anotó del pliego (para el simulador); {} si no hay."""
    _exige_licitaciones(usuario)
    try:
        return await reglas_licitaciones.leer(motor_id) or {}
    except reglas_licitaciones.ErrorReglas as e:
        raise HTTPException(422, str(e)) from None


@app.post("/licitaciones/reglas-precio")
async def guardar_reglas_precio(entrada: ReglasPrecioEntrada, usuario: Usuario = Depends(usuario_actual)):
    """Una PERSONA anota cómo puntúa el pliego el precio (fórmula, puntos, umbral de baja anormal). El agente no tiene esta operación."""
    _exige_licitaciones(usuario)
    try:
        return await reglas_licitaciones.guardar(entrada.motor_id, entrada.model_dump(exclude={"motor_id"}), usuario.id)
    except reglas_licitaciones.ErrorReglas as e:
        raise HTTPException(422, str(e)) from None


@app.post("/licitaciones/reglas-precio/{motor_id}/borrar")
async def borrar_reglas_precio(motor_id: str, usuario: Usuario = Depends(usuario_actual)):
    _exige_licitaciones(usuario)
    try:
        return {"borrada": await reglas_licitaciones.borrar(motor_id)}
    except reglas_licitaciones.ErrorReglas as e:
        raise HTTPException(422, str(e)) from None


# ---- Ofertas de licitación (cerebro/licitaciones/ofertas.py): el borrador por secciones que redactan los agentes; revisar, aprobar y fijar el precio lo hace una PERSONA ----

class SeccionOfertaEntrada(BaseModel):
    motor_id: str
    sobre: str
    clave: str
    contenido: str
    citas: list[int] | None = None
    titulo: str | None = None


class EstadoSeccionEntrada(BaseModel):
    estado: str


class PrecioOfertaEntrada(BaseModel):
    precio: float
    iva_pct: float | None = None


def _oferta_error(e: Exception):
    if isinstance(e, ofertas_licitaciones.NoExiste):
        return HTTPException(404, str(e))
    if isinstance(e, MotorNoDisponible):
        return HTTPException(503, f"No se ha podido consultar el motor de licitaciones: {e}")
    if isinstance(e, LookupError):
        return HTTPException(404, str(e) or "No existe esa licitación")
    return HTTPException(422, str(e))


@app.get("/licitaciones/ofertas/{motor_id}")
async def leer_oferta(motor_id: str, usuario: Usuario = Depends(usuario_actual)):
    """La oferta de la licitación con todas sus secciones; {"existe": false} si aún no se ha preparado."""
    _exige_licitaciones(usuario)
    try:
        return await ofertas_licitaciones.leer(motor_id)
    except ofertas_licitaciones.ErrorOferta as e:
        raise _oferta_error(e) from None


@app.post("/licitaciones/ofertas/{motor_id}/preparar")
async def preparar_oferta(motor_id: str, usuario: Usuario = Depends(usuario_actual)):
    """Crea las secciones de la oferta a partir del pliego (criterios de la ficha y requisitos confirmados). Idempotente: no toca lo ya escrito."""
    _exige_licitaciones(usuario)
    try:
        ficha = await motor_lic._get(f"/tenders/{motor_id.strip().lower()}") if motor_lic._UUID.match(motor_id.strip()) else {}
        return await ofertas_licitaciones.plan(motor_id, ficha, usuario.id)
    except (ofertas_licitaciones.ErrorOferta, MotorNoDisponible, LookupError) as e:
        raise _oferta_error(e) from None


async def _fijar_sociedad(motor_id: str, oferta: dict, empresa: str | None) -> None:
    """Deja elegida la sociedad con la que se presenta la oferta. Si el ERP tiene varias y no se ha elegido, VariasEmpresas (el panel pide elegir). Si el ERP no responde, se sigue: lo dirá la
    documentación administrativa cuando haga falta, y el resto de la oferta no depende de ello."""
    try:
        nombre = await empresa_erp.elegir(empresa or oferta.get("empresa"))
    except empresa_erp.VariasEmpresas:
        raise
    except empresa_erp.ErrorEmpresa as e:
        log.warning("ofertas: no se ha podido fijar la sociedad de %s: %s", motor_id, e)
        return
    if nombre != oferta.get("empresa"):
        await ofertas_licitaciones.fijar_empresa(motor_id, nombre)


def _plantillas_error(e: Exception):
    if isinstance(e, empresa_erp.VariasEmpresas):
        return HTTPException(409, {"mensaje": str(e), "empresas": e.empresas})
    if isinstance(e, empresa_erp.ErrorEmpresa):
        return HTTPException(503 if "ERP" in str(e) and "leer" in str(e) else 422, str(e))
    if isinstance(e, ofertas_licitaciones.NoExiste):
        return HTTPException(404, str(e))
    return HTTPException(422, str(e))


class PlantillasEntrada(BaseModel):
    empresa: str | None = None        # la sociedad del ERP con cuyos datos se rellena; se recuerda para esta oferta


@app.get("/licitaciones/empresas")
async def empresas_del_erp(usuario: Usuario = Depends(usuario_actual)):
    """Las sociedades del ERP con las que se puede presentar una oferta (nombre, razón social y NIF)."""
    _exige_licitaciones(usuario)
    try:
        return {"empresas": await empresa_erp.empresas()}
    except empresa_erp.ErrorEmpresa as e:
        raise _plantillas_error(e) from None


@app.get("/licitaciones/ofertas/{motor_id}/plantillas")
async def plantillas_de_la_oferta(motor_id: str, usuario: Usuario = Depends(usuario_actual)):
    """La documentación administrativa preparada: cada plantilla del concurso rellenada (con el origen de cada dato) y lo que falta."""
    _exige_licitaciones(usuario)
    try:
        return await plantillas_ofertas.listar(motor_id)
    except ofertas_licitaciones.ErrorOferta as e:
        raise _plantillas_error(e) from None


@app.post("/licitaciones/ofertas/{motor_id}/plantillas")
async def preparar_plantillas(motor_id: str, entrada: PlantillasEntrada | None = None, usuario: Usuario = Depends(usuario_actual)):
    """Rellena las plantillas administrativas del concurso con los datos de la sociedad elegida (ERP). Trabaja sobre COPIAS: el documento original no se toca. Se puede repetir."""
    _exige_licitaciones(usuario)
    try:
        ficha = await motor_lic._get(f"/tenders/{motor_id.strip().lower()}") if motor_lic._UUID.match(motor_id.strip()) else {}
        return await plantillas_ofertas.preparar(motor_id, ficha, usuario.id, (entrada or PlantillasEntrada()).empresa)
    except (MotorNoDisponible, LookupError) as e:
        raise _oferta_error(e) from None
    except (empresa_erp.ErrorEmpresa, plantillas_ofertas.ErrorPlantilla, ofertas_licitaciones.ErrorOferta) as e:
        raise _plantillas_error(e) from None


@app.get("/licitaciones/ofertas/{motor_id}/plantillas/{doc_id}/fichero")
async def descargar_plantilla_rellenada(motor_id: str, doc_id: int, usuario: Usuario = Depends(usuario_actual)):
    """El documento rellenado, en base64 (el panel solo habla JSON), listo para revisarlo y firmarlo con certificado digital."""
    _exige_licitaciones(usuario)
    try:
        nombre, datos, tipo = await plantillas_ofertas.fichero(motor_id, doc_id)
    except (ofertas_licitaciones.ErrorOferta, ofertas_licitaciones.NoExiste, plantillas_ofertas.ErrorPlantilla) as e:
        raise _plantillas_error(e) from None
    log.info("ofertas: %s descarga «%s» de %s (%d bytes)", usuario.id, nombre, motor_id, len(datos))
    import base64
    return {"nombre": nombre, "tipo": tipo, "base64": base64.b64encode(datos).decode("ascii")}


class RedactarEntrada(BaseModel):
    rehacer: bool = False             # también rehace los borradores de los agentes (nunca lo que haya escrito o revisado una persona)
    empresa: str | None = None        # la sociedad del ERP con la que se presenta; si el ERP tiene varias y no se ha elegido nunca, hay que indicarla
    modelo: str = "auto"              # con qué modelo externo redactar la memoria técnica: auto (lo que diga la configuración), claude o chatgpt
    modos: dict[str, str] = {}        # cómo se hace, en este caso, cada paso elegible (administrativo, costes): local, externo (Claude/ChatGPT con datos anonimizados) o manual (lo escribe una persona)
    confirmados: list[str] = []       # los pasos en «externo» que la persona ha confirmado expresamente (sin esto, «externo» se rechaza)


@app.post("/licitaciones/ofertas/{motor_id}/redactar", status_code=202)
async def redactar_oferta_con_agentes(motor_id: str, entrada: RedactarEntrada | None = None, usuario: Usuario = Depends(usuario_actual)):
    """«Preparar la oferta»: crea las secciones a partir del pliego y encola que los agentes de Licitaciones redacten el borrador, uno detrás de otro (tarda: son modelos de IA).
    Responde 202 con la ejecución en curso; el panel consulta `/ejecucion` hasta que termina. Solo escriben borradores: una persona los revisa, fija el precio y presenta."""
    _exige_licitaciones(usuario)
    entrada = entrada or RedactarEntrada()
    try:
        ficha = await motor_lic._get(f"/tenders/{motor_id.strip().lower()}") if motor_lic._UUID.match(motor_id.strip()) else {}
        oferta = await ofertas_licitaciones.plan(motor_id, ficha, usuario.id)
        await _fijar_sociedad(motor_id, oferta, entrada.empresa)
        modos = redaccion_externa_ofertas.validar_modos(entrada.modos, entrada.confirmados, usuario.id)
        ejecucion = await redaccion_ofertas.reservar(motor_id, usuario.id, entrada.rehacer, modelo=entrada.modelo, modos=modos)
    except redaccion_ofertas.Conflicto as e:
        raise HTTPException(409, str(e)) from None
    except empresa_erp.VariasEmpresas as e:
        raise HTTPException(409, {"mensaje": str(e), "empresas": e.empresas}) from None
    except (ofertas_licitaciones.ErrorOferta, MotorNoDisponible, LookupError) as e:
        raise _oferta_error(e) from None
    try:
        from ..tareas.celery_app import app as celery
        celery.send_task("cerebro.tareas.celery_app.redactar_oferta", args=[ejecucion["id"]], queue="peticiones")
    except Exception as e:      # noqa: BLE001 — sin cola no hay trabajo: se cierra la ejecución para poder volver a pedirla
        log.error("ofertas: no se ha podido encolar la redacción de %s: %s: %s", motor_id, type(e).__name__, e)
        await redaccion_ofertas.cerrar(ejecucion["id"], "No se ha podido encolar el trabajo: inténtalo de nuevo")
        raise HTTPException(503, "No se ha podido encolar el trabajo") from None
    return {"ejecucion": ejecucion, "oferta": oferta}


class RepetirPaso(BaseModel):
    rehacer: bool = False             # también rehace los borradores que ya escribió este agente (nunca lo que haya escrito o revisado una persona)
    modelo: str = "auto"              # con qué modelo externo, si el paso lo redacta uno: auto, claude o chatgpt
    modos: dict[str, str] = {}        # cómo se hace este paso si es elegible (administrativo, costes): local, externo o manual
    confirmados: list[str] = []       # el paso, si se manda a Claude o ChatGPT, confirmado expresamente


@app.post("/licitaciones/ofertas/{motor_id}/redactar/{paso}", status_code=202)
async def repetir_paso_de_la_oferta(motor_id: str, paso: str, entrada: RepetirPaso | None = None, usuario: Usuario = Depends(usuario_actual)):
    """Repite UNA acción de «Preparar la oferta» (la de un agente: el Arquitecto, el Redactor, Costes…) sin volver a lanzar toda la cadena. Los demás pasos conservan lo que dieron.
    Responde 202 con la ejecución en curso; el panel consulta `/ejecucion`. Solo escriben borradores: lo de una persona no se toca."""
    _exige_licitaciones(usuario)
    entrada = entrada or RepetirPaso()
    try:
        modos = redaccion_externa_ofertas.validar_modos(entrada.modos, entrada.confirmados, usuario.id)
        ejecucion = await redaccion_ofertas.reservar(motor_id, usuario.id, entrada.rehacer, modelo=entrada.modelo, solo=paso, modos=modos)
    except redaccion_ofertas.Conflicto as e:
        raise HTTPException(409, str(e)) from None
    except (ofertas_licitaciones.ErrorOferta, MotorNoDisponible, LookupError) as e:
        raise _oferta_error(e) from None
    try:
        from ..tareas.celery_app import app as celery
        celery.send_task("cerebro.tareas.celery_app.redactar_oferta", args=[ejecucion["id"]], queue="peticiones")
    except Exception as e:      # noqa: BLE001 — sin cola no hay trabajo: se cierra la ejecución para poder volver a pedirla
        log.error("ofertas: no se ha podido encolar el paso %s de %s: %s: %s", paso, motor_id, type(e).__name__, e)
        await redaccion_ofertas.cerrar(ejecucion["id"], "No se ha podido encolar el trabajo: inténtalo de nuevo")
        raise HTTPException(503, "No se ha podido encolar el trabajo") from None
    return {"ejecucion": ejecucion}


@app.get("/licitaciones/ofertas/{motor_id}/revision")
async def revision_previa_de_la_oferta(motor_id: str, usuario: Usuario = Depends(usuario_actual)):
    """«Revisar antes de preparar la oferta»: qué hay y qué falta (ficha, sociedad y sus datos en el ERP, DEUC, pliegos, requisitos, oferta y última pasada de los agentes) SIN llamar a ningún modelo ni cambiar nada."""
    _exige_licitaciones(usuario)
    try:
        ofertas_licitaciones._id(motor_id)           # un identificador válido (UUID)
    except ofertas_licitaciones.ErrorOferta as e:
        raise HTTPException(422, str(e)) from None
    return await revision_previa.revisar(motor_id)


@app.post("/licitaciones/ofertas/{motor_id}/cancelar")
async def cancelar_la_preparacion(motor_id: str, usuario: Usuario = Depends(usuario_actual)):
    """Cancela la preparación de la oferta en curso. El agente que esté trabajando termina su paso y no empieza ninguno más; lo ya escrito se conserva y se puede volver a lanzar."""
    _exige_licitaciones(usuario)
    try:
        return {"ejecucion": await redaccion_ofertas.cancelar(motor_id, usuario.id)}
    except (ofertas_licitaciones.ErrorOferta, LookupError) as e:
        raise _oferta_error(e) from None


class SubidaFicha(BaseModel):
    nombre: str = Field(min_length=1, max_length=200)
    marca: str = Field(default="", max_length=60)
    referencia: str = Field(default="", max_length=60)
    base64: str = Field(min_length=1)


class CargaFichas(BaseModel):
    importacion: int = Field(ge=1)


class FichaPorDireccion(BaseModel):
    url: str = Field(min_length=8, max_length=500)
    marca: str = Field(default="", max_length=60)
    referencia: str = Field(default="", max_length=60)


@app.get("/licitaciones/fichas")
async def fichas_cargadas(usuario: Usuario = Depends(usuario_actual)):
    """Fichas técnicas cargadas, las listas de proveedor de las que se pueden cargar, las últimas cargas y los dominios autorizados."""
    _exige_licitaciones(usuario)
    cfg = fichas_tecnicas.configuracion()
    return {**await fichas_tecnicas.listar(), "listas": await fichas_tecnicas.listas(), "cargas": await fichas_tecnicas.cargas(), "dominios": cfg["hosts"]}


@app.get("/licitaciones/fabricantes/ranking")
async def ranking_de_fabricantes(sector: str = "", orden: str = "seleccion", usuario: Usuario = Depends(usuario_actual)):
    """Los 10 fabricantes principales de cada sector de seguridad con sus ventas y plantilla publicadas (referencia, no ranking mundial exacto) y si su dominio está autorizado para fichas."""
    _exige_licitaciones(usuario)
    try:
        r = fabricantes_dir.top_por_sector(sector, orden)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    hosts = fichas_tecnicas.configuracion()["hosts"]
    for s in r["sectores"]:
        for f in s["fabricantes"]:
            f["autorizado"] = bool(f["dominio"] and pliegos_licitaciones.host_permitido(f["web"], hosts))
    return {**r, "todos_los_sectores": fabricantes_dir.sectores()}


@app.get("/licitaciones/fichas/ejemplos")
async def fichas_de_ejemplo(usuario: Usuario = Depends(usuario_actual)):
    """Modelos de ejemplo del directorio de fabricantes: cuáles se pueden descargar, cuáles piden autorizar el dominio y cuáles hay que subir a mano."""
    _exige_licitaciones(usuario)
    return {"ejemplos": fichas_tecnicas.ejemplos(), "acciones": fichas_tecnicas.ACCIONES_EJEMPLO}


@app.post("/licitaciones/fichas/ejemplos/cargar")
async def cargar_fichas_de_ejemplo(usuario: Usuario = Depends(usuario_actual)):
    """Descarga los ejemplos que son PDF directo de un dominio autorizado (pocos, así que va en la misma petición)."""
    _exige_licitaciones(usuario)
    log.info("fichas: %s carga los modelos de ejemplo", usuario.id)
    return await fichas_tecnicas.cargar_ejemplos(usuario.id)


@app.get("/licitaciones/fichas/revisar/{importacion}")
async def revisar_fichas_de_una_lista(importacion: int, usuario: Usuario = Depends(usuario_actual)):
    """Qué se descargaría de esa lista (sin descargar nada) y qué dominios quedan fuera de la lista autorizada."""
    _exige_licitaciones(usuario)
    try:
        return await fichas_tecnicas.revisar_lista(importacion)
    except fichas_tecnicas.ErrorFicha as e:
        raise HTTPException(404, str(e)) from None


@app.post("/licitaciones/fichas/cargar")
async def cargar_fichas_de_una_lista(entrada: CargaFichas, usuario: Usuario = Depends(usuario_actual)):
    """Lanza en segundo plano la carga de las fichas de los enlaces autorizados de una lista de proveedor."""
    _exige_licitaciones(usuario)
    try:
        carga = await fichas_tecnicas.iniciar_carga(entrada.importacion, usuario.id)
    except fichas_tecnicas.ErrorFicha as e:
        raise HTTPException(409 if "en curso" in str(e) else 404, str(e)) from None
    celery.send_task("cerebro.tareas.celery_app.cargar_fichas", args=[carga], queue="peticiones")
    log.info("fichas: %s lanza la carga %s (lista %s)", usuario.id, carga, entrada.importacion)
    return {"carga": carga}


@app.post("/licitaciones/fichas/url")
async def cargar_ficha_por_direccion(entrada: FichaPorDireccion, usuario: Usuario = Depends(usuario_actual)):
    """Descarga una ficha de una dirección de un dominio autorizado."""
    _exige_licitaciones(usuario)
    try:
        return await fichas_tecnicas.desde_url(entrada.url, entrada.marca, entrada.referencia, "web", usuario.id)
    except fichas_tecnicas.ErrorFicha as e:
        raise HTTPException(422, str(e)) from None


@app.post("/licitaciones/fichas/subir")
async def subir_ficha_a_mano(entrada: SubidaFicha, usuario: Usuario = Depends(usuario_actual)):
    """Una ficha en PDF subida a mano: antivirus, lectura e indexado como las demás."""
    _exige_licitaciones(usuario)
    cfg = fichas_tecnicas.configuracion()
    if len(entrada.base64) > cfg["max_mb"] * 1_400_000:
        raise HTTPException(413, f"La ficha pesa más de {cfg['max_mb']} MB")
    try:
        datos = base64.b64decode(entrada.base64, validate=True)
    except ValueError:
        raise HTTPException(422, "La ficha no se ha recibido bien") from None
    try:
        return await fichas_tecnicas.subir(datos, entrada.nombre, entrada.marca, entrada.referencia, usuario.id, cfg)
    except fichas_tecnicas.ErrorFicha as e:
        raise HTTPException(422, str(e)) from None


@app.get("/licitaciones/ofertas/{motor_id}/envios-externos")
async def envios_externos_de_la_oferta(motor_id: str, usuario: Usuario = Depends(usuario_actual)):
    """El registro de lo que ha salido a Claude o ChatGPT en los pasos sensibles (quién lo confirmó, qué paso, cuánto texto anonimizado). No contiene el texto enviado."""
    _exige_licitaciones(usuario)
    try:
        return {"envios": await redaccion_externa_ofertas.envios(motor_id), "pasos_elegibles": {p: s for p, s in redaccion_externa_ofertas.PASOS_A_ELEGIR.items()}}
    except (ofertas_licitaciones.ErrorOferta, LookupError) as e:
        raise _oferta_error(e) from None


class PartidaEntrada(BaseModel):
    producto: str = Field(min_length=2, max_length=160)
    cantidad: str | None = Field(default=None, max_length=20)


class PartidaCambio(BaseModel):
    cantidad: str | None = Field(default=None, max_length=20)       # vacío = quitar la cantidad
    excluida: bool | None = None


def _error_partida(e: Exception):
    if isinstance(e, partidas_ofertas.ErrorPartida):
        return HTTPException(422, str(e))
    return _oferta_error(e)


@app.get("/licitaciones/ofertas/{motor_id}/partidas")
async def partidas_de_la_oferta(motor_id: str, usuario: Usuario = Depends(usuario_actual)):
    """Las partidas de equipos de la oferta con su coste real calculado con las tarifas de proveedor (CONFIDENCIAL: solo Dirección y Licitaciones) y los totales."""
    _exige_licitaciones(usuario)
    try:
        return await partidas_ofertas.listar(motor_id)
    except (ofertas_licitaciones.ErrorOferta, LookupError) as e:
        raise _oferta_error(e) from None


@app.post("/licitaciones/ofertas/{motor_id}/partidas/proponer")
async def proponer_partidas_de_la_oferta(motor_id: str, usuario: Usuario = Depends(usuario_actual)):
    """Rellena las partidas con los productos que recomienda la tabla de equivalencias (lo que una persona ya haya tocado se conserva)."""
    _exige_licitaciones(usuario)
    try:
        return await partidas_ofertas.proponer(motor_id, usuario.id)
    except (partidas_ofertas.ErrorPartida, ofertas_licitaciones.ErrorOferta, LookupError) as e:
        raise _error_partida(e) from None


@app.post("/licitaciones/ofertas/{motor_id}/partidas")
async def anadir_partida_a_la_oferta(motor_id: str, entrada: PartidaEntrada, usuario: Usuario = Depends(usuario_actual)):
    """Añade un producto a mano (marca y referencia, para casarlo con las tarifas) con su cantidad."""
    _exige_licitaciones(usuario)
    try:
        return await partidas_ofertas.anadir(motor_id, entrada.producto, entrada.cantidad, usuario.id)
    except (partidas_ofertas.ErrorPartida, ofertas_licitaciones.ErrorOferta, LookupError) as e:
        raise _error_partida(e) from None


@app.post("/licitaciones/ofertas/{motor_id}/partidas/{partida}")
async def cambiar_partida_de_la_oferta(motor_id: str, partida: int, entrada: PartidaCambio, usuario: Usuario = Depends(usuario_actual)):
    """Pone o quita la cantidad de una partida y/o la excluye o recupera."""
    _exige_licitaciones(usuario)
    try:
        return await partidas_ofertas.ajustar(motor_id, partida, entrada.cantidad if "cantidad" in entrada.model_fields_set else ..., entrada.excluida, usuario.id)
    except (partidas_ofertas.ErrorPartida, ofertas_licitaciones.ErrorOferta, LookupError) as e:
        raise _error_partida(e) from None


@app.post("/licitaciones/ofertas/{motor_id}/partidas/{partida}/quitar")      # POST: la pasarela del panel solo reenvía GET y POST
async def quitar_partida_de_la_oferta(motor_id: str, partida: int, usuario: Usuario = Depends(usuario_actual)):
    _exige_licitaciones(usuario)
    try:
        return await partidas_ofertas.quitar(motor_id, partida)
    except (ofertas_licitaciones.ErrorOferta, LookupError) as e:
        raise _oferta_error(e) from None


@app.get("/licitaciones/ofertas/{motor_id}/equivalencia")
async def equivalencia_de_la_oferta(motor_id: str, usuario: Usuario = Depends(usuario_actual)):
    """La tabla de equivalencias «iguala o supera» de la oferta (null si aún no se ha hecho). Solo Dirección y Licitaciones."""
    _exige_licitaciones(usuario)
    try:
        return {"equivalencia": await equivalencia_ofertas.leer(motor_id)}
    except (ofertas_licitaciones.ErrorOferta, LookupError) as e:
        raise _oferta_error(e) from None


@app.get("/licitaciones/ofertas/{motor_id}/descubrimiento")
async def descubrimiento_de_la_oferta(motor_id: str, usuario: Usuario = Depends(usuario_actual)):
    """Las pistas de más opciones encontradas en internet (null si aún no se ha buscado). Solo Dirección y Licitaciones."""
    _exige_licitaciones(usuario)
    try:
        return {"descubrimiento": await descubrimiento_ofertas.leer(motor_id)}
    except (ofertas_licitaciones.ErrorOferta, LookupError) as e:
        raise _oferta_error(e) from None


@app.post("/licitaciones/ofertas/{motor_id}/descubrimiento")
async def buscar_mas_opciones_en_internet(motor_id: str, entrada: RedactarEntrada | None = None, usuario: Usuario = Depends(usuario_actual)):
    """Lanza en segundo plano la búsqueda en internet de más opciones para los parámetros sin cubrir. Las pistas son por verificar: no son evidencia hasta cargar su ficha."""
    _exige_licitaciones(usuario)
    try:
        await descubrimiento_ofertas.iniciar(motor_id, usuario.id)
    except (ofertas_licitaciones.ErrorOferta, LookupError) as e:
        raise _oferta_error(e) from None
    celery.send_task("cerebro.tareas.celery_app.descubrir_opciones", args=[motor_id, (entrada.modelo if entrada and getattr(entrada, "modelo", None) else "auto")], queue="peticiones")
    log.info("descubrimiento: %s busca más opciones para %s", usuario.id, motor_id)
    return {"estado": "en_curso"}


@app.get("/licitaciones/ofertas/{motor_id}/comparativa")
async def comparativa_de_la_oferta(motor_id: str, usuario: Usuario = Depends(usuario_actual)):
    """La comparativa de productos y ventaja competitiva de la oferta (null si aún no se ha hecho), con la evidencia en que se apoya cada afirmación. Solo Dirección y Licitaciones."""
    _exige_licitaciones(usuario)
    try:
        return {"comparativa": await comparativa_ofertas.leer(motor_id)}
    except ofertas_licitaciones.ErrorOferta as e:
        raise _oferta_error(e) from None


@app.get("/licitaciones/ofertas/{motor_id}/encargos")
async def encargos_de_la_oferta(motor_id: str, usuario: Usuario = Depends(usuario_actual)):
    """El encargo a medida que recibe cada agente de «Preparar la oferta» en esta licitación (vacío mientras no se haya generado), con quién lo redactó."""
    _exige_licitaciones(usuario)
    try:
        return {"encargos": await encargos_ofertas.listar(motor_id)}
    except ofertas_licitaciones.ErrorOferta as e:
        raise _oferta_error(e) from None


class EncargoEntrada(BaseModel):
    contenido: str = ""               # vacío = quitar mi versión y volver al encargo generado


@app.post("/licitaciones/ofertas/{motor_id}/encargos/{agente}")
async def escribir_encargo(motor_id: str, agente: str, e: EncargoEntrada, usuario: Usuario = Depends(usuario_actual)):
    """Una persona de Licitaciones o Dirección edita el encargo de un agente. Lo suyo no lo pisa ninguna ejecución nueva; se aplica a los agentes que aún no han empezado."""
    _exige_licitaciones(usuario)
    try:
        return await encargos_ofertas.escribir_persona(motor_id, agente, e.contenido, usuario.id)
    except ofertas_licitaciones.ErrorOferta as err:
        raise _oferta_error(err) from None


@app.get("/licitaciones/ofertas/{motor_id}/ejecucion")
async def ejecucion_de_la_oferta(motor_id: str, usuario: Usuario = Depends(usuario_actual)):
    """La última redacción por los agentes de esta oferta, con el estado de cada paso (null si nunca se ha pedido)."""
    _exige_licitaciones(usuario)
    try:
        return {"ejecucion": await redaccion_ofertas.ultima(motor_id)}
    except ofertas_licitaciones.ErrorOferta as e:
        raise _oferta_error(e) from None


@app.post("/licitaciones/ofertas/seccion")
async def escribir_seccion_oferta(entrada: SeccionOfertaEntrada, usuario: Usuario = Depends(usuario_actual)):
    """Una persona escribe (o corrige) una sección: queda en borrador hasta que se revise."""
    _exige_licitaciones(usuario)
    try:
        return await ofertas_licitaciones.escribir_seccion(entrada.motor_id, entrada.sobre, entrada.clave, entrada.contenido, entrada.citas, entrada.titulo, usuario=usuario.id)
    except (ofertas_licitaciones.ErrorOferta, LookupError) as e:
        raise _oferta_error(e) from None


@app.post("/licitaciones/ofertas/seccion/{seccion_id}/estado")
async def estado_seccion_oferta(seccion_id: int, entrada: EstadoSeccionEntrada, usuario: Usuario = Depends(usuario_actual)):
    """Una persona marca la sección como revisada o aprobada (o la devuelve a borrador). El agente no tiene esta operación."""
    _exige_licitaciones(usuario)
    try:
        return await ofertas_licitaciones.revisar_seccion(seccion_id, entrada.estado, usuario.id)
    except (ofertas_licitaciones.ErrorOferta, LookupError) as e:
        raise _oferta_error(e) from None


@app.get("/licitaciones/ofertas/seccion/{seccion_id}/historial")
async def historial_seccion_oferta(seccion_id: int, usuario: Usuario = Depends(usuario_actual)):
    _exige_licitaciones(usuario)
    return {"versiones": await ofertas_licitaciones.historial(seccion_id)}


@app.post("/licitaciones/ofertas/{motor_id}/precio")
async def fijar_precio_oferta(motor_id: str, entrada: PrecioOfertaEntrada, usuario: Usuario = Depends(usuario_actual)):
    """Una PERSONA fija el precio de la oferta (sin IVA). Con él se genera la proposición económica. Los agentes no pueden."""
    _exige_licitaciones(usuario)
    try:
        oferta = await ofertas_licitaciones.fijar_precio(motor_id, entrada.precio, entrada.iva_pct, usuario.id)
    except (ofertas_licitaciones.ErrorOferta, LookupError) as e:
        raise _oferta_error(e) from None
    await crm_licitaciones.anotar_por_oferta(motor_id, *crm_licitaciones.nota_de_precio(entrada.precio, entrada.iva_pct, usuario.id))
    return {**oferta, "plantillas_actualizadas": await _refrescar_plantillas(motor_id, usuario.id)}


async def _refrescar_plantillas(motor_id: str, usuario: str) -> int | None:
    """Con el precio fijado, los modelos de proposición económica ya preparados se rellenan con el importe (en número y en letra, IVA y total). Si algo falla (el ERP, el motor), el precio
    ya está fijado y se dice con None: las plantillas se pueden rellenar de nuevo a mano desde la tarjeta."""
    try:
        if not (await plantillas_ofertas.listar(motor_id))["documentos"]:
            return 0
        return len((await plantillas_ofertas.preparar(motor_id, await plantillas_ofertas.ficha_del_motor(motor_id), usuario))["documentos"])
    except Exception as e:      # noqa: BLE001 — el precio ya está guardado; esto es solo comodidad
        log.warning("ofertas: no se han podido actualizar las plantillas de %s al fijar el precio: %s: %s", motor_id, type(e).__name__, e)
        return None


@app.get("/licitaciones/ofertas/{motor_id}/documento")
async def documento_oferta(motor_id: str, usuario: Usuario = Depends(usuario_actual)):
    """El borrador de la oferta en Word, en base64 dentro del JSON (la pasarela del panel solo lleva JSON). Lo no aprobado sale marcado como borrador."""
    _exige_licitaciones(usuario)
    try:
        ficha = await motor_lic._get(f"/tenders/{motor_id.strip().lower()}") if motor_lic._UUID.match(motor_id.strip()) else {}
        datos = await ofertas_licitaciones.exportar_docx(motor_id, str(ficha.get("titulo") or ""))
    except (ofertas_licitaciones.ErrorOferta, MotorNoDisponible, LookupError) as e:
        raise _oferta_error(e) from None
    exp = re.sub(r"[^A-Za-z0-9._-]+", "-", str(ficha.get("expediente") or motor_id))[:60].strip("-") or "licitacion"
    log.info("ofertas: %s exporta la oferta de %s (%d bytes)", usuario.id, motor_id, len(datos))
    return {"nombre": f"oferta-{exp}.docx", "tipo": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "base64": base64.b64encode(datos).decode("ascii")}


@app.post("/licitaciones/embudo/{lid}/estado")
async def cambiar_estado_licitacion(lid: int, entrada: CambioEstadoEntrada, usuario: Usuario = Depends(usuario_actual)):
    """Anota la decisión de una persona: pasar a en estudio, presentada, ganada, perdida (con motivo) o descartada."""
    _exige_licitaciones(usuario)
    try:
        fila = await embudo_licitaciones.cambiar_estado(lid, entrada.estado, entrada.motivo_perdida)
    except embudo_licitaciones.NoExiste as e:
        raise HTTPException(404, str(e)) from None
    except embudo_licitaciones.ErrorEmbudo as e:
        raise HTTPException(422, str(e)) from None
    log.info("embudo: %s pasa la licitación %s a %s", usuario.id, lid, fila["estado"])
    await crm_licitaciones.anotar(lid, *crm_licitaciones.nota_de_estado(fila["estado"], fila.get("motivo_perdida_texto"), usuario.id))
    if fila["estado"] == "en_estudio":
        _encolar_analisis_pliegos(lid)
    return fila


# ---- Alertas guardadas y avisos (cerebro/licitaciones/alertas.py): personales o de un departamento. Cambiar y borrar van por POST (la pasarela solo deja GET y POST) ----

class AlertaEntrada(BaseModel):
    nombre: str
    ambito: str
    departamento: str | None = None
    filtro: dict
    eventos: list[str]
    canal: str = "panel"
    correo_destino: str | None = None        # con canal «correo»: dirección de la empresa a la que llega el aviso
    tipo: str = "licitacion"                 # «competencia»: avisa cuando un competidor gana (solo adjudicaciones)
    competidores: list[str] | None = None    # NIF de los competidores a vigilar; vacío = cualquier adjudicatario del mercado del filtro


class AlertaCambio(BaseModel):
    nombre: str | None = None
    filtro: dict | None = None
    eventos: list[str] | None = None
    activa: bool | None = None
    canal: str | None = None
    correo_destino: str | None = None
    competidores: list[str] | None = None


class AvisosLeidos(BaseModel):
    ids: list[int] | None = None


def _alerta_error(e: Exception) -> HTTPException:
    if isinstance(e, alertas_licitaciones.NoExiste):
        return HTTPException(404, str(e))
    if isinstance(e, alertas_licitaciones.SinPermiso):
        return HTTPException(403, str(e))
    return HTTPException(422, str(e))


@app.get("/licitaciones/alertas")
async def listar_alertas_licitaciones(usuario: Usuario = Depends(usuario_actual)):
    """Las alertas que ve el usuario (las suyas personales y las de sus departamentos), y los valores que admite el formulario."""
    try:
        return {"items": await alertas_licitaciones.listar(usuario), "eventos": list(alertas_licitaciones.EVENTOS), "canales": list(alertas_licitaciones.CANALES)}
    except alertas_licitaciones.SinPermiso as e:
        raise _alerta_error(e) from None


@app.post("/licitaciones/alertas")
async def crear_alerta_licitaciones(entrada: AlertaEntrada, usuario: Usuario = Depends(usuario_actual)):
    try:
        a = await alertas_licitaciones.crear(usuario, entrada.model_dump())
    except (alertas_licitaciones.ErrorAlerta, alertas_licitaciones.SinPermiso) as e:
        raise _alerta_error(e) from None
    log.info("alertas: %s crea la alerta %s (%s)", usuario.id, a["id"], a["ambito"])
    return a


@app.post("/licitaciones/alertas/{aid}")
async def cambiar_alerta_licitaciones(aid: int, cambio: AlertaCambio, usuario: Usuario = Depends(usuario_actual)):
    try:
        return await alertas_licitaciones.cambiar(usuario, aid, cambio.model_dump(exclude_unset=True))
    except (alertas_licitaciones.ErrorAlerta, alertas_licitaciones.SinPermiso, alertas_licitaciones.NoExiste) as e:
        raise _alerta_error(e) from None


@app.post("/licitaciones/alertas/{aid}/borrar")
async def borrar_alerta_licitaciones(aid: int, usuario: Usuario = Depends(usuario_actual)):
    try:
        await alertas_licitaciones.borrar(usuario, aid)
    except (alertas_licitaciones.SinPermiso, alertas_licitaciones.NoExiste) as e:
        raise _alerta_error(e) from None
    log.info("alertas: %s borra la alerta %s", usuario.id, aid)
    return {"borrada": aid}


@app.get("/licitaciones/avisos")
async def listar_avisos_licitaciones(no_leidos: bool = False, limite: int = 50, usuario: Usuario = Depends(usuario_actual)):
    """Los avisos de las alertas que ve el usuario, del más reciente al más antiguo, y cuántos hay sin leer."""
    try:
        return await alertas_licitaciones.listar_avisos(usuario, no_leidos, limite)
    except alertas_licitaciones.SinPermiso as e:
        raise _alerta_error(e) from None


@app.post("/licitaciones/avisos/leer")
async def leer_avisos_licitaciones(entrada: AvisosLeidos, usuario: Usuario = Depends(usuario_actual)):
    try:
        return {"leidos": await alertas_licitaciones.marcar_leidos(usuario, entrada.ids)}
    except (alertas_licitaciones.ErrorAlerta, alertas_licitaciones.SinPermiso) as e:
        raise _alerta_error(e) from None



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

# ---------------------------------------------------------------- Precios de venta: pantalla de revisión (solo Dirección)
class PrecioAjustes(BaseModel):
    ajustes: dict[str, float] = {}          # {código: precio de venta sin IVA}
    excluir: list[str] = []
    incluir: list[str] = []


class PrecioEstrategia(BaseModel):
    estrategia: str = Field(min_length=2, max_length=40)
    codigos: list[str] | None = None
    familia: str | None = Field(default=None, max_length=80)


class PrecioProponer(BaseModel):
    solo_marca: str | None = Field(default=None, max_length=60)


class PrecioAplicar(BaseModel):
    confirmo: bool = False                  # Dirección ha visto la vista previa y firma la aplicación en el ERP


def _exige_direccion(usuario: Usuario) -> None:
    if "direccion" not in usuario.roles:
        raise HTTPException(403, "Los precios de venta los revisa y aprueba Dirección")


def _error_precios(e: Exception):
    if isinstance(e, listas_precios_mod.NoExiste):
        return HTTPException(404, str(e))
    return HTTPException(422, str(e))


@app.get("/ventas/ranking")
async def ranking_de_ventas(dias: int = 365, top: int = 10, usuario: Usuario = Depends(usuario_actual)):
    """Los artículos y fabricantes que más venden en cada tipo de producto (CCTV, accesos, intrusión…) en un periodo. Solo Dirección: son ventas de la empresa."""
    if "direccion" not in usuario.roles:
        raise HTTPException(403, "Las ventas de la empresa las ve Dirección")
    try:
        return await ranking_ventas.obtener(dias, top)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    except Exception as e:  # noqa: BLE001 — el ERP puede fallar de muchas formas; se dice sin enseñar detalles internos
        log.warning("ventas: no se ha podido leer el ERP: %s", type(e).__name__)
        raise HTTPException(502, "No se han podido leer los pedidos de venta del ERP (¿está en marcha y con permiso de lectura para Dirección?)") from None


@app.get("/precios/propuestas")
async def propuestas_de_precios(usuario: Usuario = Depends(usuario_actual)):
    """Las últimas propuestas de precios de venta (sin líneas). Solo Dirección: llevan costes de proveedor, que son confidenciales."""
    _exige_direccion(usuario)
    return {"propuestas": await precios_venta_pantalla.propuestas()}


@app.post("/precios/propuestas")
async def proponer_precios_de_venta(entrada: PrecioProponer, usuario: Usuario = Depends(usuario_actual)):
    """Calcula una propuesta nueva con los costes cargados (no escribe nada en el ERP)."""
    _exige_direccion(usuario)
    try:
        r = await precios_venta_pantalla.proponer(f"usuario:{usuario.id}", "operaciones", solo_marca=entrada.solo_marca)
    except (precios_venta_pantalla.ErrorVenta, listas_precios_mod.ErrorImportacion, listas_precios_mod.NoExiste) as e:
        raise _error_precios(e) from None
    log.info("precios: %s propone precios de venta (propuesta %s)", usuario.id, r.get("propuesta"))
    return r


@app.get("/precios/propuestas/{propuesta}")
async def ver_propuesta_de_precios(propuesta: int, familia: str = "", cambio: str = "", q: str = "", bajo_minimo: bool = False, pagina: int = 1, usuario: Usuario = Depends(usuario_actual)):
    _exige_direccion(usuario)
    try:
        return await precios_venta_pantalla.ver(propuesta, "operaciones", familia[:80], cambio[:12], q[:80], bajo_minimo, pagina)
    except (precios_venta_pantalla.ErrorVenta, listas_precios_mod.NoExiste) as e:
        raise _error_precios(e) from None


@app.post("/precios/propuestas/{propuesta}/ajustar")
async def ajustar_propuesta_de_precios(propuesta: int, entrada: PrecioAjustes, usuario: Usuario = Depends(usuario_actual)):
    """Corrige precios a mano, saca o mete artículos. No escribe en el ERP."""
    _exige_direccion(usuario)
    try:
        r = await precios_venta_pantalla.ajustar(propuesta, entrada.ajustes, entrada.excluir, entrada.incluir)
    except (precios_venta_pantalla.ErrorVenta, listas_precios_mod.NoExiste) as e:
        raise _error_precios(e) from None
    await constancia.dejar_constancia(None, f"usuario:{usuario.id}", "listas_precios", "ajustar_venta", None,
                                      f"propuesta {propuesta}: {len(entrada.ajustes)} precios a mano, {len(entrada.excluir)} excluidos, {len(entrada.incluir)} incluidos")
    return r


@app.post("/precios/propuestas/{propuesta}/estrategia")
async def elegir_estrategia_de_precios(propuesta: int, entrada: PrecioEstrategia, usuario: Usuario = Depends(usuario_actual)):
    """Aplica una estrategia de precio (competitivo, alineado, premium…) a todos los artículos, a una familia o a los códigos indicados. No escribe en el ERP."""
    _exige_direccion(usuario)
    try:
        r = await precios_venta_pantalla.elegir_estrategia(propuesta, entrada.estrategia, entrada.codigos, entrada.familia)
    except (precios_venta_pantalla.ErrorVenta, listas_precios_mod.NoExiste) as e:
        raise _error_precios(e) from None
    await constancia.dejar_constancia(None, f"usuario:{usuario.id}", "listas_precios", "elegir_estrategia", None,
                                      f"propuesta {propuesta}: estrategia {entrada.estrategia} en {r.get('articulos')} artículos")
    return r


@app.post("/precios/propuestas/{propuesta}/descartar")
async def descartar_propuesta_de_precios(propuesta: int, usuario: Usuario = Depends(usuario_actual)):
    _exige_direccion(usuario)
    try:
        return await precios_venta_pantalla.descartar(propuesta)
    except (precios_venta_pantalla.ErrorVenta, listas_precios_mod.NoExiste) as e:
        raise _error_precios(e) from None


@app.post("/precios/propuestas/{propuesta}/aplicar")
async def aplicar_propuesta_de_precios(propuesta: int, entrada: PrecioAplicar, usuario: Usuario = Depends(usuario_actual)):
    """Escribe en el ERP los precios de venta que han cambiado. Es una acción que sale de la empresa: la firma Dirección (una sola persona, como en la bandeja) y exige la confirmación expresa tras ver la vista previa.
    Queda constancia de quién firmó y qué se aplicó. Repetible: lo que ya está igual no se toca."""
    _exige_direccion(usuario)
    if not entrada.confirmo:
        raise HTTPException(422, "Falta la confirmación: revisa la vista previa y confirma que aplicas estos precios en el ERP")
    try:
        vista = await precios_venta_pantalla.vista_aplicar(propuesta, "operaciones")
        resultado = await precios_venta_pantalla.aplicar(propuesta, "operaciones")
    except (precios_venta_pantalla.ErrorVenta, listas_precios_mod.NoExiste) as e:
        raise _error_precios(e) from None
    await constancia.dejar_constancia(None, f"usuario:{usuario.id}", "listas_precios", "aplicar_venta", f"firmado en el panel por {usuario.id}",
                                      f"propuesta {propuesta}: {vista['titulo']}; resultado: {str(resultado)[:600]}")
    log.info("precios: %s aplica la propuesta %s en el ERP", usuario.id, propuesta)
    return {"propuesta": propuesta, "resultado": resultado}


# ---------------------------------------------------------------- Tarifas de proveedores: actualización periódica (solo Dirección)
def _error_tarifa(e: Exception):
    if isinstance(e, listas_precios_mod.NoExiste):
        return HTTPException(404, str(e))
    return HTTPException(422, str(e))


@app.get("/precios/tarifas")
async def tarifas_de_proveedores(usuario: Usuario = Depends(usuario_actual)):
    """Los proveedores vigilados (última comprobación y error), los errores de configuración y las actualizaciones recientes con su resumen de cambios. Solo Dirección."""
    _exige_direccion(usuario)
    return await tarifas_automaticas.listar()


@app.post("/precios/tarifas/comprobar", status_code=202)
async def comprobar_tarifas_ahora(usuario: Usuario = Depends(usuario_actual)):
    """Mira ahora las carpetas y servicios web de tarifas (en segundo plano). Deja propuestas; no aplica nada."""
    _exige_direccion(usuario)
    try:
        from ..tareas.celery_app import app as celery
        celery.send_task("cerebro.tareas.celery_app.actualizar_tarifas", queue="peticiones")
    except Exception as e:      # noqa: BLE001
        log.error("tarifas: no se ha podido encolar la comprobación: %s: %s", type(e).__name__, e)
        raise HTTPException(503, "No se ha podido encolar el trabajo") from None
    log.info("tarifas: %s pide comprobar las tarifas de los proveedores", usuario.id)
    return {"estado": "en_cola"}


@app.get("/precios/tarifas/{actualizacion}")
async def vista_de_una_tarifa(actualizacion: int, usuario: Usuario = Depends(usuario_actual)):
    """La vista previa de aplicar esa tarifa: proveedor, líneas y rango de costes, y los cambios frente a la última aplicada."""
    _exige_direccion(usuario)
    try:
        return await tarifas_automaticas.vista(actualizacion)
    except (tarifas_automaticas.ErrorTarifaAuto, listas_precios_mod.ErrorImportacion, listas_precios_mod.NoExiste) as e:
        raise _error_tarifa(e) from None


@app.post("/precios/tarifas/{actualizacion}/aplicar")
async def aplicar_una_tarifa(actualizacion: int, entrada: PrecioAplicar, usuario: Usuario = Depends(usuario_actual)):
    """Da de alta en el ERP el proveedor, los artículos nuevos y sus costes (los de la tarifa). Sale de la empresa: firma Dirección con confirmación expresa y queda constancia. No cambia ningún precio de venta."""
    _exige_direccion(usuario)
    if not entrada.confirmo:
        raise HTTPException(422, "Falta la confirmación: revisa la vista previa y confirma que cargas esta tarifa en el ERP")
    try:
        v = await tarifas_automaticas.vista(actualizacion)
        resultado = await tarifas_automaticas.aplicar(actualizacion, usuario.id)
    except (tarifas_automaticas.ErrorTarifaAuto, listas_precios_mod.ErrorImportacion, listas_precios_mod.NoExiste) as e:
        raise _error_tarifa(e) from None
    await constancia.dejar_constancia(None, f"usuario:{usuario.id}", "listas_precios", "aplicar", f"firmado en el panel por {usuario.id}",
                                      f"tarifa {actualizacion}: {v['vista']['titulo']}; resultado: {str(resultado)[:600]}")
    log.info("tarifas: %s aplica la tarifa %s en el ERP", usuario.id, actualizacion)
    return {"actualizacion": actualizacion, "resultado": resultado}


@app.post("/precios/tarifas/{actualizacion}/descartar")
async def descartar_una_tarifa(actualizacion: int, usuario: Usuario = Depends(usuario_actual)):
    _exige_direccion(usuario)
    try:
        return await tarifas_automaticas.descartar(actualizacion, usuario.id)
    except (tarifas_automaticas.ErrorTarifaAuto, listas_precios_mod.NoExiste) as e:
        raise _error_tarifa(e) from None
