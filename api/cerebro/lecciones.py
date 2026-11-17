"""Lecciones aprendidas de los agentes: cuando un agente falla, el código reconoce QUÉ le pasó, le da una corrección, reintenta, y si con la corrección lo consigue la lección queda activa para todas
las ejecuciones siguientes de ese agente (se añade a su «Método de trabajo»).

Dos orígenes de lecciones, los dos por los mismos guardarraíles:
- CATÁLOGO FIJO (`analizar`): el código reconoce el patrón de fallo en las llamadas hechas (repite, nunca guarda, una herramienta falla). Determinista, sin modelo.
- REFLEXIÓN DINÁMICA (`reflexionar`): el modelo LOCAL propone UNA lección nueva a partir de un resumen de lo ocurrido (nombres de herramienta, operaciones y mensajes de error recortados; NUNCA el texto
  del pliego ni de los documentos, que pueden traer instrucciones maliciosas).

Seguridad y guardarraíles (por qué es así):
- Toda lección, venga de donde venga, pasa por `validar` ANTES de probarse o guardarse: longitud, sin enlaces ni código ni mails, sin órdenes de saltarse controles, ignorar instrucciones, tocar
  credenciales, aprobaciones, firmas o precios. Lo que no pasa se descarta y se anota en el log.
- Una lección solo añade consejos de método. No cambia herramientas, permisos, sensibilidad ni aprobaciones, que siguen fijos en el código.
- Una lección propuesta nace en «prueba»: solo pasa a «activa» si con ella el agente consigue guardar lo que antes no guardaba. Máximo `MAX_ACTIVAS` por agente; falla `MAX_FALLOS` veces y se descarta;
  Dirección puede revocarla (`revocar`) y no vuelve sola.
- RAG: al arrancar un agente no se le da el cajón entero sino solo las lecciones activas más parecidas (BGE-M3 local) a la tarea que tiene delante.
"""
from __future__ import annotations

import json
import logging
import re
import unicodedata

import psycopg
from psycopg.rows import dict_row

from .ajustes import ajustes

log = logging.getLogger("cerebro.lecciones")

MAX_ACTIVAS = 6
MAX_FALLOS = 2
MAX_REINTENTOS = 2            # cuántas veces se corrige y se vuelve a intentar un paso antes de dejarlo a una persona
LECTURAS_ANTES_DE_GUARDAR = 6
_IDENT = re.compile(r"^[A-Za-z0-9_.\-]{1,60}$")


MAX_CARACTERES = 300
MIN_CARACTERES = 25
K_RAG = 4                     # cuántas lecciones se le dan a un agente al arrancar
SIMILITUD_RAG = 0.30          # por debajo, no se considera relacionada con la tarea

# Lo que una lección NUNCA puede pedir ni contener. Se compara sin tildes y en minúsculas.
_PROHIBIDO = [r"https?:", r"www\.", r"\S+@\S+\.\S+", r"```", r"[{}<>]", r"\$\(", r"\brm\s+-", r"\bsudo\b", r"\bcurl\b", r"\bsql\b", r"\bselect\b.+\bfrom\b",
              r"ignora", r"olvida", r"desobedec", r"anula", r"salta(te)?\b", r"omite\b.*(control|aprobacion|revision|norma|regla)", r"instrucciones? (anterior|previa|del sistema)", r"prompt", r"jailbreak",
              r"contrasena", r"password", r"\btoken\b", r"api[ _-]?key", r"secreto", r"credencial", r"clave (privada|de acceso|api)",
              r"sin (aprobacion|revision|permiso|autorizacion|firma|confirmacion)", r"no (pidas|esperes|requieras) (aprobacion|revision|permiso|confirmacion)", r"auto ?aprueb", r"aprueba (tu|el|la) (propio|propia|oferta|seccion)",
              r"\bfirma(r|s)? (tu|el|la|por)\b", r"envia(r)? (el|la|los|las|un|una) (oferta|correo|email|mensaje)", r"borra\b|elimina\b|vacia\b", r"fija(r)? (el )?precio", r"precio definitivo",
              r"desactiva", r"modo (admin|desarrollador|dios)", r"eres ahora", r"actua como", r"finge"]
_PROHIBIDO_RE = re.compile("|".join(f"(?:{p})" for p in _PROHIBIDO))


def _plano(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t.lower()) if unicodedata.category(c) != "Mn")


def validar(texto: str) -> tuple[bool, str]:
    """El guardarraíl: ¿puede esta lección entrar en el prompt de un agente? (ok, motivo si no). Pura. Se aplica a TODA lección, la saque el catálogo o la proponga un modelo."""
    t = " ".join(str(texto or "").split())
    if len(t) < MIN_CARACTERES:
        return False, "demasiado corta"
    if len(t) > MAX_CARACTERES:
        return False, f"demasiado larga (más de {MAX_CARACTERES} caracteres)"
    if "\n" in str(texto).strip():
        return False, "debe ser una sola frase o párrafo corto"
    m = _PROHIBIDO_RE.search(_plano(t))
    if m:
        return False, f"contiene algo que una lección no puede pedir: «{m.group(0)[:30]}»"
    return True, ""


def _conectar():
    return psycopg.AsyncConnection.connect(ajustes.database_url, row_factory=dict_row, connect_timeout=5)


def _nombre(p: dict) -> str:
    h, o = str(p.get("herramienta") or "?"), str(p.get("operacion") or "?")
    return f"{h}.{o}" if _IDENT.match(h) and _IDENT.match(o) else "?"


def analizar(pasos: list[dict] | None, guardo: bool = False) -> list[tuple[str, str]]:
    """Los patrones de fallo que muestran las llamadas hechas: [(id_del_patron, leccion)]. `guardo`: si el agente llegó a guardar algo. Pura: mismas llamadas, mismas lecciones."""
    pasos = [p for p in (pasos or []) if isinstance(p, dict)]
    if not pasos:
        return []
    nombres = [_nombre(p) for p in pasos]
    out: list[tuple[str, str]] = []
    repetidas = sum(1 for a, b in zip(nombres, nombres[1:]) if a == b)
    if repetidas >= 2:
        out.append(("repite", "No repitas una lectura que ya has hecho: su resultado está en la conversación. Cada llamada nueva tiene que traer algo que aún no sabes."))
    guardados = [i for i, n in enumerate(nombres) if n.endswith(".guardar_seccion")]
    if not guardados and not guardo and len(pasos) >= LECTURAS_ANTES_DE_GUARDAR:
        out.append(("sin_guardar", f"Lee lo imprescindible (como mucho {LECTURAS_ANTES_DE_GUARDAR - 2} lecturas) y guarda la primera sección en cuanto tengas algo que escribir. "
                                   "Un borrador guardado con [PENDIENTE: …] vale más que seguir leyendo."))
    fallos = [n for p, n in zip(pasos, nombres) if p.get("ok") is False and n != "?"]
    if len(fallos) >= 2:
        peor = max(set(fallos), key=fallos.count)
        out.append((f"falla:{peor}", f"La llamada «{peor}» ha fallado varias veces. No insistas: sigue con las demás herramientas y marca en el texto [PENDIENTE: lo que no has podido consultar]."))
    if not out:
        out.append(("sin_terminar", "Te has quedado sin pasos antes de acabar. Planifica: haz las lecturas mínimas, guarda cada sección en cuanto la tengas y responde con un resumen corto."))
    return [(p, t) for p, t in out if validar(t)[0]]            # incluso las del catálogo pasan por el guardarraíl


def resumen_de_traza(pasos: list[dict] | None, respuesta: str = "") -> str:
    """Lo único que ve el modelo que reflexiona: las llamadas (herramienta.operación y si fallaron) y la parte inicial del último mensaje de error del agente, sin el texto de ningún documento. Pura."""
    pasos = [p for p in (pasos or []) if isinstance(p, dict)][:40]
    linea = ", ".join(f"{_nombre(p)}{'' if p.get('ok') is not False else ' (ERROR)'}" for p in pasos) or "(ninguna llamada)"
    return f"Llamadas en orden: {linea}.\nTotal: {len(pasos)}; con error: {sum(1 for p in pasos if p.get('ok') is False)}."


ESQUEMA_REFLEXION = {"type": "object", "properties": {"leccion": {"type": "string"}}, "required": ["leccion"]}


async def reflexionar(agente: str, pasos: list[dict] | None, consulta=None) -> tuple[str, str] | None:
    """El modelo LOCAL propone UNA lección nueva a partir del resumen de la traza. Devuelve (patron, texto) o None si no propone nada o no pasa el guardarraíl. `consulta` solo para pruebas:
    async (mensajes, esquema) -> dict."""
    resumen = resumen_de_traza(pasos)
    mensajes = [{"role": "system", "content": "Eres un entrenador de agentes. Un agente de IA se quedó sin pasos antes de terminar su trabajo. Te doy SOLO la lista de herramientas que llamó. "
                                              "Escribe UNA lección de método, en castellano, imperativa, de una sola frase (máximo 250 caracteres), que le ayude a terminar la próxima vez: "
                                              "qué lecturas evitar, cuándo guardar, cómo no repetirse. No menciones documentos ni datos concretos, ni enlaces, ni código, ni permisos, ni precios. "
                                              "Responde con JSON {\"leccion\": \"…\"}."},
                {"role": "user", "content": resumen}]
    try:
        if consulta is None:
            from . import llm, router_modelos
            from .registro import registro
            asig = router_modelos.asignar(registro().fichas[agente], origen="programada")
            datos = await llm.chat(asig, mensajes, esquema=ESQUEMA_REFLEXION, temperatura=0.2, timeout=120, max_tokens=300)
        else:
            datos = await consulta(mensajes, ESQUEMA_REFLEXION)
        texto = " ".join(str((datos or {}).get("leccion") or "").split())
    except Exception as e:      # noqa: BLE001 — sin modelo no hay lección dinámica; el catálogo sigue
        log.info("lecciones: no se ha podido reflexionar para %s: %s", agente, type(e).__name__)
        return None
    ok, motivo = validar(texto)
    if not ok:
        log.warning("lecciones: lección propuesta para %s descartada por el guardarraíl (%s): %.80s", agente, motivo, texto)
        return None
    import hashlib
    return "dinamica:" + hashlib.sha1(_plano(texto).encode()).hexdigest()[:10], texto


def bloque(lecciones: list[str]) -> str:
    """El texto que se añade al prompt del agente. Vacío si no hay lecciones. Pura."""
    lecciones = [l.strip() for l in lecciones if l and l.strip()][:MAX_ACTIVAS]
    if not lecciones:
        return ""
    return "\n\nLecciones aprendidas en ejecuciones anteriores de tu trabajo (síguelas):\n" + "\n".join(f"- {l}" for l in lecciones)


async def activas(agente: str, tarea: str = "", embed=None) -> list[str]:
    """Las lecciones activas de ese agente MÁS RELACIONADAS con la tarea que va a hacer (RAG: BGE-M3 local, similitud ≥ SIMILITUD_RAG, hasta K_RAG). Sin tarea o sin embeddings, las que
    más éxitos tienen. Si la base no responde, ninguna: los agentes trabajan como siempre."""
    try:
        async with await _conectar() as conn:
            if tarea.strip():
                try:
                    from .llm import embeddings
                    v = (await (embed or embeddings)([tarea[:1500]]))[0]
                    cur = await conn.execute("SELECT texto, 1 - (embedding::vector(1024) <=> %s::vector) AS sim FROM lecciones_agentes WHERE agente = %s AND estado = 'activa' AND embedding IS NOT NULL "
                                             "ORDER BY embedding::vector(1024) <=> %s::vector LIMIT %s", [str(v), agente, str(v), K_RAG])
                    cerca = [f["texto"] for f in await cur.fetchall() if float(f["sim"]) >= SIMILITUD_RAG]
                    if cerca:
                        return cerca
                except Exception as e:      # noqa: BLE001 — sin embeddings se sigue por éxitos
                    log.debug("lecciones: sin búsqueda por significado para %s: %s", agente, type(e).__name__)
            cur = await conn.execute("SELECT texto FROM lecciones_agentes WHERE agente = %s AND estado = 'activa' ORDER BY exitos DESC, id LIMIT %s", [agente, K_RAG])
            return [f["texto"] for f in await cur.fetchall()]
    except Exception as e:      # noqa: BLE001 — nunca debe romper al agente
        log.debug("lecciones: no se han podido leer las de %s: %s", agente, type(e).__name__)
        return []


async def _anotar(conn, agente: str, patron: str, texto: str, exito: bool) -> str:
    """Una lección probada en un reintento: si funcionó se activa (con tope), si no cuenta un fallo y a los MAX_FALLOS se descarta. Devuelve el estado en que queda."""
    cur = await conn.execute("SELECT id, estado, exitos, fallos FROM lecciones_agentes WHERE agente = %s AND patron = %s", [agente, patron])
    f = await cur.fetchone()
    if f is None:
        try:
            from .llm import embeddings
            vec = [float(x) for x in (await embeddings([texto]))[0]]
        except Exception:      # noqa: BLE001 — sin embeddings la lección vale igual (se recupera por éxitos)
            vec = None
        await conn.execute("INSERT INTO lecciones_agentes (agente, patron, texto, estado, embedding) VALUES (%s,%s,%s,'prueba',%s::real[])", [agente, patron, texto, vec])
        cur = await conn.execute("SELECT id, estado, exitos, fallos FROM lecciones_agentes WHERE agente = %s AND patron = %s", [agente, patron])
        f = await cur.fetchone()
    if f["estado"] in ("revocada", "descartada"):                    # lo que Dirección quitó, o lo que ya falló, no vuelve solo
        return f["estado"]
    if exito:
        n = (await (await conn.execute("SELECT count(*) AS n FROM lecciones_agentes WHERE agente = %s AND estado = 'activa'", [agente])).fetchone())["n"]
        nuevo = "activa" if (f["estado"] == "activa" or n < MAX_ACTIVAS) else "prueba"
        await conn.execute("UPDATE lecciones_agentes SET exitos = exitos + 1, estado = %s, actualizada = now() WHERE id = %s", [nuevo, f["id"]])
        return nuevo
    nuevo = "descartada" if f["fallos"] + 1 >= MAX_FALLOS and f["estado"] != "activa" else f["estado"]
    await conn.execute("UPDATE lecciones_agentes SET fallos = fallos + 1, estado = %s, actualizada = now() WHERE id = %s", [nuevo, f["id"]])
    return nuevo


async def anotar_resultado(agente: str, lecciones: list[tuple[str, str]], exito: bool) -> list[str]:
    """Anota que esas lecciones (patron, texto) se probaron y el reintento salió bien o mal. Devuelve el estado en que queda cada una. No rompe nunca."""
    try:
        async with await _conectar() as conn:
            return [await _anotar(conn, agente, p, t, exito) for p, t in lecciones]
    except Exception as e:      # noqa: BLE001
        log.warning("lecciones: no se han podido anotar las de %s: %s: %s", agente, type(e).__name__, e)
        return []


async def listar(agente: str | None = None) -> list[dict]:
    async with await _conectar() as conn:
        cur = await conn.execute("SELECT id, agente, patron, texto, estado, exitos, fallos, creada, actualizada FROM lecciones_agentes "
                                 + ("WHERE agente = %s " if agente else "") + "ORDER BY agente, estado, id", [agente] if agente else [])
        return [dict(f) for f in await cur.fetchall()]


async def revocar(leccion_id: int) -> bool:
    """Dirección quita una lección: no vuelve a activarse sola."""
    async with await _conectar() as conn:
        cur = await conn.execute("UPDATE lecciones_agentes SET estado = 'revocada', actualizada = now() WHERE id = %s RETURNING id", [int(leccion_id)])
        return await cur.fetchone() is not None


def texto_de_reintento(lecciones: list[tuple[str, str]]) -> str:
    """Lo que se le dice al agente en el reintento. Pura."""
    return ("\n\nCORRECCIÓN DEL SISTEMA: en el intento anterior no conseguiste guardar el trabajo. Esto es lo que ha fallado y cómo corregirlo (síguelo al pie de la letra):\n"
            + "\n".join(f"- {t}" for _p, t in lecciones))
