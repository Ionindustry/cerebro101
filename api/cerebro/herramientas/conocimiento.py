"""Base de conocimiento: búsqueda semántica en PostgreSQL + pgvector (embeddings BGE-M3).

Cada documento tiene departamento y sensibilidad; un agente solo recupera documentos
de su departamento o comunes, y nunca de sensibilidad mayor que la suya.
"""
from __future__ import annotations

import psycopg

from ..ajustes import ajustes
from ..llm import embeddings
from ..registro import SENSIBILIDADES
from .base import Herramienta, registrar


async def buscar(consulta: str, departamento: str, sensibilidad: str = "media", k: int = 6) -> list[dict]:
    [vector] = await embeddings([consulta])
    permitidas = list(SENSIBILIDADES[: SENSIBILIDADES.index(sensibilidad) + 1])
    async with await psycopg.AsyncConnection.connect(ajustes.database_url) as conn:
        cur = await conn.execute(
            """SELECT titulo, fuente, texto, 1 - (embedding <=> %s::vector) AS similitud
                 FROM documentos
                WHERE (departamento = %s OR departamento = 'comun')
                  AND sensibilidad = ANY(%s)
             ORDER BY embedding <=> %s::vector
                LIMIT %s""",
            (str(vector), departamento, permitidas, str(vector), k),
        )
        filas = await cur.fetchall()
    return [{"titulo": t, "fuente": f, "texto": x, "similitud": round(s, 3)} for t, f, x, s in filas]


async def indexar(titulo: str, texto: str, fuente: str, departamento: str = "comun",
                  sensibilidad: str = "media", trozo: int = 1500) -> int:
    trozos = [texto[i:i + trozo] for i in range(0, len(texto), trozo)] or [""]
    vectores = await embeddings(trozos)
    async with await psycopg.AsyncConnection.connect(ajustes.database_url) as conn:
        for t, v in zip(trozos, vectores):
            await conn.execute(
                "INSERT INTO documentos (titulo, fuente, departamento, sensibilidad, texto, embedding) "
                "VALUES (%s, %s, %s, %s, %s, %s::vector)",
                (titulo, fuente, departamento, sensibilidad, t, str(v)),
            )
    return len(trozos)


registrar(Herramienta(
    nombre="conocimiento",
    descripcion="Busca en los documentos, procedimientos y actas de la empresa. Operación: buscar(consulta).",
    operaciones={"buscar": buscar, "indexar": indexar},
))
