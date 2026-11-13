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
    {"id": "comparativa", "agente": "comparador-productos", "titulo": "Comparativa de productos y ventaja competitiva", "comparativa": True},
    {"id": "equivalencia", "agente": "comparador-productos", "titulo": "Tabla de equivalencias · «iguala o supera» frente al catálogo", "equivalencia": True},
    {"id": "encargos", "agente": "director-oferta", "titulo": "Director de la oferta · encargo a cada agente", "encargos": True},
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
    if paso.get("informe") or paso.get("encargos") or paso.get("comparativa") or paso.get("equivalencia"):
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
        if not p.get("informe") and not p.get("encargos") and not p.get("comparativa") and not p.get("equivalencia"):
            sel = seleccion(p, secciones, rehacer)
            paso["secciones"] = [s["clave"] for s in sel]
            if not sel and not p.get("antes"):
                paso.update(estado=OMITIDO, resumen="Nada que escribir: las secciones ya tienen contenido o las tiene una persona.")
        out.append(paso)
    return out


def _ejecucion(f: dict) -> dict:
    return {"id": f["id"], "licitacion": str(f["motor_id"]), "estado": f["estado"], "por": f["por"], "rehacer": f["rehacer"], "modelo": f.get("modelo") or "auto", "pasos": list(f["pasos"] or []), "error": f["error"],
            "creada": _iso(f["creada"]), "terminada": _iso(f["terminada"])}


def pasos_de_repeticion(inicial: list[dict], anteriores: list[dict] | None, solo: str) -> list[dict]:
    """Los pasos de una ejecución que repite SOLO uno: ese paso empieza de nuevo (pendiente) y los demás conservan lo que dio la ejecución anterior (para que el panel siga enseñando el cuadro
    completo). Un paso que la ejecución anterior no tenía (se añadió después) queda como «omitido». Pura."""
    previos = {p["id"]: p for p in (anteriores or [])}
    out = []
    for p in inicial:
        if p["id"] == solo:
            out.append(p)
        elif p["id"] in previos:
            q = dict(previos[p["id"]])
            if q.get("estado") in (PENDIENTE, EN_CURSO):       # no llegó a hacerse: no se hace ahora (solo se pidió otro paso), pero queda a la vista con su propio botón para repetirlo
                q = {**q, "estado": ERROR, "error": "No llegó a hacerse en la ejecución anterior: repítelo con su botón.", "fin": None}
            out.append(q)
        else:
            out.append({**p, "estado": OMITIDO, "resumen": "No se repite: solo se ha pedido repetir otro paso."})
    return out


async def reservar(motor_id: str, usuario: str, rehacer: bool = False, ahora: datetime | None = None, modelo: str = "auto", solo: str | None = None) -> dict:
    """Anota una ejecución nueva antes de encolar el trabajo. Conflicto si ya hay una en curso (y reciente); NoExiste si la oferta aún no está preparada."""
    motor_id = O._id(motor_id)
    ahora = _ahora(ahora)
    if solo is not None and solo not in _PASO:
        raise O.ErrorOferta("Ese paso no existe: " + ", ".join(_PASO))
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
            from .redaccion_externa import modelo_pedido
            pasos = pasos_iniciales(o["secciones"], bool(rehacer))
            if solo is not None:
                cur = await conn.execute("SELECT pasos FROM ofertas_ejecuciones WHERE motor_id = %s ORDER BY id DESC LIMIT 1", [motor_id])
                previa = await cur.fetchone()
                if not previa:
                    raise O.NoExiste("Todavía no se ha preparado la oferta con los agentes: pulsa primero «Preparar la oferta con los agentes»")
                pasos = pasos_de_repeticion(pasos, list(previa["pasos"] or []), solo)
            cur = await conn.execute("INSERT INTO ofertas_ejecuciones (motor_id, por, rehacer, pasos, creada, modelo) VALUES (%s,%s,%s,%s,%s,%s) RETURNING *",
                                     [motor_id, str(usuario)[:200], bool(rehacer), Jsonb(pasos), ahora, modelo_pedido(modelo)])
            f = await cur.fetchone()
    log.info("oferta: %s pide que los agentes %s la oferta de %s (ejecución %s, rehacer=%s)", usuario, f"repitan el paso «{solo}» de" if solo else "redacten", motor_id, f["id"], bool(rehacer))
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


def ultima_actividad(f: dict) -> datetime:
    """Cuándo se movió por última vez una ejecución: la hora en que se creó o la última vez que un paso empezó o terminó. Pura."""
    marcas = [f["creada"]]
    for p in f.get("pasos") or []:
        for k in ("inicio", "fin"):
            try:
                if p.get(k):
                    marcas.append(datetime.fromisoformat(p[k]))
            except (TypeError, ValueError):
                pass
    return max(marcas)


async def interrumpir_huerfanas(ahora: datetime | None = None, gracia_s: int = 90) -> list[int]:
    """Al arrancar el worker: toda ejecución «en curso» se quedó sin tarea (el reinicio la mató), así que se cierra como interrumpida y se puede volver a lanzar. Las creadas hace menos de `gracia_s`
    segundos se dejan: pueden estar esperando en la cola del worker nuevo."""
    ahora = _ahora(ahora)
    async with await O._conectar() as conn:
        cur = await conn.execute("SELECT id FROM ofertas_ejecuciones WHERE estado = 'en_curso' AND creada < %s", [ahora - timedelta(seconds=gracia_s)])
        ids = [f["id"] for f in await cur.fetchall()]
    for i in ids:
        await cerrar(i, "Interrumpida: el servidor se reinició mientras trabajaban los agentes. Vuelve a lanzarla: lo ya escrito se conserva.", ahora)
    return ids


async def caducar_inactivas(ahora: datetime | None = None, minutos: int = 60) -> list[int]:
    """Cierra como interrumpidas las ejecuciones «en curso» sin ninguna actividad desde hace `minutos` (un paso del modelo local tarda como mucho unos 25 minutos): así no se quedan «trabajando» para siempre."""
    ahora = _ahora(ahora)
    async with await O._conectar() as conn:
        cur = await conn.execute("SELECT * FROM ofertas_ejecuciones WHERE estado = 'en_curso'")
        filas = await cur.fetchall()
    ids = []
    for f in filas:
        parado = (ahora - ultima_actividad(f)).total_seconds() / 60
        if parado >= minutos:
            await cerrar(f["id"], f"Sin actividad desde hace {int(parado)} min: se da por interrumpida. Puedes volver a lanzarla; lo ya escrito se conserva.", ahora)
            ids.append(f["id"])
    return ids


async def cancelar(motor_id: str, usuario: str, ahora: datetime | None = None) -> dict:
    """Una persona cancela la preparación en curso. No se puede parar al agente a mitad de un paso: termina ese paso y no empieza ninguno más; lo ya escrito se conserva."""
    motor_id = O._id(motor_id)
    async with await O._conectar() as conn:
        cur = await conn.execute("SELECT id FROM ofertas_ejecuciones WHERE motor_id = %s AND estado = 'en_curso' ORDER BY id DESC LIMIT 1", [motor_id])
        f = await cur.fetchone()
    if not f:
        raise O.NoExiste("No hay ninguna preparación en marcha en esta oferta")
    log.info("oferta: %s cancela la preparación de %s (ejecución %s)", usuario, motor_id, f["id"])
    return await cerrar(f["id"], f"Cancelada por {str(usuario)[:60]}. El agente que estuviera trabajando termina su paso y no empieza ninguno más; lo ya escrito se conserva.", _ahora(ahora))


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
        "- Trabajas SOLO y de forma automática: nadie va a contestar a una pregunta. NO pidas confirmación ni permiso y no preguntes si debes seguir: haz el trabajo con las herramientas. "
        "Sé eficiente (pocas lecturas) y guarda CADA sección en cuanto la tengas escrita, no al final.\n"
        "- Si no hay requisitos confirmados o te falta información, guarda igualmente el borrador (sin citas si no las hay) y marca lo que falta con [PENDIENTE: …].\n"
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
        "Trabajas SOLO y de forma automática: nadie va a contestar a una pregunta; no pidas confirmación, haz el informe con lo que tengas y di qué falta.\n"
        "Responde SOLO con el informe, de 12 líneas como máximo: precio sin IVA recomendado y su rango, baja respecto al presupuesto, riesgo de baja anormal, probabilidad estimada de ganar y los supuestos "
        "que falta confirmar."
    )


def peticion_evaluacion(motor_id: str, titulo: str, ficha: dict, secciones: list[dict]) -> str:
    borrador = "\n\n".join(f"## {s['titulo']} [{s['sobre']}, {s['estado']}]\n{s.get('contenido') or '(vacía)'}" for s in secciones if s["clave"] != O.PROPOSICION)
    return (
        f"Actúa como la mesa de contratación y evalúa el borrador de la oferta de 101.cat a la licitación «{titulo}» (identificador {motor_id}).\n\n"
        f"Criterios de adjudicación:\n{_criterios_texto(ficha)}\n\nBorrador actual de la oferta (cada sección, recortada):\n{borrador}\n\n"
        "Responde SOLO con un informe de 15 líneas como máximo: la puntuación estimada de cada criterio de juicio de valor (sobre sus puntos), los incumplimientos excluyentes o riesgos de exclusión, "
        "las secciones con [PENDIENTE] y qué mejorar primero. No modifiques nada. Trabajas SOLO y de forma automática: nadie va a contestar a una pregunta, no pidas confirmación."
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
    return await plantillas.preparar(motor_id, await plantillas.ficha_del_motor(motor_id), usuario)      # la ficha completa del motor, no la resumida que ven los agentes


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
    from . import encargos as encargos_mod
    encargo = await encargos_mod.texto_para(motor_id, defin["agente"])
    defin_externo = {**defin, "contexto": f"{defin.get('contexto', '')}\n\n{encargo}".strip()} if encargo else defin       # Claude y ChatGPT reciben el encargo completo
    encargo_local = await encargos_mod.texto_para(motor_id, defin["agente"], encargos_mod.MAX_LOCAL) if encargo else ""
    if encargo_local:                                # el modelo local, más corto: su ventana es pequeña (se suma a las reglas fijas de la petición)
        defin = {**defin, "contexto": f"{defin.get('contexto', '')}\n\n{encargo_local}".strip()}
    if defin["id"] in ("solucion", "memoria"):         # el Arquitecto y el Redactor reciben también la comparativa de productos (completa para Claude/ChatGPT, corta para el modelo local)
        from . import comparativa as comparativa_mod
        completa = await comparativa_mod.texto_para(motor_id)
        if completa:
            defin_externo = {**defin_externo, "contexto": f"{defin_externo.get('contexto', '')}\n\n{completa}".strip()}
            corta = await comparativa_mod.texto_para(motor_id, 1500)
            defin = {**defin, "contexto": f"{defin.get('contexto', '')}\n\n{corta}".strip()}
        from . import equivalencia as equivalencia_mod
        try:
            eq = await equivalencia_mod.leer(motor_id)
        except Exception as ex:      # noqa: BLE001 — sin la tabla se sigue igual
            log.warning("redacción: no se ha podido leer la tabla de equivalencias de %s: %s", motor_id, type(ex).__name__)
            eq = None
        tabla = equivalencia_mod.texto_equivalencia((eq or {}).get("contenido") or {}, 1200)
        if tabla:                                                       # un producto por parámetro medible, ya comprobado por el código: coherencia entre solución y memoria
            bloque = "Equivalencias comprobadas (parámetro del pliego → producto que lo iguala o supera; no propongas otro sin evidencia):\n" + tabla
            defin_externo = {**defin_externo, "contexto": f"{defin_externo.get('contexto', '')}\n\n{bloque}".strip()}
            defin = {**defin, "contexto": f"{defin.get('contexto', '')}\n\n{bloque[:700]}".strip()}
    estado, externa = None, ""
    from . import redaccion_externa as externa_mod
    if externa_mod.paso_activo(defin["id"]):
        # Claude o ChatGPT, si Dirección los ha conectado: redactan el paso de una vez, con todo el material. Si no procede o falla, lo hace el modelo local como siempre.
        await _marcar(ejecucion_id, indice, resumen="Redactando con Claude o ChatGPT…")
        res, motivo = await externa_mod.intentar(motor_id, defin_externo, sel, titulo, ficha or {}, modelo=e.get("modelo") or "auto")
        if res:
            estado = {"respuesta": res["resumen"]}
        else:
            externa = f"Se ha usado el modelo local: {motivo}."
            log.info("redacción: el paso %s de %s lo hace el modelo local (%s)", defin["id"], motor_id, motivo)
    if estado is None:
        estado = await invocar(defin["agente"], peticion_escritor(defin, motor_id, titulo, sel) + adicional)
    despues = {s["clave"]: s for s in (await O.leer(motor_id, con_contenido=False))["secciones"]}
    escritas = [s["clave"] for s in sel if despues.get(s["clave"], {}).get("estado") != "vacia" and despues[s["clave"]]["por"] == f"agente:{defin['agente']}"]
    faltan = [s["clave"] for s in sel if s["clave"] not in escritas]
    resumen = (resumen_plantillas + "\n" if resumen_plantillas else "") + (externa + "\n" if externa else "") + _respuesta(estado)
    campos = {"secciones": [s["clave"] for s in sel], "escritas": len(escritas), "faltan": faltan, "resumen": resumen[:MAX_RESUMEN], "fin": _iso(_ahora(None))}
    if (estado or {}).get("error") and not escritas:
        await _marcar(ejecucion_id, indice, estado=ERROR, error=str(estado["error"])[:300], **campos)
    elif not escritas:
        await _marcar(ejecucion_id, indice, estado=ERROR, error="El agente no ha guardado ninguna sección: se puede volver a intentar.", **campos)
    else:
        await _marcar(ejecucion_id, indice, estado=PARCIAL if faltan else HECHO, error="", **campos)


async def _paso_comparativa(ejecucion_id: int, indice: int, e: dict, defin: dict, titulo: str, ficha: dict) -> None:
    """La comparativa de productos y ventaja competitiva con Claude o ChatGPT. Sin evidencia de producto o sin modelo externo no se hace (no se compara sin datos): el paso queda «omitido» con el motivo."""
    from . import comparativa
    res = await comparativa.preparar(e["licitacion"], titulo, ficha or {}, modelo=e.get("modelo") or "auto")
    await _marcar(ejecucion_id, indice, estado=HECHO if res["estado"] == "hecha" else OMITIDO, error="", resumen=res["resumen"][:MAX_RESUMEN], secciones=[], fin=_iso(_ahora(None)))


async def _paso_equivalencia(ejecucion_id: int, indice: int, e: dict, defin: dict, titulo: str, ficha: dict) -> None:
    """La tabla de equivalencias «iguala o supera» (parámetros medibles del pliego frente al catálogo). Sin evidencia o sin modelo externo no se hace: el paso queda «omitido» con el motivo."""
    from . import equivalencia
    res = await equivalencia.preparar(e["licitacion"], titulo, ficha or {}, modelo=e.get("modelo") or "auto")
    await _marcar(ejecucion_id, indice, estado=HECHO if res["estado"] == "hecha" else OMITIDO, error="", resumen=res["resumen"][:MAX_RESUMEN], secciones=[], fin=_iso(_ahora(None)))


async def _paso_encargos(ejecucion_id: int, indice: int, e: dict, defin: dict, titulo: str, ficha: dict) -> None:
    """El director de la oferta redacta el encargo de cada agente (con Claude o ChatGPT si están conectados; si no, con la plantilla). Respeta lo que haya escrito una persona."""
    from . import encargos
    res = await encargos.preparar(e["licitacion"], titulo, ficha or {}, modelo=e.get("modelo") or "auto")
    await _marcar(ejecucion_id, indice, estado=HECHO, error="", resumen=res["resumen"][:MAX_RESUMEN], secciones=[], escritas=len(res["guardados"]), fin=_iso(_ahora(None)))


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
    from . import encargos as encargos_mod
    encargo = await encargos_mod.texto_para(motor_id, defin["agente"], encargos_mod.MAX_LOCAL)         # los informes los hace siempre el modelo local
    if encargo:
        peticion = f"{peticion}\n\n{encargo}"
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
        actual = await _cargar(ejecucion_id)
        if not actual or actual["estado"] != "en_curso":            # la han cancelado (o se dio por perdida): no se empieza ningún paso más
            log.info("redacción: la ejecución %s ya no está en curso (%s): se detiene antes del paso %s", ejecucion_id, (actual or {}).get("estado"), paso["id"])
            return actual or {}
        defin = _PASO[paso["id"]]
        await _marcar(ejecucion_id, i, estado=EN_CURSO, inicio=_iso(_ahora(None)), error="")
        try:
            if defin.get("comparativa"):
                await _paso_comparativa(ejecucion_id, i, e, defin, titulo, ficha)
            elif defin.get("equivalencia"):
                await _paso_equivalencia(ejecucion_id, i, e, defin, titulo, ficha)
            elif defin.get("encargos"):
                await _paso_encargos(ejecucion_id, i, e, defin, titulo, ficha)
            elif defin.get("informe"):
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
