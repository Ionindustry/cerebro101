"""Construcción del grafo: Director General → director de departamento → agente → aprobaciones."""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from . import nodos
from .estado import Estado


def construir(checkpointer=None):
    g = StateGraph(Estado)
    g.add_node("enrutar", nodos.enrutar)
    g.add_node("elegir_agente", nodos.elegir_agente)
    g.add_node("ejecutar_agente", nodos.ejecutar_agente)
    g.add_node("registrar_aprobaciones", nodos.registrar_aprobaciones)
    g.add_node("esperar_aprobaciones", nodos.esperar_aprobaciones)
    g.add_node("ejecutar_acciones", nodos.ejecutar_acciones)

    g.add_edge(START, "enrutar")
    g.add_edge("enrutar", "elegir_agente")
    g.add_edge("elegir_agente", "ejecutar_agente")
    g.add_conditional_edges("ejecutar_agente",
                            lambda e: "registrar_aprobaciones" if e.get("acciones") else END)
    g.add_edge("registrar_aprobaciones", "esperar_aprobaciones")
    g.add_edge("esperar_aprobaciones", "ejecutar_acciones")
    g.add_edge("ejecutar_acciones", END)
    return g.compile(checkpointer=checkpointer)
