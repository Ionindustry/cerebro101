"""Estado de las copias de seguridad y aviso a soporte@ si pasan más de 3 días sin una correcta."""
import asyncio
import os
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import _sin_servicios  # noqa: F401

try:
    import psycopg
    from cerebro import copias as C
except ImportError as e:      # pragma: no cover
    raise unittest.SkipTest(str(e))

URL = os.environ.get("CEREBRO_TEST_PG")
ESQUEMA = Path(__file__).resolve().parents[2] / "db" / "esquema.sql"
AHORA = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)


def ejecutar(c):
    return asyncio.run(c)


class TestEvaluar(unittest.TestCase):
    def test_sin_vigilancia_no_se_alerta(self):
        self.assertFalse(C.evaluar(None, None, AHORA)["alerta"])

    def test_una_copia_reciente_no_alerta_y_una_vieja_si(self):
        self.assertFalse(C.evaluar(AHORA - timedelta(days=2), None, AHORA)["alerta"])
        r = C.evaluar(AHORA - timedelta(days=5), None, AHORA)
        self.assertTrue(r["alerta"])
        self.assertIn("Hace 5 días", r["motivo"])

    def test_sin_ninguna_copia_cuenta_desde_que_se_empezo_a_vigilar(self):
        self.assertFalse(C.evaluar(None, AHORA - timedelta(days=1), AHORA)["alerta"])
        r = C.evaluar(None, AHORA - timedelta(days=4), AHORA)
        self.assertTrue(r["alerta"])
        self.assertIn("No consta ninguna", r["motivo"])

    def test_la_ultima_correcta_manda_aunque_la_ultima_haya_fallado(self):
        self.assertFalse(C.evaluar(AHORA - timedelta(days=1), AHORA - timedelta(days=30), AHORA)["alerta"])


@unittest.skipUnless(URL and hasattr(psycopg, "AsyncConnection"), "sin CEREBRO_TEST_PG")
class TestEnBase(unittest.TestCase):
    def setUp(self):
        self.schema = f"t_cop_{time.time_ns()}"
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"CREATE SCHEMA {self.schema}")
            c.execute(f"SET search_path = {self.schema}")
            t = ESQUEMA.read_text(encoding="utf-8")
            c.execute(t[t.index("-- Copias de seguridad (api/cerebro/copias.py)"):t.index("-- Resumen diario de licitaciones")])
        sep = "&" if "?" in URL else "?"
        self.parche = mock.patch.object(C, "ajustes", SimpleNamespace(database_url=f"{URL}{sep}options=-csearch_path%3D{self.schema}"))
        self.parche.start()
        self.enviados = []

    def tearDown(self):
        self.parche.stop()
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"DROP SCHEMA {self.schema} CASCADE")

    def enviar(self, d, a, c, e):
        self.enviados.append((d, a, c))
        return len(d), 0

    def vigilar(self, ahora):
        from cerebro import avisar_soporte as S
        with mock.patch.object(S.vigilante, "_enviar_a", self.enviar), mock.patch.object(S.vigilante, "configuracion", lambda cfg=None: {"destinatarios": ["soporte@101.cat"]}):
            return ejecutar(C.vigilar(None, ahora))

    def test_el_estado_distingue_ultima_ultima_correcta_y_restauracion(self):
        ejecutar(C.registrar("copia", True, "/x/a", "bien", 5_000_000, AHORA - timedelta(days=2)))
        ejecutar(C.registrar("copia", False, "/x/b", "falló", None, AHORA - timedelta(hours=3)))
        ejecutar(C.registrar("restauracion", True, "/x/a", "Restauración probada", None, AHORA - timedelta(days=1)))
        e = ejecutar(C.estado(AHORA))
        self.assertFalse(e["ultima"]["ok"])
        self.assertTrue(e["ultima_correcta"]["ok"])
        self.assertEqual(e["ultima_correcta"]["bytes"], 5_000_000)
        self.assertTrue(e["restauracion"]["ok"])
        self.assertEqual((e["alerta"], e["dias_sin_copia"]), (False, 2.0))
        self.assertNotIn("carpeta", e["ultima"])                                    # sin rutas del servidor

    def test_sin_copias_primero_empieza_a_vigilar_y_despues_de_3_dias_avisa_una_vez_cada_24_horas(self):
        self.assertEqual(self.vigilar(AHORA)["estado"], "ok")                         # primera pasada: anota el inicio
        self.assertEqual(self.vigilar(AHORA + timedelta(days=2))["estado"], "ok")
        self.assertEqual(self.vigilar(AHORA + timedelta(days=4))["estado"], "avisado")
        self.assertEqual(len(self.enviados), 1)
        self.assertIn("No consta ninguna", self.enviados[0][2])
        self.assertEqual(self.vigilar(AHORA + timedelta(days=4, hours=6))["estado"], "ya_avisado")
        self.assertEqual(self.vigilar(AHORA + timedelta(days=5, hours=1))["estado"], "avisado")      # pasadas 24 h, recuerda
        self.assertEqual(len(self.enviados), 2)

    def test_una_copia_correcta_apaga_la_alerta(self):
        self.vigilar(AHORA)
        ejecutar(C.registrar("copia", True, "/x", "ok", 1, AHORA + timedelta(days=3, hours=20)))
        self.assertEqual(self.vigilar(AHORA + timedelta(days=4))["estado"], "ok")
        self.assertEqual(self.enviados, [])

    def test_conserva_solo_las_ultimas_filas_de_cada_tipo(self):
        for i in range(C.CONSERVAR + 5):
            ejecutar(C.registrar("copia", True, f"/x/{i}", "ok", i, AHORA + timedelta(minutes=i)))
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"SET search_path = {self.schema}")
            self.assertEqual(c.execute("SELECT count(*) FROM copias_registro").fetchone()[0], C.CONSERVAR)

    def test_la_tarjeta_de_jarvis_responde_a_cualquier_usuario_identificado(self):
        from cerebro.api import main
        from cerebro.api.main import Usuario, usuario_actual
        from fastapi.testclient import TestClient
        ejecutar(C.registrar("copia", True, "/x/a", "bien", 123, AHORA))
        main.app.dependency_overrides[usuario_actual] = lambda: Usuario("albert", {"usuario"}, set())
        try:
            r = TestClient(main.app).get("/salud/copias")
        finally:
            main.app.dependency_overrides.clear()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["ultima_correcta"]["bytes"], 123)

    def test_tipo_desconocido(self):
        with self.assertRaises(ValueError):
            ejecutar(C.registrar("otra", True))
        self.assertEqual(C.main([]), 2)


if __name__ == "__main__":
    unittest.main()
