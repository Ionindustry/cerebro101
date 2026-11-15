"""Documentos que redactan los agentes en una licitación, reunidos en un solo sitio para verlos y bajarlos en Word.

Hasta ahora cada resultado vivía en un rincón distinto: las secciones de la oferta en «Oferta», los informes de Precio y del Evaluador solo como el resumen de un paso, la comparativa y la tabla de
equivalencias en sus tarjetas, los encargos en otra. Aquí se juntan en una lista: Descripción de la solución, Memoria técnica, Documentación administrativa, Justificación del precio, Informe de precio,
Informe del evaluador, Comparativa de productos, Tabla de equivalencias y Encargos a los agentes; y, aparte, las plantillas administrativas ya rellenadas (que ya se bajaban como fichero).

SOLO LEE: no escribe nada ni cambia ningún estado. Los documentos son BORRADORES de agentes: el Word lo dice y marca lo no aprobado. Cada documento se reconstruye al pedirlo desde lo guardado,
así que siempre es la última versión. Los precios de venta no aparecen aquí (la proposición económica la fija una persona y sigue en la oferta); el informe de precio y la justificación sí, como los
ve ya quien tiene acceso a la oferta (Dirección y Licitaciones).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from . import comparativa as C
from . import encargos as E
from . import equivalencia as EQ
from . import ofertas as O
from . import plantillas as P
from . import redaccion as R

log = logging.getLogger("cerebro.licitaciones.documentos_agentes")

ORDEN_ESTADO = ("vacia", "borrador", "revisada", "aprobada")
ETIQUETA_ESTADO = {"vacia": "sin redactar", "borrador": "borrador", "revisada": "revisada", "aprobada": "aprobada", "informe": "informe del agente", "agente": "redactado por un agente"}
NOTA_BORRADOR = "Documento redactado por agentes del Cerebro: es un BORRADOR. Debe revisarlo una persona antes de usarlo."

# id → (título, agente, dónde está)
DOCUMENTOS = (
    {"id": "solucion", "titulo": "Descripción de la solución", "agente": "arquitecto-solucion", "tipo": "secciones", "sobre": "tecnico", "claves": ("descripcion-solucion",)},
    {"id": "memoria", "titulo": "Memoria técnica", "agente": "redactor-memoria", "tipo": "secciones", "sobre": "tecnico", "excepto": ("descripcion-solucion",)},
    {"id": "administrativo", "titulo": "Documentación administrativa", "agente": "administrativo-licitaciones", "tipo": "secciones", "sobre": "administrativo"},
    {"id": "costes", "titulo": "Justificación del precio", "agente": "costes-licitacion", "tipo": "secciones", "sobre": "economico", "claves": ("justificacion-precio",)},
    {"id": "precio", "titulo": "Informe de precio (orientativo)", "agente": "precio-licitacion", "tipo": "informe", "paso": "precio"},
    {"id": "evaluacion", "titulo": "Informe del evaluador: puntuación estimada y riesgos", "agente": "evaluador-ofertas", "tipo": "informe", "paso": "evaluacion"},
    {"id": "comparativa", "titulo": "Comparativa de productos y ventaja competitiva", "agente": "comparador-productos", "tipo": "comparativa"},
    {"id": "equivalencia", "titulo": "Tabla de equivalencias «iguala o supera»", "agente": "comparador-productos", "tipo": "equivalencia"},
    {"id": "encargos", "titulo": "Encargos a los agentes", "agente": "director-oferta", "tipo": "encargos"},
)
_POR_ID = {d["id"]: d for d in DOCUMENTOS}


class NoExisteDocumento(LookupError):
    pass


def _texto(v) -> str:
    return str(v or "").strip()


def _estado_conjunto(secs: list[dict]) -> str:
    return min((s["estado"] for s in secs), key=ORDEN_ESTADO.index)


def _de_secciones(d: dict, oferta: dict | None) -> dict | None:
    """Las secciones con contenido de un sobre (o de unas claves) hechas un documento. None si no hay ninguna redactada. Pura."""
    secs = [s for s in (oferta or {}).get("secciones", []) if s["sobre"] == d["sobre"] and s["clave"] != O.PROPOSICION and _texto(s.get("contenido")) and s["estado"] != "vacia"
            and (not d.get("claves") or s["clave"] in d["claves"]) and s["clave"] not in d.get("excepto", ())]
    if not secs:
        return None
    bloques = []
    for s in secs:
        bloques.append(("h2", s["titulo"]))
        if s["estado"] != "aprobada":
            bloques.append(("nota", "[BORRADOR — pendiente de revisión]" if s["estado"] == "borrador" else "[REVISADA — pendiente de aprobación]"))
        bloques.append(("texto", s["contenido"]))
    autores = sorted({s["por"] for s in secs if s.get("por")})
    return {"estado": _estado_conjunto(secs), "por": ", ".join(autores), "actualizado": max((s["actualizado"] for s in secs if s.get("actualizado")), default=None), "bloques": bloques}


def _de_informe(d: dict, ejecucion: dict | None) -> dict | None:
    paso = next((p for p in (ejecucion or {}).get("pasos", []) if p.get("id") == d["paso"]), None)
    if not paso or not _texto(paso.get("resumen")) or paso.get("estado") != "hecho":
        return None
    return {"estado": "informe", "por": f"agente:{d['agente']}", "actualizado": paso.get("fin"), "bloques": [("texto", paso["resumen"])]}


def _de_comparativa(c: dict | None) -> dict | None:
    if not c or not c.get("contenido"):
        return None
    texto = C.texto_comparativa(c["contenido"])
    if not texto:
        return None
    return {"estado": "agente", "por": f"{c.get('proveedor') or 'modelo'} · agente:comparador-productos", "actualizado": c.get("actualizado"), "bloques": [("texto", texto)]}


def _de_equivalencia(e: dict | None) -> dict | None:
    cont = (e or {}).get("contenido") or {}
    params = cont.get("parametros") or []
    if not params:
        return None
    filas = [["Parámetro", "Exigido", "Producto recomendado", "Productos evaluados"]]
    for p in params:
        op = "" if p.get("operador") == "texto" else f"{p.get('operador')} "
        cands = "; ".join(f"{c.get('producto')}: {c.get('valor_producto') or 'sin dato'} ({c.get('veredicto')})" for c in (p.get("candidatos") or [])[:6])
        filas.append([_texto(p.get("parametro")), f"{op}{_texto(p.get('valor_exigido'))}", _texto(p.get("recomendado")) or "SIN PRODUCTO QUE LO CUMPLA ACREDITADO", cands or "—"])
    bloques = [("tabla", filas)]
    sol = cont.get("solucion") or {}
    if sol.get("productos"):
        bloques.insert(0, ("h2", "Solución mínima de productos"))
        bloques.insert(1, ("texto", "\n".join(f"- {x['producto']}: cubre {len(x.get('cubre') or [])} parámetro(s)" for x in sol["productos"])))
        bloques.insert(2, ("h2", "Parámetro a parámetro"))
        if sol.get("sin_cubrir"):
            bloques.append(("nota", "Sin cubrir por ningún producto: " + ", ".join(map(str, sol["sin_cubrir"]))))
    if cont.get("pendientes"):
        bloques.append(("h2", "Pendiente (fichas que faltan)"))
        bloques.append(("texto", "\n".join(f"- {x}" for x in cont["pendientes"])))
    return {"estado": "agente", "por": f"{(e or {}).get('proveedor') or 'modelo'} · agente:comparador-productos", "actualizado": (e or {}).get("actualizado"), "bloques": bloques}


def _de_encargos(encargos: list[dict] | None) -> dict | None:
    con = [x for x in (encargos or []) if _texto(x.get("contenido"))]
    if not con:
        return None
    bloques = []
    for x in con:
        bloques += [("h2", f"Encargo a {x.get('nombre') or x.get('agente')}"), ("texto", x["contenido"])]
    return {"estado": "agente", "por": ", ".join(sorted({_texto(x.get("por")) for x in con if x.get("por")})), "actualizado": max((x["actualizado"] for x in con if x.get("actualizado")), default=None), "bloques": bloques}


def construir(fuentes: dict) -> list[dict]:
    """Los documentos que hay ahora mismo, con su contenido en bloques, a partir de lo leído de la base (`oferta`, `ejecucion`, `comparativa`, `equivalencia`, `encargos`). Pura."""
    out = []
    for d in DOCUMENTOS:
        r = {"secciones": lambda: _de_secciones(d, fuentes.get("oferta")), "informe": lambda: _de_informe(d, fuentes.get("ejecucion")),
             "comparativa": lambda: _de_comparativa(fuentes.get("comparativa")), "equivalencia": lambda: _de_equivalencia(fuentes.get("equivalencia")),
             "encargos": lambda: _de_encargos(fuentes.get("encargos"))}[d["tipo"]]()
        if r:
            out.append({"id": d["id"], "titulo": d["titulo"], "agente": d["agente"], **r})
    return out


def a_texto(doc: dict) -> str:
    """El documento como texto plano (para verlo en pantalla y copiarlo). Pura."""
    partes = [doc["titulo"].upper()]
    for tipo, v in doc["bloques"]:
        if tipo == "h2":
            partes.append(f"\n{v}")
        elif tipo == "tabla":
            partes += [" | ".join(f) for f in v]
        else:
            partes.append(str(v))
    return "\n".join(partes).strip()


def publico(doc: dict) -> dict:
    """La ficha de un documento para la lista: sin el contenido."""
    n = sum(len(str(v)) if t != "tabla" else sum(len(c) for f in v for c in f) for t, v in doc["bloques"])
    return {"id": doc["id"], "titulo": doc["titulo"], "agente": doc["agente"], "estado": doc["estado"], "estado_texto": ETIQUETA_ESTADO.get(doc["estado"], doc["estado"]),
            "por": doc.get("por") or "", "actualizado": doc.get("actualizado"), "caracteres": n}


def a_docx(doc: dict, titulo_licitacion: str = "", ahora: datetime | None = None) -> bytes:
    """El documento en Word, con el mismo formato que el borrador de la oferta. Marca que es un borrador de agentes. Pura."""
    ahora = (ahora or datetime.now(timezone.utc)).astimezone()
    x = [O._p(doc["titulo"], "Title")]
    if titulo_licitacion:
        x.append(O._p(O._una_linea(titulo_licitacion, 200), negrita=True))
    x.append(O._p(f"{NOTA_BORRADOR} Generado el {ahora:%d/%m/%Y %H:%M}" + (f" · autor: {doc['por']}" if doc.get("por") else "") + ".", cursiva=True))
    for tipo, v in doc["bloques"]:
        if tipo == "h2":
            x.append(O._p(v, "Heading2"))
        elif tipo == "nota":
            x.append(O._p(v, negrita=True))
        elif tipo == "tabla":
            x.append(O._tabla(v))
        else:
            x += O._parrafos(str(v))
    return O.construir_docx("".join(x))


def nombre_fichero(doc: dict, expediente: str = "") -> str:
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", f"{doc['id']}-{expediente}" if expediente else doc["id"])[:80].strip("-") or "documento"
    return f"{base}.docx"


async def _leer(nombre: str, f):
    try:
        return await f
    except Exception as e:      # noqa: BLE001 — una fuente rota no tumba la lista
        log.warning("documentos de agentes: no se ha podido leer %s: %s: %s", nombre, type(e).__name__, e)
        return None


async def reunir(motor_id: str) -> dict:
    """Lee de la base todo lo que redactan los agentes de esa licitación. Una fuente que falla se omite."""
    oferta = await _leer("oferta", O.leer(motor_id))
    return {"oferta": oferta if oferta and oferta.get("existe") else None, "ejecucion": await _leer("ejecucion", R.ultima(motor_id)),
            "comparativa": await _leer("comparativa", C.leer(motor_id)), "equivalencia": await _leer("equivalencia", EQ.leer(motor_id)),
            "encargos": await _leer("encargos", E.listar(motor_id)), "plantillas": await _leer("plantillas", P.listar(motor_id))}


async def listar(motor_id: str) -> dict:
    f = await reunir(motor_id)
    docs = [publico(d) for d in construir(f)]
    plantillas = [{"id": d["id"], "nombre": d["nombre"], "fichero": d["fichero"], "estado": d["estado"], "formato": d["formato"], "por": d["por"], "creado": d["creado"], "pendientes": len(d["pendientes"])}
                  for d in ((f.get("plantillas") or {}).get("documentos") or []) if d.get("fichero")]
    return {"licitacion": motor_id, "documentos": docs, "plantillas": plantillas, "nota": NOTA_BORRADOR}


async def obtener(motor_id: str, doc_id: str) -> dict:
    """Un documento entero (con `texto` para verlo). NoExisteDocumento si el id no existe o aún no hay nada redactado."""
    if doc_id not in _POR_ID:
        raise NoExisteDocumento("Ese documento no existe")
    doc = next((d for d in construir(await reunir(motor_id)) if d["id"] == doc_id), None)
    if not doc:
        raise NoExisteDocumento("Los agentes aún no han redactado este documento")
    return doc
