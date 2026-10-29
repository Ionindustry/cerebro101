"""Vigilante del motor: qué se considera atascado, cuándo avisar (una vez, recordatorio, recuperado) y el flujo con PostgreSQL (con CEREBRO_TEST_PG)."""
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
    from cerebro.licitaciones import vigilante as V
except ImportError as e:      # pragma: no cover
    raise unittest.SkipTest(str(e))

URL = os.environ.get("CEREBRO_TEST_PG")
ESQUEMA = Path(__file__).resolve().parents[2] / "db" / "esquema.sql"
AHORA = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)


def ejecutar(c):
    return asyncio.run(c)


def estado(horas, estado="ok", fuente="placsp-643"):
    return {"estado": estado, "fuentes": [{"fuente": fuente, "antiguedad_s": None if horas is None else int(horas * 3600)}]}


class TestProblemas(unittest.TestCase):
    def test_al_dia_no_hay_problemas(self):
        self.assertEqual(V.problemas(estado(1), 6), [])

    def test_fuente_pasada_de_horas_o_sin_ingesta_completa(self):
        self.assertIn("7.0 horas", V.problemas(estado(7), 6)[0])
        self.assertIn("no ha completado", V.problemas(estado(None), 6)[0])

    def test_motor_sin_respuesta_y_motor_caido(self):
        self.assertIn("no responde", V.problemas(None, 6)[0])
        self.assertIn("caído", V.problemas({"estado": "caido", "fuentes": []}, 6)[0])

    def test_el_nombre_de_la_fuente_no_rompe_el_texto(self):
        self.assertLessEqual(len(V.problemas(estado(9, fuente="x" * 500), 6)[0]), 200)


class TestDecidir(unittest.TestCase):
    def test_ciclo_completo(self):
        self.assertEqual(V.decidir(None, False, AHORA, 24), ("ok", None))
        self.assertEqual(V.decidir({"estado": "ok", "desde": AHORA, "avisado_en": None}, True, AHORA, 24), ("atascado", "problema"))
        atascado = {"estado": "atascado", "desde": AHORA - timedelta(hours=3), "avisado_en": AHORA - timedelta(hours=3)}
        self.assertEqual(V.decidir(atascado, True, AHORA, 24), ("atascado", None))                              # ya avisado: callado
        self.assertEqual(V.decidir(atascado, True, AHORA + timedelta(hours=20), 24), ("atascado", None))
        self.assertEqual(V.decidir(atascado, True, AHORA + timedelta(hours=21), 24), ("atascado", "recordatorio"))
        self.assertEqual(V.decidir(atascado, False, AHORA, 24), ("ok", "recuperado"))
        self.assertEqual(V.decidir({"estado": "ok", "desde": AHORA, "avisado_en": None}, False, AHORA, 24), ("ok", None))

    def test_si_el_primer_aviso_no_salio_se_reintenta(self):
        self.assertEqual(V.decidir({"estado": "atascado", "desde": AHORA, "avisado_en": None}, True, AHORA, 24), ("atascado", "problema"))


class TestRedactar(unittest.TestCase):
    def test_textos(self):
        a, c = V.redactar("problema", ["La fuente x lleva 7.0 horas sin ingesta correcta (límite: 6)."], AHORA - timedelta(hours=7), AHORA)
        self.assertIn("atascada", a)
        self.assertIn("7.0 horas", c)
        self.assertIn("recordatorio", V.redactar("recordatorio", ["x"], AHORA, AHORA)[0])
        a, c = V.redactar("recuperado", [], AHORA - timedelta(hours=7), AHORA)
        self.assertIn("vuelve a funcionar", a)
        self.assertIn("atascado desde", c)


class TestConfig(unittest.TestCase):
    def test_limites_y_defecto(self):
        c = V.configuracion({"vigilante": {"horas_sin_ingesta": 0, "repetir_cada_horas": 9999, "destinatarios": ["a@101.cat", 5]}})
        self.assertEqual((c["horas_sin_ingesta"], c["repetir_cada_horas"], c["destinatarios"]), (1, 168, ["a@101.cat"]))
        self.assertEqual(V.configuracion({})["destinatarios"], [])


@unittest.skipUnless(URL and hasattr(psycopg, "AsyncConnection"), "sin CEREBRO_TEST_PG")
class TestFlujo(unittest.TestCase):
    def setUp(self):
        self.schema = f"t_vig_{time.time_ns()}"
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"CREATE SCHEMA {self.schema}")
            c.execute(f"SET search_path = {self.schema}")
            t = ESQUEMA.read_text(encoding="utf-8")
            i = t.index("-- Vigilante del motor de licitaciones")
            c.execute(t[i:])
        sep = "&" if "?" in URL else "?"
        self.p = [mock.patch.object(V, "ajustes", SimpleNamespace(database_url=f"{URL}{sep}options=-csearch_path%3D{self.schema}", zona_horaria="Europe/Madrid")),
                  mock.patch.object(V.correo, "configuracion", lambda: {"buzon": "notificaciones", "dominios": ["101.cat"]}),
                  mock.patch.object(V.B, "cargar", lambda: {"buzones": {"notificaciones": {"direccion": "notificaciones@101.cat"}}})]
        for p in self.p:
            p.start()
        self.enviados, self.estado, self.falla = [], estado(1), False

    def tearDown(self):
        for p in self.p:
            p.stop()
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"DROP SCHEMA {self.schema} CASCADE")

    async def consulta(self, ruta, params=None):
        if self.estado is None:
            raise V.motor.MotorNoDisponible("caído")
        return self.estado

    def enviar(self, buzon, mensaje):
        if self.falla:
            raise OSError("smtp caído")
        self.enviados.append((mensaje["To"], mensaje["Subject"]))

    def paso(self, horas=0, destinatarios=("tec@101.cat",)):
        cfg = {"vigilante": {"destinatarios": list(destinatarios), "horas_sin_ingesta": 6, "repetir_cada_horas": 24}}
        return ejecutar(V.vigilar(self.consulta, self.enviar, AHORA + timedelta(hours=horas), cfg))

    def test_avisa_una_vez_recuerda_y_avisa_al_recuperarse(self):
        self.assertEqual(self.paso()["aviso"], None)                                   # todo bien
        self.estado = estado(8)
        r = self.paso(1)
        self.assertEqual((r["aviso"], r["enviados"]), ("problema", 1))
        self.assertEqual(self.paso(2)["aviso"], None)                                  # sigue mal pero ya se avisó
        self.assertEqual(self.paso(3)["aviso"], None)
        r = self.paso(26)
        self.assertEqual(r["aviso"], "recordatorio")
        self.estado = estado(1)
        r = self.paso(27)
        self.assertEqual((r["aviso"], r["estado"]), ("recuperado", "ok"))
        self.assertEqual(self.paso(28)["aviso"], None)
        self.assertEqual([a for _, a in self.enviados], ["Licitaciones: la ingesta lleva atascada", "Licitaciones: la ingesta lleva atascada (recordatorio)", "Licitaciones: el motor vuelve a funcionar"])

    def test_si_el_correo_falla_se_reintenta(self):
        self.estado, self.falla = estado(8), True
        r = self.paso()
        self.assertEqual((r["aviso"], r["enviados"], r["fallidos"]), ("problema", 0, 1))
        self.falla = False
        self.assertEqual((self.paso(0.25)["aviso"], len(self.enviados)), ("problema", 1))        # a la siguiente pasada sale
        self.assertEqual(self.paso(0.5)["aviso"], None)

    def test_si_falla_el_aviso_de_recuperacion_se_reintenta(self):
        self.estado = estado(8)
        self.paso()
        self.estado, self.falla = estado(1), True
        self.assertEqual(self.paso(1)["aviso"], "recuperado")
        self.falla = False
        self.assertEqual(self.paso(1.25)["aviso"], "recuperado")
        self.assertEqual(self.paso(1.5)["aviso"], None)

    def test_motor_que_no_responde_cuenta_como_atascado(self):
        self.estado = None
        self.assertEqual(self.paso()["aviso"], "problema")

    def test_sin_destinatarios_solo_queda_en_el_registro(self):
        self.estado = estado(8)
        r = self.paso(destinatarios=())
        self.assertEqual((r["aviso"], r["enviados"]), ("problema", 0))
        self.assertEqual(self.paso(1, destinatarios=())["aviso"], None)                  # no insiste cada pasada

    def test_una_direccion_de_fuera_de_la_empresa_no_recibe_nada(self):
        self.estado = estado(8)
        r = self.paso(destinatarios=("alguien@gmail.com",))
        self.assertEqual((r["enviados"], r["fallidos"], self.enviados), (0, 1, []))


if __name__ == "__main__":
    unittest.main()
