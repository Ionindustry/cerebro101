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
