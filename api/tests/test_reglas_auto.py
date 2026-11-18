"""Deducción automática de la fórmula del precio: patrones sobre el corpus real, verificación de lo que propone un modelo, interruptor."""
import asyncio
import json
import os
import unittest
from pathlib import Path
from unittest import mock

import _sin_servicios  # noqa: F401

try:
    from cerebro.licitaciones import reglas_auto as A, pliegos_sombra as S
except ImportError as e:      # pragma: no cover
    raise unittest.SkipTest(str(e))

CORPUS = Path(__file__).resolve().parent / "corpus_pliegos"
PLIEGO = "El precio se valorará así: la oferta con mayor baja obtiene 40 puntos y las demás de forma proporcional a la baja."


def corpus(nombre):
    d = json.loads((CORPUS / f"{nombre}.json").read_text(encoding="utf-8"))
    return "\n".join(x["texto"] for x in d["documentos"])


class TestReglasAuto(unittest.TestCase):
    def test_caser_proporcional(self):
        r = A.regla_desde_texto(corpus("caser_formula_real"))
        self.assertTrue(r)
        self.assertEqual((r[0]["formula"], r[0]["puntos_precio"]), ("proporcional_baja", 60))
        self.assertTrue(r[1])

    def test_santona_usa_el_criterio_principal(self):
        r = A.regla_desde_texto(corpus("santona_dos_criterios_economicos"))
        self.assertTrue(r)
        self.assertEqual(r[0]["puntos_precio"], 65)
        self.assertEqual(len(r[2]), 2)

    def test_sin_pistas(self):
        self.assertIsNone(A.regla_desde_texto("Texto sin nada de puntuación."))

    def test_modelo_verificado(self):
        ok = {"criterios": [{"nombre": "Precio", "formula": "proporcional_baja", "puntos": 40, "cita": "la oferta con mayor baja obtiene 40 puntos y las demás de forma proporcional"}], "puntos_total": 100}
        r = A.verificar(ok, PLIEGO)
        self.assertTrue(r)
        self.assertEqual((r[0]["formula"], r[0]["puntos_precio"]), ("proporcional_baja", 40))

    def test_lo_que_inventa_el_modelo_se_descarta(self):
        cita_ok = "la oferta con mayor baja obtiene 40 puntos y las demás"
        self.assertIsNone(A.verificar({"criterios": [{"nombre": "P", "formula": "inversa", "puntos": 40, "cita": "esta frase no está en el pliego para nada"}]}, PLIEGO))
        self.assertIsNone(A.verificar({"criterios": [{"nombre": "P", "formula": "inversa", "puntos": 99, "cita": cita_ok}]}, PLIEGO))
        self.assertIsNone(A.verificar({"criterios": [{"nombre": "P", "formula": "otra", "puntos": 40, "cita": cita_ok}]}, PLIEGO))
        self.assertIsNone(A.verificar(None, PLIEGO))

    def test_aviso_de_la_revision_cuando_es_automatica(self):
        av = S.avisos_formulas([], {"origen": "automatica", "formula": "inversa", "puntos_precio": 60.0, "cita": "x"})
        self.assertEqual(av[0]["nivel"], "ok")
        self.assertIn("deducido sola", av[0]["texto"])
        self.assertEqual(S.avisos_formulas([], {"origen": "persona", "formula": "inversa", "puntos_precio": 60.0}), [])

    def test_interruptor(self):
        with mock.patch.dict(os.environ, {"REGLAS_PRECIO_AUTOMATICAS": "0"}):
            self.assertEqual(asyncio.run(A.asegurar("x")), {"estado": "desactivada"})


if __name__ == "__main__":
    unittest.main()
