"""Calendario con el servidor CalDAV propio.

huecos y proponer_cita solo leen; crear_cita escribe en el calendario de otra persona
o envía invitaciones, así que requiere aprobación.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timedelta

from .base import Herramienta, registrar
from .integraciones import config, credenciales


def calcular_huecos(ocupado: list[tuple[datetime, datetime]], desde: date, hasta: date, duracion_min: int,
                    inicio: str = "08:00", fin: str = "18:00", dias: tuple[int, ...] = (0, 1, 2, 3, 4),
                    paso_min: int = 30) -> list[tuple[datetime, datetime]]:
    """Huecos libres de `duracion_min` dentro de la jornada, sin solaparse con lo ocupado."""
    h_ini, h_fin = time.fromisoformat(inicio), time.fromisoformat(fin)
    duracion, paso = timedelta(minutes=duracion_min), timedelta(minutes=paso_min)
    ocupado = sorted(ocupado)
    libres = []
    dia = desde
    while dia <= hasta:
        if dia.weekday() in dias:
            t = datetime.combine(dia, h_ini)
            limite = datetime.combine(dia, h_fin)
            while t + duracion <= limite:
                if not any(a < t + duracion and t < b for a, b in ocupado):
                    libres.append((t, t + duracion))
                    t += duracion
                else:
                    t += paso
        dia += timedelta(days=1)
    return libres


def _cliente(departamento: str):
    import caldav  # import diferido
    usuario, clave = credenciales("CALENDARIO", departamento)
    return caldav.DAVClient(url=config()["calendario"]["url"], username=usuario, password=clave)


def _ocupado(departamento: str, desde: datetime, hasta: datetime) -> list[tuple[datetime, datetime]]:
    principal = _cliente(departamento).principal()
    franjas = []
    for cal in principal.calendars():
        for ev in cal.search(start=desde, end=hasta, event=True, expand=True):
            comp = ev.icalendar_component
            ini, fin = comp.get("dtstart").dt, comp.get("dtend").dt
            if isinstance(ini, datetime):
                franjas.append((ini.replace(tzinfo=None), fin.replace(tzinfo=None)))
            else:  # evento de día completo
                franjas.append((datetime.combine(ini, time.min), datetime.combine(fin, time.min)))
    return franjas


async def huecos(departamento: str, desde: str, hasta: str, duracion_min: int = 60) -> list[dict]:
    d, h = date.fromisoformat(desde), date.fromisoformat(hasta)
    ocupado = await asyncio.to_thread(_ocupado, departamento, datetime.combine(d, time.min),
                                      datetime.combine(h, time.max))
    j = config()["calendario"]["jornada"]
    libres = calcular_huecos(ocupado, d, h, duracion_min, j["inicio"], j["fin"], tuple(j["dias"]))
    return [{"inicio": a.isoformat(), "fin": b.isoformat()} for a, b in libres[:20]]


async def proponer_cita(departamento: str, desde: str, hasta: str, duracion_min: int = 60, opciones: int = 3) -> list[dict]:
    return (await huecos(departamento, desde, hasta, duracion_min))[:opciones]


def _crear(departamento: str, titulo: str, inicio: datetime, fin: datetime, descripcion: str, invitados: list[str]) -> str:
    principal = _cliente(departamento).principal()
    cal = principal.calendars()[0]
    ev = cal.save_event(dtstart=inicio, dtend=fin, summary=titulo, description=descripcion,
                        attendee=[f"mailto:{i}" for i in invitados] or None)
    return str(ev.url)


async def crear_cita(departamento: str, titulo: str, inicio: str, fin: str, descripcion: str = "",
                     invitados: list[str] | None = None) -> dict:
    url = await asyncio.to_thread(_crear, departamento, titulo, datetime.fromisoformat(inicio),
                                  datetime.fromisoformat(fin), descripcion, invitados or [])
    return {"cita": url}


registrar(Herramienta(
    nombre="calendario",
    descripcion="Calendario (CalDAV propio). Las fechas van en formato ISO 8601 (AAAA-MM-DDThh:mm).",
    operaciones={"huecos": huecos, "proponer_cita": proponer_cita, "crear_cita": crear_cita},
    externas=frozenset({"crear_cita"}),
    ayuda={"huecos": "huecos libres entre dos fechas", "proponer_cita": "propone varias franjas libres sin reservar nada",
           "crear_cita": "reserva la cita y avisa a los invitados"},
    ejemplos={"proponer_cita": {"desde": "2026-10-08T09:00", "hasta": "2026-10-08T14:00", "duracion_min": 60, "opciones": 3}},
))
