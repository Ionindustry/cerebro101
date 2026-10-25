"""Objetivos permanentes: una firma de Dirección que cubre varias peticiones, en vez de firmar cada una.

Un objetivo dice qué se autoriza (operaciones concretas, en qué departamentos y, si se quiere, qué agentes), cuánto (tope de acciones) y hasta cuándo
(caducidad obligatoria). Reglas que aplica el código:
- Solo cubre operaciones **supervisadas**. Las reservadas (compromisos económicos o legales) siempre se firman una a una; las estándar no necesitan firma.
- Caduca siempre (máximo MAX_DIAS) y tiene tope de acciones (máximo MAX_ACCIONES). Se consume de forma atómica: dos peticiones a la vez no pueden pasarse del tope.
- Se puede revocar al instante. Las acciones cubiertas dejan constancia en el registro de acciones con el identificador del objetivo.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import psycopg
from psycopg.rows import dict_row

from ..ajustes import ajustes
from ..herramientas import base as H
from ..politicas import AccionProhibida, clase_de
from ..registro import Registro

MAX_DIAS = 30
MAX_ACCIONES = 500


class ObjetivoNoValido(ValueError):
    pass


def validar_nuevo(titulo: str, departamentos: list[str], agentes: list[str], operaciones: list[str], max_acciones: int, dias: float,
                  reg: Registro, ahora: datetime | None = None) -> dict:
    """Comprueba y normaliza un objetivo nuevo. Lanza ObjetivoNoValido con el motivo en castellano."""
    titulo = " ".join((titulo or "").split())
    if len(titulo) < 5:
        raise ObjetivoNoValido("Pon un título que explique el objetivo (mínimo 5 caracteres)")
    deps = sorted({d.strip() for d in departamentos or [] if d.strip()})
    if not deps:
        raise ObjetivoNoValido("Indica al menos un departamento")
    for d in deps:
        if d not in reg.departamentos:
            raise ObjetivoNoValido(f"El departamento «{d}» no existe")
    ags = sorted({a.strip() for a in agentes or [] if a.strip()})
    for a in ags:
        if a not in reg.fichas or reg.fichas[a].departamento not in deps:
            raise ObjetivoNoValido(f"El agente «{a}» no existe o no es de esos departamentos")
    ops = sorted({o.strip() for o in operaciones or [] if o.strip()})
    if not ops:
        raise ObjetivoNoValido("Indica al menos una operación (por ejemplo correo.enviar)")
    for o in ops:
        herramienta, _, operacion = o.partition(".")
        if not operacion or herramienta not in H._REGISTRO or operacion not in H._REGISTRO[herramienta].operaciones:
            raise ObjetivoNoValido(f"La operación «{o}» no existe")
        try:
            clase = clase_de(o, herramienta, operacion, H.es_externa(herramienta, operacion))
        except AccionProhibida as e:
            raise ObjetivoNoValido(str(e)) from e
        if clase == "reservada":
            raise ObjetivoNoValido(f"«{o}» es una operación reservada: se firma siempre una a una, no se puede cubrir con un objetivo")
        if clase == "estandar":
            raise ObjetivoNoValido(f"«{o}» es estándar: ya se ejecuta sin firma, no necesita objetivo")
    if not 1 <= int(max_acciones) <= MAX_ACCIONES:
        raise ObjetivoNoValido(f"El tope de acciones debe estar entre 1 y {MAX_ACCIONES}")
    if not 0 < float(dias) <= MAX_DIAS:
        raise ObjetivoNoValido(f"La validez debe ser de más de 0 y hasta {MAX_DIAS} días")
    ahora = ahora or datetime.now(timezone.utc)
    return {"titulo": titulo[:200], "departamentos": deps, "agentes": ags, "operaciones": ops,
            "max_acciones": int(max_acciones), "caduca": ahora + timedelta(days=float(dias))}


def operaciones_cubribles() -> list[str]:
    """Operaciones supervisadas que un objetivo puede cubrir (para el selector del panel)."""
    sal = []
    for h in H._REGISTRO.values():
        for op in h.operaciones:
            try:
                if clase_de(f"{h.nombre}.{op}", h.nombre, op, H.es_externa(h.nombre, op)) == "supervisada":
                    sal.append(f"{h.nombre}.{op}")
            except AccionProhibida:
                pass
    return sorted(sal)


async def crear(datos: dict, usuario: str) -> str:
    oid = str(uuid.uuid4())
    async with await psycopg.AsyncConnection.connect(ajustes.database_url) as conn:
        await conn.execute(
            """INSERT INTO objetivos (id, titulo, departamentos, agentes, operaciones, max_acciones, caduca, creado_por)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (oid, datos["titulo"], datos["departamentos"], datos["agentes"], datos["operaciones"], datos["max_acciones"], datos["caduca"], usuario))
    return oid


async def listar(solo_vigentes: bool = False) -> list[dict]:
    donde = "WHERE estado='activo' AND caduca > now() AND usadas < max_acciones" if solo_vigentes else ""
    async with await psycopg.AsyncConnection.connect(ajustes.database_url, row_factory=dict_row) as conn:
        cur = await conn.execute(f"SELECT * FROM objetivos {donde} ORDER BY creado DESC LIMIT 200")
        filas = await cur.fetchall()
    ahora = datetime.now(timezone.utc)
    for f in filas:
        f["id"] = str(f["id"])
        f["vigente"] = f["estado"] == "activo" and f["caduca"] > ahora and f["usadas"] < f["max_acciones"]
    return filas


async def revocar(oid: str, usuario: str) -> bool:
    async with await psycopg.AsyncConnection.connect(ajustes.database_url) as conn:
        cur = await conn.execute(
            "UPDATE objetivos SET estado='revocado', revocado_por=%s, revocado=now() WHERE id=%s AND estado='activo'", (usuario, oid))
        return cur.rowcount > 0


async def consumir(departamento: str, agente: str, herramienta: str, operacion: str) -> str | None:
    """Si un objetivo vigente cubre esta acción, gasta una de sus acciones y devuelve su id; si no, None. Atómico."""
    async with await psycopg.AsyncConnection.connect(ajustes.database_url) as conn:
        cur = await conn.execute(
            """UPDATE objetivos SET usadas = usadas + 1
               WHERE id = (SELECT id FROM objetivos
                           WHERE estado='activo' AND caduca > now() AND usadas < max_acciones
                             AND %s = ANY(departamentos) AND (cardinality(agentes)=0 OR %s = ANY(agentes)) AND %s = ANY(operaciones)
                           ORDER BY caduca LIMIT 1 FOR UPDATE SKIP LOCKED)
               RETURNING id""",
            (departamento, agente, f"{herramienta}.{operacion}"))
        fila = await cur.fetchone()
    return str(fila[0]) if fila else None
