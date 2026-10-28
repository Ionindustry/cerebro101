"""Almacenamiento del resumen de licitaciones en PostgreSQL real. Necesita CEREBRO_TEST_PG (dirección de una base de pruebas); sin ella se omite.
Cada prueba usa un esquema propio y lo borra."""
import asyncio
import os
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import _sin_servicios  # noqa: F401

try:
    import psycopg
    from cerebro.licitaciones import resumen
except ImportError as e:      # pragma: no cover
    raise unittest.SkipTest(str(e))

URL = os.environ.get("CEREBRO_TEST_PG")
ESQUEMA = Path(__file__).resolve().parents[2] / "db" / "esquema.sql"


def ejecutar(coro):
    return asyncio.run(coro)


def doc(estado="ok", n=1, aviso=None, hasta="2026-10-28T15:00:00+00:00"):
    return {"estado": estado, "aviso": aviso, "ventana": {"desde": "2026-10-27T15:00:00+00:00", "hasta": hasta},
            "totales": {"oportunidades": n}, "oportunidades": [{"id": str(i), "encaje": 50 + i} for i in range(n)]}


@unittest.skipUnless(URL and hasattr(psycopg, "AsyncConnection"), "sin CEREBRO_TEST_PG")
class TestAlmacen(unittest.TestCase):
    def setUp(self):
        self.schema = f"t_resumen_{time.time_ns()}"
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"CREATE SCHEMA {self.schema}")
            c.execute(f"SET search_path = {self.schema}")
            bloque = ESQUEMA.read_text(encoding="utf-8")
            c.execute(bloque[bloque.index("CREATE TABLE IF NOT EXISTS licitaciones_resumenes"):])
        sep = "&" if "?" in URL else "?"
        self.url = f"{URL}{sep}options=-csearch_path%3D{self.schema}"
        self.parche = mock.patch.object(resumen, "ajustes", SimpleNamespace(database_url=self.url, zona_horaria="Europe/Madrid"))
        self.parche.start()

    def tearDown(self):
        self.parche.stop()
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"DROP SCHEMA {self.schema} CASCADE")

    def test_el_de_las_16_se_sustituye_y_no_se_duplica(self):
        a = ejecutar(resumen.guardar(doc("sin_datos", 0, "el motor no responde"), "programada"))
        b = ejecutar(resumen.guardar(doc("ok", 3), "programada"))          # el reintento, mismo día
        self.assertEqual(a, b)
        filas = ejecutar(resumen.listar())
        self.assertEqual(len(filas), 1)
        self.assertEqual((filas[0]["estado"], filas[0]["totales"]["oportunidades"], filas[0]["aviso"]), ("ok", 3, False))

    def test_otro_dia_es_otra_fila_y_lo_manual_no_pisa_lo_programado(self):
        ejecutar(resumen.guardar(doc(hasta="2026-10-28T15:00:00+00:00"), "programada"))
        ejecutar(resumen.guardar(doc(hasta="2026-10-29T15:00:00+00:00"), "programada"))
        ejecutar(resumen.guardar(doc(hasta="2026-10-29T16:30:00+00:00"), "manual"))
        ejecutar(resumen.guardar(doc(hasta="2026-10-29T16:31:00+00:00"), "manual"))
        filas = ejecutar(resumen.listar())
        self.assertEqual([(f["fecha"], f["origen"]) for f in filas].count(("2026-10-29", "manual")), 2)
        self.assertEqual(len(filas), 4)
        self.assertEqual(filas[0]["fecha"], "2026-10-29")          # los más recientes primero

    def test_la_fecha_es_la_local_y_no_la_utc(self):
        # 23:30 UTC del 28 son las 00:30 del 29 en Madrid (CET): el resumen pertenece al 29
        ejecutar(resumen.guardar(doc(hasta="2026-10-28T23:30:00+00:00"), "manual"))
        self.assertEqual(ejecutar(resumen.listar())[0]["fecha"], "2026-10-29")

    def test_leer_el_ultimo_uno_concreto_y_uno_que_no_existe(self):
        a = ejecutar(resumen.guardar(doc(n=2, hasta="2026-10-27T15:00:00+00:00"), "programada"))
        b = ejecutar(resumen.guardar(doc(n=5, hasta="2026-10-28T15:00:00+00:00"), "programada"))
        self.assertEqual(ejecutar(resumen.leer())["id"], b)
        r = ejecutar(resumen.leer(a))
        self.assertEqual(r["contenido"]["totales"]["oportunidades"], 2)
        self.assertIsNone(ejecutar(resumen.leer(999999)))
        self.assertEqual(ejecutar(resumen.listar())[0]["mejor_encaje"], 54)

    def test_sin_resumenes_no_hay_ultimo(self):
        self.assertIsNone(ejecutar(resumen.leer()))
        self.assertEqual(ejecutar(resumen.listar()), [])

    def test_el_estado_solo_admite_los_valores_del_esquema(self):
        with self.assertRaises(psycopg.errors.CheckViolation):
            ejecutar(resumen.guardar(doc("raro"), "programada"))

    def test_un_manual_repetido_se_reutiliza_de_verdad(self):
        with mock.patch.object(resumen, "construir", mock.AsyncMock(return_value=doc("ok", 2))) as c:
            a = ejecutar(resumen.generar("manual"))
            b = ejecutar(resumen.generar("manual"))
        self.assertEqual((a["id"], b["id"], b.get("reutilizado")), (a["id"], a["id"], True))
        self.assertEqual(c.call_count, 1)
        self.assertEqual(len(ejecutar(resumen.listar())), 1)


if __name__ == "__main__":
    unittest.main()
