"""Comprobación de «lo de hoy» al abrir la aplicación: al día, actualizando o el motor sin responder. El motor se sustituye por funciones."""
import asyncio
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import _sin_servicios  # noqa: F401
from cerebro.licitaciones import frescura as F
from cerebro.herramientas import licitaciones as motor

CFG = {"umbral_min": 20}


def ejecutar(c):
    return asyncio.run(c)


def estado(*edades):
    return {"fuentes": [{"fuente": f"f{i}", "antiguedad_s": e} for i, e in enumerate(edades)]}


class Motor:
    def __init__(self, estado_=None, cae=False, falla_pedir=False, nueva=True):
        self.estado_, self.cae, self.falla_pedir, self.nueva, self.pedidos = estado_, cae, falla_pedir, nueva, []

    async def consulta(self, ruta, params=None):
        assert ruta == "/ops/status"
        if self.cae:
            raise motor.MotorNoDisponible("caído")
        return self.estado_

    async def pedir(self, por):
        if self.falla_pedir:
            raise motor.MotorNoDisponible("no acepta")
        self.pedidos.append(por)
        return self.nueva


class TestFrescura(unittest.TestCase):
    def comprobar(self, m):
        return ejecutar(F.comprobar("albert", m.consulta, m.pedir, CFG))

    def test_reciente_esta_al_dia_y_no_pide_nada(self):
        m = Motor(estado(60))
        self.assertEqual(self.comprobar(m), {"estado": "al_dia", "antiguedad_s": 60, "solicitada": False})
        self.assertEqual(m.pedidos, [])

    def test_viejo_pide_actualizar_y_lo_dice(self):
        m = Motor(estado(60, 21 * 60 + 1))                          # la fuente más atrasada manda
        r = self.comprobar(m)
        self.assertEqual((r["estado"], r["antiguedad_s"], r["solicitada"]), ("actualizando", 21 * 60 + 1, True))
        self.assertEqual(m.pedidos, ["albert"])

    def test_aunque_la_cabecera_sea_reciente_si_se_esta_poniendo_al_dia_no_esta_al_dia(self):
        """Tras apagar el equipo, el ingestor mira la cabecera enseguida (parece reciente) pero aún baja los días atrasados."""
        m = Motor({"fuentes": [{"fuente": "f", "antiguedad_s": 30, "al_dia": False}]})
        r = self.comprobar(m)
        self.assertEqual((r["estado"], r["poniendose_al_dia"]), ("actualizando", True))
        self.assertEqual(m.pedidos, ["albert"])
        self.assertEqual(self.comprobar(Motor({"fuentes": [{"fuente": "f", "antiguedad_s": 30, "al_dia": True}]}))["estado"], "al_dia")
        self.assertEqual(self.comprobar(Motor(estado(30)))["estado"], "al_dia")                  # un motor antiguo sin el campo: se ignora

    def test_justo_en_el_umbral_sigue_al_dia(self):
        self.assertEqual(self.comprobar(Motor(estado(20 * 60)))["estado"], "al_dia")

    def test_sin_ingesta_completa_o_sin_fuentes_tambien_pide(self):
        for e in (estado(None), estado(30, None), {"fuentes": []}, {}):
            m = Motor(e)
            self.assertEqual(self.comprobar(m)["estado"], "actualizando", e)
            self.assertEqual(len(m.pedidos), 1)

    def test_si_ya_habia_una_peticion_reciente_se_dice_igual(self):
        r = self.comprobar(Motor(estado(3600), nueva=False))
        self.assertEqual((r["estado"], r["solicitada"]), ("actualizando", False))

    def test_motor_caido_o_que_no_acepta_la_peticion_se_dice_sin_lanzar(self):
        self.assertEqual(self.comprobar(Motor(cae=True)), {"estado": "motor_no_responde", "antiguedad_s": None, "solicitada": False})
        r = self.comprobar(Motor(estado(3600), falla_pedir=True))
        self.assertEqual((r["estado"], r["antiguedad_s"]), ("motor_no_responde", 3600))

    def test_el_umbral_sale_de_la_configuracion_y_esta_acotado(self):
        with mock.patch.object(F, "ajustes", SimpleNamespace(dir_config=Path(__file__).resolve().parents[2] / "config")):
            self.assertEqual(F.configuracion()["umbral_min"], 20)


class TestPedirAlMotor(unittest.TestCase):
    def test_hace_un_post_con_el_token_y_quien_lo_pide(self):
        visto = {}

        class Cliente:
            def __init__(self, **kw): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def post(self, url, headers=None):
                visto.update(url=url, headers=headers)
                return SimpleNamespace(status_code=202, json=lambda: {"solicitada": True})
        with mock.patch.dict("os.environ", {"LICITACIONES_API_TOKEN": "t" * 40, "LICITACIONES_API_URL": "http://motor:8080"}), mock.patch.object(motor.httpx, "AsyncClient", Cliente):
            self.assertTrue(ejecutar(motor.pedir_actualizacion("albert")))
        self.assertTrue(visto["url"].endswith("/api/v1/ops/actualizar"))
        self.assertEqual((visto["headers"]["Authorization"], visto["headers"]["X-Pedido-Por"]), ("Bearer " + "t" * 40, "albert"))

    def test_sin_credencial_o_con_respuesta_rara_es_motor_no_disponible(self):
        with mock.patch.dict("os.environ", {"LICITACIONES_API_TOKEN": ""}), self.assertRaises(motor.MotorNoDisponible):
            ejecutar(motor.pedir_actualizacion("albert"))


if __name__ == "__main__":
    unittest.main()
