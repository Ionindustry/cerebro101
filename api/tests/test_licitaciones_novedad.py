"""«Nuevo competidor»: configuración, mercado de comparación, cobertura del histórico y validación de la alerta."""
import unittest
from datetime import date

import _sin_servicios  # noqa: F401

try:
    from cerebro.licitaciones import alertas, novedad
except ImportError as e:      # pragma: no cover
    raise unittest.SkipTest(str(e))


class TestPuro(unittest.TestCase):
    def test_la_configuracion_tiene_defecto_y_limites(self):
        self.assertEqual(novedad.configuracion(None), {"cobertura_meses": 12})
        self.assertEqual(novedad.configuracion({"nuevo_competidor": {"cobertura_meses": 6}})["cobertura_meses"], 6)
        self.assertEqual(novedad.configuracion({"nuevo_competidor": {"cobertura_meses": 0}})["cobertura_meses"], 1)
        self.assertEqual(novedad.configuracion({"nuevo_competidor": {"cobertura_meses": 9999}})["cobertura_meses"], 120)

    def test_el_mercado_es_el_de_la_alerta_o_el_grupo_del_expediente(self):
        item = {"cpv": ["32323500", "32235000", "35125300"]}
        self.assertEqual(novedad.mercado_de({"cpv": ["72"], "nuts": ["ES51"]}, item), {"cpv": ["72"], "nuts": ["ES51"]})
        self.assertEqual(novedad.mercado_de({"q": "cámaras"}, item), {"cpv": ["3223", "3232", "3512"], "nuts": []})
        self.assertEqual(novedad.mercado_de({}, {}), {"cpv": [], "nuts": []})

    def test_hace_meses(self):
        self.assertEqual(novedad._hace_meses(date(2026, 10, 29), 12), date(2025, 10, 28))
        self.assertEqual(novedad._hace_meses(date(2026, 2, 10), 3), date(2025, 11, 10))
        self.assertEqual(novedad._hace_meses(date(2026, 1, 15), 1), date(2025, 12, 15))


class TestValidacion(unittest.TestCase):
    def test_solo_en_competencia_y_sin_lista_de_competidores(self):
        self.assertFalse(alertas.limpiar_solo_nuevos(False, False, []))
        self.assertTrue(alertas.limpiar_solo_nuevos(True, True, []))
        for args in ((True, False, []), (True, True, ["B12345678"])):
            with self.assertRaises(alertas.ErrorAlerta):
                alertas.limpiar_solo_nuevos(*args)
        with self.assertRaises(alertas.ErrorAlerta):
            alertas.limpiar_solo_nuevos("si", True, [])

    def test_los_ganadores_llevan_el_nif_entero_solo_si_se_pide(self):
        ficha = {"adjudicaciones": [{"lote": "1", "resultado": "adjudicado", "adjudicatario": {"nombre": "Pedro", "nif": "12345678Z"}, "importes": []}]}
        self.assertNotIn("_nif", alertas.ganadores(ficha, [])[0])
        self.assertEqual(alertas.ganadores(ficha, [], con_nif_completo=True)[0]["_nif"], "12345678Z")
        self.assertIsNone(alertas.ganadores(ficha, [], con_nif_completo=True)[0]["nif"])          # lo que se guarda no lleva el NIF de una persona


if __name__ == "__main__":
    unittest.main()
