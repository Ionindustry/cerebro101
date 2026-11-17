"""Decisión de Dirección: una sola firma (Dirección) en los niveles simple y doble. Si se cambia, que sea a propósito."""
import unittest
from pathlib import Path

try:
    import yaml
except ImportError as e:      # pragma: no cover
    raise unittest.SkipTest(str(e))

RUTA = Path(__file__).resolve().parents[2] / "config" / "politicas_aprobacion.yaml"


class TestFirmaUnica(unittest.TestCase):
    def test_simple_y_doble_piden_solo_a_direccion(self):
        n = yaml.safe_load(RUTA.read_text(encoding="utf-8"))["niveles"]
        self.assertEqual(n["simple"]["aprobadores"], ["direccion"])
        self.assertEqual(n["doble"]["aprobadores"], ["direccion"])

    def test_presentar_una_licitacion_sigue_siendo_reservada(self):
        p = yaml.safe_load(RUTA.read_text(encoding="utf-8"))
        self.assertIn("presentar_licitacion", p["supervision"]["reservadas"])


if __name__ == "__main__":
    unittest.main()
