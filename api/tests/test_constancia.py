import asyncio
import os
import tempfile
import unittest
from unittest import mock

from tests import _sin_servicios  # noqa: F401
from cerebro import constancia


def correr(c):
    return asyncio.run(c)


class TestConstancia(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"CEREBRO_DATOS": self.dir.name})
        self.env.start()
        self.espera = mock.patch.object(constancia, "REINTENTOS", (0, 0))
        self.espera.start()
        constancia.ESTADO.update(fallos=0, ultimo_fallo=None)

    def tearDown(self):
        self.espera.stop()
        self.env.stop()
        self.dir.cleanup()

    def test_camino_normal(self):
        with mock.patch.object(constancia, "_insertar", mock.AsyncMock()) as ins:
            self.assertEqual(correr(constancia.dejar_constancia("h", "ag", "cotizador", "cotizar", None, "OK")), "ok")
        ins.assert_awaited_once()
        self.assertEqual(constancia.pendientes(), 0)

    def test_reintenta_y_acaba_escribiendo(self):
        ins = mock.AsyncMock(side_effect=[OSError("base reiniciando"), None])
        with mock.patch.object(constancia, "_insertar", ins):
            self.assertEqual(correr(constancia.dejar_constancia("h", "ag", "t", "o", None, "OK")), "ok")
        self.assertEqual(ins.await_count, 2)
        self.assertEqual(constancia.ESTADO["fallos"], 0)

    def test_si_la_base_no_responde_queda_en_cola_local_y_se_avisa(self):
        with mock.patch.object(constancia, "_insertar", mock.AsyncMock(side_effect=OSError("caída"))):
            with self.assertLogs("cerebro.constancia", "CRITICAL"):
                self.assertEqual(correr(constancia.dejar_constancia("h", "ag", "t", "o", None, "OK")), "en_cola")
        self.assertEqual(constancia.pendientes(), 1)
        self.assertEqual(constancia.ESTADO["fallos"], 1)
        modo = os.stat(constancia._fichero()).st_mode & 0o777
        self.assertEqual(modo, 0o600)

    def test_se_vuelcan_al_volver_la_base_y_conservan_la_hora(self):
        with mock.patch.object(constancia, "_insertar", mock.AsyncMock(side_effect=OSError("caída"))):
            with self.assertLogs("cerebro.constancia", "CRITICAL"):
                correr(constancia.dejar_constancia("h", "ag", "t", "o", None, "OK"))
                correr(constancia.dejar_constancia("h", "ag", "t", "o2", None, "OK"))
        self.assertEqual(constancia.pendientes(), 2)
        ins = mock.AsyncMock()
        with mock.patch.object(constancia, "_insertar", ins), self.assertLogs("cerebro.constancia", "WARNING"):
            self.assertEqual(correr(constancia.volcar_pendientes()), {"volcadas": 2, "quedan": 0, "apartadas": 0})
        self.assertEqual(constancia.pendientes(), 0)
        self.assertTrue(all("creado" in c.args[0] for c in ins.await_args_list))

    def test_lo_que_sigue_fallando_se_conserva(self):
        with mock.patch.object(constancia, "_insertar", mock.AsyncMock(side_effect=OSError("caída"))):
            with self.assertLogs("cerebro.constancia", "CRITICAL"):
                correr(constancia.dejar_constancia("h", "ag", "t", "o", None, "OK"))
            with self.assertLogs("cerebro.constancia", "WARNING"):
                self.assertEqual(correr(constancia.volcar_pendientes()), {"volcadas": 0, "quedan": 1, "apartadas": 0})
        self.assertEqual(constancia.pendientes(), 1)

    def test_una_fila_que_la_base_rechaza_se_aparta_y_no_atasca_a_las_buenas(self):
        import psycopg
        if not hasattr(psycopg, "errors"):
            self.skipTest("requiere psycopg real (se ejecuta en el contenedor)")
        mala = {"hilo": "h", "agente": "a", "herramienta": "t", "operacion": "mala", "aprobacion": "no-es-un-uuid",
                "resultado": "OK", "creado": "2026-10-05T00:00:00+00:00"}
        buena = {**mala, "operacion": "buena", "aprobacion": None}
        for f in (mala, buena):
            constancia._guardar_local(f)

        async def insertar(f):
            if f["operacion"] == "mala":
                raise psycopg.errors.InvalidTextRepresentation("invalid input syntax for type uuid")

        with mock.patch.object(constancia, "_insertar", insertar), self.assertLogs("cerebro.constancia", "CRITICAL"):
            r = correr(constancia.volcar_pendientes())
        self.assertEqual(r, {"volcadas": 1, "quedan": 0, "apartadas": 1})
        self.assertEqual((constancia.pendientes(), constancia.rechazadas()), (0, 1))
        self.assertIn("motivo_rechazo", constancia._fichero_rechazadas().read_text(encoding="utf-8"))

    def test_una_base_caida_no_aparta_nada(self):
        constancia._guardar_local({"hilo": "h", "agente": "a", "herramienta": "t", "operacion": "o", "aprobacion": None,
                                   "resultado": "OK", "creado": "2026-10-05T00:00:00+00:00"})
        with mock.patch.object(constancia, "_insertar", mock.AsyncMock(side_effect=OSError("caída"))), \
                self.assertLogs("cerebro.constancia", "WARNING"):
            r = correr(constancia.volcar_pendientes())
        self.assertEqual((r["quedan"], r["apartadas"], constancia.rechazadas()), (1, 0, 0))

    def test_sin_disco_ni_base_se_dice_perdida(self):
        with mock.patch.object(constancia, "_insertar", mock.AsyncMock(side_effect=OSError("caída"))), \
             mock.patch.object(constancia, "_guardar_local", return_value=False):
            with self.assertLogs("cerebro.constancia", "CRITICAL"):
                self.assertEqual(correr(constancia.dejar_constancia("h", "ag", "t", "o", None, "OK")), "perdida")


if __name__ == "__main__":
    unittest.main()
