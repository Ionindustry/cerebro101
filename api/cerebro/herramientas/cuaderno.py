"""Cuadernos de investigación: el equivalente local de NotebookLM.

Un agente reúne en un cuaderno las fuentes de una investigación (páginas web públicas y sus propias notas) y luego le hace
preguntas: la consulta devuelve los fragmentos más parecidos, numerados, para que la respuesta cite de dónde sale cada dato.
Todo vive en PostgreSQL + pgvector (embeddings BGE-M3, como la base de conocimiento): nada sale del servidor salvo la visita
a la página pública, que pasa por los mismos controles que la herramienta «web».

Cada cuaderno es de un departamento: un agente solo ve los cuadernos del suyo (el departamento lo pone el sistema).
"""
from __future__ import annotations

import uuid

import psycopg

from ..ajustes import ajustes
from ..llm import embeddings
from . import web
from .base import Herramienta, registrar

TROZO = 1500             # caracteres por fragmento (como la base de conocimiento)
SOLAPE = 200             # lo que repite cada fragmento del anterior, para no partir una frase importante en dos
MAX_TEXTO = 20_000       # caracteres que se guardan de cada fuente
MAX_FUENTES = 100        # fuentes por cuaderno


def trocear(texto: str, trozo: int = TROZO, solape: int = SOLAPE) -> list[str]:
    texto = texto.strip()
    if not texto:
        return []
    paso = max(1, trozo - solape)
    # el último trozo que solo repetiría el solape del anterior no aporta nada
    return [texto[i:i + trozo] for i in range(0, len(texto), paso) if i == 0 or i + solape < len(texto)]


def citas(filas: list[tuple]) -> list[dict]:
    """(titulo, url, texto, similitud) → fragmentos numerados [1], [2]… para citar en la respuesta."""
    return [{"cita": n, "titulo": t, "url": u, "texto": x, "similitud": round(s, 3)}
            for n, (t, u, x, s) in enumerate(filas, start=1)]


def _conectar():
    return psycopg.AsyncConnection.connect(ajustes.database_url)


async def _resolver(conn, cuaderno: str, departamento: str) -> tuple[str, str]:
    """El cuaderno por su id o por su título (sin distinguir mayúsculas), siempre dentro del departamento."""
    try:
        cur = await conn.execute("SELECT id, titulo FROM cuadernos WHERE id = %s AND departamento = %s",
                                 (str(uuid.UUID(cuaderno)), departamento))
    except ValueError:
        cur = await conn.execute("SELECT id, titulo FROM cuadernos WHERE lower(titulo) = lower(%s) AND departamento = %s",
                                 (cuaderno.strip(), departamento))
    fila = await cur.fetchone()
    if fila is None:
        cur = await conn.execute("SELECT titulo FROM cuadernos WHERE departamento = %s ORDER BY actualizado DESC LIMIT 20",
                                 (departamento,))
        hay = [t for (t,) in await cur.fetchall()]
        raise LookupError(f"No existe el cuaderno «{cuaderno}». Cuadernos del departamento: {', '.join(hay) or 'ninguno (créalo con «crear»)'}")
    return str(fila[0]), fila[1]


async def _asegurar(conn, cuaderno: str, departamento: str) -> tuple[str, str]:
    """Como `_resolver`, pero si se nombra por título y no existe, lo crea: así guardar la primera fuente no gasta un paso del agente."""
    try:
        uuid.UUID(cuaderno)
        return await _resolver(conn, cuaderno, departamento)
    except ValueError:
        pass
    titulo = cuaderno.strip()[:200]
    if not titulo:
        raise ValueError("Indica el cuaderno (su título o su id)")
    cur = await conn.execute(
        """INSERT INTO cuadernos (titulo, departamento) VALUES (%s, %s)
           ON CONFLICT (departamento, lower(titulo)) DO UPDATE SET actualizado = now() RETURNING id, titulo""",
        (titulo, departamento))
    cid, nombre = await cur.fetchone()
    return str(cid), nombre


async def _guardar(cuaderno: str, departamento: str, tipo: str, titulo: str, url: str, texto: str) -> dict:
    texto = texto.strip()[:MAX_TEXTO]
    trozos = trocear(texto)
    if not trozos:
        raise ValueError("La fuente no tiene texto")
    vectores = await embeddings(trozos)
    async with await _conectar() as conn:
        async with conn.transaction():
            cid, nombre = await _asegurar(conn, cuaderno, departamento)
            cur = await conn.execute("SELECT count(*) FROM cuaderno_fuentes WHERE cuaderno = %s", (cid,))
            if (await cur.fetchone())[0] >= MAX_FUENTES:
                raise ValueError(f"El cuaderno «{nombre}» ya tiene {MAX_FUENTES} fuentes: crea otro para seguir")
            if url:
                cur = await conn.execute("SELECT id FROM cuaderno_fuentes WHERE cuaderno = %s AND url = %s", (cid, url))
                if await cur.fetchone():
                    return {"cuaderno": nombre, "fuente": titulo, "estado": "ya estaba en el cuaderno"}
            cur = await conn.execute(
                "INSERT INTO cuaderno_fuentes (cuaderno, tipo, titulo, url, texto) VALUES (%s, %s, %s, %s, %s) RETURNING id",
                (cid, tipo, titulo[:300], url, texto))
            (fid,) = await cur.fetchone()
            for orden, (t, v) in enumerate(zip(trozos, vectores)):
                await conn.execute(
                    "INSERT INTO cuaderno_trozos (fuente, cuaderno, orden, texto, embedding) VALUES (%s, %s, %s, %s, %s::vector)",
                    (fid, cid, orden, t, str(v)))
            await conn.execute("UPDATE cuadernos SET actualizado = now() WHERE id = %s", (cid,))
    return {"cuaderno": nombre, "fuente": titulo, "fragmentos": len(trozos), "estado": "guardada"}


async def crear(titulo: str, departamento: str, descripcion: str = "") -> dict:
    titulo = titulo.strip()[:200]
    if not titulo:
        raise ValueError("El cuaderno necesita un título")
    async with await _conectar() as conn:
        cur = await conn.execute(
            """INSERT INTO cuadernos (titulo, descripcion, departamento) VALUES (%s, %s, %s)
               ON CONFLICT (departamento, lower(titulo)) DO UPDATE SET actualizado = now()
               RETURNING id, (xmax = 0) AS nuevo""",
            (titulo, descripcion.strip()[:1000], departamento))
        cid, nuevo = await cur.fetchone()
    return {"id": str(cid), "titulo": titulo, "estado": "creado" if nuevo else "ya existía"}


async def listar(departamento: str) -> list[dict]:
    async with await _conectar() as conn:
        cur = await conn.execute(
            """SELECT c.id, c.titulo, c.descripcion, count(f.id), c.actualizado
                 FROM cuadernos c LEFT JOIN cuaderno_fuentes f ON f.cuaderno = c.id
                WHERE c.departamento = %s GROUP BY c.id ORDER BY c.actualizado DESC LIMIT 50""",
            (departamento,))
        filas = await cur.fetchall()
    return [{"id": str(i), "titulo": t, "descripcion": d, "fuentes": n, "actualizado": a.isoformat()} for i, t, d, n, a in filas]


async def fuentes(cuaderno: str, departamento: str) -> dict:
    async with await _conectar() as conn:
        cid, nombre = await _resolver(conn, cuaderno, departamento)
        cur = await conn.execute(
            "SELECT tipo, titulo, url, length(texto), creado FROM cuaderno_fuentes WHERE cuaderno = %s ORDER BY creado", (cid,))
        filas = await cur.fetchall()
    return {"cuaderno": nombre, "fuentes": [{"tipo": t, "titulo": ti, "url": u, "caracteres": n, "fecha": c.isoformat()}
                                            for t, ti, u, n, c in filas]}


def _solo_baja(sensibilidad: str) -> None:
    # Traer páginas de internet es la misma salida al exterior que la herramienta «web»: solo para agentes de sensibilidad baja
    if sensibilidad != "baja":
        raise PermissionError("Solo los agentes de sensibilidad baja pueden traer páginas de internet a un cuaderno; "
                              "usa «guardar_nota» con lo que ya tengas")


async def guardar_web(cuaderno: str, url: str, departamento: str, sensibilidad: str = "baja") -> dict:
    _solo_baja(sensibilidad)
    pagina = await web.leer(url, max_caracteres=MAX_TEXTO)
    return await _guardar(cuaderno, departamento, "web", pagina["titulo"] or pagina["url"], pagina["url"], pagina["texto"])


async def investigar(cuaderno: str, tema: str, departamento: str, sensibilidad: str = "baja", tipo: str = "general",
                     periodo: str = "", max_fuentes: int = 4) -> dict:
    """Busca el tema en internet y guarda en el cuaderno las primeras páginas que se pueden leer, todo en un paso."""
    _solo_baja(sensibilidad)
    max_fuentes = max(1, min(int(max_fuentes), 8))
    if periodo and web.periodo_de(periodo) is None:      # el periodo es un filtro de comodidad: si no se entiende, se busca sin él
        periodo = ""
    encontrados = await web.buscar(tema, tipo=tipo, periodo=periodo, max_resultados=max_fuentes * 2)
    guardadas, descartadas = [], []
    for r in encontrados["resultados"]:
        if len(guardadas) >= max_fuentes:
            break
        try:
            g = await guardar_web(cuaderno, r["url"], departamento, sensibilidad)
            guardadas.append({"titulo": g["fuente"], "url": r["url"], "estado": g["estado"]})
        except Exception as e:  # noqa: BLE001 — una página que no se deja leer (robots, PDF, error) no para la investigación
            descartadas.append({"url": r["url"], "motivo": str(e)[:150]})
    return {"cuaderno": cuaderno, "guardadas": guardadas, "descartadas": descartadas,
            "siguiente": "pregunta al cuaderno con «consultar» para responder citando las fuentes" if guardadas
                         else "no se ha podido guardar ninguna página: prueba con otro tema o con «guardar_web»"}


async def guardar_nota(cuaderno: str, titulo: str, texto: str, departamento: str, fuente: str = "") -> dict:
    return await _guardar(cuaderno, departamento, "nota", titulo, fuente.strip()[:500], texto)


async def consultar(cuaderno: str, pregunta: str, departamento: str, k: int = 6) -> dict:
    [vector] = await embeddings([pregunta])
    async with await _conectar() as conn:
        cid, nombre = await _resolver(conn, cuaderno, departamento)
        cur = await conn.execute(
            """SELECT f.titulo, f.url, t.texto, 1 - (t.embedding <=> %s::vector)
                 FROM cuaderno_trozos t JOIN cuaderno_fuentes f ON f.id = t.fuente
                WHERE t.cuaderno = %s
             ORDER BY t.embedding <=> %s::vector LIMIT %s""",
            (str(vector), cid, str(vector), max(1, min(int(k), 12))))
        filas = await cur.fetchall()
    if not filas:
        return {"cuaderno": nombre, "fragmentos": [], "aviso": "El cuaderno no tiene fuentes todavía"}
    return {"cuaderno": nombre, "fragmentos": citas(filas),
            "aviso": "Responde solo con lo que digan estos fragmentos y cita cada dato con su número, p. ej. [2]. "
                     "Al final, lista las fuentes citadas con su título y su enlace. Si no está en los fragmentos, dilo."}


registrar(Herramienta(
    nombre="cuaderno",
    descripcion="Cuadernos de investigación (como NotebookLM): reúne fuentes de un tema (páginas web y notas) y pregunta sobre "
                "ellas con citas. Úsalo para investigaciones que se consultan más de una vez.",
    operaciones={"investigar": investigar, "consultar": consultar, "crear": crear, "listar": listar, "fuentes": fuentes,
                 "guardar_web": guardar_web, "guardar_nota": guardar_nota},
    ayuda={"investigar": "busca un tema en internet y guarda las mejores páginas en el cuaderno (lo crea si no existe), todo en un paso; "
                         "después usa «consultar»",
           "crear": "crea un cuaderno con un título (si ya existe, devuelve el mismo); guardar una fuente ya lo crea solo",
           "listar": "los cuadernos de tu departamento y cuántas fuentes tiene cada uno",
           "fuentes": "las fuentes guardadas en un cuaderno (cuaderno: su título o su id)",
           "guardar_web": "lee una página web pública y la guarda como fuente del cuaderno",
           "guardar_nota": "guarda como fuente un texto tuyo (resumen, conclusiones, datos de otra herramienta), con su procedencia en «fuente»",
           "consultar": "busca en las fuentes del cuaderno los fragmentos que responden a la pregunta, numerados para citarlos"},
    ejemplos={"investigar": {"cuaderno": "Competidores CCTV Barcelona", "tema": "empresas instaladoras de CCTV en Barcelona"},
              "consultar": {"cuaderno": "Competidores CCTV Barcelona", "pregunta": "¿Qué precios de mantenimiento publican?"},
              "guardar_web": {"cuaderno": "Competidores CCTV Barcelona", "url": "https://www.ejemplo.com/servicios"}},
))
