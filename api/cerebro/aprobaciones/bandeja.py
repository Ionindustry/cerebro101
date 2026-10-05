"""Persistencia de la bandeja de aprobaciones en PostgreSQL."""
from __future__ import annotations

import json
import uuid

import psycopg
from psycopg.rows import dict_row

from ..ajustes import ajustes
from .logica import Solicitud, decidir


def _a_solicitud(fila: dict) -> Solicitud:
    return Solicitud(id=str(fila["id"]), agente=fila["agente"], departamento=fila["departamento"],
                     accion=fila["accion"], nivel=fila["nivel"], aprobadores=tuple(fila["aprobadores"]),
                     voz_permitida=fila["voz_permitida"], datos=fila["datos"],
                     decisiones=fila["decisiones"], estado=fila["estado"])


async def crear(hilo: str, agente: str, departamento: str, accion: str, nivel: str,
                aprobadores: tuple[str, ...], voz_permitida: bool, datos: dict) -> str:
    sid = str(uuid.uuid4())
    async with await psycopg.AsyncConnection.connect(ajustes.database_url) as conn:
        await conn.execute(
            """INSERT INTO aprobaciones (id, hilo, agente, departamento, accion, nivel, aprobadores,
                                         voz_permitida, datos, decisiones, estado)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'[]','pendiente')""",
            (sid, hilo, agente, departamento, accion, nivel, list(aprobadores), voz_permitida, json.dumps(datos)))
    return sid


async def pendientes(departamentos: set[str] | None = None) -> list[dict]:
    async with await psycopg.AsyncConnection.connect(ajustes.database_url, row_factory=dict_row) as conn:
        cur = await conn.execute("SELECT * FROM aprobaciones WHERE estado='pendiente' ORDER BY creado")
        filas = await cur.fetchall()
    return [f for f in filas if not departamentos or f["departamento"] in departamentos]


async def registrar_decision(sid: str, usuario: str, roles: set[str], departamentos: set[str],
                             aprobado: bool, canal: str, comentario: str = "") -> tuple[Solicitud, str]:
    async with await psycopg.AsyncConnection.connect(ajustes.database_url, row_factory=dict_row) as conn:
        async with conn.transaction():
            cur = await conn.execute("SELECT * FROM aprobaciones WHERE id=%s FOR UPDATE", (sid,))
            fila = await cur.fetchone()
            if fila is None:
                raise LookupError("Solicitud no encontrada")
            s = decidir(_a_solicitud(fila), usuario, roles, departamentos, aprobado, canal, comentario)
            await conn.execute("UPDATE aprobaciones SET decisiones=%s, estado=%s, actualizado=now() WHERE id=%s",
                               (json.dumps(s.decisiones), s.estado, sid))
    return s, fila["hilo"]


async def estados_del_hilo(hilo: str) -> dict[str, str]:
    """Estado de todas las solicitudes de una conversación: {id: estado}."""
    async with await psycopg.AsyncConnection.connect(ajustes.database_url) as conn:
        cur = await conn.execute("SELECT id, estado FROM aprobaciones WHERE hilo=%s", (hilo,))
        return {str(i): e for i, e in await cur.fetchall()}


async def registrar_accion(hilo: str | None, agente: str, herramienta: str, operacion: str,
                           aprobacion: str | None, resultado: str) -> None:
    """Deja constancia de una acción ejecutada (evidencia ENS / ISO 27001). La tabla es de solo anexado."""
    async with await psycopg.AsyncConnection.connect(ajustes.database_url) as conn:
        await conn.execute(
            """INSERT INTO registro_acciones (hilo, agente, herramienta, operacion, aprobacion, resultado)
               VALUES (%s,%s,%s,%s,%s,%s)""",
            (hilo, agente, herramienta, operacion, aprobacion, resultado[:4000]))
