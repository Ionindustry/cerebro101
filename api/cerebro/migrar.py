"""Prepara la base de datos con el propietario: esquema, tablas del grafo, rol de la aplicación y permisos.

Lo ejecuta el servicio de un solo uso «migraciones» en cada arranque (es idempotente). La API, el worker y
beat no conocen la contraseña del propietario: se conectan con `cerebro_app` (ver db/roles.sql).

Variables: DATABASE_URL_ADMIN (propietario), CEREBRO_APP_PASSWORD, CEREBRO_DB_DIR (por defecto /app/db).
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

import psycopg
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import sql

log = logging.getLogger("cerebro.migrar")
ROL_APP = "cerebro_app"


async def migrar(url_admin: str, clave_app: str, carpeta: Path) -> None:
    if not clave_app or clave_app == "cambia-esto":
        raise SystemExit("Falta CEREBRO_APP_PASSWORD (o sigue siendo «cambia-esto»)")
    log.info("Aplicando el esquema")
    async with await psycopg.AsyncConnection.connect(url_admin, autocommit=True) as conn:
        await conn.execute((carpeta / "esquema.sql").read_text(encoding="utf-8"))
    log.info("Tablas del grafo (checkpointer)")
    async with AsyncPostgresSaver.from_conn_string(url_admin) as checkpointer:
        await checkpointer.setup()
    log.info("Rol %s y permisos", ROL_APP)
    async with await psycopg.AsyncConnection.connect(url_admin, autocommit=True) as conn:
        await conn.execute((carpeta / "roles.sql").read_text(encoding="utf-8"))
        await conn.execute(sql.SQL("ALTER ROLE {} WITH PASSWORD {}").format(sql.Identifier(ROL_APP), sql.Literal(clave_app)))
    log.info("Migraciones terminadas")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    url = os.environ.get("DATABASE_URL_ADMIN")
    if not url:
        raise SystemExit("Falta DATABASE_URL_ADMIN")
    asyncio.run(migrar(url, os.environ.get("CEREBRO_APP_PASSWORD", ""), Path(os.environ.get("CEREBRO_DB_DIR", "/app/db"))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
