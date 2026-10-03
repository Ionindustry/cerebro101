"""Motor de cotización de instalaciones.

Replica la lógica del contador de instalaciones corregido (hoja «Puesta Marcha»),
con todos los valores fijos sacados a config/contador/parametros.yaml.

Es código determinista: el modelo de IA nunca calcula importes. Los agentes
(Cotizador, Medidor Técnico, Especialistas) solo rellenan la `Solicitud` —partidas,
metros, horas ajustadas— y el motor devuelve el desglose con coste, venta y márgenes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml

RUTA_PARAMETROS = Path(__file__).resolve().parents[3] / "config" / "contador" / "parametros.yaml"

Cuadrilla = Literal["uno", "pareja"]


def cargar_parametros(ruta: Path | str = RUTA_PARAMETROS) -> dict:
    with open(ruta, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@dataclass
class Solicitud:
    """Lo que el agente rellena para un caso concreto."""

    partidas: dict[str, float] = field(default_factory=dict)          # id partida → unidades
    ajuste_horas: dict[str, float] = field(default_factory=dict)      # id partida → horas/unidad para este caso
    cuadrilla_tecnicos: Cuadrilla | None = None                       # None = sin técnicos
    metros_cableado: dict[str, float] = field(default_factory=dict)   # tipo cableado → metros
    cuadrilla_lampistas: Cuadrilla | None = None
    materiales: dict[str, float] = field(default_factory=dict)        # id material → metros o unidades
    tareas_ingenieria: dict[str, float] = field(default_factory=dict) # id tarea → unidades
    ingenieros: int = 1
    horas_comerciales: dict[str, float] = field(default_factory=dict) # comercial → horas
    operarios_dietas_instaladores: int = 1
    operarios_dietas_tecnicos: int = 1
    elevador: int = 0
    documentacion_proteccion_datos: int = 0
    precio_definitivo: float | None = None                            # redondeo comercial; None = automático
    tarifa_instalador_externo: dict[str, float] | None = None         # coste/hora negociado que sustituye al interno


@dataclass
class Linea:
    concepto: str
    venta: float
    coste: float


@dataclass
class Resultado:
    lineas: list[Linea]
    horas_instalacion: float
    horas_cableado: float
    venta_base: float               # total configuración y puesta en marcha
    coste_base: float
    coste_financiero: float
    venta_con_financiero: float
    contingencia: float
    venta_total: float
    coste_total: float
    precio_definitivo: float
    coste_por_metro: float | None
    margen_total: float             # (venta_total - coste_total) / venta_total
    margen_definitivo: float        # (precio_definitivo - coste_total) / precio_definitivo
    avisos: list[str]

    def como_dict(self) -> dict:
        d = self.__dict__.copy()
        d["lineas"] = [l.__dict__ for l in self.lineas]
        return d


def _r(x: float) -> float:
    return round(x + 0.0, 2)


def calcular(solicitud: Solicitud, p: dict | None = None) -> Resultado:
    p = p or cargar_parametros()
    avisos: list[str] = []
    f2 = p["factor_dos_operarios"]
    jornada = p["horas_por_jornada"]
    lineas: list[Linea] = []

    # 1. Tiempos de instalación (horas de un operario)
    horas_inst = 0.0
    for pid, uds in solicitud.partidas.items():
        if pid not in p["partidas_instalacion"]:
            raise ValueError(f"Partida desconocida: {pid}")
        h = solicitud.ajuste_horas.get(pid, p["partidas_instalacion"][pid]["horas"])
        if pid in solicitud.ajuste_horas:
            avisos.append(f"Horas de «{pid}» ajustadas a {h} h/ud para este caso")
        horas_inst += h * uds

    # 2. Técnicos
    t = p["tecnicos"]
    ext = solicitud.tarifa_instalador_externo or {}
    coste_t1 = ext.get("tecnico_primera", t["primera"]["coste_hora"])
    coste_t2 = ext.get("tecnico_ayudante", t["ayudante"]["coste_hora"])
    venta_t1 = t["primera"]["coste_hora"] * t["primera"]["recargo"]
    venta_t2 = t["ayudante"]["coste_hora"] * t["ayudante"]["recargo"]
    if solicitud.cuadrilla_tecnicos == "uno":
        lineas.append(Linea("Técnicos (1 operario)", venta_t1 * horas_inst, coste_t1 * horas_inst))
    elif solicitud.cuadrilla_tecnicos == "pareja":
        h = horas_inst * f2
        lineas.append(Linea("Técnicos (pareja)", (venta_t1 + venta_t2) * h, (coste_t1 + coste_t2) * h))
    elif horas_inst:
        avisos.append("Hay partidas de instalación pero no se ha elegido cuadrilla de técnicos")
    else:
        lineas.append(Linea("Técnicos", 0.0, 0.0))

    # 3. Cableado y lampistas (horas por metro y operario; la pareja aplica el factor)
    horas_cab = 0.0
    for tipo, metros in solicitud.metros_cableado.items():
        if tipo not in p["cableado"]:
            raise ValueError(f"Tipo de cableado desconocido: {tipo}")
        horas_cab += p["cableado"][tipo] * metros
    lam = p["lampistas"]
    coste_l1 = ext.get("lampista_oficial", lam["oficial"]["coste_hora"])
    coste_l2 = ext.get("lampista_ayudante", lam["ayudante"]["coste_hora"])
    venta_l1 = lam["oficial"]["coste_hora"] * lam["oficial"]["recargo"]
    venta_l2 = lam["ayudante"]["coste_hora"] * lam["ayudante"]["recargo"]
    if solicitud.cuadrilla_lampistas == "uno":
        lineas.append(Linea("Lampistas (1 operario)", venta_l1 * horas_cab, coste_l1 * horas_cab))
    elif solicitud.cuadrilla_lampistas == "pareja":
        h = horas_cab * f2
        lineas.append(Linea("Lampistas (pareja)", (venta_l1 + venta_l2) * h, (coste_l1 + coste_l2) * h))
    elif horas_cab:
        avisos.append("Hay metros de cableado pero no se ha elegido cuadrilla de lampistas")

    # 4. Material
    venta_mat = coste_mat = 0.0
    for mid, cant in solicitud.materiales.items():
        if mid not in p["materiales"]:
            raise ValueError(f"Material desconocido: {mid}")
        m = p["materiales"][mid]
        divisor = p["margen_material"][m["tipo"]]
        venta_mat += m["coste"] / divisor * cant
        coste_mat += m["coste"] * cant
    lineas.append(Linea("Material", venta_mat, coste_mat))

    # 5. Ingeniería
    horas_ing = 0.0
    for tid, uds in solicitud.tareas_ingenieria.items():
        if tid not in p["tareas_ingenieria"]:
            raise ValueError(f"Tarea de ingeniería desconocida: {tid}")
        horas_ing += p["tareas_ingenieria"][tid]["horas"] * uds
    ing = p["ingeniero"]
    lineas.append(Linea("Ingeniería", horas_ing * ing["venta_hora"] * solicitud.ingenieros,
                        horas_ing * ing["coste_hora"] * solicitud.ingenieros))

    # 6. Comerciales
    hc = sum(solicitud.horas_comerciales.values())
    com = p["comercial"]
    lineas.append(Linea("Comercial", hc * com["venta_hora"], hc * com["coste_hora"]))

    # 7. Desplazamientos y dietas (días = horas de un operario / jornada)
    dias_inst = (horas_inst + horas_cab) / jornada
    dias_tec = horas_ing / jornada
    d, di = p["desplazamiento"], p["dieta"]
    venta_dd = (dias_inst * d["venta_dia"] + dias_tec * d["venta_dia"]
                + dias_inst * solicitud.operarios_dietas_instaladores * di["venta_dia"]
                + (di["fija_instaladores"] if dias_inst else 0.0)
                + dias_tec * solicitud.operarios_dietas_tecnicos * di["venta_dia"])
    coste_dd = (dias_inst * d["coste_dia"] + dias_tec * d["coste_dia"]
                + dias_inst * solicitud.operarios_dietas_instaladores * di["coste_dia"]
                + dias_tec * solicitud.operarios_dietas_tecnicos * di["coste_dia"])
    lineas.append(Linea("Desplazamientos y dietas", venta_dd, coste_dd))

    # 8. Varios
    v = p["varios"]
    lineas.append(Linea("Elevador", solicitud.elevador * v["elevador"]["venta"],
                        solicitud.elevador * v["elevador"]["coste"]))
    doc = v["documentacion_proteccion_datos"]
    venta_doc = solicitud.documentacion_proteccion_datos * doc["venta"]
    coste_doc = solicitud.documentacion_proteccion_datos * doc["coste"]
    lineas.append(Linea("Documentación de protección de datos", venta_doc, coste_doc))

    # 9. Totales (misma estructura que el contador corregido)
    venta_base = sum(l.venta for l in lineas)
    coste_sin_doc = sum(l.coste for l in lineas) - coste_doc
    coste_fin = coste_sin_doc * p["coste_financiero"]
    venta_con_fin = venta_base + coste_fin
    contingencia = venta_con_fin * p["contingencia"]
    venta_total = venta_con_fin + contingencia
    coste_total = coste_sin_doc + coste_fin + coste_doc

    precio_def = solicitud.precio_definitivo if solicitud.precio_definitivo is not None else round(venta_total)
    if solicitud.precio_definitivo is not None and solicitud.precio_definitivo < coste_total:
        avisos.append("El precio definitivo está por debajo del coste total")
    metros = sum(solicitud.metros_cableado.values())
    return Resultado(
        lineas=[Linea(l.concepto, _r(l.venta), _r(l.coste)) for l in lineas],
        horas_instalacion=_r(horas_inst),
        horas_cableado=_r(horas_cab),
        venta_base=_r(venta_base),
        coste_base=_r(coste_sin_doc),
        coste_financiero=_r(coste_fin),
        venta_con_financiero=_r(venta_con_fin),
        contingencia=_r(contingencia),
        venta_total=_r(venta_total),
        coste_total=_r(coste_total),
        precio_definitivo=_r(precio_def),
        coste_por_metro=_r(precio_def / metros) if metros else None,
        margen_total=round((venta_total - coste_total) / venta_total, 4) if venta_total else 0.0,
        margen_definitivo=round((precio_def - coste_total) / precio_def, 4) if precio_def else 0.0,
        avisos=avisos,
    )
