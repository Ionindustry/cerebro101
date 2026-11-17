"""Las líneas de las tarifas de proveedores, buscables por significado.

Hasta ahora una línea de tarifa solo se encontraba si compartía palabras con lo que pide el pliego (con un pequeño diccionario castellano↔inglés). Aquí cada línea se convierte en un vector con
BGE-M3 (el mismo modelo local de la base de conocimiento; nada sale de la máquina) y se guarda en `lineas_vectores`. La tabla es un índice: se puede borrar y se recalcula sola.

El vector solo PROPONE candidatos. Que un producto «iguale o supere» lo decide el código con los valores de la ficha (equivalencia.py), nunca el parecido.
El texto vectorizado NO lleva precio: es lo que se enseña como evidencia a los modelos.
"""
from __future__ import annotations

import hashlib
import logging
import re

import psycopg

from psycopg.types.json import Jsonb

from . import atributos_producto as AP
from .ajustes import ajustes
from .llm import embeddings

log = logging.getLogger("cerebro.lineas_vectores")
LOTE = 32                  # textos por llamada a Ollama
MAX_TEXTO = 400
MAX_ESPECIFICACIONES = 6
CERROJO = 7_310_101      # clave del cerrojo de PostgreSQL de la pasada de vectorización
MAX_TEXTO_LINEA = 450          # texto del índice que se enseña cuando no se encuentra la línea original (respaldo)
MAX_EVIDENCIA_PRODUCTO = 1100  # lo que ve el modelo de UN producto: todas las características de la línea original, de todas las listas que lo traigan
_NO_ES_CARACTERISTICA = re.compile(r"precio|coste|costo|pvp|tarifa|descuento|margen|dto|neto|iva|stock|proveedor", re.I)   # nada de dinero en la evidencia, aunque venga como «característica»
SIMILITUD_MINIMA = 0.45    # por debajo, el parecido es ruido (a calibrar con tarifas reales)


def texto_completo(l: dict, maximo: int = 700) -> str:
    """El producto tal como lo describe la línea ORIGINAL de la tarifa: marca, referencia, descripción y TODAS sus características (el índice solo guarda las primeras para poder buscar; el modelo
    necesita el zoom, la focal, las salidas… aunque estén al final). Sin precio ni nada que se parezca a dinero. Pura."""
    esp = l.get("especificaciones") if isinstance(l.get("especificaciones"), dict) else {}
    partes = [_corto(l.get("marca"), 40), _corto(l.get("ref"), 60), _corto(l.get("desc"), 500)]
    carac = [f"{_corto(k, 40)}: {_corto(v, 80)}" for k, v in esp.items() if str(v or "").strip() and not _NO_ES_CARACTERISTICA.search(str(k))]
    texto = " | ".join(p for p in partes if p)
    if carac:
        texto += " | " + "; ".join(carac)
    return texto[:maximo]


def unir_textos(textos: list[str], maximo: int = MAX_EVIDENCIA_PRODUCTO) -> str:
    """Los textos de un mismo producto (viene en varias listas de proveedor) sin repetir, hasta `maximo` caracteres: cada lista aporta datos distintos (una dice «32X», otra «zoom» a secas). Pura."""
    out: list[str] = []
    vistos: set[str] = set()
    for t in textos:
        t = " ".join(str(t or "").split())
        if t and t.casefold() not in vistos:
            vistos.add(t.casefold())
            out.append(t)
    return " || ".join(out)[:maximo]


async def _lineas_de(conn, refs: list[str]) -> dict[str, list[dict]]:
    """Las líneas ORIGINALES (de la última tarifa de cada proveedor y lista) de esas referencias, por referencia en minúsculas. Si algo falla, vacío: se usa el texto del índice."""
    if not refs:
        return {}
    try:
        cur = await conn.execute("SELECT l FROM (SELECT DISTINCT ON (proveedor->>'nombre', lista) lineas FROM importaciones_precios WHERE estado IN ('propuesta', 'aplicada') "
                                 "ORDER BY proveedor->>'nombre', lista, id DESC) t, jsonb_array_elements(t.lineas) l WHERE l->>'ref' = ANY(%s)", [refs])
        out: dict[str, list[dict]] = {}
        for (l,) in await cur.fetchall():
            if isinstance(l, dict):
                out.setdefault(str(l.get("ref") or "").casefold(), []).append(l)
        return out
    except Exception as e:      # noqa: BLE001 — sin las líneas originales se sigue con el texto del índice
        log.warning("lineas_vectores: no se han podido leer las líneas originales: %s: %s", type(e).__name__, e)
        return {}


def _corto(t, n: int) -> str:
    return " ".join(str(t or "").split())[:n]


def texto_de_linea(l: dict) -> str:
    """Lo que se vectoriza: marca, referencia, descripción y las primeras características. Sin precio ni código interno. Pura."""
    esp = l.get("especificaciones") if isinstance(l.get("especificaciones"), dict) else {}
    partes = [_corto(l.get("marca"), 40), _corto(l.get("ref"), 60), _corto(l.get("desc"), 250)]
    carac = [f"{_corto(k, 30)}: {_corto(v, 40)}" for k, v in list(esp.items())[:MAX_ESPECIFICACIONES] if str(v or "").strip()]
    texto = " | ".join(p for p in partes if p)
    if carac:
        texto += " | " + "; ".join(carac)
    return texto[:MAX_TEXTO]


def huella(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()[:32]


def pendientes(lineas: list[dict], existentes: dict[str, str]) -> list[dict]:
    """De las líneas de una lista, las que hay que vectorizar: las nuevas y las que han cambiado de texto. `existentes`: {ref: huella}. Una referencia repetida cuenta una vez. Pura."""
    vistos, salida = set(), []
    for l in lineas:
        if not isinstance(l, dict):
            continue
        ref = _corto(l.get("ref") or l.get("codigo"), 80)
        texto = texto_de_linea(l)
        if not ref or not texto or ref in vistos:
            continue
        vistos.add(ref)
        h = huella(texto)
        if existentes.get(ref) != h:
            salida.append({"ref": ref, "texto": texto, "huella": h, "marca": _corto(l.get("marca"), 60), "atributos": AP.atributos_de_linea(l)})
    return salida


def atributos_por_ref(lineas: list[dict]) -> dict[str, dict]:
    """{ref: atributos normalizados} de las líneas de una lista (la primera de cada referencia). Pura."""
    r: dict[str, dict] = {}
    for l in lineas:
        if isinstance(l, dict):
            ref = _corto(l.get("ref") or l.get("codigo"), 80)
            if ref and ref not in r:
                r[ref] = AP.atributos_de_linea(l)
    return r


def _conectar():
    return psycopg.AsyncConnection.connect(ajustes.database_url)


async def _ultimas_listas(conn) -> list[tuple[str, str, list]]:
    """La tarifa más reciente (aplicada o propuesta) de cada proveedor y lista: (proveedor, lista, líneas)."""
    cur = await conn.execute("SELECT DISTINCT ON (proveedor->>'nombre', lista) proveedor->>'nombre', lista, lineas FROM importaciones_precios "
                             "WHERE estado IN ('propuesta', 'aplicada') ORDER BY proveedor->>'nombre', lista, id DESC")
    return [(p or "", lista, lineas or []) for p, lista, lineas in await cur.fetchall()]


async def indexar_pendientes(maximo: int = 2000, embed=embeddings) -> dict:
    """Vectoriza hasta `maximo` líneas nuevas o cambiadas (el resto, en la pasada siguiente) y borra las que ya no están en la tarifa. {indexadas, pendientes, listas}. Si Ollama falla, deja lo ya hecho."""
    hechas, quedan, listas = 0, 0, 0
    async with await _conectar() as conn:
        cur = await conn.execute("SELECT pg_try_advisory_lock(%s)", [CERROJO])       # una sola pasada a la vez (se suelta al cerrar la conexión)
        if not (await cur.fetchone())[0]:
            return {"indexadas": 0, "pendientes": 0, "listas": 0, "omitida": "ya hay otra pasada en marcha"}
        for proveedor, lista, lineas in await _ultimas_listas(conn):
            listas += 1
            cur = await conn.execute("SELECT ref, huella, atributos FROM lineas_vectores WHERE lista = %s", [lista])
            filas = await cur.fetchall()
            existentes = {r: h for r, h, _a in filas}
            guardados = {r: a for r, _h, a in filas}
            # los atributos se recalculan siempre (es barato y no lleva modelo): si las reglas mejoran o la tarifa cambia, se actualizan sin recalcular el vector
            por_ref = atributos_por_ref(lineas)
            cambian = [(Jsonb(por_ref[r]), lista, r) for r in guardados if r in por_ref and guardados[r] != por_ref[r]]
            if cambian:
                await conn.cursor().executemany("UPDATE lineas_vectores SET atributos = %s WHERE lista = %s AND ref = %s", cambian)
                await conn.commit()
            falta = pendientes(lineas, existentes)
            vigentes = {_corto(l.get("ref") or l.get("codigo"), 80) for l in lineas if isinstance(l, dict)}
            sobran = [r for r in existentes if r not in vigentes]
            if sobran:
                await conn.execute("DELETE FROM lineas_vectores WHERE lista = %s AND ref = ANY(%s)", [lista, sobran])
                await conn.commit()
            for i in range(0, len(falta), LOTE):
                if hechas >= maximo:
                    quedan += len(falta) - i
                    break
                lote = falta[i:i + LOTE]
                try:
                    vectores = await embed([x["texto"] for x in lote])
                except Exception as e:      # noqa: BLE001 - sin Ollama se reintenta en la pasada siguiente
                    log.warning("lineas_vectores: no se han podido calcular los vectores: %s: %s", type(e).__name__, e)
                    return {"indexadas": hechas, "pendientes": quedan + len(falta) - i, "listas": listas, "error": type(e).__name__}
                for x, v in zip(lote, vectores):
                    await conn.execute(
                        "INSERT INTO lineas_vectores (lista, ref, proveedor, marca, texto, huella, embedding, atributos) VALUES (%s,%s,%s,%s,%s,%s,%s::vector,%s) "
                        "ON CONFLICT (lista, ref) DO UPDATE SET proveedor = EXCLUDED.proveedor, marca = EXCLUDED.marca, texto = EXCLUDED.texto, huella = EXCLUDED.huella, "
                        "embedding = EXCLUDED.embedding, atributos = EXCLUDED.atributos, creado = now()",
                        [lista, x["ref"], proveedor, x["marca"], x["texto"], x["huella"], str(v), Jsonb(x["atributos"])])
                await conn.commit()
                hechas += len(lote)
    log.info("lineas_vectores: %d líneas vectorizadas, %d pendientes", hechas, quedan)
    return {"indexadas": hechas, "pendientes": quedan, "listas": listas}


async def buscar(consultas: list[str], por_consulta: int = 4, embed=embeddings) -> list[dict]:
    """Las líneas más parecidas por significado a cada consulta: [{ref, desc, similitud}]. Una por referencia, la mejor puntuación; sin precio. Vacío si la tabla no tiene nada.
    Se piden el triple de candidatos y se ordenan comprobando con el código los atributos que pide la consulta (resolución, focal, IP…): los que incumplen un dato leído pasan al final y todos llevan una nota
    «comprobado por el código». Nunca se descarta a nadie por un atributo: sin dato no es un incumplimiento."""
    consultas = [_corto(q, 300) for q in consultas if _corto(q, 300)]
    if not consultas:
        return []
    vectores = await embed(consultas)
    por_q: list[list[tuple[tuple[str, str], dict]]] = []
    async with await _conectar() as conn:
        for q, v in zip(consultas, vectores):
            rest = AP.restricciones(q)
            cur = await conn.execute("SELECT lista, ref, texto, 1 - (embedding <=> %s::vector) AS similitud, atributos FROM lineas_vectores ORDER BY embedding <=> %s::vector LIMIT %s",
                                     [str(v), str(v), por_consulta * 3])
            candidatos = []
            for lista, ref, texto, sim, attrs in await cur.fetchall():
                if sim < SIMILITUD_MINIMA:
                    continue
                res = AP.evaluar(rest, attrs or AP.extraer(texto))
                candidatos.append((AP.orden(res), -float(sim), lista, ref, texto, float(sim), AP.texto_de_comprobacion(res)))
            por_q.append([((lista, ref), {"ref": ref, "desc": (_corto(texto, MAX_TEXTO_LINEA) + " " + nota).strip(), "nota": nota, "similitud": round(sim, 3)})
                          for _o, _s, lista, ref, texto, sim, nota in sorted(candidatos)[:por_consulta]])
    # Por turnos: primero el mejor de cada consulta, luego el segundo de cada una... Ordenar todo junto por parecido dejaba que las consultas con mejor puntuación media (p. ej. «licencia del VMS»)
    # se llevaran todo el cupo de la evidencia y los productos de las demás (domos, servidores…) no llegaban nunca al modelo. Un producto solo cuenta una vez aunque venga en varias listas.
    salida: list[dict] = []
    vistos: set[str] = set()
    for ronda in range(por_consulta):
        for lista in por_q:
            if ronda < len(lista) and lista[ronda][1]["ref"].casefold() not in vistos:
                vistos.add(lista[ronda][1]["ref"].casefold())
                salida.append(lista[ronda][1])
    # El modelo ve el producto ENTERO (línea original de todas las listas), no el texto recortado del índice: el zoom o la focal suelen estar al final y quedaban fuera.
    async with await _conectar() as conn:
        originales = await _lineas_de(conn, [x["ref"] for x in salida])
    for x in salida:
        completo = unir_textos([texto_completo(l) for l in originales.get(x["ref"].casefold(), [])])
        nota = x.pop("nota", "")
        if completo:
            x["desc"] = (completo + " " + nota).strip()
    return salida
