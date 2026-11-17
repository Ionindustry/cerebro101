"""El identificador de la licitación tal como lo escribe un modelo local: se recorta lo que sobra; nada se inventa."""
import unittest

import _sin_servicios  # noqa: F401

try:
    from cerebro.licitaciones import identificador as I
    from cerebro.licitaciones import ofertas as O
    from cerebro.licitaciones import pliegos as P
except ImportError as e:      # pragma: no cover
    raise unittest.SkipTest(str(e))

U = "d9cfcbaa-3f95-4677-961b-6c131e529021"


class TestIdentificador(unittest.TestCase):
    def test_acepta_lo_que_escriben_los_modelos(self):
        for v in (U, U.upper(), f" {U} ", f"«{U}»", f'"{U}"', f"[{U}]", f"{U}.", f"{U} (Renting de cámaras de vigilancia)", f"licitacion={U}", f"{U} {U}"):
            self.assertEqual(I.limpiar(v), U, v)

    def test_rechaza_lo_que_no_es_un_unico_identificador(self):
        otro = "0b1f7a3e-1111-4222-8333-444444444444"
        for v in (None, 5, "", "Renting de cámaras", "d9cfcbaa-3f95-4677-961b", f"{U} {otro}", U + "0", "a" + U, "x" * 300 + U, ["x"]):
            self.assertIsNone(I.limpiar(v), repr(v)[:40])

    def test_pliegos_y_ofertas_lo_usan(self):
        self.assertEqual(P._id_valido(f"«{U}»"), U)
        self.assertEqual(O._id(f"{U} (título)"), U)
        with self.assertRaises(P.ErrorPliego):
            P._id_valido("el que te dije")
        with self.assertRaises(O.ErrorOferta):
            O._id(None)


if __name__ == "__main__":
    unittest.main()
