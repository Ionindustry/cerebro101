"""Plazos de las licitaciones en el calendario de la empresa (botón «Añadir el plazo al calendario» del embudo).

Una persona pulsa el botón y se crea (o se actualiza) UN evento en el calendario CalDAV de la empresa: termina a la hora del plazo de presentación, dura unos
minutos y lleva recordatorios unos días antes. Sin invitados: no sale nada de la empresa, por eso no pasa por la bandeja de aprobaciones (lo que sí pasa por ella es
`calendario.crear_cita` de los agentes, que puede invitar a gente de fuera). El evento se identifica con un UID fijo sacado del `motor_id`: volver a pulsar lo actualiza
(si el plazo ha cambiado en el motor) en vez de duplicarlo, y «Quitar» lo borra. Los textos de la licitación son datos de terceros: se escapan como texto, nada más.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from ..ajustes import ajustes
from . import embudo
from .embudo import ErrorEmbudo, NoExiste

log = logging.getLogger("cerebro.licitaciones.calendario_plazos")

DEPARTAMENTO = "licitaciones"          # de él salen las credenciales del calendario (CALENDARIO_LICITACIONES_* o CALENDARIO_*)
DEFECTO = {"duracion_min": 30, "recordatorios_dias": [3, 1], "calendario": ""}


class ErrorCalendario(RuntimeError):
    """El calendario no está configurado o no responde; el mensaje es para quien pulsó el botón."""


def configuracion() -> dict:
    try:
        c = yaml.safe_load((Path(ajustes.dir_config) / "licitaciones.yaml").read_text(encoding="utf-8")).get("calendario_plazos") or {}
    except OSError:
        c = {}
    cfg = {**DEFECTO, **c}
    cfg["duracion_min"] = min(max(int(cfg["duracion_min"]), 5), 480)
    cfg["recordatorios_dias"] = [int(d) for d in cfg["recordatorios_dias"] if 0 < int(d) <= 60][:5]
    return cfg


def uid_de(motor_id: str) -> str:
    return f"plazo-licitacion-{motor_id}@101.cat"


def _plazo(fila: dict) -> datetime:
    try:
        t = datetime.fromisoformat(str(fila.get("fecha_limite")))
    except ValueError:
        raise ErrorEmbudo("Esa licitación no tiene un plazo de presentación que poner en el calendario") from None
    if t.tzinfo is None:
        raise ErrorEmbudo("El plazo de esa licitación no lleva zona horaria: no se puede poner en el calendario")
    return t.astimezone(timezone.utc)


def construir_ics(fila: dict, cfg: dict, ahora: datetime) -> str:
    """El iCalendar del plazo de una licitación. Pura: no toca el calendario ni el reloj."""
    from icalendar import Alarm, Calendar, Event
    limite = _plazo(fila)
    if limite <= ahora:
        raise ErrorEmbudo("El plazo de esa licitación ya ha pasado")
    titulo = " ".join(str(fila.get("titulo") or "(sin título)").split())
    ev = Event()
    ev.add("uid", uid_de(fila["motor_id"]))
    ev.add("dtstamp", ahora)
    ev.add("dtstart", limite - timedelta(minutes=cfg["duracion_min"]))
    ev.add("dtend", limite)
    ev.add("summary", f"Plazo: {titulo[:150]}")
    detalle = [f"Fin del plazo de presentación: {limite.astimezone(ZoneInfo(ajustes.zona_horaria)):%d/%m/%Y %H:%M} (hora de {ajustes.zona_horaria.split('/')[-1]})",
               f"Organismo: {fila['organismo']}" if fila.get("organismo") else "",
               f"Expediente: {fila['expediente']}" if fila.get("expediente") else "",
               f"Importe (sin IVA): {fila['importe']:,.0f} €".replace(",", ".") if fila.get("importe") is not None else "",
               f"Anuncio: {fila['enlace']}" if str(fila.get("enlace") or "").startswith(("http://", "https://")) else "",
               "Creado desde el embudo de licitaciones de 101.cat."]
    ev.add("description", "\n".join(x for x in detalle if x))
    ev.add("categories", ["Licitaciones"])
    for dias in cfg["recordatorios_dias"]:
        a = Alarm()
        a.add("action", "DISPLAY")
        a.add("trigger", -timedelta(days=dias))
        a.add("description", f"Plazo de licitación en {dias} día{'s' if dias != 1 else ''}: {titulo[:80]}")
        ev.add_component(a)
    cal = Calendar()
    cal.add("prodid", "-//101.cat//Cerebro//ES")
    cal.add("version", "2.0")
    cal.add_component(ev)
    return cal.to_ical().decode()


# ---- Lo que habla con el servidor CalDAV (se sustituye en las pruebas) ----

def _calendario(nombre: str):
    from ..herramientas.calendario import _cliente
    calendarios = _cliente(DEPARTAMENTO).principal().calendars()
    if nombre:
        for c in calendarios:
            if (getattr(c, "name", "") or "").strip().lower() == nombre.strip().lower():
                return c
        raise ErrorCalendario(f"El calendario «{nombre}» no existe en la cuenta (config/licitaciones.yaml, calendario_plazos.calendario)")
    if not calendarios:
        raise ErrorCalendario("La cuenta del calendario no tiene ningún calendario")
    return calendarios[0]


def _guardar(ics: str, nombre: str) -> None:
    _calendario(nombre).save_event(ics)          # el UID es fijo: si ya existe, lo sustituye


def _borrar(uid: str, nombre: str) -> None:
    try:
        _calendario(nombre).event_by_uid(uid).delete()
    except Exception as e:      # noqa: BLE001 — si ya no estaba, está igual de quitado
        if type(e).__name__ != "NotFoundError":
            raise


async def _en_el_calendario(accion, *args) -> None:
    try:
        await asyncio.to_thread(accion, *args)
    except ErrorCalendario:
        raise
    except PermissionError:
        raise ErrorCalendario("El calendario de Licitaciones no está configurado (faltan CALENDARIO_LICITACIONES_USUARIO y _CLAVE, o CALENDARIO_USUARIO y _CLAVE)") from None
    except Exception as e:      # noqa: BLE001 — el servidor de calendario falla de muchas maneras: se dice sin ruido y se anota
        log.warning("calendario de plazos: %s: %s", type(e).__name__, e)
        raise ErrorCalendario("No se ha podido escribir en el calendario. Inténtalo en unos minutos.") from None


async def poner(lid: int, guardar=None, ahora: datetime | None = None, cfg: dict | None = None) -> dict:
    """Crea o actualiza el evento del plazo de la licitación y anota qué plazo quedó en el calendario. Devuelve la fila del embudo."""
    fila = await embudo.obtener(lid)
    if not fila:
        raise NoExiste("No existe esa licitación en el embudo")
    if fila["estado"] in embudo.ESTADOS_RESUELTOS:
        raise ErrorEmbudo("Esa licitación ya está resuelta: no hace falta recordar su plazo")
    if not fila.get("motor_id"):
        raise ErrorEmbudo("Esa licitación no está vinculada a un expediente del motor de licitaciones")
    cfg = cfg or configuracion()
    ics = construir_ics(fila, cfg, ahora or datetime.now(timezone.utc))
    await _en_el_calendario(guardar or _guardar, ics, cfg["calendario"])
    return await embudo.marcar_calendario(lid, _plazo(fila))


async def quitar(lid: int, borrar=None, cfg: dict | None = None) -> dict:
    """Borra el evento del plazo (si estaba) y lo anota. Devuelve la fila del embudo."""
    fila = await embudo.obtener(lid)
    if not fila:
        raise NoExiste("No existe esa licitación en el embudo")
    if fila.get("motor_id") and fila.get("calendario_plazo"):
        cfg = cfg or configuracion()
        await _en_el_calendario(borrar or _borrar, uid_de(fila["motor_id"]), cfg["calendario"])
    return await embudo.marcar_calendario(lid, None)
