"""Herramientas de cálculo deterministas: cotizador y comparador de instaladores."""
from __future__ import annotations

from dataclasses import MISSING

from ..cotizador import Solicitud, calcular
from ..cotizador.motor import cargar_parametros
from ..red_instaladores import PESOS_POR_DEFECTO, Oferta, puntuar
from .base import Herramienta, registrar


CAMPOS_OFERTA = tuple(Oferta.__dataclass_fields__)
CAMPOS_OBLIGATORIOS = tuple(n for n, f in Oferta.__dataclass_fields__.items() if f.default is MISSING)


async def cotizar(**campos) -> dict:
    return calcular(Solicitud(**campos)).como_dict()


def _validar_pesos(pesos: dict | None) -> dict | None:
    """`pesos` es opcional y un objeto libre: se comprueba con mensajes que el modelo pueda corregir (antes daba un TypeError)."""
    if not pesos:
        return None
    sobran = [k for k in pesos if k not in PESOS_POR_DEFECTO]
    if sobran:
        raise ValueError(f"«pesos» solo admite las claves {', '.join(PESOS_POR_DEFECTO)}; sobra: {', '.join(repr(k[:40]) for k in sobran)}. "
                         "Si nadie ha pedido otros pesos, omite «pesos»")
    if set(pesos) != set(PESOS_POR_DEFECTO) or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in pesos.values()):
        raise ValueError(f"«pesos» necesita las tres claves {', '.join(PESOS_POR_DEFECTO)} con números que sumen 1 "
                         f"(por defecto {PESOS_POR_DEFECTO}). Si nadie ha pedido otros pesos, omite «pesos»")
    return pesos


def _oferta(i: int, o: dict) -> Oferta:
    if not isinstance(o, dict):
        raise ValueError(f"La oferta {i + 1} debe ser un objeto con los campos {', '.join(CAMPOS_OFERTA)}")
    sobran = [k for k in o if k not in CAMPOS_OFERTA]
    faltan = [k for k in CAMPOS_OBLIGATORIOS if k not in o]
    if sobran or faltan:
        raise ValueError(f"Oferta {i + 1} ({str(o.get('instalador', '?'))[:30]}): " + "; ".join(
            m for m in (f"sobran {', '.join(repr(k[:40]) for k in sobran)}" if sobran else "",
                        f"faltan {', '.join(faltan)}" if faltan else "") if m) + f". Campos: {', '.join(CAMPOS_OFERTA)}")
    return Oferta(**o)


async def comparar(ofertas: list[dict], pesos: dict | None = None) -> list[dict]:
    return [p.__dict__ for p in puntuar([_oferta(i, o) for i, o in enumerate(ofertas)], _validar_pesos(pesos))]


def _ids(seccion: str) -> str:
    try:
        return ", ".join(cargar_parametros()[seccion])
    except Exception:  # noqa: BLE001 - sin catálogo disponible el esquema sigue sirviendo
        return "(ver config/contador/parametros.yaml)"


def _campos_cotizar() -> dict[str, str]:
    return {
        "partidas": f"objeto {{id_partida: unidades}}. Ids: {_ids('partidas_instalacion')}",
        "ajuste_horas": "objeto {id_partida: horas por unidad para este caso}",
        "cuadrilla_tecnicos": "«uno» o «pareja» (sin técnicos si se omite)",
        "metros_cableado": f"objeto {{tipo: metros}}. Tipos: {_ids('cableado')}",
        "cuadrilla_lampistas": "«uno» o «pareja»",
        "materiales": f"objeto {{id_material: metros o unidades}}. Ids: {_ids('materiales')}",
        "tareas_ingenieria": f"objeto {{id_tarea: unidades}}. Ids: {_ids('tareas_ingenieria')}",
        "ingenieros": "entero", "horas_comerciales": "objeto {nombre: horas}",
        "operarios_dietas_instaladores": "entero", "operarios_dietas_tecnicos": "entero", "elevador": "entero (días)",
        "documentacion_proteccion_datos": "entero (0 o 1)", "precio_definitivo": "número: redondeo comercial; si se omite es automático",
        "tarifa_instalador_externo": "objeto {categoría: coste/hora} que sustituye al coste interno",
    }


registrar(Herramienta(
    nombre="cotizador",
    descripcion="Calcula un presupuesto de instalación con el motor del contador. Los ids de partidas, cableado y "
                "materiales deben ser exactamente los del catálogo: un id desconocido da error.",
    operaciones={"cotizar": cotizar},
    ayuda={"cotizar": "devuelve venta, coste y margen con sus líneas; todos los campos son opcionales"},
    campos={"cotizar": _campos_cotizar()},
    ejemplos={"cotizar": {"partidas": {"camara_exterior": 2}, "cuadrilla_tecnicos": "uno"}},
))
registrar(Herramienta(
    nombre="comparador_instaladores",
    descripcion="Ordena presupuestos de instaladores por precio, rapidez y eficiencia.",
    operaciones={"comparar": comparar},
    ayuda={"comparar": "cada oferta es un objeto {instalador, precio, dias_hasta_inicio, horas_respuesta, ratio_horas_historico, "
                       "incidencias_historico, valoracion_calidad (0-5), trabajos_previos?}; pesos: OMÍTELO salvo que se pidan otros; si se pasa, "
                       "son exactamente {precio, rapidez, eficiencia} y suman 1 (por defecto 0.4, 0.3, 0.3)"},
    ejemplos={"comparar": {"ofertas": [{"instalador": "Roca SL", "precio": 1000, "dias_hasta_inicio": 5, "horas_respuesta": 4,
                                        "ratio_horas_historico": 1.0, "incidencias_historico": 0, "valoracion_calidad": 4.5}]}},
))
