"""Precios de venta (cerebro/precios.py): margen SOBRE LA VENTA, redondeo, coste en euros del canal y elección del mejor coste. Todo con Decimal, sin IA."""
import unittest
from decimal import Decimal as D
from pathlib import Path

import yaml

from cerebro import precios as P

RAIZ = Path(__file__).resolve().parents[2]


def cfg(**extra):
    base = {"margen": {"por_defecto": 0.5, "minimo": 0.1, "familias": {"Cámaras": 0.4, "Accesorios / Cableado": 0.6}}, "redondeo": {"modo": "centimo"},
            "canales": {"fabricante": {"moneda": "USD", "logistica_pct": 0.15}, "distribuidor": {"moneda": "EUR", "logistica_pct": 0}}, "cambio_a_eur": {"USD": 0.92}, "provisional": []}
    base.update(extra)
    return P.configuracion(base)


class TestMargenSobreLaVenta(unittest.TestCase):
    def test_con_coste_100_y_margen_50_la_venta_es_200_no_150(self):
        self.assertEqual(P.precio_venta(D(100), D("0.5")), D(200))
        c = P.calcular(100, "EUR", "distribuidor", "Otros", cfg())
        self.assertEqual((c.venta, c.margen_real, c.recargo_sobre_coste), (D("200.00"), D("0.5000"), D("1.0000")))      # ganar 100 sobre 100 de coste = 100 % de recargo

    def test_un_recargo_del_50_es_un_margen_del_33_por_ciento(self):
        c = P.calcular(100, "EUR", "distribuidor", "Otros", cfg(), margen=D(1) / D(3))
        self.assertEqual((c.venta, c.recargo_sobre_coste), (D("150.00"), D("0.5000")))

    def test_margen_por_familia_sin_importar_tildes_ni_niveles(self):
        c = cfg()
        self.assertEqual(P.margen_de("Cámaras", c), D("0.4"))
        self.assertEqual(P.margen_de("camaras", c), D("0.4"))
        self.assertEqual(P.margen_de("Accesorios / Cableado / RJ45", c), D("0.6"))        # el camino completo no está: se prueba cada camino más corto
        self.assertEqual(P.margen_de("Cableado", c), D("0.5"))                              # «Cableado» solo no figura (figura «Accesorios / Cableado»): margen general
        self.assertEqual(P.margen_de("Desconocida", c), D("0.5"))
        self.assertEqual(P.margen_de("", c), D("0.5"))


class TestRedondeo(unittest.TestCase):
    def test_modos(self):
        d = D("142.857142")
        self.assertEqual(P.redondear(d, cfg()), D("142.86"))
        self.assertEqual(P.redondear(d, cfg(redondeo={"modo": "euro"})), D("143.00"))
        self.assertEqual(P.redondear(d, cfg(redondeo={"modo": "terminar_en", "terminacion": 0.90})), D("142.90"))
        self.assertEqual(P.redondear(D("142.95"), cfg(redondeo={"modo": "terminar_en", "terminacion": 0.90})), D("143.90"))   # hacia arriba: nunca baja el margen
        self.assertEqual(P.redondear(D("142.90"), cfg(redondeo={"modo": "terminar_en", "terminacion": 0.90})), D("142.90"))
        self.assertEqual(P.redondear(D("10.01"), cfg(redondeo={"modo": "terminar_en", "terminacion": 0.99})), D("10.99"))

    def test_redondear_hacia_arriba_no_baja_el_margen(self):
        for modo in ({"modo": "euro"}, {"modo": "terminar_en", "terminacion": 0.99}):
            c = cfg(redondeo=modo)
            for coste in ("3.17", "17.5", "82.5", "1234.56"):
                calc = P.calcular(coste, "EUR", "distribuidor", "Otros", c)
                self.assertGreaterEqual(calc.margen_real, D("0.5") - D("0.0001"), (modo, coste))


class TestCosteEnEuros(unittest.TestCase):
    def test_fabricante_en_dolares_con_cambio_y_logistica(self):
        c, av = P.coste_en_euros("100", "USD", "fabricante", cfg())
        self.assertEqual(c, D("100") * D("0.92") * D("1.15"))
        self.assertEqual(av, [])

    def test_distribuidor_en_euros_sin_cambio(self):
        c, av = P.coste_en_euros("90.5", "EUR", "distribuidor", cfg())
        self.assertEqual((c, av), (D("90.5"), []))

    def test_los_valores_provisionales_avisan(self):
        _, av = P.coste_en_euros("100", "USD", "fabricante", cfg(provisional=["cambio_a_eur.USD", "canales.fabricante.logistica_pct"]))
        self.assertEqual(av, ["cambio USD→EUR provisional", "logística de «fabricante» provisional"])
        c = P.calcular("100", "USD", "fabricante", "Otros", cfg(provisional=["margen.por_defecto"]))
        self.assertIn("margen general provisional", c.avisos)
        self.assertNotIn("margen general provisional", P.calcular("100", "USD", "fabricante", "Cámaras", cfg(provisional=["margen.por_defecto"])).avisos)

    def test_sin_tipo_de_cambio_no_se_adivina(self):
        with self.assertRaisesRegex(P.ErrorPrecios, "Falta el tipo de cambio de GBP"):
            P.coste_en_euros("100", "GBP", "fabricante", cfg())
        with self.assertRaisesRegex(P.ErrorPrecios, "Falta el tipo de cambio de USD"):
            P.coste_en_euros("100", "USD", "fabricante", cfg(cambio_a_eur={"USD": None}))

    def test_sin_logistica_avisa_y_no_suma(self):
        c, av = P.coste_en_euros("100", "EUR", "fabricante", cfg(canales={"fabricante": {"moneda": "USD", "logistica_pct": None}}))
        self.assertEqual(c, D("100"))
        self.assertIn("sin logística", av[0])

    def test_costes_imposibles(self):
        for malo in (0, -5, "abc", None):
            with self.assertRaises(P.ErrorPrecios):
                P.coste_en_euros(malo, "EUR", "distribuidor", cfg())

    def test_margen_bajo_el_minimo_avisa_pero_calcula(self):
        c = P.calcular(100, "EUR", "distribuidor", "Otros", cfg(), margen=D("0.05"))
        self.assertEqual(c.venta, D("105.26"))
        self.assertTrue(any("por debajo del mínimo" in a for a in c.avisos))


class TestMejorCoste(unittest.TestCase):
    OFERTAS = [{"proveedor": "Fabricante", "canal": "fabricante", "coste": "103.4", "moneda": "USD", "stock": None},
               {"proveedor": "Distribuidor", "canal": "distribuidor", "coste": "90.5", "moneda": "EUR", "stock": "9"}]

    def test_compara_ya_en_euros_y_con_logistica(self):
        elegida = P.mejor_coste(self.OFERTAS, cfg())
        self.assertEqual(elegida["proveedor"], "Distribuidor")            # 90,50 € frente a 103,4 × 0,92 × 1,15 = 109,40 €
        self.assertGreater(P.coste_en_euros("103.4", "USD", "fabricante", cfg())[0], D("109"))

    def test_prefiere_el_que_tiene_stock_aunque_sea_mas_caro(self):
        ofertas = [{**self.OFERTAS[0], "coste": "10", "moneda": "EUR", "stock": "5"}, {**self.OFERTAS[1], "stock": "0"}]
        self.assertEqual(P.mejor_coste(ofertas, cfg())["proveedor"], "Fabricante")
        self.assertEqual(P.mejor_coste(ofertas, cfg(), solo_con_stock=False)["proveedor"], "Fabricante")
        sin_ninguno = [{**o, "stock": "0"} for o in self.OFERTAS]
        self.assertEqual(P.mejor_coste(sin_ninguno, cfg())["proveedor"], "Distribuidor")        # si ninguno tiene, se elige entre todos

    def test_ofertas_no_calculables_se_ignoran(self):
        ofertas = [{"proveedor": "A", "canal": "fabricante", "coste": "10", "moneda": "GBP"}, self.OFERTAS[1]]
        self.assertEqual(P.mejor_coste(ofertas, cfg())["proveedor"], "Distribuidor")
        self.assertIsNone(P.mejor_coste([ofertas[0]], cfg()))
        self.assertIsNone(P.mejor_coste([], cfg()))


class TestConfiguracion(unittest.TestCase):
    def test_valores_imposibles_son_un_error_claro(self):
        for malo in ({"margen": {"por_defecto": 1}}, {"margen": {"por_defecto": -0.1}}, {"margen": {"familias": {"X": 2}}}, {"margen": {"base": "coste"}},
                     {"redondeo": {"modo": "raro"}}, {"redondeo": {"modo": "terminar_en", "terminacion": 1.5}}, {"margen": {"por_defecto": "abc"}}):
            with self.assertRaises(P.ErrorPrecios, msg=str(malo)):
                P.configuracion(malo)

    def test_la_configuracion_real_es_valida_y_es_el_50_sobre_la_venta(self):
        raw = yaml.safe_load((RAIZ / "config" / "precios.yaml").read_text(encoding="utf-8"))
        c = P.configuracion(raw)
        self.assertEqual((c["margen"]["por_defecto"], c["redondeo"]["modo"]), (D("0.5"), "centimo"))
        self.assertIn("cambio_a_eur.USD", c["provisional"])                          # lo provisional está marcado como tal hasta que se confirme
        self.assertEqual(P.calcular(100, "EUR", "distribuidor", "Otros", c).venta, D("200.00"))


if __name__ == "__main__":
    unittest.main()
