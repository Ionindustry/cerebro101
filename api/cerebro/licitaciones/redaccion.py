"""«Preparar la oferta»: pone a trabajar a los agentes de Licitaciones, uno detrás de otro, hasta tener el borrador completo.

Cada pulsación del botón es una EJECUCIÓN (tabla ofertas_ejecuciones) con un paso por agente. El orden es el del trabajo real: el Arquitecto de Solución diseña la solución, el Redactor de Memoria
escribe la memoria técnica sobre ella, el Administrativo prepara la documentación del sobre administrativo, Costes desglosa y justifica el precio, Precio propone un precio ORIENTATIVO y el Evaluador
puntúa el borrador como lo haría la mesa. Los tres últimos pasos no deciden nada: Precio y Evaluador solo dejan un informe.

Las reglas de siempre siguen mandando (cerebro/licitaciones/ofertas.py): los agentes solo escriben BORRADORES, no pisan lo que haya escrito o revisado una persona, no escriben la proposición económica
ni fijan el precio. Aquí solo se organiza el trabajo y se comprueba lo que de verdad quedó escrito, porque un modelo puede decir «hecho» sin haber guardado nada.

La ejecución es reanudable: si el modelo no está disponible, el paso en curso vuelve a «pendiente» y la tarea (celery_app.redactar_oferta) la retoma más tarde sin repetir lo ya hecho.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from psycopg.types.json import Jsonb

from ..llm import ModeloNoDisponible, ModeloOcupado, ModeloTimeout
from . import ofertas as O

log = logging.getLogger("cerebro.licitaciones.redaccion")

FALLOS_DEL_MODELO = (ModeloNoDisponible, ModeloOcupado, ModeloTimeout)
VENTANA = timedelta(hours=3)         # una ejecución «en curso» más vieja se da por perdida (se reinició el servidor): se puede volver a pedir
MAX_RESUMEN = 4000

PENDIENTE, EN_CURSO, HECHO, PARCIAL, OMITIDO, ERROR = "pendiente", "en_curso", "hecho", "parcial", "omitido", "error"
TERMINADOS = (HECHO, PARCIAL, OMITIDO, ERROR)

# Los pasos, en orden. «sobre» + «claves»/«excepto» dicen qué secciones escribe cada agente; «informe» marca los pasos que no escriben secciones, solo dejan un informe.
# La proposición económica y «criterios-automaticos» no las escribe ningún agente: la primera sale sola del precio y la segunda son compromisos que decide una persona.
PASOS = (
    {"id": "solucion", "agente": "arquitecto-solucion", "titulo": "Arquitecto de Solución · descripción de la solución", "sobre": "tecnico", "claves": ("descripcion-solucion",),
     "contexto": "Diseña la mejor solución, criterio a criterio, dentro del presupuesto: qué se instala o presta, con qué equipos, cómo cubre cada requisito técnico del pliego."},
    {"id": "memoria", "agente": "redactor-memoria", "titulo": "Redactor de Memoria · memoria técnica", "sobre": "tecnico", "excepto": ("descripcion-solucion",),
     "contexto": "La descripción de la solución ya está en la sección «descripcion-solucion» (léela con «seccion» y mantén la coherencia con ella). Respeta la estructura exacta que pide el pliego."},
    {"id": "administrativo", "agente": "administrativo-licitaciones", "titulo": "Administrativo · documentación administrativa", "sobre": "administrativo", "antes": "plantillas",
     "contexto": "Lee el pliego (PCAP) para saber exactamente qué documentación administrativa exige y en qué forma (modelos, anexos, DEUC). Los modelos del concurso ya se han rellenado con los datos "
                 "de la sociedad que se presenta (ver más abajo): en las secciones anota qué documentos se aportan, en qué estado están, qué falta y qué tiene que firmar una persona con poder. "
                 "Las declaraciones las firma siempre una persona: tú solo preparas el texto."},
    {"id": "costes", "agente": "costes-licitacion", "titulo": "Costes · desglose y justificación del precio", "sobre": "economico", "claves": ("justificacion-precio",),
     "contexto": "Calcula el coste real (convenio, materiales, gastos generales, riesgos) con los datos del ERP y del cotizador, y justifica que es viable. No propongas aquí el precio de venta."},
    {"id": "precio", "agente": "precio-licitacion", "titulo": "Precio · propuesta orientativa de precio", "informe": "precio"},
    {"id": "evaluacion", "agente": "evaluador-ofertas", "titulo": "Evaluador · puntuación estimada y riesgos", "informe": "evaluacion"},
)
_PASO = {p["id"]: p for p in PASOS}


class Conflicto(O.ErrorOferta):
    """Ya hay una ejecución en curso para esta oferta."""


def _ahora(ahora: datetime | None) -> datetime:
    return ahora or datetime.now(timezone.utc)


def _iso(t: datetime | None) -> str | None:
    return t.isoformat() if t else None


def editable_por_agente(s: dict, rehacer: bool) -> bool:
    """¿Puede un agente escribir esta sección ahora? Nunca lo de una persona (escrito o revisado). Sin `rehacer`, solo las vacías; con él, también sus propios borradores."""
    de_agente = str(s["por"]).startswith("agente:")
    if s["version"] > 0 and not de_agente:
        return False
    if s["estado"] == "vacia":
        return True
    return rehacer and s["estado"] == "borrador" and de_agente


def seleccion(paso: dict, secciones: list[dict], rehacer: bool) -> list[dict]:
    """Las secciones que este paso tiene que escribir. Los pasos de informe no escriben ninguna."""
    if paso.get("informe"):
        return []
    out = []
    for s in secciones:
        if s["sobre"] != paso["sobre"] or s["clave"] == O.PROPOSICION or s["clave"] in paso.get("excepto", ()):
            continue
        if "claves" in paso and s["clave"] not in paso["claves"]:
            continue
        if editable_por_agente(s, rehacer):
            out.append(s)
    return out


def pasos_iniciales(secciones: list[dict], rehacer: bool) -> list[dict]:
    """Los pasos de una ejecución nueva: pendientes, salvo los que no tienen nada que escribir (omitidos)."""
    out = []
    for p in PASOS:
        paso = {"id": p["id"], "agente": p["agente"], "titulo": p["titulo"], "estado": PENDIENTE, "resumen": "", "error": "", "secciones": [], "escritas": 0, "faltan": [],
                "inicio": None, "fin": None}
        if not p.get("informe"):
            sel = seleccion(p, secciones, rehacer)
            paso["secciones"] = [s["clave"] for s in sel]
            if not sel and not p.get("antes"):
                paso.update(estado=OMITIDO, resumen="Nada que escribir: las secciones ya tienen contenido o las tiene una persona.")
        out.append(paso)
    return out


def _ejecucion(f: dict) -> dict:
    return {"id": f["id"], "licitacion": str(f["motor_id"]), "estado": f["estado"], "por": f["por"], "rehacer": f["rehacer"], "pasos": list(f["pasos"] or []), "error": f["error"],
            "creada": _iso(f["creada"]), "terminada": _iso(f["terminada"])}


async def reservar(motor_id: str, usuario: str, rehacer: bool = False, ahora: datetime | None = None) -> dict:
    """Anota una ejecución nueva antes de encolar el trabajo. Conflicto si ya hay una en curso (y reciente); NoExiste si la oferta aún no está preparada."""
    motor_id = O._id(motor_id)
    ahora = _ahora(ahora)
    o = await O.leer(motor_id, con_contenido=False)
    if not o["existe"]:
        raise O.NoExiste("Esta licitación aún no tiene la oferta preparada")
    async with await O._conectar() as conn:
        async with conn.transaction():
            cur = await conn.execute("SELECT id, creada FROM ofertas_ejecuciones WHERE motor_id = %s AND estado = 'en_curso' FOR UPDATE", [motor_id])
            vieja = await cur.fetchone()
            if vieja:
                if ahora - vieja["creada"] < VENTANA:
                    raise Conflicto("Los agentes ya están trabajando en esta oferta")
                await conn.execute("UPDATE ofertas_ejecuciones SET estado = 'error', error = %s, terminada = %s WHERE id = %s",
                                   ["La ejecución anterior no terminó (¿se reinició el servidor?)", ahora, vieja["id"]])
            cur = await conn.execute("INSERT INTO ofertas_ejecuciones (motor_id, por, rehacer, pasos, creada) VALUES (%s,%s,%s,%s,%s) RETURNING *",
                                     [motor_id, str(usuario)[:200], bool(rehacer), Jsonb(pasos_iniciales(o["secciones"], bool(rehacer))), ahora])
            f = await cur.fetchone()
    log.info("oferta: %s pide que los agentes redacten la oferta de %s (ejecución %s, rehacer=%s)", usuario, motor_id, f["id"], bool(rehacer))
    return _ejecucion(f)


async def ultima(motor_id: str) -> dict | None:
    """La ejecución más reciente de esta oferta (para que el panel enseñe el progreso), o None."""
    async with await O._conectar() as conn:
        cur = await conn.execute("SELECT * FROM ofertas_ejecuciones WHERE motor_id = %s ORDER BY id DESC LIMIT 1", [O._id(motor_id)])
        f = await cur.fetchone()
    return _ejecucion(f) if f else None


async def _cargar(ejecucion_id: int) -> dict | None:
    async with await O._conectar() as conn:
        cur = await conn.execute("SELECT * FROM ofertas_ejecuciones WHERE id = %s", [ejecucion_id])
        f = await cur.fetchone()
    return _ejecucion(f) if f else None


async def _marcar(ejecucion_id: int, indice: int, ahora: datetime | None = None, **campos) -> None:
    """Cambia campos de un paso. Se hace con la fila bloqueada, para que dos escrituras no se pisen."""
    async with await O._conectar() as conn:
        async with conn.transaction():
            cur = await conn.execute("SELECT pasos FROM ofertas_ejecuciones WHERE id = %s FOR UPDATE", [ejecucion_id])
            f = await cur.fetchone()
            if not f:
                return
            pasos = list(f["pasos"])
            pasos[indice] = {**pasos[indice], **campos}
            await conn.execute("UPDATE ofertas_ejecuciones SET pasos = %s WHERE id = %s", [Jsonb(pasos), ejecucion_id])


def _estado_final(pasos: list[dict]) -> str:
    if all(p["estado"] in (HECHO, OMITIDO) for p in pasos):
        return "completa"
    return "parcial" if any(p["estado"] in (HECHO, PARCIAL) for p in pasos) else "error"


async def cerrar(ejecucion_id: int, error: str = "", ahora: datetime | None = None) -> dict:
    """Termina la ejecución con lo que haya: «completa» si todo salió, «parcial» si algo salió, «error» si nada. Lo ya escrito se conserva siempre."""
    ahora = _ahora(ahora)
    async with await O._conectar() as conn:
        async with conn.transaction():
            cur = await conn.execute("SELECT * FROM ofertas_ejecuciones WHERE id = %s FOR UPDATE", [ejecucion_id])
            f = await cur.fetchone()
            if not f or f["estado"] != "en_curso":
                return _ejecucion(f) if f else {}
            pasos = [{**p, "estado": PENDIENTE} if p["estado"] == EN_CURSO else p for p in f["pasos"]]
            estado = _estado_final(pasos)
            cur = await conn.execute("UPDATE ofertas_ejecuciones SET estado = %s, pasos = %s, error = %s, terminada = %s WHERE id = %s RETURNING *",
                                     [estado, Jsonb(pasos), str(error)[:300], ahora, ejecucion_id])
            f = await cur.fetchone()
    log.info("oferta: la redacción de %s (ejecución %s) termina en «%s»", f["motor_id"], ejecucion_id, f["estado"])
    resultado = _ejecucion(f)
    from . import crm      # el seguimiento en el CRM es comodidad: no falla ni retrasa la ejecución
    await crm.anotar_por_oferta(resultado["licitacion"], *crm.nota_de_redaccion(resultado))
    return resultado


# ---- Lo que se le pide a cada agente ----

def _criterios_texto(ficha: dict) -> str:
    out = []
    for c in (ficha.get("criterios") or [])[:25]:
        if isinstance(c, dict):
            peso = f" ({c['peso']:g} puntos)" if isinstance(c.get("peso"), (int, float)) else ""
            out.append(f"- {O._una_linea(c.get('descripcion'), 300)}{peso} [{c.get('tipo') or 'sin tipo'}]")
    return "\n".join(out) or "(la ficha no trae criterios: míralos en el pliego)"


def peticion_escritor(paso: dict, motor_id: str, titulo: str, secciones: list[dict]) -> str:
    lista = "\n".join(f"- sobre «{s['sobre']}», clave «{s['clave']}»: {s['titulo']}\n    Guía: {O._una_linea(s['guia'], 700)}" for s in secciones)
    return (
        f"Prepara el BORRADOR de la oferta de 101.cat para la licitación «{titulo}» (identificador {motor_id}). Es tu parte del trabajo en equipo: {paso['titulo']}.\n"
        f"{paso.get('contexto', '')}\n\n"
        "Cómo hacerlo:\n"
        "1. Lee la oferta con la herramienta «ofertas» (operación «leer») y la ficha con «licitaciones» (operación «ficha»). Lee lo que pide el pliego con «pliegos» (requisitos confirmados y texto) "
        "y apóyate en «conocimiento» y en los datos de 101.cat.\n"
        "2. Para CADA una de estas secciones, guarda el borrador con «ofertas», operación «guardar_seccion» (licitacion, sobre, clave, contenido y citas):\n"
        f"{lista}\n"
        "3. En «citas» pon los ids de los requisitos confirmados del pliego en los que te apoyas.\n\n"
        "Reglas:\n"
        "- Escribe en castellano, con la estructura y el detalle que pide el pliego, sin mezclar lo de un sobre con lo de otro.\n"
        "- No inventes certificados, referencias, cifras, plazos ni precios. Si falta un dato, escribe en el texto [PENDIENTE: qué hace falta] para que una persona lo complete.\n"
        "- Solo borradores: no revises ni apruebes secciones, no fijes ni propongas el precio, no escribas la proposición económica y no firmes ni presentes nada.\n"
        "- No pises lo que haya escrito o revisado una persona (la herramienta te lo impedirá).\n"
        "Al terminar, responde con 2 o 3 líneas: qué has escrito y qué queda pendiente de una persona."
    )


def peticion_precio(motor_id: str, titulo: str) -> str:
    return (
        f"Propón un precio ORIENTATIVO para la oferta de 101.cat a la licitación «{titulo}» (identificador {motor_id}). Usa la ficha y los criterios de adjudicación («licitaciones», operación «ficha»), "
        "el simulador («licitaciones», operación «simular») para ver con qué baja se ha ganado en concursos parecidos y el riesgo de baja anormal, y el desglose de costes de la oferta "
        "(«ofertas», operación «seccion», sobre economico, clave justificacion-precio) si ya está escrito.\n"
        "No fijes el precio ni escribas la proposición económica: lo decide una persona.\n"
        "Responde SOLO con el informe, de 12 líneas como máximo: precio sin IVA recomendado y su rango, baja respecto al presupuesto, riesgo de baja anormal, probabilidad estimada de ganar y los supuestos "
        "que falta confirmar."
    )


def peticion_evaluacion(motor_id: str, titulo: str, ficha: dict, secciones: list[dict]) -> str:
    borrador = "\n\n".join(f"## {s['titulo']} [{s['sobre']}, {s['estado']}]\n{s.get('contenido') or '(vacía)'}" for s in secciones if s["clave"] != O.PROPOSICION)
    return (
        f"Actúa como la mesa de contratación y evalúa el borrador de la oferta de 101.cat a la licitación «{titulo}» (identificador {motor_id}).\n\n"
        f"Criterios de adjudicación:\n{_criterios_texto(ficha)}\n\nBorrador actual de la oferta (cada sección, recortada):\n{borrador}\n\n"
        "Responde SOLO con un informe de 15 líneas como máximo: la puntuación estimada de cada criterio de juicio de valor (sobre sus puntos), los incumplimientos excluyentes o riesgos de exclusión, "
        "las secciones con [PENDIENTE] y qué mejorar primero. No modifiques nada."
    )


# ---- La ejecución ----

async def _titulo_y_ficha(motor_id: str) -> tuple[str, dict]:
    """El título y la ficha de la licitación, para los textos que se le piden a los agentes. Si el motor no responde, se sigue sin ellos: los agentes también pueden leerla."""
    try:
        from ..herramientas import licitaciones as motor
        ficha = await motor.ficha(motor_id)
    except Exception as e:      # noqa: BLE001 — sin la ficha el trabajo sigue: es solo contexto
        log.warning("redacción: no se ha podido leer la ficha de %s: %s: %s", motor_id, type(e).__name__, e)
        return "(sin título)", {}
    ficha = ficha if isinstance(ficha, dict) else {}
    return O._una_linea(ficha.get("titulo") or "(sin título)", 200), ficha


def _respuesta(estado: dict | None) -> str:
    return str((estado or {}).get("respuesta") or "").strip()[:MAX_RESUMEN]


async def _preparar_plantillas(motor_id: str, ficha: dict, usuario: str) -> dict:
    from . import plantillas
    return await plantillas.preparar(motor_id, ficha, usuario)


def texto_plantillas(resultado: dict | None, error: str = "") -> str:
    """Lo que se le cuenta al Administrativo de las plantillas del concurso: qué se ha rellenado ya y qué huecos quedan, para que elija el dato de los dudosos (nunca el valor)."""
    if error:
        return f"\nPlantillas del concurso: no se han podido rellenar ({error}). Lo verá una persona; en las secciones anota que quedan pendientes."
    docs = (resultado or {}).get("documentos") or []
    if not docs:
        return "\nPlantillas del concurso: ninguno de los documentos del pliego bajados es una plantilla rellenable (Word o PDF con formulario). Si el pliego pide modelos, anota en las secciones cuáles son."
    lineas = []
    for d in docs:
        pend = [p for p in d["pendientes"] if p["bloquea"]][:8]
        lineas.append(f"- Documento {d['documento']} «{d['nombre']}»" + (f" (miembro «{d['miembro']}»)" if d.get("miembro") else "") + f": {d['estado']}, {len(d['rellenados'])} huecos rellenados" + (
            ". Pendientes: " + "; ".join(f"{p['id']} «{p['etiqueta'][-50:]}» ({p['motivo']})" for p in pend) if pend else ""))
    return ("\nPlantillas del concurso (ya rellenadas por el sistema con los datos del ERP; el original no se toca):\n" + "\n".join(lineas) +
            "\nSi un hueco pendiente es dudoso y sabes qué dato le corresponde, elígelo con «plantillas», operación «rellenar» (documento y asignaciones {hueco: clave}); mira antes «datos_disponibles». "
            "El «Documento 0» (si está) es el DEUC de la sociedad: ya trae los datos de la empresa y solo falta lo propio del concurso; completa sus huecos con «rellenar» (documento 0). "
            "Nunca escribas el valor: sale del ERP. Los datos que faltan en el ERP los completa una persona allí.")


async def _paso_escritor(ejecucion_id: int, indice: int, e: dict, defin: dict, invocar, titulo: str, ficha: dict | None = None) -> None:
    motor_id = e["licitacion"]
    adicional, resumen_plantillas = "", ""
    if defin.get("antes") == "plantillas":
        try:
            res = await _preparar_plantillas(motor_id, ficha or {}, f"agente:{defin['agente']}")
            adicional = texto_plantillas(res)
            docs = res.get("documentos") or []
            resumen_plantillas = (f"Plantillas del concurso: {sum(1 for d in docs if d['estado'] == 'lista_para_firma')} listas para firmar y "
                                  f"{sum(1 for d in docs if d['estado'] == 'faltan_datos')} con datos pendientes.") if docs else "Plantillas del concurso: ninguna rellenable."
        except FALLOS_DEL_MODELO:
            raise
        except Exception as ex:      # noqa: BLE001 — sin plantillas se sigue con las secciones; el motivo queda a la vista
            motivo = str(ex)[:200] or type(ex).__name__
            log.warning("redacción: no se han podido preparar las plantillas de %s: %s: %s", motor_id, type(ex).__name__, ex)
            adicional, resumen_plantillas = texto_plantillas(None, motivo), f"Plantillas del concurso: no se han podido rellenar ({motivo})."
    antes = (await O.leer(motor_id, con_contenido=False))["secciones"]
    sel = seleccion(defin, antes, e["rehacer"])           # se recalcula: desde que se pidió, una persona puede haber escrito alguna
    if not sel:
        if resumen_plantillas:
            await _marcar(ejecucion_id, indice, estado=HECHO, resumen=resumen_plantillas, secciones=[], fin=_iso(_ahora(None)))
        else:
            await _marcar(ejecucion_id, indice, estado=OMITIDO, resumen="Nada que escribir: las secciones ya tienen contenido o las tiene una persona.", secciones=[], fin=_iso(_ahora(None)))
        return
    estado = await invocar(defin["agente"], peticion_escritor(defin, motor_id, titulo, sel) + adicional)
    despues = {s["clave"]: s for s in (await O.leer(motor_id, con_contenido=False))["secciones"]}
    escritas = [s["clave"] for s in sel if despues.get(s["clave"], {}).get("estado") != "vacia" and despues[s["clave"]]["por"] == f"agente:{defin['agente']}"]
    faltan = [s["clave"] for s in sel if s["clave"] not in escritas]
    resumen = (resumen_plantillas + "\n" if resumen_plantillas else "") + _respuesta(estado)
    campos = {"secciones": [s["clave"] for s in sel], "escritas": len(escritas), "faltan": faltan, "resumen": resumen[:MAX_RESUMEN], "fin": _iso(_ahora(None))}
    if (estado or {}).get("error") and not escritas:
        await _marcar(ejecucion_id, indice, estado=ERROR, error=str(estado["error"])[:300], **campos)
    elif not escritas:
        await _marcar(ejecucion_id, indice, estado=ERROR, error="El agente no ha guardado ninguna sección: se puede volver a intentar.", **campos)
    else:
        await _marcar(ejecucion_id, indice, estado=PARCIAL if faltan else HECHO, error="", **campos)


async def _paso_informe(ejecucion_id: int, indice: int, e: dict, defin: dict, invocar, titulo: str, ficha: dict) -> None:
    motor_id = e["licitacion"]
    if defin["informe"] == "precio":
        peticion = peticion_precio(motor_id, titulo)
    else:
        con_texto = [s for s in (await O.leer(motor_id, True, 1500))["secciones"] if s["contenido"].strip() and s["clave"] != O.PROPOSICION]
        if not con_texto:
            await _marcar(ejecucion_id, indice, estado=OMITIDO, resumen="Aún no hay contenido que evaluar.", fin=_iso(_ahora(None)))
            return
        peticion = peticion_evaluacion(motor_id, titulo, ficha, con_texto)
    estado = await invocar(defin["agente"], peticion)
    resumen = _respuesta(estado)
    if not resumen or (estado or {}).get("error"):
        await _marcar(ejecucion_id, indice, estado=ERROR, error=str((estado or {}).get("error") or "El agente no ha dado informe")[:300], resumen=resumen, fin=_iso(_ahora(None)))
    else:
        await _marcar(ejecucion_id, indice, estado=HECHO, error="", resumen=resumen, fin=_iso(_ahora(None)))


async def ejecutar(ejecucion_id: int, invocar) -> dict:
    """Hace los pasos pendientes de la ejecución, en orden. `invocar(agente_id, peticion)` ejecuta al agente y devuelve su estado (con «respuesta»).
    Si el modelo no está disponible relanza el fallo (el paso en curso vuelve a «pendiente» y la tarea reintenta más tarde sin repetir lo hecho); cualquier otro fallo deja ese paso en
    «error» y se sigue con los demás: una oferta a medias es mejor que ninguna, y lo escrito se conserva."""
    e = await _cargar(ejecucion_id)
    if not e or e["estado"] != "en_curso":
        return e or {}
    titulo, ficha = await _titulo_y_ficha(e["licitacion"])
    for i, paso in enumerate(e["pasos"]):
        if paso["estado"] in TERMINADOS:
            continue
        defin = _PASO[paso["id"]]
        await _marcar(ejecucion_id, i, estado=EN_CURSO, inicio=_iso(_ahora(None)), error="")
        try:
            if defin.get("informe"):
                await _paso_informe(ejecucion_id, i, e, defin, invocar, titulo, ficha)
            else:
                await _paso_escritor(ejecucion_id, i, e, defin, invocar, titulo, ficha)
        except FALLOS_DEL_MODELO:
            await _marcar(ejecucion_id, i, estado=PENDIENTE)
            raise
        except Exception as ex:      # noqa: BLE001 — un paso que falla no impide los demás
            log.warning("redacción: el paso %s de la ejecución %s ha fallado: %s: %s", paso["id"], ejecucion_id, type(ex).__name__, ex)
            await _marcar(ejecucion_id, i, estado=ERROR, error=f"No se ha podido hacer este paso ({type(ex).__name__})", fin=_iso(_ahora(None)))
    return await cerrar(ejecucion_id)
