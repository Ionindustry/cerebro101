"""Aptitud de 101.cat frente a los requisitos del pliego: sugerencias prudentes a partir del perfil de la empresa (la matriz de cumplimiento la sigue anotando una persona)."""
import unittest

import _sin_servicios  # noqa: F401

from cerebro.licitaciones import aptitud as A

NUEVA = {"nueva_creacion": True, "rolece": "en trámite", "seguro_rc": "300.000 €", "experiencia": "20 años en videovigilancia",
         "certificaciones": ["ISO 9001", "ISO 14001", "ISO 27001", "ENS nivel alto (en proceso de certificación)"]}


def req(tipo, resumen, valor="", cita=""):
    return {"tipo": tipo, "resumen": resumen, "valor": valor, "cita": cita}


class TestSugerir(unittest.TestCase):
    def test_sin_perfil_no_se_sugiere_nada(self):
        self.assertIsNone(A.sugerir(req("solvencia_economica", "Volumen anual de negocios de 500.000 €"), None))
        self.assertIsNone(A.sugerir(req("solvencia_economica", "Volumen anual de negocios"), {}))

    def test_volumen_de_negocios_no_lo_puede_acreditar_una_empresa_nueva_y_se_dan_las_vias(self):
        s = A.sugerir(req("solvencia_economica", "Volumen anual de negocios mínimo de 300.000 € en el mejor de los tres últimos ejercicios"), NUEVA)
        self.assertEqual(s["sugerencia"], "no_cumple")
        self.assertTrue(any("UTE" in v for v in s["vias"]) and any("medios" in v for v in s["vias"]))
        self.assertIsNone(A.sugerir(req("solvencia_economica", "Volumen anual de negocios mínimo"), {**NUEVA, "nueva_creacion": False}))

    def test_experiencia_por_trabajos_es_no_cumple_pero_lo_del_equipo_consta(self):
        s = A.sugerir(req("solvencia_tecnica", "Relación de los principales servicios similares ejecutados en los últimos tres años"), NUEVA)
        self.assertEqual(s["sugerencia"], "no_cumple")
        self.assertIn("20 años en videovigilancia", s["motivo"])
        self.assertTrue(any("otros medios" in v for v in s["vias"]))

    def test_certificaciones(self):
        self.assertEqual(A.sugerir(req("tecnico", "Certificado ISO 9001 y UNE-EN ISO 14001 en vigor"), NUEVA)["sugerencia"], "cumple")
        self.assertEqual(A.sugerir(req("tecnico", "Estar certificado en el Esquema Nacional de Seguridad nivel alto"), NUEVA)["sugerencia"], "parcial")
        s = A.sugerir(req("tecnico", "Certificación ISO 45001 de seguridad y salud"), NUEVA)
        self.assertEqual((s["sugerencia"], "45001" in s["motivo"]), ("no_cumple", True))
        self.assertIsNone(A.sugerir(req("tecnico", "El licitador tendrá medios suficientes"), NUEVA))

    def test_rolece(self):
        r = req("administrativo", "Estar inscrito en el ROLECE")
        self.assertEqual(A.sugerir(r, NUEVA)["sugerencia"], "parcial")
        self.assertEqual(A.sugerir(r, {**NUEVA, "rolece": "sí"})["sugerencia"], "cumple")
        self.assertEqual(A.sugerir(r, {**NUEVA, "rolece": "no"})["sugerencia"], "no_cumple")
        self.assertEqual(A.sugerir(r, {**NUEVA, "rolece": ""})["sugerencia"], "revisar")

    def test_seguro_se_compara_con_el_importe_exigido(self):
        self.assertEqual(A.sugerir(req("solvencia_economica", "Seguro de responsabilidad civil con cobertura de 150.000 €"), NUEVA)["sugerencia"], "cumple")
        s = A.sugerir(req("solvencia_economica", "Seguro de responsabilidad civil de al menos 600.000 euros"), NUEVA)
        self.assertEqual(s["sugerencia"], "parcial")
        self.assertIn("ampliar", s["motivo"])
        self.assertEqual(A.sugerir(req("solvencia_economica", "Seguro de responsabilidad civil"), NUEVA)["sugerencia"], "revisar")
        self.assertEqual(A.sugerir(req("otro", "Seguro de responsabilidad civil"), {"nueva_creacion": True})["sugerencia"], "revisar")

    def test_clasificacion_empresarial(self):
        self.assertEqual(A.sugerir(req("administrativo", "Clasificación empresarial: Grupo P, subgrupo 1, categoría 2"), NUEVA)["sugerencia"], "no_cumple")
        self.assertIsNone(A.sugerir(req("administrativo", "No se exige clasificación empresarial: la solvencia se acredita por los medios del apartado 7"), NUEVA))

    def test_importe_toma_el_mayor_en_euros(self):
        self.assertEqual(A.importe("entre 100.000 € y 1.500.000,50 euros"), 1500000.5)
        self.assertEqual(A.importe("600000 €"), 600000.0)
        self.assertIsNone(A.importe("sin cifras 2026"))

    def test_los_requisitos_de_entrada_no_se_tocan_y_el_resumen_cuenta(self):
        reqs = [req("solvencia_economica", "Volumen anual de negocios de 500.000 €"), req("administrativo", "Estar inscrito en el ROLECE"), req("plazo", "Entrega en 30 días")]
        out = A.con_sugerencias(reqs, NUEVA)
        self.assertNotIn("sugerencia", reqs[0])
        self.assertIsNone(out[2]["sugerencia"])
        r = A.resumen(out)
        self.assertEqual((r["no_cumple"], r["parcial"], r["bloqueos"]), (1, 1, 1))
        self.assertIn("orientativa", r["aviso"])


if __name__ == "__main__":
    unittest.main()
