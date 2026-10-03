"""Reglas de la bandeja de aprobaciones (sin base de datos, para poder probarlas).

- simple: basta el responsable del departamento.
- doble: responsable del departamento y dirección, dos personas distintas.
- La voz solo vale para aprobaciones simples; las dobles se confirman en el panel.
- Un rechazo de cualquiera de los aprobadores rechaza la acción.
"""
from __future__ import annotations

from dataclasses import dataclass, field


class DecisionNoValida(PermissionError):
    pass


@dataclass
class Solicitud:
    id: str
    agente: str
    departamento: str
    accion: str
    nivel: str                               # simple | doble
    aprobadores: tuple[str, ...]             # roles requeridos
    voz_permitida: bool
    datos: dict = field(default_factory=dict)
    decisiones: list[dict] = field(default_factory=list)
    estado: str = "pendiente"                # pendiente | aprobada | rechazada


def roles_cubiertos(s: Solicitud) -> set[str]:
    return {d["rol"] for d in s.decisiones if d["aprobado"]}


def decidir(s: Solicitud, usuario: str, roles_usuario: set[str], departamentos_usuario: set[str],
            aprobado: bool, canal: str, comentario: str = "") -> Solicitud:
    if s.estado != "pendiente":
        raise DecisionNoValida(f"La solicitud ya está {s.estado}")
    if canal == "voz" and not s.voz_permitida:
        raise DecisionNoValida("Esta aprobación es doble: confírmala en el panel")
    if any(d["usuario"] == usuario for d in s.decisiones):
        raise DecisionNoValida("Ya has decidido sobre esta solicitud; la segunda firma la hace otra persona")
    pendientes = [r for r in s.aprobadores if r not in roles_cubiertos(s)]
    rol = None
    for r in pendientes:
        if r == "direccion" and "direccion" in roles_usuario:
            rol = r
            break
        if r == "responsable_departamento" and "responsable" in roles_usuario \
                and s.departamento in departamentos_usuario:
            rol = r
            break
    if rol is None:
        raise DecisionNoValida("No tienes el rol que falta para esta aprobación")
    s.decisiones.append({"usuario": usuario, "rol": rol, "aprobado": aprobado,
                         "canal": canal, "comentario": comentario})
    if not aprobado:
        s.estado = "rechazada"
    elif set(s.aprobadores) <= roles_cubiertos(s):
        s.estado = "aprobada"
    return s
