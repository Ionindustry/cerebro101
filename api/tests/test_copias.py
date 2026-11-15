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


class TestValidar(unittest.TestCase):
    def test_valores_buenos(self):
        r = C.validar({"conservar": "10", "conservar_extra": 30, "dias_aviso": "2", "extra": " /mnt/d/Copias101/ "})
        self.assertEqual(r, {"conservar": 10, "conservar_extra": 30, "dias_aviso": 2, "extra": "/mnt/d/Copias101"})
        self.assertEqual(C.validar({"extra": ""}), {"extra": ""})
        self.assertEqual(C.validar({"conservar_extra": 0}), {"conservar_extra": 0})
        self.assertEqual(C.validar({"extra": "/media/pc/USB/Cerebro"})["extra"], "/media/pc/USB/Cerebro")

    def test_numeros_fuera_de_rango_o_raros(self):
        for dato in ({"conservar": 0}, {"conservar": 61}, {"conservar": "x"}, {"conservar": 2.5}, {"conservar": True}, {"conservar_extra": -1}, {"conservar_extra": 366}, {"dias_aviso": 0}, {"dias_aviso": 15}):
            with self.assertRaises(ValueError, msg=str(dato)):
                C.validar(dato)

    def test_rutas_peligrosas_o_con_mala_forma(self):
        for ruta in ("/", "/etc", "/etc/cron.d", "/mnt/d", "/mnt/d/", "/mnt/dd/x", "relativa/x", "/mnt/d/../etc", "/mnt/d/a b", "/mnt/d/a;rm", "/mnt/d/$(x)", "/mnt/d/a\nb", "/home/pc", "/mnt/d/./x", "/tmp/x"):
            with self.assertRaises(ValueError, msg=ruta):
                C.validar({"extra": ruta})

    def test_claves_desconocidas_y_formato(self):
        with self.assertRaisesRegex(ValueError, "desconocido"):
            C.validar({"conservar": 3, "comando": "rm -rf /"})
        with self.assertRaises(ValueError):
            C.validar([])
        self.assertEqual(C.validar({}), {})


@unittest.skipUnless(URL, "sin CEREBRO_TEST_PG")
class TestAjustesEnBase(unittest.TestCase):
    def setUp(self):
        import re
        self.schema = f"t_copaj_{time.time_ns()}"
        t = ESQUEMA.read_text(encoding="utf-8")
        tabla = re.search(r"CREATE TABLE IF NOT EXISTS copias_ajustes \(.*?\n\);", t, re.S).group(0)
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"CREATE SCHEMA {self.schema}")
            c.execute(f"SET search_path = {self.schema}")
            c.execute(t[t.index("-- Copias de seguridad (api/cerebro/copias.py)"):t.index("-- Resumen diario de licitaciones")])
            c.execute(tabla)
        sep = "&" if "?" in URL else "?"
        self.parche = mock.patch.object(C, "ajustes", SimpleNamespace(database_url=f"{URL}{sep}options=-csearch_path%3D{self.schema}"))
        self.parche.start()

    def tearDown(self):
        self.parche.stop()
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"DROP SCHEMA {self.schema} CASCADE")

    def test_sin_nada_fijado_valen_los_de_siempre(self):
        r = ejecutar(C.en_vigor())
        self.assertEqual(r["valores"], C.DEFECTOS)
        self.assertEqual(r["fijados"], {})

    def test_guardar_actualiza_solo_lo_enviado_y_anota_quien(self):
        ejecutar(C.guardar({"conservar": 14, "extra": "/mnt/d/Copias101"}, "albert"))
        r = ejecutar(C.guardar({"conservar": 20}, "ana"))
        self.assertEqual((r["valores"]["conservar"], r["valores"]["extra"], r["valores"]["dias_aviso"]), (20, "/mnt/d/Copias101", 3))
        self.assertEqual((r["fijados"]["conservar"]["por"], r["fijados"]["extra"]["por"]), ("ana", "albert"))
        with self.assertRaises(ValueError):
            ejecutar(C.guardar({}, "albert"))
        with self.assertRaises(ValueError):
            ejecutar(C.guardar({"extra": "/etc"}, "albert"))
        self.assertEqual(ejecutar(C.en_vigor())["valores"]["conservar"], 20)                  # lo malo no cambia nada

    def test_la_salida_para_el_script_solo_trae_lo_fijado(self):
        import contextlib
        import io
        ejecutar(C.guardar({"conservar": 5, "extra": ""}, "albert"))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(C.main(["config"]), 0)
        self.assertEqual(sorted(buf.getvalue().split("\n")[:-1]), ["conservar=5", "extra="])

    def test_los_dias_para_avisar_se_aplican_al_estado_y_al_vigilante(self):
        ejecutar(C.registrar("copia", True, "/x", "bien", 1, AHORA - timedelta(days=2)))
        self.assertFalse(ejecutar(C.estado(AHORA))["alerta"])                                # 2 días < 3 por defecto
        ejecutar(C.guardar({"dias_aviso": 1}, "albert"))
        e = ejecutar(C.estado(AHORA))
        self.assertTrue(e["alerta"])
        self.assertEqual(e["dias_limite"], 1)

    def test_endpoints_solo_direccion_y_errores_claros(self):
        from cerebro.api import main
        from cerebro.api.main import Usuario, usuario_actual
        from fastapi.testclient import TestClient
        cl = TestClient(main.app)
        try:
            main.app.dependency_overrides[usuario_actual] = lambda: Usuario("ana", {"usuario"}, {"licitaciones"})
            self.assertEqual(cl.get("/salud/copias/ajustes").status_code, 403)
            self.assertEqual(cl.post("/salud/copias/ajustes", json={"conservar": 3}).status_code, 403)
            main.app.dependency_overrides[usuario_actual] = lambda: Usuario("albert", {"direccion"}, set())
            r = cl.post("/salud/copias/ajustes", json={"conservar": 9, "extra": "/mnt/d/Copias101"})
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(r.json()["valores"]["conservar"], 9)
            self.assertEqual(r.json()["fijados"]["conservar"]["por"], "albert")
            self.assertEqual(cl.get("/salud/copias/ajustes").json()["valores"]["extra"], "/mnt/d/Copias101")
            mala = cl.post("/salud/copias/ajustes", json={"extra": "/etc/cron.d"})
            self.assertEqual(mala.status_code, 422)
            self.assertIn("carpeta del servidor", mala.json()["detail"])
            self.assertEqual(cl.post("/salud/copias/ajustes", json={}).status_code, 422)
        finally:
            main.app.dependency_overrides.clear()


if __name__ == "__main__":
    unittest.main()
