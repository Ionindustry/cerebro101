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

    def test_control_de_lo_de_hoy_solo_en_dia_laborable_y_pasada_la_hora(self):
        from datetime import datetime
        jueves, sabado = datetime(2026, 10, 29, 12, 30), datetime(2026, 10, 31, 12, 30)
        self.assertIn("Hoy no ha entrado ninguna licitación", V.sin_novedades_hoy(jueves, 0, 11))
        self.assertIsNone(V.sin_novedades_hoy(jueves, 3, 11))                                  # hay novedades
        self.assertIsNone(V.sin_novedades_hoy(jueves.replace(hour=9), 0, 11))                  # aún es pronto
        self.assertIsNone(V.sin_novedades_hoy(sabado, 0, 11))                                  # fin de semana
        self.assertIsNone(V.sin_novedades_hoy(jueves, None, 11))                               # no se ha podido contar: no se avisa por eso
        self.assertEqual(V.problemas(estado(1), 6, V.sin_novedades_hoy(jueves, 0, 11))[0][:6], "Hoy no")

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


class TestHisteresis(unittest.TestCase):
    ATASCADO = {"estado": "atascado", "desde": AHORA - timedelta(hours=3), "avisado_en": AHORA - timedelta(hours=3), "malas": 0, "buenas": 0}

    def test_un_corte_breve_no_avisa_ni_de_que_se_para_ni_de_que_vuelve(self):
        e, a, m, b = V.decidir_con_racha(None, True, AHORA, 24, 2, 2)
        self.assertEqual((e, a, m), ("ok", None, 1))                                              # primera pasada mala: aún no
        e, a, m, b = V.decidir_con_racha({"estado": "ok", "desde": AHORA, "avisado_en": None, "malas": 1, "buenas": 0}, False, AHORA, 24, 2, 2)
        self.assertEqual((e, a, m), ("ok", None, 0))                                              # se arregló sola: no se avisó de nada

    def test_un_problema_que_dura_avisa_a_la_segunda_pasada_y_recuerda_igual_que_antes(self):
        e, a, m, b = V.decidir_con_racha({"estado": "ok", "desde": AHORA, "avisado_en": None, "malas": 1, "buenas": 0}, True, AHORA, 24, 2, 2)
        self.assertEqual((e, a), ("atascado", "problema"))
        self.assertEqual(V.decidir_con_racha(self.ATASCADO, True, AHORA, 24, 2, 2)[:2], ("atascado", None))
        self.assertEqual(V.decidir_con_racha(self.ATASCADO, True, AHORA + timedelta(hours=22), 24, 2, 2)[:2], ("atascado", "recordatorio"))

    def test_para_dar_el_problema_por_arreglado_hacen_falta_pasadas_buenas_seguidas(self):
        e, a, m, b = V.decidir_con_racha(self.ATASCADO, False, AHORA, 24, 2, 2)
        self.assertEqual((e, a, b), ("atascado", None, 1))
        e, a, m, b = V.decidir_con_racha({**self.ATASCADO, "buenas": 1}, False, AHORA, 24, 2, 2)
        self.assertEqual((e, a), ("ok", "recuperado"))
        e, a, m, b = V.decidir_con_racha({**self.ATASCADO, "buenas": 1}, True, AHORA, 24, 2, 2)      # una pasada mala en medio reinicia la cuenta de buenas
        self.assertEqual((e, a, b), ("atascado", None, 0))

    def test_con_una_pasada_se_comporta_como_antes(self):
        self.assertEqual(V.decidir_con_racha(None, True, AHORA, 24, 1, 1)[:2], ("atascado", "problema"))
        self.assertEqual(V.decidir_con_racha(self.ATASCADO, False, AHORA, 24, 1, 1)[:2], ("ok", "recuperado"))

    def test_lo_de_hoy_cerrado_por_el_reloj_no_es_una_recuperacion(self):
        hoy = {"estado": "atascado", "detalle": "Hoy no ha entrado ninguna licitación nueva ni actualizada (son las 22:10…)."}
        self.assertTrue(V.solo_por_el_reloj(hoy, False, 0))
        self.assertTrue(V.solo_por_el_reloj(hoy, False, None))
        self.assertFalse(V.solo_por_el_reloj(hoy, False, 4))                                      # entró algo: recuperación de verdad
        self.assertFalse(V.solo_por_el_reloj(hoy, True, 0))
        self.assertFalse(V.solo_por_el_reloj({"estado": "atascado", "detalle": "La fuente x lleva 7.0 horas sin ingesta correcta."}, False, 0))
        self.assertFalse(V.solo_por_el_reloj({"estado": "atascado", "detalle": "Hoy no ha entrado nada\nLa fuente x no ha completado ninguna ingesta."}, False, 0))
        self.assertFalse(V.solo_por_el_reloj(None, False, 0))

    def test_configuracion_de_pasadas_acotada(self):
        c = V.configuracion({"vigilante": {"pasadas_para_avisar": 0, "pasadas_para_recuperar": 99}})
        self.assertEqual((c["pasadas_para_avisar"], c["pasadas_para_recuperar"]), (1, 12))
        self.assertEqual(V.configuracion({})["pasadas_para_avisar"], 2)


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
        self.enviados, self.estado, self.falla, self.novedades_hoy, self.consultas_hoy = [], estado(1), False, 5, []

    def tearDown(self):
        for p in self.p:
            p.stop()
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"DROP SCHEMA {self.schema} CASCADE")

    async def consulta(self, ruta, params=None):
        if self.estado is None:
            raise V.motor.MotorNoDisponible("caído")
        if ruta == "/tenders":
            self.consultas_hoy.append(params)
            return {"total": {"valor": self.novedades_hoy}, "items": []}
        return self.estado

    def enviar(self, buzon, mensaje):
        if self.falla:
            raise OSError("smtp caído")
        self.enviados.append((mensaje["To"], mensaje["Subject"]))

    def paso(self, horas=0, destinatarios=("tec@101.cat",), pasadas=1):
        cfg = {"vigilante": {"destinatarios": list(destinatarios), "horas_sin_ingesta": 6, "repetir_cada_horas": 24, "hora_control_hoy": 11,
                             "pasadas_para_avisar": pasadas, "pasadas_para_recuperar": pasadas}}
        return ejecutar(V.vigilar(self.consulta, self.enviar, AHORA + timedelta(hours=horas), cfg))

    def test_sin_nada_de_hoy_en_dia_laborable_avisa_aunque_la_ingesta_figure_al_dia(self):
        self.novedades_hoy = 0
        r = self.paso()
        self.assertEqual((r["aviso"], len(r["problemas"])), ("problema", 1))
        self.assertIn("Hoy no ha entrado ninguna licitación", r["problemas"][0])
        self.assertEqual(self.consultas_hoy[0]["limit"], 1)
        self.assertTrue(self.consultas_hoy[0]["actualizada_desde"].startswith("2026-"))
        self.novedades_hoy = 7
        self.assertEqual(self.paso(1)["aviso"], "recuperado")

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

    def test_un_reinicio_breve_del_motor_no_manda_ningun_correo(self):
        self.estado = None                                                                    # el motor no responde (p. ej. se está actualizando el servidor)
        self.assertEqual(self.paso(0, pasadas=2)["aviso"], None)
        self.estado = estado(1)                                                               # a la siguiente pasada ya responde
        self.assertEqual(self.paso(0.25, pasadas=2)["aviso"], None)
        self.assertEqual(self.enviados, [])
        self.estado = None                                                                    # y si en cambio sigue caído dos pasadas seguidas, sí se avisa
        self.assertEqual(self.paso(0.5, pasadas=2)["aviso"], None)
        self.assertEqual(self.paso(0.75, pasadas=2)["aviso"], "problema")
        self.estado = estado(1)
        self.assertEqual(self.paso(1, pasadas=2)["aviso"], None)                              # una pasada buena no basta
        self.assertEqual(self.paso(1.25, pasadas=2)["aviso"], "recuperado")

    def test_lo_de_hoy_que_se_cierra_por_el_reloj_no_manda_el_correo_de_recuperado(self):
        self.novedades_hoy = 0
        self.assertEqual(self.paso()["aviso"], "problema")                                    # 12:00 UTC = 13:00 Madrid, pasada la hora de control (11)
        antes = len(self.enviados)
        r = self.paso(11)                                                                     # a medianoche (hora local < control): ya no es problema, pero no ha entrado nada
        self.assertEqual((r["aviso"], r["estado"]), (None, "ok"))
        self.assertEqual(len(self.enviados), antes)

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
