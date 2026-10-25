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


async def historial(departamentos: set[str] | None = None, decision: str | None = None, texto: str | None = None,
                    limite: int = 30, pagina: int = 0) -> dict:
    """Solicitudes ya resueltas (aprobadas o rechazadas), de la más reciente a la más antigua, con lo que se ejecutó al aprobarlas.
    `departamentos` None = todas (dirección). `decision`: «aprobada» | «rechazada» | None. `texto` busca en la acción, el resumen y el agente."""
    cond, params = ["a.estado IN ('aprobada','rechazada')"], []
    if departamentos is not None:
        cond.append("a.departamento = ANY(%s)")
        params.append(sorted(departamentos))
    if decision in ("aprobada", "rechazada"):
        cond.append("a.estado = %s")
        params.append(decision)
    if texto and texto.strip():
        cond.append("(a.accion ILIKE %s OR a.agente ILIKE %s OR a.datos->>'resumen' ILIKE %s)")
        params += [f"%{texto.strip()[:80]}%"] * 3
    donde = " AND ".join(cond)
    limite = max(1, min(int(limite), 100))
    async with await psycopg.AsyncConnection.connect(ajustes.database_url, row_factory=dict_row) as conn:
        total = (await (await conn.execute(f"SELECT count(*) AS n FROM aprobaciones a WHERE {donde}", params)).fetchone())["n"]
        cur = await conn.execute(
            f"""SELECT a.*, (SELECT r.resultado FROM registro_acciones r WHERE r.aprobacion = a.id ORDER BY r.id DESC LIMIT 1) AS resultado
                FROM aprobaciones a WHERE {donde} ORDER BY a.actualizado DESC LIMIT %s OFFSET %s""",
            params + [limite, max(0, int(pagina)) * limite])
        filas = await cur.fetchall()
    return {"total": total, "pagina": max(0, int(pagina)), "limite": limite, "items": filas}


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
