"""La batería de enrutado debe ser coherente con las fichas: si se renombra un agente o un
departamento, esta prueba avisa antes de que la medición dé fallos falsos."""
import sys
import unittest
from collections import Counter
from pathlib import Path

import _sin_servicios  # noqa: F401

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "scripts"))

from cerebro.registro import registro  # noqa: E402
from evaluar_enrutado import cargar, resumen  # noqa: E402


class TestBateria(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.preguntas = cargar()
        cls.reg = registro()

    def test_son_50_con_ids_unicos(self):
        self.assertEqual(len(self.preguntas), 50)
        self.assertEqual(len({q["id"] for q in self.preguntas}), 50)
        self.assertEqual(len({q["pregunta"] for q in self.preguntas}), 50)

    def test_departamentos_y_agentes_existen_y_coinciden(self):
        for q in self.preguntas:
            self.assertIn(q["departamento"], self.reg.departamentos, q["id"])
            self.assertIn(q["agente"], self.reg.fichas, q["id"])
            self.assertEqual(self.reg.fichas[q["agente"]].departamento, q["departamento"], q["id"])

    def test_cubre_todos_los_departamentos(self):
        cubiertos = Counter(q["departamento"] for q in self.preguntas)
        self.assertEqual(set(cubiertos), set(self.reg.departamentos))
        self.assertGreaterEqual(min(cubiertos.values()), 2)

    def test_hay_preguntas_en_catalan(self):
        self.assertGreaterEqual(sum(q.get("idioma") == "ca" for q in self.preguntas), 4)

    def test_resumen(self):
        r = resumen([{"departamento": "a", "ok_departamento": True, "ok_agente": False},
                     {"departamento": "a", "ok_departamento": True, "ok_agente": True}])
        self.assertEqual((r["acierto_departamento"], r["acierto_agente"]), (1.0, 0.5))
        self.assertEqual(r["por_departamento"], {"a": "2/2"})


if __name__ == "__main__":
    unittest.main()
