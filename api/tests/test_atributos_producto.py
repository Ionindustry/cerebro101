"""Atributos normalizados de producto: lectura por reglas, requisitos del pliego y comprobación «iguala o supera» hecha por el código."""
import unittest

import _sin_servicios  # noqa: F401
from cerebro import atributos_producto as AP


class TestExtraer(unittest.TestCase):
    def test_camara_completa(self):
        a = AP.extraer("Cámara bullet 4 MP, lente 2,8 mm, IP67, IK10, 0,0005 lux, microSD hasta 512 GB, PoE")
        self.assertEqual(a["resolucion_mp"], 4.0)
        self.assertEqual((a["focal_min_mm"], a["focal_max_mm"]), (2.8, 2.8))
        self.assertEqual((a["ip"], a["ik"]), (67.0, 10.0))
        self.assertEqual(a["luz_min_lux"], 0.0005)
        self.assertEqual(a["almacenamiento_gb"], 512.0)
        self.assertEqual(a["poe"], 1.0)

    def test_resolucion_por_pixeles_y_focal_en_rango(self):
        a = AP.extraer("Domo 2560x1440 varifocal 2.7-13.5 mm")
        self.assertAlmostEqual(a["resolucion_mp"], 3.69, 2)
        self.assertEqual((a["focal_min_mm"], a["focal_max_mm"]), (2.7, 13.5))

    def test_dimensiones_no_son_focal(self):
        self.assertNotIn("focal_min_mm", AP.extraer("Caja de conexión 120x80x50 mm"))

    def test_sin_datos_no_inventa(self):
        self.assertEqual(AP.extraer("Cable UTP categoría 6"), {})

    def test_exigencia_toma_el_ip_mas_bajo_aceptable(self):
        self.assertEqual(AP.extraer("IP66/IP67", para_exigencia=True)["ip"], 66.0)
        self.assertEqual(AP.extraer("IP66/IP67")["ip"], 67.0)


class TestComprobar(unittest.TestCase):
    def test_restricciones_del_requisito(self):
        r = AP.restricciones("Cámara de 4 MP, IP66 e IK08, lente 8-32 mm")
        claves = {(x["atributo"], x["op"], x["valor"]) for x in r}
        self.assertIn(("resolucion_mp", ">=", 4.0), claves)
        self.assertIn(("ip", ">=", 66.0), claves)
        self.assertIn(("ik", ">=", 8.0), claves)
        self.assertIn(("focal_min_mm", "<=", 8.0), claves)
        self.assertIn(("focal_max_mm", ">=", 32.0), claves)

    def test_iguala_o_supera_incumple_y_sin_dato(self):
        rest = AP.restricciones("Cámara de 4 MP, IP66, IK10")
        r = AP.evaluar(rest, AP.extraer("Cámara 2 MP IP67"))
        self.assertEqual([x[0] for x in r["cumple"]].count("ip"), 1)
        self.assertEqual(len(r["no_cumple"]), 1)      # resolución
        self.assertEqual(len(r["sin_dato"]), 1)       # IK no aparece
        self.assertIn("NO cumple", AP.texto_de_comprobacion(r))

    def test_orden_baja_al_que_incumple_pero_no_al_que_no_tiene_dato(self):
        rest = AP.restricciones("Cámara de 4 MP")
        bueno = AP.orden(AP.evaluar(rest, {"resolucion_mp": 4.0}))
        sin = AP.orden(AP.evaluar(rest, {}))
        malo = AP.orden(AP.evaluar(rest, {"resolucion_mp": 2.0}))
        self.assertLess(bueno, malo)
        self.assertLess(sin, malo)

    def test_sin_requisitos_no_dice_nada(self):
        self.assertEqual(AP.texto_de_comprobacion(AP.evaluar([], {"ip": 67.0})), "")


if __name__ == "__main__":
    unittest.main()
