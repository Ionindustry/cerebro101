"""La lectura de las propuestas de precios que esperan a Dirección (para «Hoy»), contra una base de datos de pruebas."""
import asyncio
import os
import re
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import _sin_servicios  # noqa: F401

try:
    import psycopg
    from psycopg.types.json import Jsonb

    from cerebro import listas_precios as LP
    from cerebro import precios_venta as V
except ImportError as e:      # pragma: no cover
    raise unittest.SkipTest(str(e))

URL = os.environ.get("CEREBRO_TEST_PG")
ESQUEMA = Path(__file__).resolve().parents[2] / "db" / "esquema.sql"


@unittest.skipUnless(URL, "sin CEREBRO_TEST_PG")
class TestPendientes(unittest.TestCase):
    def setUp(self):
        self.schema = f"t_phoy_{time.time_ns()}"
        t = ESQUEMA.read_text(encoding="utf-8")
        tabla = re.search(r"CREATE TABLE IF NOT EXISTS propuestas_venta \(.*?\n\);", t, re.S).group(0)
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"CREATE SCHEMA {self.schema}")
            c.execute(f"SET search_path = {self.schema}")
            c.execute(tabla)
        sep = "&" if "?" in URL else "?"
        self.p = mock.patch.object(LP, "ajustes", SimpleNamespace(database_url=f"{URL}{sep}options=-csearch_path%3D{self.schema}"))
        self.p.start()

    def tearDown(self):
        self.p.stop()
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"DROP SCHEMA {self.schema} CASCADE")

    def poner(self, estado):
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"SET search_path = {self.schema}")
            c.execute("INSERT INTO propuestas_venta (agente, departamento, estado, lista, lineas, resumen) VALUES ('a', 'operaciones', %s, 'Venta', %s, %s)",
                      [estado, Jsonb([]), Jsonb({"incluidos": 3})])

    def test_solo_las_pendientes_y_con_error_la_mas_nueva_primero(self):
        for e in ("aplicada", "propuesta", "descartada", "error", "aplicando"):
            self.poner(e)
        filas = asyncio.run(V.pendientes_de_revisar())
        self.assertEqual([f["estado"] for f in filas], ["error", "propuesta"])
        self.assertGreater(filas[0]["id"], filas[1]["id"])
        self.assertEqual(filas[0]["resumen"], {"incluidos": 3})

    def test_sin_propuestas(self):
        self.assertEqual(asyncio.run(V.pendientes_de_revisar()), [])


if __name__ == "__main__":
    unittest.main()
