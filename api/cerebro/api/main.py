"""API del Cerebro: la usan el panel, Jarvis (voz) y las tareas programadas."""
from __future__ import annotations

import base64
import logging
import os
import re
import uuid
from contextlib import asynccontextmanager

import psycopg
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command
from pydantic import BaseModel

from .. import subidas
from ..ajustes import ajustes
from ..aprobaciones import bandeja, objetivos
from ..aprobaciones.logica import DecisionNoValida
from .. import actividad, constancia, kpis, modelos_externos, oficina
from ..herramientas import licitaciones as motor_lic
from ..herramientas.licitaciones import MotorNoDisponible
from ..licitaciones import alertas as alertas_licitaciones
from ..licitaciones import calendario_plazos
from ..licitaciones import pliegos as pliegos_licitaciones
from ..licitaciones import ofertas as ofertas_licitaciones
from ..licitaciones import empresa as empresa_erp
from ..licitaciones import plantillas as plantillas_ofertas
from ..licitaciones import redaccion as redaccion_ofertas
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
    peticion = m.texto
    if m.documentos:
        try:
            peticion += await subidas.para_chat(usuario.id, m.documentos)          # lo añade el sistema, solo con documentos de esta persona que han pasado el antivirus
        except subidas.ErrorSubida as e:
            raise HTTPException(422, str(e)) from None
    config = {"configurable": {"thread_id": hilo}, "callbacks": callbacks(), "metadata": metadatos(hilo, usuario.id)}
    estado = await GRAFO["g"].ainvoke({"peticion": peticion, "usuario": usuario.id, "origen": m.origen,
                                       "sensibilidad": m.sensibilidad}, config)
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
    return fila


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
        return {**await pliegos_licitaciones.documentos(motor_id), **{"requisitos": (await pliegos_licitaciones.requisitos(motor_id))["requisitos"]}}
    except (pliegos_licitaciones.ErrorPliego, LookupError, MotorNoDisponible) as e:
        raise _error_pliegos(e) from None


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
        ejecucion = await redaccion_ofertas.reservar(motor_id, usuario.id, entrada.rehacer)
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
    return {**oferta, "plantillas_actualizadas": await _refrescar_plantillas(motor_id, usuario.id)}


async def _refrescar_plantillas(motor_id: str, usuario: str) -> int | None:
    """Con el precio fijado, los modelos de proposición económica ya preparados se rellenan con el importe (en número y en letra, IVA y total). Si algo falla (el ERP, el motor), el precio
    ya está fijado y se dice con None: las plantillas se pueden rellenar de nuevo a mano desde la tarjeta."""
    try:
        if not (await plantillas_ofertas.listar(motor_id))["documentos"]:
            return 0
        ficha = await motor_lic._get(f"/tenders/{motor_id.strip().lower()}") if motor_lic._UUID.match(motor_id.strip()) else {}
        return len((await plantillas_ofertas.preparar(motor_id, ficha, usuario))["documentos"])
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
