"""Comprueba que el rol de la aplicación tiene los permisos mínimos (ISO 27001) y nada más.

Se ejecuta con el mismo usuario que la API (DATABASE_URL):
    docker compose exec api python /app/scripts/comprobar_permisos.py
Todas las pruebas se deshacen (ROLLBACK): no deja datos. Termina con código 1 si algo no es como debe.
"""
from __future__ import annotations

import os
import sys

import psycopg
from psycopg import errors

CERO = "[" + ",".join(["0"] * 1024) + "]"

# (descripción, SQL, debe_funcionar)
PRUEBAS = [
    ("leer aprobaciones", "SELECT count(*) FROM aprobaciones", True),
    ("leer registro_acciones", "SELECT count(*) FROM registro_acciones", True),
    ("anexar a registro_acciones",
     "INSERT INTO registro_acciones (agente, herramienta, operacion, resultado) VALUES ('comprobacion','x','y','OK')", True),
    ("crear una aprobación",
     "INSERT INTO aprobaciones (id, hilo, agente, departamento, accion, nivel, aprobadores, datos) "
     "VALUES (gen_random_uuid(), 'h', 'a', 'd', 'x', 'simple', '{r}', '{}')", True),
    ("actualizar una aprobación", "UPDATE aprobaciones SET actualizado = now() WHERE false", True),
    ("escribir y borrar conocimiento",
     f"WITH n AS (INSERT INTO documentos (titulo, fuente, texto, embedding) VALUES ('t','f','x','{CERO}') RETURNING id) "
     "DELETE FROM documentos WHERE id IN (SELECT id FROM n)", True),
    ("estado del grafo (checkpoints)", "DELETE FROM checkpoints WHERE false", True),
    # --- lo que no debe poder hacer ---
    ("modificar registro_acciones", "UPDATE registro_acciones SET resultado = 'x'", False),
    ("borrar de registro_acciones", "DELETE FROM registro_acciones", False),
    ("vaciar registro_acciones", "TRUNCATE registro_acciones", False),
    ("borrar aprobaciones", "DELETE FROM aprobaciones", False),
    ("vaciar aprobaciones", "TRUNCATE aprobaciones", False),
    ("quitar el disparador del registro", "DROP TRIGGER registro_acciones_solo_anexar ON registro_acciones", False),
    ("desactivar disparadores", "ALTER TABLE registro_acciones DISABLE TRIGGER ALL", False),
    ("borrar una tabla", "DROP TABLE registro_acciones", False),
    ("crear tablas", "CREATE TABLE intruso (x int)", False),
    ("alterar el esquema", "ALTER TABLE aprobaciones ADD COLUMN extra text", False),
    ("crear roles", "CREATE ROLE intruso LOGIN", False),
    ("cambiar de rol a otro con más permisos", "SET ROLE cerebro", False),
]


def main() -> int:
    url = os.environ["DATABASE_URL"]
    fallos = 0
    with psycopg.connect(url) as conn:
        usuario = conn.execute("SELECT current_user, (SELECT rolsuper FROM pg_roles WHERE rolname = current_user)").fetchone()
        print(f"Conectado como {usuario[0]} (superusuario: {usuario[1]})")
        if usuario[1]:
            print("FALLO: la aplicación no debe conectarse como superusuario")
            return 1
        for descripcion, consulta, debe in PRUEBAS:
            try:
                conn.execute(consulta)
                resultado = "puede"
            except errors.InsufficientPrivilege:
                resultado = "denegado"
            except errors.Error as e:      # p. ej. un disparador que lo impide: también cuenta como bloqueado
                resultado = f"bloqueado ({type(e).__name__})"
            finally:
                conn.rollback()
            ok = (resultado == "puede") == debe
            fallos += not ok
            print(f"  {'✓' if ok else '✗'} {descripcion}: {resultado}" + ("" if ok else "  <-- NO ES LO ESPERADO"))
    print("Permisos correctos." if not fallos else f"{fallos} comprobaciones fallidas.")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
