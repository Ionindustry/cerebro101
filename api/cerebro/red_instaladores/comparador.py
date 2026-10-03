"""Comparador de presupuestos de instaladores.

Puntúa las respuestas de los instaladores con acuerdo por precio, rapidez y
eficiencia (pesos configurables por tipo de obra). La propuesta la aprueba
siempre una persona: este módulo solo ordena y explica.
"""
from __future__ import annotations

from dataclasses import dataclass

PESOS_POR_DEFECTO = {"precio": 0.40, "rapidez": 0.30, "eficiencia": 0.30}


@dataclass
class Oferta:
    instalador: str
    precio: float                 # importe total ofertado
    dias_hasta_inicio: float      # primera fecha disponible
    horas_respuesta: float        # tiempo que tardó en responder
    ratio_horas_historico: float  # horas reales / estimadas en trabajos anteriores (1.0 = exacto)
    incidencias_historico: int    # incidencias en los últimos 12 meses
    valoracion_calidad: float     # 0–5 de la Evaluación de Instaladores
    trabajos_previos: int = 0


@dataclass
class Puntuacion:
    instalador: str
    total: float
    precio: float
    rapidez: float
    eficiencia: float
    notas: list[str]


def _proporcional(valor: float, mejor: float) -> float:
    """1.0 para el mejor (el más bajo) y proporcional para el resto: un 15 % más caro
    puntúa 0,87, no 0, así que una diferencia pequeña no decide sola la adjudicación."""
    return (mejor + 1) / (valor + 1)


def puntuar(ofertas: list[Oferta], pesos: dict[str, float] | None = None) -> list[Puntuacion]:
    if not ofertas:
        return []
    pesos = pesos or PESOS_POR_DEFECTO
    if abs(sum(pesos.values()) - 1.0) > 1e-6:
        raise ValueError("Los pesos deben sumar 1")
    precios = [o.precio for o in ofertas]
    rapidez_bruta = [o.dias_hasta_inicio + o.horas_respuesta / 24 for o in ofertas]
    resultado = []
    for o, rb in zip(ofertas, rapidez_bruta):
        notas = []
        p_precio = _proporcional(o.precio, min(precios))
        p_rapidez = _proporcional(rb, min(rapidez_bruta))
        desvio = abs(o.ratio_horas_historico - 1.0)
        p_eficiencia = max(0.0, 1.0 - desvio) * 0.5 + (o.valoracion_calidad / 5) * 0.4 \
            + max(0.0, 1.0 - o.incidencias_historico / 5) * 0.1
        if o.trabajos_previos < 3:
            p_eficiencia = min(p_eficiencia, 0.6)
            notas.append("Pocos trabajos previos: eficiencia limitada a 0,6 hasta tener historial")
        if o.ratio_horas_historico > 1.2:
            notas.append("Suele superar las horas estimadas en más de un 20 %")
        total = pesos["precio"] * p_precio + pesos["rapidez"] * p_rapidez + pesos["eficiencia"] * p_eficiencia
        resultado.append(Puntuacion(o.instalador, round(total, 4), round(p_precio, 4),
                                    round(p_rapidez, 4), round(p_eficiencia, 4), notas))
    return sorted(resultado, key=lambda x: x.total, reverse=True)
