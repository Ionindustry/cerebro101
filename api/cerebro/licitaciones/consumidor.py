"""Consumidor de eventos del motor de licitaciones (ADR 0007 §3): mete en el embudo las licitaciones nuevas con buen encaje y anota los cambios de estado.

Servicio aparte (`python -m cerebro.licitaciones.consumidor`, el contenedor «licitaciones-eventos»), con dos consumidores DURADEROS de JetStream, cada uno con su
avance, que se conserva entre reinicios: `cerebro-embudo` y `cerebro-alertas`. Qué hace `cerebro-embudo` con cada evento, y nada más:
  - `licitacion.nueva`: si está abierta, dentro del importe y con encaje >= el umbral, la apunta en el embudo como «detectada»;
  - `licitacion.adjudicada` / `.formalizada` / `.anulada`: si ya está en el embudo, anota su estado en el motor (y una detectada que se anula pasa a descartada).
NO ejecuta agentes ni encola tareas, y NUNCA cambia el estado que haya puesto una persona. Es idempotente por versión (ADR 0003): JetStream entrega «al
menos una vez», y una reentrega o un evento viejo no cambia nada.

El evento solo lleva la fuente y el identificador de origen (no los datos): el consumidor pide el expediente a la API del motor. Si el proyector aún no
lo ha proyectado, se reintenta más tarde con espera creciente (10 s, 1 min, 5 min, 30 min, 2 h) hasta MAX_ENTREGAS veces.

`cerebro-alertas` atiende las alertas guardadas (alertas.py): por cada evento, para cada alerta activa que pida ese tipo, pregunta AL MOTOR si el expediente cumple
su filtro y, si sí, deja un aviso en el panel (uno por alerta y evento). Solo avisa de expedientes actualizados hace pocos días (alertas.max_antiguedad_dias en
config/licitaciones.yaml): la carga del histórico no inunda a nadie.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
from dataclasses import dataclass
from datetime import datetime, timezone

from ..herramientas import licitaciones as motor
from . import alertas as alertas_mod
from . import embudo
from . import resumen as resumen_mod

log = logging.getLogger("cerebro.licitaciones.consumidor")

STREAM = "LICITACIONES"
DURABLE = "cerebro-embudo"
DURABLE_ALERTAS = "cerebro-alertas"
TIPOS = ("nueva", "adjudicada", "formalizada", "anulada")
SUJETOS = [f"licitacion.{t}.>" for t in TIPOS]
SUJETOS_ALERTAS = [f"{e}.>" for e in alertas_mod.EVENTOS]
ESPERAS = (10, 60, 300, 1800, 7200)       # segundos entre reintentos (ADR 0002)
MAX_ENTREGAS = 6
LOTE = 20
MAX_EN_VUELO = 100

# Nombre interno de la fuente (el del evento) → el de la API del motor.
FUENTES_EXTERNAS = {"placsp-643": "placsp", "placsp-1044": "placsp_agregadas", "placsp-1143": "placsp_menores", "ted": "ted", "cat": "cat"}


class ErrorPermanente(ValueError):
    """Un mensaje que repetir no arregla (no se lee, le faltan campos): se da por terminado y se registra."""


class AunNoProyectado(RuntimeError):
    """El motor todavía no tiene el expediente en su modelo de lectura (o tiene una versión anterior): se reintenta más tarde."""


@dataclass(frozen=True)
class Evento:
    id: str
    tipo: str            # sin el prefijo «licitacion.»: nueva, adjudicada…
    fuente: str
    id_origen: str
    version: int


def decodificar(datos: bytes) -> Evento:
    """El mensaje que publica el motor (internal/bus: id, tipo, fuente, id_origen, version…) como Evento. Cualquier fallo es permanente."""
    try:
        d = json.loads(datos)
        ev = Evento(str(d["id"]), str(d["tipo"]).removeprefix("licitacion."), str(d["fuente"]), str(d["id_origen"]), int(d["version"]))
    except (ValueError, KeyError, TypeError) as e:
        raise ErrorPermanente(f"mensaje no válido: {type(e).__name__}") from None
    if not ev.id or not ev.tipo or ev.fuente not in FUENTES_EXTERNAS or not ev.id_origen or ev.version < 1:
        raise ErrorPermanente("al mensaje le faltan campos obligatorios o la fuente es desconocida")
    return ev


def encaje_minimo(cfg: dict | None = None) -> int:
    """El umbral de encaje: la variable LICITACIONES_ENCAJE_MIN si está y es válida (0–100); si no, el de config/licitaciones.yaml."""
    v = os.environ.get("LICITACIONES_ENCAJE_MIN", "").strip()
    if v:
        try:
            n = int(v)
        except ValueError:
            raise ValueError("LICITACIONES_ENCAJE_MIN debe ser un número entero entre 0 y 100") from None
        if not 0 <= n <= 100:
            raise ValueError("LICITACIONES_ENCAJE_MIN debe estar entre 0 y 100")
        return n
    return int((cfg or resumen_mod.config())["embudo"]["encaje_min"])


async def buscar_expediente(ev: Evento, consulta=None) -> dict | None:
    """El expediente del evento en la API del motor (GET /tenders?fuente=&id_origen=), o None si no existe todavía."""
    r = await (consulta or motor._get)("/tenders", {"fuente": FUENTES_EXTERNAS[ev.fuente], "id_origen": ev.id_origen, "limit": 1})
    items = r.get("items") or []
    return items[0] if items else None


async def procesar(ev: Evento, *, consulta=None, cfg: dict | None = None, minimo: int | None = None, ahora: datetime | None = None) -> str:
    """Aplica un evento. Devuelve una frase con lo que ha hecho (para el registro). Lanza AunNoProyectado si hay que esperar al motor."""
    ahora = ahora or datetime.now(timezone.utc)
    cfg = cfg or resumen_mod.config()
    minimo = encaje_minimo(cfg) if minimo is None else minimo
    item = await buscar_expediente(ev, consulta)
    if item is None:
        raise AunNoProyectado(f"el motor aún no tiene {ev.fuente} {ev.id_origen}")
    if (item.get("version_entidad") or 0) < ev.version:
        raise AunNoProyectado(f"el motor tiene la versión {item.get('version_entidad')} y el evento es de la {ev.version}")
    d = embudo.datos_de_resumen(item, cfg, ahora)
    if ev.tipo == "nueva":
        entra, motivo = embudo.cumple_el_umbral(d, minimo)
        if not entra:
            return f"ignorada: {motivo}"
        datos = {k: v for k, v in d.items() if k != "fuera_de_importe"}
        nueva = await embudo.registrar_detectada(datos, ahora)
        return {True: f"detectada ({motivo})", False: f"datos refrescados ({motivo})", None: "ignorada: versión anterior a la guardada"}[nueva]
    if ev.tipo in TIPOS:
        estado = await embudo.actualizar_estado_motor(d["motor_id"], d["motor_version"], d["estado_motor"], ahora)
        return "no está en el embudo" if estado is None else f"estado en el motor «{d['estado_motor']}» (embudo: {estado})"
    return f"ignorada: tipo {ev.tipo}"


async def procesar_alertas(ev: Evento, *, consulta=None, cfg: dict | None = None, ahora: datetime | None = None) -> str:
    """Avisa de un evento a las alertas que lo piden y cuyo filtro cumple el expediente. Idempotente: el mismo evento no avisa dos veces a la misma alerta."""
    ahora = ahora or datetime.now(timezone.utc)
    cfg = cfg or resumen_mod.config()
    pedidas = await alertas_mod.activas_para(f"licitacion.{ev.tipo}")
    if not pedidas:
        return "ninguna alerta pide este evento"
    item = await buscar_expediente(ev, consulta)
    if item is None or (item.get("version_entidad") or 0) < ev.version:
        raise AunNoProyectado(f"el motor aún no tiene {ev.fuente} {ev.id_origen} en la versión {ev.version}")
    max_dias = int(cfg.get("alertas", {}).get("max_antiguedad_dias", 7))
    try:
        actualizada = datetime.fromisoformat(str(item["actualizada_en"]).replace("Z", "+00:00"))
    except (KeyError, ValueError):
        return "ignorada: sin fecha de actualización"
    if (ahora - actualizada).days > max_dias:
        return f"ignorada: actualizada hace más de {max_dias} días"
    if ev.tipo == "nueva" and item.get("estado") not in resumen_mod.ABIERTAS:
        return f"ignorada: no está abierta ({item.get('estado')})"
    d = embudo.datos_de_resumen(item, cfg, ahora)
    avisos = 0
    for a in pedidas:
        if await alertas_mod.ya_avisada(a["id"], ev.id):
            continue
        try:
            r = await (consulta or motor._get)("/tenders", alertas_mod.parametros_de_consulta(a["filtro"], FUENTES_EXTERNAS[ev.fuente], ev.id_origen))
        except ValueError as e:        # el motor rechaza ese filtro (no debería: se valida al crear): se salta la alerta, no se pierde el evento
            log.warning("la alerta %s tiene un filtro que el motor rechaza: %s", a["id"], e)
            continue
        if r.get("items"):
            if await alertas_mod.registrar_aviso(a["id"], ev.id, f"licitacion.{ev.tipo}", d, ahora):
                avisos += 1
    return f"{avisos} aviso(s) de {len(pedidas)} alerta(s)"


def espera(entregas: int) -> int:
    """Segundos hasta el siguiente reintento tras `entregas` entregas fallidas."""
    return ESPERAS[min(max(entregas, 1), len(ESPERAS)) - 1]


async def atender(m, funcion=None, **kw) -> str:
    """Un mensaje de JetStream: lo procesa (con `funcion`, por defecto la del embudo) y lo confirma (ack), lo da por terminado (term) o lo devuelve con espera (nak)."""
    entregas = getattr(getattr(m, "metadata", None), "num_delivered", 1) or 1
    try:
        ev = decodificar(m.data)
        resultado = await (funcion or procesar)(ev, **kw)
    except ErrorPermanente as e:
        log.error("mensaje descartado: %s", e)
        await m.term()
        return "descartado"
    except AunNoProyectado as e:
        log.info("se reintenta (entrega %d): %s", entregas, e)
        await m.nak(delay=espera(entregas))
        return "reintento"
    except Exception as e:      # el motor o la base no responden, o un fallo inesperado: se reintenta (JetStream corta en MAX_ENTREGAS)
        log.warning("se reintenta (entrega %d): %s: %s", entregas, type(e).__name__, e)
        await m.nak(delay=espera(entregas))
        return "reintento"
    log.info("%s %s v%d → %s", ev.tipo, ev.id_origen, ev.version, resultado)
    await m.ack()
    return "ok"


async def _bucle(sub, nombre: str, funcion, parar: asyncio.Event, **kw) -> None:
    """Un consumidor: pide lotes y atiende cada mensaje hasta que se pida parar."""
    import nats

    while not parar.is_set():
        pedir = asyncio.ensure_future(sub.fetch(LOTE, timeout=5))
        salir = asyncio.ensure_future(parar.wait())
        await asyncio.wait({pedir, salir}, return_when=asyncio.FIRST_COMPLETED)
        if not pedir.done():            # se pidió parar mientras se esperaba: lo que llegara sin confirmar se reentrega al volver
            pedir.cancel()
            await asyncio.gather(pedir, return_exceptions=True)
            return
        salir.cancel()
        try:
            mensajes = pedir.result()
        except nats.errors.TimeoutError:
            continue
        for m in mensajes:
            await atender(m, funcion, **kw)


async def ejecutar(parar: asyncio.Event | None = None) -> None:
    """Conecta con NATS y consume (embudo y alertas) hasta que se pida parar. NATS reconecta solo; un fallo al conectar la primera vez se reintenta."""
    import nats
    from nats.js.api import ConsumerConfig, DeliverPolicy
    from nats.js.errors import BadRequestError

    parar = parar or asyncio.Event()
    url = os.environ.get("LICITACIONES_NATS_URL", "nats://licitaciones-nats:4222")
    usuario, clave = os.environ.get("LICITACIONES_NATS_USUARIO") or None, os.environ.get("LICITACIONES_NATS_CLAVE") or None
    minimo = encaje_minimo()
    cfg = resumen_mod.config()
    while not parar.is_set():
        try:
            nc = await nats.connect(url, user=usuario, password=clave, name="cerebro-licitaciones", max_reconnect_attempts=-1, reconnect_time_wait=2)
            break
        except Exception as e:
            log.warning("no se puede conectar con NATS (%s): %s; se reintenta en 10 s", url, type(e).__name__)
            try:
                await asyncio.wait_for(parar.wait(), 10)
            except asyncio.TimeoutError:
                pass
    else:
        return
    js = nc.jetstream()
    backoff = [float(e) for e in ESPERAS[: MAX_ENTREGAS - 1]]
    suscripciones = []
    for durable, sujetos, descripcion in ((DURABLE, SUJETOS, "Embudo de licitaciones del Cerebro"), (DURABLE_ALERTAS, SUJETOS_ALERTAS, "Alertas guardadas de licitaciones")):
        config = ConsumerConfig(
            durable_name=durable, ack_policy="explicit", ack_wait=120, max_deliver=MAX_ENTREGAS, max_ack_pending=MAX_EN_VUELO,
            filter_subjects=sujetos, deliver_policy=DeliverPolicy.ALL, backoff=backoff, description=descripcion)
        try:
            await js.add_consumer(STREAM, config)
        except BadRequestError:      # ya existe con otra configuración: se usa el que hay (cambiarlo es una decisión de quien lo opera)
            log.info("el consumidor %s ya existe: se usa tal cual", durable)
        suscripciones.append((durable, await js.pull_subscribe("licitacion.>", durable=durable, stream=STREAM)))
    log.info("consumidores %s en marcha (umbral de encaje del embudo: %d)", ", ".join(d for d, _ in suscripciones), minimo)
    try:
        await asyncio.gather(
            _bucle(suscripciones[0][1], DURABLE, procesar, parar, cfg=cfg, minimo=minimo),
            _bucle(suscripciones[1][1], DURABLE_ALERTAS, procesar_alertas, parar, cfg=cfg),
        )
    finally:
        await nc.close()        # no drain(): cada mensaje se confirma antes de pasar al siguiente, y drain espera sin fin la cola de una suscripción «pull»


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parar = asyncio.Event()

    async def _run():
        bucle = asyncio.get_running_loop()
        for s in (signal.SIGINT, signal.SIGTERM):
            bucle.add_signal_handler(s, parar.set)
        await ejecutar(parar)

    asyncio.run(_run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
