"""Oferta de una licitación: el borrador por secciones que redactan los agentes (api/cerebro/licitaciones/ofertas.py).

Los agentes solo escriben BORRADORES. No pueden revisar ni aprobar una sección, ni fijar el precio, ni pisar lo que una persona editó o aprobó, ni citar requisitos del pliego que no existan o no estén
confirmados. Nada se presenta ni se firma desde aquí: una persona revisa, exporta a Word, firma y presenta. Quién escribe lo pone el sistema (el agente que llama), no el modelo.
"""
from __future__ import annotations

from ..licitaciones import ofertas as O
from . import licitaciones as motor
from .base import Herramienta, registrar

MAX_LISTADO = 1500            # caracteres de cada sección en el listado: para leerla entera, «seccion»


async def plan(licitacion: str) -> dict:
    ficha = await motor.ficha(licitacion)
    return await _tal_cual(O.plan(licitacion, ficha, "agente"))


async def leer(licitacion: str) -> dict:
    return await _tal_cual(O.leer(licitacion, True, MAX_LISTADO))


async def seccion(licitacion: str, sobre: str, clave: str) -> dict:
    o = await O.leer(licitacion)
    if not o["existe"]:
        raise LookupError("Esta licitación aún no tiene la oferta preparada: usa primero «plan»")
    for s in o["secciones"]:
        if s["sobre"] == sobre and s["clave"] == clave:
            return {**s, "nota": o["nota"]}
    raise LookupError("No existe esa sección: mira «leer» para ver las que hay")


async def guardar_seccion(licitacion: str, sobre: str, clave: str, contenido: str, citas: list[int] | None = None, titulo: str | None = None, agente: str | None = None) -> dict:
    s = await O.escribir_seccion(licitacion, sobre, clave, contenido, citas, titulo, agente=agente or "agente")
    return {"guardada": True, "sobre": s["sobre"], "clave": s["clave"], "estado": s["estado"], "version": s["version"], "citas": s["citas"],
            "nota": "Es un borrador: una persona lo revisará. Si aún quedan secciones, sigue con la siguiente."}


async def _tal_cual(coro) -> dict:
    try:
        return await coro
    except O.NoExiste as e:
        raise LookupError(str(e)) from None


registrar(Herramienta(
    nombre="ofertas",
    descripcion="La oferta de una licitación, por secciones (sobre administrativo, técnico y económico). Prepara las secciones a partir del pliego, lee las que hay y guarda el borrador de una sección. "
                "SOLO escribes borradores: una persona los revisa, aprueba y presenta, y el precio de la oferta lo fija una persona (no escribas la proposición económica ni inventes el precio). "
                "Cita siempre los requisitos del pliego en los que te apoyas (sus ids, que salen de la herramienta «pliegos», operación «requisitos»). "
                "La licitación se indica por su identificador (UUID), que NO hay que pedirle a la persona: se obtiene con la herramienta «licitaciones».",
    operaciones={"plan": plan, "leer": leer, "seccion": seccion, "guardar_seccion": guardar_seccion},
    ayuda={"plan": "prepara la oferta (si no estaba) y devuelve sus secciones, cada una con su «guia» (lo que pide el pliego), su estado y los requisitos técnicos aún sin cubrir",
           "leer": "las secciones de la oferta con su estado y el principio de su contenido, y los requisitos técnicos del pliego que ninguna sección cita todavía",
           "seccion": "una sección entera: su guía, su contenido actual, su estado y quién la escribió",
           "guardar_seccion": "guarda el borrador de una sección (sobre: administrativo, tecnico o economico; clave: la de «plan»). Reemplaza el borrador anterior si es tuyo; no puede tocar lo que haya "
                              "editado o aprobado una persona. Pasa en «citas» los ids de los requisitos confirmados del pliego en los que te apoyas. Para crear una sección nueva (no en el sobre económico) indica «titulo»"},
    ejemplos={"plan": {"licitacion": "0b1f7a3e-1111-4222-8333-444444444444"}, "leer": {"licitacion": "0b1f7a3e-1111-4222-8333-444444444444"},
              "seccion": {"licitacion": "0b1f7a3e-1111-4222-8333-444444444444", "sobre": "tecnico", "clave": "descripcion-solucion"},
              "guardar_seccion": {"licitacion": "0b1f7a3e-1111-4222-8333-444444444444", "sobre": "tecnico", "clave": "descripcion-solucion",
                                  "contenido": "Instalaremos 40 cámaras IP de 4K con grabación a 30 días…", "citas": [12, 15]}},
))
