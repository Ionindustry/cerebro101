import unittest

from cerebro.licitaciones import equivalencia as E
from cerebro.licitaciones import familias as F

TABLA = {"cctv": (("resolucion_mp", "MP efectiva"), ("wdr_db", "WDR real")), "incendio": (("norma_en54", "Partes y certificado"),)}


class TestFamilias(unittest.TestCase):
    def test_el_fichero_real_se_lee(self):
        t = F.familias()
        for fam in ("comun", "cctv", "intrusion", "control_acceso", "incendio", "intercom", "redes_poe", "vms"):
            self.assertIn(fam, t)
        self.assertIn("resolucion_mp", [c for c, _ in t["cctv"]])

    def test_detecta_familia_por_pistas(self):
        self.assertEqual(F.detectar("Suministro de cámaras IP de 4 megapíxeles y NVR"), ["cctv"])
        self.assertEqual(F.detectar("Central de incendios conforme a EN 54 con lazo")[0], "incendio")
        self.assertEqual(F.detectar("Servicio de limpieza de edificios"), [])

    def test_no_detecta_por_trozos_de_palabra(self):
        self.assertEqual(F.detectar("calarmas arcoiris"), [])

    def test_guia_lista_campos_y_vacia_sin_familia(self):
        g = F.guia("cámaras con WDR", TABLA)
        self.assertIn("resolucion_mp (MP efectiva)", g)
        self.assertIn("no añadas parámetros", g)
        self.assertEqual(F.guia("limpieza", TABLA), "")

    def test_semillas(self):
        s = F.semillas()
        self.assertGreaterEqual(len(s), 20)
        self.assertTrue(all(x["fabricante"] and x["url"].startswith("https://") for x in s))

    def test_el_prompt_incluye_la_guia_solo_si_hay(self):
        m = E.construir_mensajes("T", "O", "pliego", "reqs", "evid", "GUIA-X")
        self.assertIn("GUIA-X", m[1]["content"])
        m = E.construir_mensajes("T", "O", "pliego", "reqs", "evid")
        self.assertNotIn("Guía por familia", m[1]["content"])


if __name__ == "__main__":
    unittest.main()
