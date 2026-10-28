"""Embudo propio de licitaciones: transiciones, fechas, cálculo del resumen (función pura) y datos que se toman del motor."""
import unittest
from datetime import datetime, timedelta, timezone

import _sin_servicios  # noqa: F401

try:
    from cerebro.licitaciones import embudo
    from cerebro.licitaciones.embudo import ErrorEmbudo, calcular_resumen, datos_de_ficha, desde_periodo, fechas_del_cambio, validar_cambio
except ImportError as e:      # pragma: no cover
    raise unittest.SkipTest(str(e))

ZONA = "Europe/Madrid"
AHORA = datetime(2026, 10, 28, 14, 0, tzinfo=timezone.utc)          # 15:00 en Madrid (horario de invierno desde el 25/10)
CFG = {
    "pesos": {"cpv": 40, "zona": 20, "importe": 15, "plazo": 15, "procedimiento": 10}, "importe_max": 1_000_000,
    "cpv": [{"codigo": "72000000", "area": "TI"}], "zona": {"prioritaria": "ES51", "pais": "ES"},
}


def fila(estado, creado_h=48, **kw):
    f = {"estado": estado, "creado": AHORA - timedelta(hours=creado_h), "decidida_en": None, "presentada_en": None, "resuelta_en": None, "motivo_perdida": None}
    f.update(kw)
    return f


class TestTransiciones(unittest.TestCase):
    def test_el_camino_normal(self):
        for a, b in (("detectada", "en_estudio"), ("en_estudio", "presentada"), ("presentada", "ganada"), ("detectada", "descartada"), ("descartada", "en_estudio")):
            self.assertIsNone(validar_cambio(a, b, None), (a, b))

    def test_no_se_saltan_pasos_ni_se_sale_de_un_estado_final(self):
        for a, b in (("detectada", "presentada"), ("detectada", "ganada"), ("en_estudio", "ganada"), ("ganada", "perdida"), ("perdida", "en_estudio"),
                     ("presentada", "descartada"), ("en_estudio", "detectada"), ("detectada", "detectada")):
            with self.assertRaises(ErrorEmbudo, msg=(a, b)):
                validar_cambio(a, b, None)

    def test_estado_desconocido(self):
        with self.assertRaises(ErrorEmbudo):
            validar_cambio("detectada", "volando", None)

    def test_perdida_pide_un_motivo_de_la_lista_y_solo_ella_lo_lleva(self):
        self.assertEqual(validar_cambio("presentada", "perdida", "precio"), "precio")
        for mal in (None, "", "porque sí"):
            with self.assertRaises(ErrorEmbudo, msg=mal):
                validar_cambio("presentada", "perdida", mal)
        with self.assertRaises(ErrorEmbudo):
            validar_cambio("presentada", "ganada", "precio")

    def test_fechas_que_se_anotan(self):
        self.assertEqual(fechas_del_cambio("detectada", "en_estudio", AHORA), {"decidida_en": AHORA})
        self.assertEqual(fechas_del_cambio("detectada", "descartada", AHORA), {"decidida_en": AHORA})
        self.assertEqual(fechas_del_cambio("descartada", "en_estudio", AHORA), {})            # reabrir no cambia cuándo se decidió por primera vez
        self.assertEqual(fechas_del_cambio("en_estudio", "presentada", AHORA), {"presentada_en": AHORA})
        self.assertEqual(fechas_del_cambio("presentada", "ganada", AHORA), {"resuelta_en": AHORA})
        self.assertEqual(fechas_del_cambio("presentada", "perdida", AHORA), {"resuelta_en": AHORA})


class TestPeriodo(unittest.TestCase):
    def test_hoy_es_desde_las_00_00_locales(self):
        self.assertEqual(desde_periodo(AHORA, ZONA, 1), datetime(2026, 10, 27, 23, 0, tzinfo=timezone.utc))      # 00:00 del 28 en Madrid (UTC+1)

    def test_siete_dias_incluyen_hoy_y_respetan_el_cambio_de_hora(self):
        # El 25/10/2026 se pasa de horario de verano a invierno: las 00:00 del 22/10 son UTC+2.
        self.assertEqual(desde_periodo(AHORA, ZONA, 7), datetime(2026, 10, 21, 22, 0, tzinfo=timezone.utc))


class TestResumen(unittest.TestCase):
    def test_vacio(self):
        r = calcular_resumen([], 30, AHORA, ZONA)
        self.assertEqual(r["por_estado"], {e: 0 for e in embudo.ESTADOS})
        self.assertEqual(r["tasa_exito"], {"valor": None, "ganadas": 0, "decididas": 0, "minimo": 5})
        self.assertEqual((r["motivos_perdida"], r["horas_hasta_decision_p50"]), ([], None))

    def test_foto_y_periodo(self):
        dentro, fuera = AHORA - timedelta(days=2), AHORA - timedelta(days=60)
        filas = [
            fila("detectada", 10),
            fila("en_estudio", 30, decidida_en=dentro),
            fila("presentada", 100, decidida_en=dentro, presentada_en=dentro),
            fila("ganada", 900, decidida_en=fuera, presentada_en=fuera, resuelta_en=dentro),
            fila("perdida", 900, decidida_en=fuera, presentada_en=fuera, resuelta_en=fuera, motivo_perdida="precio"),    # resuelta fuera del periodo
            fila("descartada", 5, decidida_en=dentro),
        ]
        r = calcular_resumen(filas, 30, AHORA, ZONA)
        self.assertEqual(r["por_estado"], {"detectada": 1, "en_estudio": 1, "presentada": 1, "ganada": 1, "perdida": 1, "descartada": 1})
        self.assertEqual(r["en_periodo"], {"detectadas": 4, "presentadas": 1, "ganadas": 1, "perdidas": 0, "descartadas": 1})

    def test_la_tasa_de_exito_necesita_al_menos_cinco_decididas(self):
        d = AHORA - timedelta(days=1)
        filas = [fila("ganada", resuelta_en=d)] + [fila("perdida", resuelta_en=d, motivo_perdida="precio")] * 3
        self.assertIsNone(calcular_resumen(filas, 30, AHORA, ZONA)["tasa_exito"]["valor"])
        filas.append(fila("ganada", resuelta_en=d))
        t = calcular_resumen(filas, 30, AHORA, ZONA)["tasa_exito"]
        self.assertEqual((t["valor"], t["ganadas"], t["decididas"]), (0.4, 2, 5))

    def test_motivos_de_perdida_ordenados_y_acotados(self):
        d = AHORA - timedelta(days=1)
        motivos = ["precio"] * 3 + ["solvencia"] * 2 + ["plazo", "otro", "documentacion", "puntuacion_tecnica"]
        r = calcular_resumen([fila("perdida", resuelta_en=d, motivo_perdida=m) for m in motivos], 30, AHORA, ZONA)
        self.assertEqual(len(r["motivos_perdida"]), 5)
        self.assertEqual([(m["motivo"], m["total"]) for m in r["motivos_perdida"][:2]], [("precio", 3), ("solvencia", 2)])
        self.assertEqual(r["motivos_perdida"][0]["etiqueta"], embudo.MOTIVOS_PERDIDA["precio"])

    def test_mediana_de_horas_hasta_decidir(self):
        filas = [fila("en_estudio", 10, decidida_en=AHORA - timedelta(hours=7)), fila("en_estudio", 30, decidida_en=AHORA - timedelta(hours=5)),
                 fila("descartada", 60, decidida_en=AHORA - timedelta(hours=1))]
        # Las tres decisiones son del periodo: de creada a decidida pasaron 3, 25 y 59 horas; la mediana es 25.
        self.assertEqual(calcular_resumen(filas, 7, AHORA, ZONA)["horas_hasta_decision_p50"], 25.0)

    def test_dias_fuera_de_rango(self):
        for d in (0, -1, 366):
            with self.assertRaises(ErrorEmbudo):
                calcular_resumen([], d, AHORA, ZONA)


class TestDatosDeLaFicha(unittest.TestCase):
    FICHA = {
        "id": "0b1f7a3e-1111-4222-8333-444444444444", "version_entidad": 3, "expediente": "2026/045", "titulo": "Videovigilancia   del puerto",
        "comprador": {"nombre": "Ayuntamiento de Girona", "nif": "P1708500A"}, "estado": "abierta", "procedimiento": "abierto",
        "cpv": ["32323500"], "nuts": ["ES512"], "plazos": {"presentacion": "2026-11-20T10:00:00Z"}, "url_origen": "https://contrataciondelestado.es/x",
        "importes": [{"valor": "180000.00", "moneda": "EUR", "impuestos": "sin_iva", "significado": "presupuesto_base"},
                     {"valor": "200000.00", "moneda": "EUR", "impuestos": "sin_iva", "significado": "valor_estimado"}],
    }

    def test_campos_de_la_fila(self):
        d = datos_de_ficha(self.FICHA, CFG, AHORA)
        self.assertEqual((d["motor_id"], d["motor_version"], d["expediente"], d["organismo"]), (self.FICHA["id"], 3, "2026/045", "Ayuntamiento de Girona"))
        self.assertEqual((d["titulo"], str(d["importe"]), d["fecha_limite"], d["enlace"]), ("Videovigilancia del puerto", "200000.00", "2026-11-20T10:00:00Z", "https://contrataciondelestado.es/x"))
        self.assertEqual(d["cpv"], ["32323500"])
        self.assertIsInstance(d["encaje"], int)

    def test_sin_expediente_titulo_ni_importe(self):
        d = datos_de_ficha({"id": "0b1f7a3e-1111-4222-8333-444444444444", "importes": []}, CFG, AHORA)
        self.assertEqual((d["expediente"], d["titulo"], d["importe"], d["fecha_limite"]), ("0b1f7a3e-1111-4222-8333-444444444444", "(sin título)", None, None))

    def test_un_enlace_que_no_es_web_no_se_guarda(self):
        d = datos_de_ficha({**self.FICHA, "url_origen": "javascript:alert(1)"}, CFG, AHORA)
        self.assertIsNone(d["enlace"])


if __name__ == "__main__":
    unittest.main()
