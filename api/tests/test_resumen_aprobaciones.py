"""Dashboard de Aprobaciones: el cálculo de las cifras (sin base de datos)."""
import unittest
from datetime import datetime, timedelta, timezone

import _sin_servicios  # noqa: F401

from cerebro.aprobaciones.bandeja import calcular_resumen

AHORA = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)


def fila(dep, estado, creado_hace_h, decidido_hace_h=None, agente="cobros", accion="enviar_correo"):
    creado = AHORA - timedelta(hours=creado_hace_h)
    actualizado = AHORA - timedelta(hours=decidido_hace_h) if decidido_hace_h is not None else creado
    return {"departamento": dep, "agente": agente, "accion": accion, "estado": estado, "creado": creado, "actualizado": actualizado}


FILAS = [
    fila("finanzas", "pendiente", 50),
    fila("finanzas", "pendiente", 2),
    fila("comercial", "pendiente", 1, agente="comercial-1"),
    fila("finanzas", "aprobada", 30, 28),                       # tardó 2 h
    fila("finanzas", "aprobada", 10, 6),                        # tardó 4 h
    fila("comercial", "rechazada", 5, 4, accion="publicar"),    # tardó 1 h
]


class TestResumen(unittest.TestCase):
    def setUp(self):
        self.r = calcular_resumen(FILAS, 30, AHORA)

    def test_pendientes_por_departamento_y_la_mas_antigua(self):
        p = self.r["pendientes"]
        self.assertEqual((p["total"], p["por_departamento"]), (3, {"finanzas": 2, "comercial": 1}))
        self.assertEqual(p["espera_max_horas"], 50.0)
        self.assertTrue(p["mas_antigua"].startswith("2026-10-23"))

    def test_resueltas_tasa_de_aprobacion_y_tiempo_medio(self):
        r = self.r["resueltas"]
        self.assertEqual((r["total"], r["aprobadas"], r["rechazadas"], r["tasa_aprobacion"]), (3, 2, 1, 67))
        self.assertEqual(r["tiempo_medio_horas"], 2.3)                    # (2 + 4 + 1) / 3
        self.assertEqual(r["por_departamento"], {"finanzas": {"aprobadas": 2, "rechazadas": 0}, "comercial": {"aprobadas": 0, "rechazadas": 1}})

    def test_serie_por_dia_completa_con_ceros(self):
        s = self.r["por_dia"]
        self.assertEqual((len(s), s[-1]["dia"], s[0]["dia"]), (30, "2026-10-25", "2026-09-26"))
        hoy = s[-1]
        self.assertEqual((hoy["creadas"], hoy["aprobadas"], hoy["rechazadas"]), (4, 1, 1))   # creadas hoy: las de hace 1, 2, 5 y 10 h; la otra aprobada fue ayer
        self.assertEqual(s[-2]["aprobadas"], 1)
        self.assertEqual(sum(d["creadas"] for d in s), 6)
        self.assertEqual(s[3], {"dia": "2026-09-29", "creadas": 0, "aprobadas": 0, "rechazadas": 0})

    def test_agentes_y_acciones_mas_frecuentes(self):
        self.assertEqual(self.r["por_agente"][0], {"agente": "cobros", "total": 5})
        self.assertEqual(self.r["por_accion"][0], {"accion": "enviar_correo", "total": 5})

    def test_sin_datos_no_inventa_cifras(self):
        r = calcular_resumen([], 7, AHORA)
        self.assertEqual((r["pendientes"]["total"], r["pendientes"]["mas_antigua"], r["resueltas"]["tasa_aprobacion"], r["resueltas"]["tiempo_medio_horas"]),
                         (0, None, None, None))
        self.assertEqual(len(r["por_dia"]), 7)

    def test_los_dias_se_cuentan_en_la_zona_de_la_empresa(self):
        # 23:30 UTC del 24 ya es el 25 en Madrid (horario de verano acabado: UTC+1)
        f = [{**fila("finanzas", "pendiente", 0), "creado": datetime(2026, 10, 24, 23, 30, tzinfo=timezone.utc)}]
        r = calcular_resumen(f, 3, AHORA)
        self.assertEqual([d["creadas"] for d in r["por_dia"]], [0, 0, 1])

    def test_los_dias_se_limitan(self):
        self.assertEqual(len(calcular_resumen([], 9999, AHORA)["por_dia"]), 365)
        self.assertEqual(len(calcular_resumen([], 0, AHORA)["por_dia"]), 1)


if __name__ == "__main__":
    unittest.main()
