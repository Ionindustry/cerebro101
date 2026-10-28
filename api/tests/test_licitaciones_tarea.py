"""La tarea del resumen de las 16:00: calendario, reintentos si el motor no responde, y que no se confunde con las tareas de los agentes."""
import unittest
from unittest import mock

import _sin_servicios  # noqa: F401

try:
    from celery.schedules import crontab
    from cerebro.tareas import celery_app
except ImportError as e:      # pragma: no cover
    raise unittest.SkipTest(str(e))


class TestTarea(unittest.TestCase):
    def test_se_programa_todos_los_dias_a_las_16_00_en_la_cola_lote(self):
        t = celery_app.app.conf.beat_schedule["resumen-licitaciones"]
        self.assertEqual(t["task"], "cerebro.tareas.celery_app.resumen_licitaciones")
        self.assertEqual(t["schedule"], crontab(minute="00", hour="16"))
        self.assertEqual(celery_app.app.conf.task_routes["cerebro.tareas.celery_app.resumen_licitaciones"], {"queue": "lote"})
        self.assertEqual(celery_app.app.conf.timezone, celery_app.ajustes.zona_horaria)

    def test_la_hora_sale_del_yaml_y_sin_el_el_valor_por_defecto_es_16(self):
        self.assertEqual(celery_app._resumen_licitaciones()["resumen-licitaciones"]["schedule"], crontab(minute="00", hour="16"))
        malo = mock.Mock(dir_config=mock.Mock(__truediv__=lambda s, o: mock.Mock(read_text=mock.Mock(side_effect=OSError))))
        with mock.patch.object(celery_app, "ajustes", malo):
            self.assertEqual(celery_app._resumen_licitaciones()["resumen-licitaciones"]["schedule"], crontab(minute="00", hour="16"))

    def test_el_resumen_de_licitaciones_no_esta_entre_las_tareas_de_los_agentes(self):
        self.assertFalse(any(k.startswith("agente-") and "licitaciones" in k and "resumen" in k for k in celery_app.app.conf.beat_schedule))

    def test_con_el_motor_caido_reintenta_y_con_datos_o_agotados_los_reintentos_no(self):
        f = celery_app._reintentar_resumen
        self.assertFalse(f({"estado": "ok"}, 0, 3))
        self.assertTrue(f({"estado": "sin_datos"}, 0, 3))
        self.assertTrue(f({"estado": "sin_datos"}, 2, 3))
        self.assertFalse(f({"estado": "sin_datos"}, 3, 3))       # agotados: se queda guardado el «sin_datos» explicado
        self.assertEqual(celery_app.resumen_licitaciones.max_retries, 3)


if __name__ == "__main__":
    unittest.main()
