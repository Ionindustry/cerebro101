"""Importes de la oferta para los modelos de proposición económica: formato español y cantidad en letra (en un documento que se firma tiene que ser exacta)."""
import unittest
from decimal import Decimal as D

import _sin_servicios  # noqa: F401

from cerebro.licitaciones import importes as I


class TestALetras(unittest.TestCase):
    CASOS = {
        0: "cero", 1: "un", 2: "dos", 15: "quince", 16: "dieciséis", 20: "veinte", 21: "veintiún", 22: "veintidós", 29: "veintinueve", 30: "treinta", 31: "treinta y un", 45: "cuarenta y cinco",
        99: "noventa y nueve", 100: "cien", 101: "ciento un", 110: "ciento diez", 121: "ciento veintiún", 200: "doscientos", 500: "quinientos", 999: "novecientos noventa y nueve",
        1000: "mil", 1001: "mil un", 1021: "mil veintiún", 1100: "mil cien", 2000: "dos mil", 21000: "veintiún mil", 31000: "treinta y un mil", 100000: "cien mil", 101000: "ciento un mil",
        121000: "ciento veintiún mil", 125000: "ciento veinticinco mil", 999999: "novecientos noventa y nueve mil novecientos noventa y nueve", 1000000: "un millón", 1000001: "un millón un",
        1100000: "un millón cien mil", 2000000: "dos millones", 21000000: "veintiún millones", 125000000: "ciento veinticinco millones", 1000000000: "mil millones",
        1001000000: "mil un millones", 1021000000: "mil veintiún millones", 2500000000: "dos mil quinientos millones",
    }

    def test_casos(self):
        for n, esperado in self.CASOS.items():
            self.assertEqual(I.a_letras(n), esperado, n)

    def test_sin_apocope_para_el_final(self):
        self.assertEqual(I.a_letras(21, apocope=False), "veintiuno")
        self.assertEqual(I.a_letras(31, apocope=False), "treinta y uno")
        self.assertEqual(I.a_letras(21000, apocope=False), "veintiún mil")                  # delante de «mil» siempre es «un»
        self.assertEqual(I.a_letras(1000001, apocope=False), "un millón uno")

    def test_fuera_de_rango_o_de_otro_tipo(self):
        for malo in (-1, 10 ** 12, 1.5, "3", None, True):
            with self.assertRaises(ValueError, msg=str(malo)):
                I.a_letras(malo)

    def test_sin_dobles_espacios_ni_cortes(self):
        for n in range(0, 3000):
            t = I.a_letras(n)
            self.assertEqual(t, " ".join(t.split()), n)
            self.assertTrue(t and t == t.strip())


class TestEuros(unittest.TestCase):
    def test_en_letra(self):
        self.assertEqual(I.euros_en_letra(D("125000.50")), "ciento veinticinco mil euros con cincuenta céntimos")
        self.assertEqual(I.euros_en_letra(D("125000")), "ciento veinticinco mil euros")
        self.assertEqual(I.euros_en_letra(D("1")), "un euro")
        self.assertEqual(I.euros_en_letra(D("21.01")), "veintiún euros con un céntimo")
        self.assertEqual(I.euros_en_letra(D("0.99")), "cero euros con noventa y nueve céntimos")
        self.assertEqual(I.euros_en_letra(D("1000000")), "un millón de euros")                 # «de» delante de «euros» cuando son millones exactos
        self.assertEqual(I.euros_en_letra(D("2000000")), "dos millones de euros")
        self.assertEqual(I.euros_en_letra(D("1500000")), "un millón quinientos mil euros")
        self.assertEqual(I.euros_en_letra(D("2000000.25")), "dos millones de euros con veinticinco céntimos")
        self.assertEqual(I.euros_en_letra("31000.00"), "treinta y un mil euros")

    def test_sin_unidad_solo_si_no_hay_centimos(self):
        self.assertEqual(I.euros_en_letra(D("125000"), con_unidad=False), "ciento veinticinco mil")
        self.assertIsNone(I.euros_en_letra(D("125000.50"), con_unidad=False))                 # con céntimos no se puede decir bien: que lo escriba una persona
        self.assertIsNone(I.euros_en_letra(D("2000000"), con_unidad=False))                   # «dos millones euros» no es correcto: falta el «de»

    def test_redondeo_comercial_a_dos_decimales(self):
        self.assertEqual(I.euros(D("10.005")), D("10.01"))
        self.assertEqual(I.euros("10.004"), D("10.00"))
        self.assertEqual(I.euros_en_letra(D("0.005")), "cero euros con un céntimo")

    def test_importes_no_validos(self):
        for malo in ("abc", "-1", "1e20", None, float("nan")):
            with self.assertRaises(ValueError, msg=str(malo)):
                I.euros(malo)

    def test_formato_espanol(self):
        self.assertEqual(I.formato_es(D("125000.5")), "125.000,50")
        self.assertEqual(I.formato_es(D("0.5")), "0,50")
        self.assertEqual(I.formato_es(D("1234567.891")), "1.234.567,89")
        self.assertEqual(I.formato_es(D("999")), "999,00")
        self.assertEqual(I.porcentaje_es(D("21.00")), "21")
        self.assertEqual(I.porcentaje_es(D("10.5")), "10,5")
        self.assertEqual(I.porcentaje_es(D("0")), "0")


if __name__ == "__main__":
    unittest.main()
