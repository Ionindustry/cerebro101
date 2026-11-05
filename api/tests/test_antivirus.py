"""Vigilancia del antivirus: firmas al día, servicio en marcha y aviso a soporte@ una vez cada 24 h antes de que se empiecen a rechazar documentos."""
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
    from cerebro import antivirus as V
except ImportError as e:      # pragma: no cover
    raise unittest.SkipTest(str(e))

URL = os.environ.get("CEREBRO_TEST_PG")
ESQUEMA = Path(__file__).resolve().parents[2] / "db" / "esquema.sql"
AHORA = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)
VERSION = "ClamAV 1.4.6/28173/Tue Nov  3 06:27:52 2026\0"


def ejecutar(c):
    return asyncio.run(c)


def con_version(v):
    async def f():
        return v
    return f


class TestPuros(unittest.TestCase):
    def test_la_fecha_de_las_firmas(self):
        self.assertEqual(V.fecha_firmas(VERSION), datetime(2026, 11, 3, 6, 27, 52, tzinfo=timezone.utc))
        self.assertIsNone(V.fecha_firmas("ClamAV 1.4.6"))
        self.assertIsNone(V.fecha_firmas(""))

    def test_estados_segun_la_edad_de_las_firmas(self):
        r = ejecutar(V.estado(AHORA, con_version(VERSION), 48))            # 53 h: ya se rechazan
        self.assertEqual((r["estado"], r["edad_horas"]), ("viejas", 53.5))
        self.assertIn("ya se rechazan", r["motivo"])
        r = ejecutar(V.estado(datetime(2026, 11, 4, 20, 0, tzinfo=timezone.utc), con_version(VERSION), 48))   # 37.5 h: aviso, aún se aceptan
        self.assertEqual(r["estado"], "viejas")
        self.assertIn("se empezarán a rechazar", r["motivo"])
        r = ejecutar(V.estado(datetime(2026, 11, 4, 6, 0, tzinfo=timezone.utc), con_version(VERSION), 48))    # 23.5 h: bien
        self.assertEqual((r["estado"], r["motivo"]), ("ok", ""))

    def test_sin_respuesta_o_sin_fecha_legible(self):
        async def cae():
            raise ConnectionRefusedError("sin clamd")
        r = ejecutar(V.estado(AHORA, cae, 48))
        self.assertEqual((r["estado"], r["version"]), ("no_responde", None))
        self.assertEqual(ejecutar(V.estado(AHORA, con_version("ClamAV 1.4.6"), 48))["estado"], "viejas")        # falla cerrado


@unittest.skipUnless(URL and hasattr(psycopg, "AsyncConnection"), "sin CEREBRO_TEST_PG")
class TestEnBase(unittest.TestCase):
    def setUp(self):
        self.schema = f"t_av_{time.time_ns()}"
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"CREATE SCHEMA {self.schema}")
            c.execute(f"SET search_path = {self.schema}")
            t = ESQUEMA.read_text(encoding="utf-8")
            c.execute(t[t.index("-- Avisos de vigilancia del sistema (api/cerebro/antivirus.py)"):t.index("-- Resumen diario de licitaciones")])
        sep = "&" if "?" in URL else "?"
        self.parche = mock.patch.object(V, "ajustes", SimpleNamespace(database_url=f"{URL}{sep}options=-csearch_path%3D{self.schema}"))
        self.parche.start()
        self.enviados = []

    def tearDown(self):
        self.parche.stop()
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"DROP SCHEMA {self.schema} CASCADE")

    def vigilar(self, ahora, version=VERSION, falla_correo=False):
        from cerebro import avisar_soporte as S

        def enviar(d, a, c, e):
            self.enviados.append((d, a, c))
            return (0, len(d)) if falla_correo else (len(d), 0)
        with mock.patch.object(S.vigilante, "_enviar_a", enviar), mock.patch.object(S.vigilante, "configuracion", lambda cfg=None: {"destinatarios": ["soporte@101.cat"]}):
            return ejecutar(V.vigilar(None, ahora, con_version(version)))

    def test_con_firmas_al_dia_no_avisa(self):
        self.assertEqual(self.vigilar(datetime(2026, 11, 3, 18, 0, tzinfo=timezone.utc))["estado"], "ok")
        self.assertEqual(self.enviados, [])

    def test_avisa_una_vez_cada_24_horas_con_lo_que_hay_que_hacer(self):
        self.assertEqual(self.vigilar(AHORA)["estado"], "avisado")
        self.assertEqual(len(self.enviados), 1)
        self.assertIn("freshclam", self.enviados[0][2])
        self.assertIn("firmas están viejas", self.enviados[0][1])
        self.assertEqual(self.vigilar(AHORA + timedelta(hours=3))["estado"], "ya_avisado")
        self.assertEqual(self.vigilar(AHORA + timedelta(hours=25))["estado"], "avisado")
        self.assertEqual(len(self.enviados), 2)

    def test_si_el_correo_falla_no_se_anota_y_se_reintenta(self):
        self.assertEqual(self.vigilar(AHORA, falla_correo=True)["estado"], "error_correo")
        self.assertEqual(self.vigilar(AHORA + timedelta(hours=3))["estado"], "avisado")

    def test_la_tarjeta_de_jarvis_responde_a_cualquier_usuario_identificado(self):
        from cerebro.api import main
        from cerebro.api.main import Usuario, usuario_actual
        from fastapi.testclient import TestClient
        main.app.dependency_overrides[usuario_actual] = lambda: Usuario("albert", {"usuario"}, set())
        try:
            with mock.patch.object(V, "_version_de_clamd", con_version(VERSION)):
                r = TestClient(main.app).get("/salud/antivirus")
        finally:
            main.app.dependency_overrides.clear()
        self.assertEqual(r.status_code, 200)
        self.assertIn(r.json()["estado"], ("ok", "viejas"))


if __name__ == "__main__":
    unittest.main()
