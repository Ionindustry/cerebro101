"""Cada sitio de la API que encola una tarea de Celery debe importar `celery` en su propia función (un NameError se vería como «No se ha podido hacer» en el panel)."""
import ast
import unittest
from pathlib import Path

MAIN = Path(__file__).resolve().parents[1] / "cerebro" / "api" / "main.py"


class TestEncolar(unittest.TestCase):
    def test_todas_las_funciones_que_encolan_importan_celery(self):
        arbol = ast.parse(MAIN.read_text(encoding="utf-8"))
        a_nivel_de_modulo = any(isinstance(n, (ast.Import, ast.ImportFrom)) and any((a.asname or a.name) == "celery" for a in n.names) for n in arbol.body)
        malas = []
        for f in ast.walk(arbol):
            if not isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            usa = any(isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and c.func.attr == "send_task" and isinstance(c.func.value, ast.Name) and c.func.value.id == "celery" for c in ast.walk(f))
            importa = any(isinstance(n, ast.ImportFrom) and any((a.asname or a.name) == "celery" for a in n.names) for n in ast.walk(f))
            if usa and not importa and not a_nivel_de_modulo:
                malas.append(f.name)
        self.assertEqual(malas, [], f"usan `celery` sin importarlo: {malas}")


if __name__ == "__main__":
    unittest.main()
