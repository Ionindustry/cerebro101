import unittest

from cerebro.red_instaladores import Oferta, puntuar


class TestComparador(unittest.TestCase):
    def ofertas(self):
        return [
            Oferta("Barato lento", 1000, 15, 48, 1.0, 0, 4.0, 10),
            Oferta("Equilibrado", 1150, 3, 4, 1.05, 0, 4.5, 12),
            Oferta("Nuevo", 1150, 3, 4, 1.0, 0, 3.0, 0),
        ]

    def test_orden_y_explicacion(self):
        r = puntuar(self.ofertas())
        self.assertEqual(r[0].instalador, "Equilibrado")
        nuevo = next(p for p in r if p.instalador == "Nuevo")
        self.assertTrue(any("Pocos trabajos" in n for n in nuevo.notas))

    def test_pesos_configurables(self):
        r = puntuar(self.ofertas(), {"precio": 1.0, "rapidez": 0.0, "eficiencia": 0.0})
        self.assertEqual(r[0].instalador, "Barato lento")

    def test_pesos_invalidos(self):
        with self.assertRaises(ValueError):
            puntuar(self.ofertas(), {"precio": 0.5, "rapidez": 0.1, "eficiencia": 0.1})


# --- Llamada del modelo a la herramienta: errores que el modelo pueda corregir (antes: TypeError sin explicación)
import asyncio  # noqa: E402

from tests import _sin_servicios  # noqa: E402,F401
from cerebro.herramientas.calculo import comparar  # noqa: E402

OFERTA = {"instalador": "Roca SL", "precio": 1000, "dias_hasta_inicio": 5, "horas_respuesta": 4,
          "ratio_horas_historico": 1.0, "incidencias_historico": 0, "valoracion_calidad": 4.5}


class TestLlamadaDelModelo(unittest.TestCase):
    def test_sin_pesos_funciona(self):
        self.assertEqual(asyncio.run(comparar([OFERTA]))[0]["instalador"], "Roca SL")

    def test_pesos_mal_formados_dan_un_error_claro(self):
        for pesos, texto in [({"precio": 0.4, "-- texto libre": "x"}, "solo admite las claves"),
                             ({"precio": 0.5, "rapidez": "mucha", "eficiencia": 0.5}, "tres claves"),
                             ({"precio": 0.5, "rapidez": 0.5}, "tres claves")]:
            with self.subTest(pesos=pesos), self.assertRaisesRegex(ValueError, texto):
                asyncio.run(comparar([OFERTA], pesos))

    def test_oferta_con_campos_inventados_o_sin_campos(self):
        with self.assertRaisesRegex(ValueError, "sobran"):
            asyncio.run(comparar([{**OFERTA, "color": "rojo"}]))
        with self.assertRaisesRegex(ValueError, "faltan"):
            asyncio.run(comparar([{"instalador": "X", "precio": 1}]))
        with self.assertRaisesRegex(ValueError, "debe ser un objeto"):
            asyncio.run(comparar(["Roca SL 1000"]))
