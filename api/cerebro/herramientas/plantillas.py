"""Plantillas de la documentación administrativa de una licitación (api/cerebro/licitaciones/plantillas.py).

El sistema rellena SOLO las plantillas del concurso (anexos, declaración responsable…) con los datos de la sociedad que se presenta (ERP) y de la ficha. Un agente ayuda en lo dudoso: puede ELEGIR QUÉ DATO
va en un hueco (por su clave), nunca escribir el valor, que siempre sale del ERP o de la ficha. Nada se firma ni se presenta: una persona revisa y firma con su certificado digital.
"""
from __future__ import annotations

from ..licitaciones import empresa as E
from ..licitaciones import ofertas as O
from ..licitaciones import plantillas as P
from . import licitaciones as motor
from .base import Herramienta, registrar


async def _ficha(licitacion: str) -> dict:
    try:
        return await motor.ficha(licitacion)
    except Exception:      # noqa: BLE001 — sin la ficha se rellena con lo del ERP; los datos de la licitación quedan como hueco
        return {}


async def _tal_cual(coro) -> dict:
    try:
        return await coro
    except O.NoExiste as e:
        raise LookupError(str(e)) from None
    except E.VariasEmpresas as e:
        raise ValueError("Hay varias empresas en el ERP y no se ha elegido con cuál se presenta la oferta: lo elige una persona en la tarjeta «Documentación administrativa» de la oferta. "
                         "Empresas: " + ", ".join(x["razon_social"] for x in e.empresas)) from None
    except (E.ErrorEmpresa, P.ErrorPlantilla, O.ErrorOferta) as e:
        raise ValueError(str(e)) from None


async def listar(licitacion: str) -> dict:
    return await _tal_cual(P.listar(licitacion))


async def datos_disponibles(licitacion: str) -> dict:
    o = await O.leer(licitacion, con_contenido=False)
    return await _tal_cual(P.claves_disponibles(o.get("empresa"), await _ficha(licitacion), licitacion))


async def rellenar(licitacion: str, documento: int, asignaciones: dict[str, str] | None = None, miembro: str | None = None, agente: str | None = None) -> dict:
    if asignaciones is not None and (not isinstance(asignaciones, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in asignaciones.items())):
        raise ValueError("asignaciones debe ser {hueco: clave}, p. ej. {\"t4\": \"empresa.nif\"}")
    malas = [v for v in (asignaciones or {}).values() if v not in P.CLAVES_VALIDAS]
    if malas:
        raise ValueError(f"Claves no válidas: {malas[:5]}. Mira «datos_disponibles»: solo se elige entre esas claves, el valor lo pone el sistema")
    if isinstance(documento, bool) or not isinstance(documento, int) or documento < 1:
        raise ValueError("documento es el número del documento del pliego (desde 1), el que da «pliegos» → «documentos»")
    o = await O.leer(licitacion, con_contenido=False)
    return await _tal_cual(P.preparar(licitacion, await _ficha(licitacion), f"agente:{agente or 'agente'}", o.get("empresa"), documento, asignaciones, miembro))


registrar(Herramienta(
    nombre="plantillas",
    descripcion="Las plantillas de la documentación administrativa del concurso (anexos, declaración responsable, modelos), ya rellenadas con los datos de la sociedad que se presenta, que salen del ERP. "
                "El sistema rellena una COPIA y respeta el documento original; tú solo ayudas con los huecos dudosos eligiendo QUÉ DATO va en cada uno (por su clave): nunca escribes el valor, que sale del ERP o de la ficha. "
                "Nada se firma ni se presenta: una persona revisa y firma con su certificado digital. La licitación se indica por su identificador (UUID), que se obtiene con la herramienta «licitaciones».",
    operaciones={"listar": listar, "datos_disponibles": datos_disponibles, "rellenar": rellenar},
    ayuda={"listar": "las plantillas ya preparadas: estado (lista_para_firma, faltan_datos…), lo rellenado con su origen y los huecos pendientes con su id, su etiqueta y el motivo",
           "datos_disponibles": "qué datos hay para rellenar (clave y valor, del ERP y de la ficha) y cuáles faltan y dónde se completan en el ERP",
           "rellenar": "vuelve a rellenar UN documento del pliego (por su número) eligiendo qué dato va en los huecos dudosos: asignaciones = {id del hueco: clave de dato}. Si el documento es un ZIP con varios anexos, indica también el «miembro» (el fichero de dentro). Solo se elige entre las claves de «datos_disponibles»; "
                       "para la fecha usa «al_firmar». Si el dato falta en el ERP, el hueco queda pendiente y se dice dónde completarlo"},
    ejemplos={"listar": {"licitacion": "0b1f7a3e-1111-4222-8333-444444444444"}, "datos_disponibles": {"licitacion": "0b1f7a3e-1111-4222-8333-444444444444"},
              "rellenar": {"licitacion": "0b1f7a3e-1111-4222-8333-444444444444", "documento": 3, "asignaciones": {"t4": "empresa.nif"}}},
))
