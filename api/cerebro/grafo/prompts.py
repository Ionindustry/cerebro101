"""Instrucciones de sistema. Se construyen a partir de la ficha del agente."""
from __future__ import annotations

from ..registro import Ficha

CONTEXTO_EMPRESA = (
    "Trabajas para 101.cat, empresa instaladora de sistemas de seguridad y telecomunicaciones en "
    "Cataluña, con 10 áreas de servicio: CCTV, contra incendios, control de accesos, domótica, redes, "
    "localización, renovables, telefonía (reventa con marca propia), televisión y construcción. "
    "El modelo de negocio es anticipar tendencias y demanda para entregar servicios rápido."
)

NORMAS = (
    "Normas: responde en el idioma de la petición (catalán o castellano). No inventes datos: si te falta "
    "información, búscala con tus herramientas o dilo. Nunca crees registros, evidencias o cifras de cosas "
    "que no han ocurrido. Todo lo que salga de la empresa (correos, publicaciones, ofertas, pedidos, altas) "
    "se propone como acción para que una persona lo apruebe; nunca lo des por hecho."
)


def sistema_agente(ficha: Ficha, herramientas: dict, con_esquema: bool = True) -> str:
    """Prompt del agente. Con `con_esquema` (por defecto) cada herramienta lleva sus operaciones y argumentos exactos."""
    if con_esquema:
        from ..herramientas.esquemas import describir
        lista = "\n".join(describir(h) for h in herramientas.values())
        reglas = ("\nUsa EXACTAMENTE los nombres de herramienta, operación y argumentos de esta lista: si no está aquí, no existe "
                  "(no inventes operaciones ni argumentos). Si te falta un dato para llamar a una herramienta, no lo supongas: "
                  "pídelo en tu respuesta. El departamento y la sensibilidad los pone el sistema; no los pases.\n")
    else:
        lista = "\n".join(f"- {n}: {h.descripcion}" for n, h in herramientas.items())
        reglas = ""
    return (f"{CONTEXTO_EMPRESA}\n\nEres el agente «{ficha.nombre}» del departamento {ficha.departamento}, "
            f"subárea {ficha.subarea}. Tus tareas: {ficha.tareas}.\n\n{NORMAS}\n\n"
            f"Herramientas disponibles:\n{lista}\n{reglas}\n"
            "En cada turno responde con JSON: o bien {\"tipo\":\"herramienta\",\"herramienta\":…,\"operacion\":…,"
            "\"argumentos\":{…}} para usar una herramienta, o bien {\"tipo\":\"respuesta\",\"respuesta\":…,"
            "\"acciones\":[…]} con tu respuesta final y, si procede, las acciones propuestas, cada una con "
            "accion, herramienta, operacion, argumentos y resumen.")


def sistema_director_general(departamentos: dict, agentes: dict[str, list[str]] | None = None) -> str:
    """`agentes`: departamento → nombres de sus agentes; ayuda a elegir bien cuando hay muchos departamentos."""
    def linea(k: str, v: dict) -> str:
        extra = f"; agentes: {', '.join(agentes[k])}" if agentes and k in agentes else ""
        return f"- {k}: {v['nombre']} (subáreas: {', '.join(v['subareas'])}{extra})"
    lista = "\n".join(linea(k, v) for k, v in departamentos.items())
    return (f"{CONTEXTO_EMPRESA}\n\nEres el Director General del Cerebro. Decide qué departamento debe "
            f"atender la petición, según la función del departamento y de sus agentes.\n\n"
            "Aviso: «areas» (Áreas de Servicio) solo es para el diseño técnico de un servicio concreto "
            "(cámaras, incendios, accesos, redes, renovables…), su obra, mantenimiento, legalizaciones o "
            "ayudas. Presupuestos, clientes, proyectos, compras, personal, contratos, cobros, licitaciones "
            "o telecomunicaciones de operador van a su propio departamento.\n\n"
            f"Departamentos:\n{lista}")


def sistema_director_departamento(nombre_dep: str, fichas: list[Ficha]) -> str:
    lista = "\n".join(f"- {f.id}: {f.nombre} — {f.tareas}" for f in fichas)
    return (f"{CONTEXTO_EMPRESA}\n\nDiriges el departamento {nombre_dep}. Elige qué agente atiende la "
            f"petición.\n\nAgentes:\n{lista}")
