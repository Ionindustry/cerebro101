"""Toda tarea del calendario debe ir a una cola que el worker escucha (docker-compose: peticiones y lote); si no, no se ejecuta nunca."""
import unittest

import _sin_servicios  # noqa: F401
try:
    from cerebro.tareas import celery_app as C
except ImportError as e:      # pragma: no cover
    raise unittest.SkipTest(str(e))


class TestRutas(unittest.TestCase):
    def test_las_tareas_del_calendario_tienen_cola_que_escucha_el_worker(self):
        rutas = C.app.conf.task_routes
        for nombre, cfg in C.app.conf.beat_schedule.items():
            tarea = cfg["task"]
            if tarea.endswith("ejecutar_programada"):
                continue
            self.assertIn(tarea, rutas, f"{nombre}: {tarea} sin cola asignada")
            self.assertIn(rutas[tarea]["queue"], ("peticiones", "lote"), nombre)


if __name__ == "__main__":
    unittest.main()
