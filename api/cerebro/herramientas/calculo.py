"""Herramientas de cálculo deterministas: cotizador y comparador de instaladores."""
from __future__ import annotations

from ..cotizador import Solicitud, calcular
from ..cotizador.motor import cargar_parametros
from ..red_instaladores import Oferta, puntuar
from .base import Herramienta, registrar


async def cotizar(**campos) -> dict:
    return calcular(Solicitud(**campos)).como_dict()


async def comparar(ofertas: list[dict], pesos: dict | None = None) -> list[dict]:
    return [p.__dict__ for p in puntuar([Oferta(**o) for o in ofertas], pesos)]


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
                       "incidencias_historico, valoracion_calidad (0-5), trabajos_previos?}; pesos = objeto opcional"},
    ejemplos={"comparar": {"ofertas": [{"instalador": "Roca SL", "precio": 1000, "dias_hasta_inicio": 5, "horas_respuesta": 4,
                                        "ratio_horas_historico": 1.0, "incidencias_historico": 0, "valoracion_calidad": 4.5}]}},
))
