import unittest

from cerebro.licitaciones import referencias as R

MARCAS = ["Hikvision", "Axis", "Milesight", "Western Digital", "Network Optix"]


def pag(texto, doc=1, p=1):
    return [(doc, p, texto)]


class Extraccion(unittest.TestCase):
    def test_marca_y_modelo_con_equivalente(self):
        r = R.extraer(pag("Se suministrarán cámaras domo Hikvision modelo DS-2CD2143G2-I o equivalente, con óptica motorizada."), MARCAS)
        self.assertEqual(len(r), 1)
        self.assertEqual((r[0]["marca"], r[0]["modelo"]), ("Hikvision", "DS-2CD2143G2-I"))
        self.assertTrue(r[0]["equivalente"])
        self.assertIn("o equivalente", r[0]["cita"])
        self.assertEqual((r[0]["documento"], r[0]["pagina"]), (1, 1))

    def test_sin_clausula_de_equivalente(self):
        r = R.extraer(pag("Grabador Milesight MS-N5016-UH de 16 canales."), MARCAS)
        self.assertEqual(r[0]["modelo"], "MS-N5016-UH")
        self.assertFalse(r[0]["equivalente"])

    def test_marca_sin_modelo_solo_si_no_hay_otra_con_modelo(self):
        r = R.extraer(pag("Marca Axis o similar. Más adelante, Axis P3245-V."), MARCAS)
        self.assertEqual([(x["marca"], x["modelo"]) for x in r], [("Axis", "P3245-V")])
        r2 = R.extraer(pag("Equipos de la marca Axis o similar."), MARCAS)
        self.assertEqual([(x["marca"], x["modelo"]) for x in r2], [("Axis", "")])
        self.assertTrue(r2[0]["equivalente"])

    def test_palabra_entera_y_sin_repetir(self):
        self.assertEqual(R.extraer(pag("Axisimetría 1234 y taxis 5678"), MARCAS), [])
        r = R.extraer([(1, 1, "Hikvision DS-2CD2143G2-I"), (2, 7, "hikvision ds-2cd2143g2-i o equivalente")], MARCAS)
        self.assertEqual(len(r), 1)
        self.assertTrue(r[0]["equivalente"])

    def test_el_modelo_necesita_numeros(self):
        r = R.extraer(pag("Cámara Hikvision profesional de gama alta."), MARCAS)
        self.assertEqual([(x["marca"], x["modelo"]) for x in r], [("Hikvision", "")])

    def test_consultas_y_texto_para_el_modelo(self):
        r = R.extraer(pag("Hikvision DS-2CD2143G2-I o equivalente. Axis genérica."), MARCAS)
        self.assertEqual(R.consultas(r), ["Hikvision DS-2CD2143G2-I"])
        t = R.texto_para_modelo(r)
        self.assertIn("DS-2CD2143G2-I", t)
        self.assertIn("o equivalente", t)
        self.assertEqual(R.texto_para_modelo([]), "")

    def test_marcas_conocidas_une_config_y_extra(self):
        m = R.marcas_conocidas(["A-Secur Marca X", "(sin marca)", "ab"])
        self.assertIn("Hikvision", m)
        self.assertIn("A-Secur Marca X", m)
        self.assertNotIn("(sin marca)", m)
        self.assertNotIn("ab", m)


if __name__ == "__main__":
    unittest.main()
