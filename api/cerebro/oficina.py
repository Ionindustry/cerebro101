"""Estado de la oficina para el panel: cada departamento con sus agentes y qué está haciendo cada uno.

Función pura (sin base de datos) para poder probarla. Quien no es de dirección ve el detalle de lo que hacen los agentes de SUS departamentos;
de los demás solo ve si están en reposo, trabajando o esperando una aprobación.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .registro import Registro


def construir(reg: Registro, snap: dict, roles: set[str], departamentos: set[str]) -> dict:
    ve_todo = "direccion" in roles
    deps, trabajando, esperando, total = [], 0, 0, 0
    for dep_id, dep in reg.departamentos.items():
        visible = ve_todo or dep_id in departamentos
        agentes = []
        for f in reg.del_departamento(dep_id):
            a = snap["actividad"].get(f.id, {})
            pend = int(snap["pendientes"].get(f.id, 0))
            estado = "trabajando" if a.get("estado") == "trabajando" else ("esperando" if pend else "reposo")
            if estado == "trabajando":
                detalle = a.get("detalle")
            elif estado == "esperando":
                detalle = f"Espera {'una aprobación' if pend == 1 else f'{pend} aprobaciones'}"
            else:
                detalle = ("Última tarea: " + a["ultima"]) if a.get("ultima") else ("Trabaja de forma programada" if f.horario else None)
            agentes.append({"id": f.id, "nombre": f.nombre, "subarea": f.subarea, "director": f.director, "estado": estado,
                            "aprobacion": f.aprobacion, "programado": bool(f.horario),
                            "detalle": detalle if visible else None,
                            "desde": (a.get("actualizado") if estado == "trabajando" else a.get("ultima_fecha"))})
            total += 1
            trabajando += estado == "trabajando"
            esperando += estado == "esperando"
        deps.append({"id": dep_id, "nombre": dep["nombre"], "director": dep["director"], "agentes": agentes, "detalle_visible": visible})
    nombres = {f.id: f for f in reg.fichas.values()}
    eventos = []
    for u in snap.get("ultimas", [])[:12]:
        f = nombres.get(u["agente"])
        if not f or not (ve_todo or f.departamento in departamentos):
            continue
        eventos.append({"agente": f.nombre, "departamento": f.departamento, "texto": f"{u['herramienta']} · {u['operacion']}",
                        "ok": bool(u["ok"]), "cuando": u["creado"]})
    return {"departamentos": deps, "resumen": {"total": total, "trabajando": trabajando, "esperando": esperando},
            "eventos": eventos, "hora": datetime.now(timezone.utc).isoformat()}
