"""Revisión previa («pre-vuelo») de «Preparar la oferta con los agentes» para una licitación: de SOLO LECTURA, no llama a ningún modelo ni cambia nada.

Comprueba que están los ingredientes y dice qué falta ANTES de gastar una pasada de los agentes: la ficha en el motor, la sociedad y sus datos del ERP, el DEUC base, los pliegos descargados, los requisitos
(y la aptitud según el perfil de la empresa), la oferta y la última pasada de los agentes. La usan el panel (tarjeta de la ficha, botón «Revisar antes de preparar la oferta») y scripts/probar_oferta.py.

Cada comprobación sale como {"nivel": «ok»|«aviso»|«bloqueo», "texto"}. «bloqueo» = sin eso no tiene sentido lanzar (no hay ficha ni sociedad); «aviso» = se puede lanzar, pero saldrá con huecos
o con menos calidad (faltan datos de la sociedad, no hay DEUC, no hay pliegos o requisitos…). El resultado global es «bloqueada», «con_avisos» o «lista».
"""
from __future__ import annotations

from . import aptitud, embudo, empresa, ofertas, plantillas, pliegos, redaccion


def _it(nivel: str, texto: str) -> dict:
    return {"nivel": nivel, "texto": texto}


async def _ficha(motor_id: str, deps: dict) -> tuple[dict, list[dict]]:
    ficha = await deps["ficha"](motor_id)
    if ficha:
        return ficha, [_it("ok", f"El motor devuelve la ficha ({len(pliegos.documentos_de(ficha))} documentos en el pliego)")]
    # ficha_del_motor no lanza si el motor no responde: devuelve una ficha vacía (y lo deja en el registro)
    return {}, [_it("bloqueo", "El motor no devuelve la ficha de esta licitación (¿motor caído, sin token LICITACIONES_API_TOKEN o id equivocado?)")]


async def _sociedad(motor_id: str, ficha: dict, deps: dict) -> list[dict]:
    items, nombre = [], None
    try:
        nombre = await deps["elegir"](None)
        items.append(_it("ok", f"Sociedad: {nombre}"))
    except empresa.VariasEmpresas as e:
        items.append(_it("aviso", "Hay varias empresas en el ERP: hay que elegir con cuál se presenta en la tarjeta «Documentación administrativa» de la oferta (" + ", ".join(x["razon_social"] for x in e.empresas) + ")"))
        nombre = e.empresas[0]["nombre"]
    except Exception as e:      # noqa: BLE001
        return [_it("bloqueo", f"El ERP no da la sociedad: {type(e).__name__}: {str(e)[:200]}")]
    try:
        d = await deps["claves"](nombre, ficha, motor_id)
        faltan = {k: v for k, v in d["faltan"].items() if not k.startswith("oferta.")}
        items.append(_it("ok", f"{len(d['disponibles'])} datos disponibles para las plantillas"))
        if faltan:
            items.append(_it("aviso", f"Faltan {len(faltan)} datos de la sociedad en el ERP: las plantillas saldrán con esos huecos (Company, Dirección y Contacto de «{nombre}»). Faltan: " + ", ".join(f"{k} ({v})" for k, v in list(faltan.items())[:12]) + ("…" if len(faltan) > 12 else "")))
    except Exception as e:      # noqa: BLE001
        items.append(_it("aviso", f"No se han podido comprobar los datos de la sociedad: {type(e).__name__}"))
    try:
        dd = await deps["deuc"](nombre)
        items.append(_it("ok", f"DEUC base: «{dd[0]}» ({dd[2]})") if dd else _it("aviso", "No hay DEUC base de esta sociedad: súbelo a Jarvis (agente Administrativo: «Guarda este documento como DEUC base de 101.cat»)"))
    except Exception as e:      # noqa: BLE001
        items.append(_it("aviso", f"No se ha podido comprobar el DEUC base: {type(e).__name__}"))
    return items


async def _pliegos(motor_id: str, deps: dict) -> list[dict]:
    try:
        docs = (await deps["documentos"](motor_id))["documentos"]
    except Exception as e:      # noqa: BLE001
        return [_it("aviso", f"No se han podido comprobar los pliegos: {type(e).__name__}")]
    limpios = [d for d in docs if (d.get("descarga") or {}).get("estado") in ("limpio", "con_macros")]
    if limpios:
        return [_it("ok", f"{len(limpios)} de {len(docs)} documentos descargados y analizados")]
    return [_it("aviso", f"Ningún documento del pliego está descargado y analizado ({len(docs)} en la ficha): pulsa «Analizar los pliegos con el Analista» en la tarjeta «Pliegos»")]


async def _requisitos(motor_id: str, deps: dict) -> list[dict]:
    try:
        reqs = (await deps["requisitos"](motor_id))["requisitos"]
    except Exception as e:      # noqa: BLE001
        return [_it("aviso", f"No se han podido comprobar los requisitos: {type(e).__name__}")]
    if not reqs:
        return [_it("aviso", "No hay requisitos anotados: analiza los pliegos antes de preparar la oferta (la oferta se construye a partir de ellos)")]
    c = {e: sum(1 for r in reqs if r["estado"] == e) for e in ("confirmado", "borrador", "rechazado")}
    items = [_it("ok", f"{len(reqs)} requisitos: {c['confirmado']} confirmados, {c['borrador']} en borrador, {c['rechazado']} rechazados")]
    if c["borrador"]:
        items.append(_it("aviso", f"Hay {c['borrador']} requisitos en borrador sin revisar: la oferta solo se apoya en los confirmados"))
    r = aptitud.resumen(aptitud.con_sugerencias([x for x in reqs if x["estado"] != "rechazado"]))
    if r["bloqueos"]:
        items.append(_it("aviso", f"Según el perfil de la empresa, {r['bloqueos']} requisitos probablemente NO se cumplen (mira las sugerencias en la tarjeta «Pliegos»): valora si compensa seguir o ir en UTE"))
    return items


async def _oferta(motor_id: str, deps: dict) -> list[dict]:
    items = []
    try:
        o = await deps["oferta"](motor_id)
        n = len(o.get("secciones") or [])
        items.append(_it("ok", f"La oferta existe: {n} secciones") if n else _it("aviso", "La oferta aún no tiene secciones: se crean al pulsar «Preparar la oferta» (a partir de los criterios y requisitos del pliego)"))
        e = await deps["ejecucion"](motor_id)
        if not e:
            items.append(_it("ok", "Aún no se ha lanzado ninguna pasada de los agentes"))
        else:
            pasos = ", ".join(f"{p.get('titulo') or p.get('id')}: {p.get('estado')}" for p in e.get("pasos") or [])
            items.append(_it("ok" if e["estado"] in ("completa",) else "aviso", f"Última pasada de los agentes: #{e['id']} · {e['estado']}" + (f" · {e['error']}" if e.get("error") else "") + (f" ({pasos})" if pasos else "")))
            if e["estado"] == "en_curso":
                items.append(_it("aviso", "Hay una pasada «en curso»: si lleva más de 3 horas sin avanzar se sustituye sola; si acabas de reiniciar el worker, se cortó y hay que repetirla"))
    except Exception as e:      # noqa: BLE001
        items.append(_it("aviso", f"No se ha podido leer la oferta: {type(e).__name__}"))
    return items


async def revisar(motor_id: str, **sustituciones) -> dict:
    """La revisión previa de una licitación. `sustituciones` permite cambiar de dónde salen los datos (para las pruebas)."""
    deps = {"ficha": plantillas.ficha_del_motor, "elegir": empresa.elegir, "claves": plantillas.claves_disponibles, "deuc": empresa.deuc_base,
            "documentos": pliegos.documentos, "requisitos": pliegos.requisitos, "oferta": lambda m: ofertas.leer(m, con_contenido=False), "ejecucion": redaccion.ultima, **sustituciones}
    ficha, i_ficha = await _ficha(motor_id, deps)
    secciones = [("ficha", "Ficha en el motor", i_ficha), ("sociedad", "Sociedad que presenta la oferta (ERP)", await _sociedad(motor_id, ficha, deps)),
                 ("pliegos", "Pliegos", await _pliegos(motor_id, deps)), ("requisitos", "Requisitos y aptitud según el perfil de la empresa", await _requisitos(motor_id, deps)),
                 ("oferta", "Oferta y última pasada de los agentes", await _oferta(motor_id, deps))]
    todos = [i for _, _, items in secciones for i in items]
    bloqueos, avisos = sum(1 for i in todos if i["nivel"] == "bloqueo"), sum(1 for i in todos if i["nivel"] == "aviso")
    return {"licitacion": motor_id, "secciones": [{"id": a, "titulo": b, "items": c} for a, b, c in secciones], "bloqueos": bloqueos, "avisos": avisos,
            "resultado": "bloqueada" if bloqueos else ("con_avisos" if avisos else "lista")}
