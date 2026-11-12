"""Análisis técnico del pliego: el texto que se envía, la comprobación de las citas y las reglas de envío (sin red ni base de datos)."""
import unittest

import _sin_servicios  # noqa: F401

try:
    from cerebro.licitaciones import analisis_tecnico as A
except ImportError as e:      # pragma: no cover
    raise unittest.SkipTest(str(e))

DOCS = [{"n": 1, "nombre": "Pliego de prescripciones técnicas", "paginas": [(1, "El adjudicatario deberá suministrar equipos con garantía de cinco años como mínimo."), (2, "El plazo de entrega será de 30 días naturales desde la firma del contrato.")]}]


class TestTexto(unittest.TestCase):
    def test_cada_pagina_lleva_su_marca_para_poder_citarla(self):
        t, avisos = A.construir_texto(DOCS)
        self.assertIn("[Documento 1 «Pliego de prescripciones técnicas» · página 2]", t)
        self.assertEqual(avisos, [])

    def test_si_no_cabe_se_recorta_y_se_avisa(self):
        largo = [{"n": 3, "nombre": "PCAP", "paginas": [(i, "x" * 900) for i in range(1, 30)]}]
        t, avisos = A.construir_texto(largo, maximo=5000)
        self.assertLessEqual(len(t), 5000)
        self.assertEqual(len(avisos), 1)
        self.assertIn("documento 3", avisos[0])

    def test_sin_documentos_no_hay_texto(self):
        self.assertEqual(A.construir_texto([]), ("", []))

    def test_el_pliego_va_marcado_como_datos_y_sin_datos_de_la_empresa(self):
        m = A.construir_mensajes("Suministro de cámaras", "Ayto", "texto")
        self.assertEqual([x["role"] for x in m], ["system", "user"])
        self.assertIn("TEXTO DE TERCEROS", m[0]["content"])
        self.assertIn("NO inventes", m[0]["content"])
        self.assertIn("««««\ntexto\n»»»»", m[1]["content"])


class TestVerificar(unittest.TestCase):
    def informe(self, **extra):
        base = {"resumen": "r", "criterios_tecnicos": [], "puntos_fuertes": [], "puntos_debiles": []}
        return {**base, **extra}

    def test_una_cita_real_se_verifica_y_una_inventada_se_marca(self):
        r = A.verificar(self.informe(
            puntos_fuertes=[{"punto": "Garantía clara", "detalle": "d", "documento": 1, "pagina": 1, "cita": "deberá suministrar equipos con garantía de cinco años"}],
            puntos_debiles=[{"punto": "Plazo", "tipo": "plazo_ajustado", "detalle": "d", "documento": 1, "pagina": 2, "cita": "El plazo de entrega será de 90 días hábiles"}]), DOCS)
        self.assertTrue(r["puntos_fuertes"][0]["cita_verificada"])
        self.assertFalse(r["puntos_debiles"][0]["cita_verificada"])
        self.assertEqual(r["citas"], {"total": 2, "verificadas": 1, "sin_verificar": 1})

    def test_documento_o_pagina_que_no_existen_no_se_verifican(self):
        r = A.verificar(self.informe(puntos_fuertes=[{"punto": "a", "detalle": "d", "documento": 9, "pagina": 1, "cita": "deberá suministrar equipos con garantía de cinco años"},
                                                      {"punto": "b", "detalle": "d", "documento": "uno", "pagina": None, "cita": "deberá suministrar equipos con garantía de cinco años"}]), DOCS)
        self.assertEqual([x["cita_verificada"] for x in r["puntos_fuertes"]], [False, False])
        self.assertEqual([x["documento"] for x in r["puntos_fuertes"]], [9, None])

    def test_tipos_desconocidos_y_basura_se_limpian(self):
        r = A.verificar(self.informe(puntos_debiles=[{"punto": "x", "tipo": "inventado", "detalle": "d"}, "no soy un dict", {"punto": "  ", "tipo": "riesgo", "detalle": "d"}],
                                     criterios_tecnicos=[{"criterio": "Calidad", "tipo": "raro"}], preguntas_aclaracion=["¿Qué marca?", "", "  "]), DOCS)
        self.assertEqual([x["tipo"] for x in r["puntos_debiles"]], ["otro"])
        self.assertEqual(r["criterios_tecnicos"][0]["tipo"], "desconocido")
        self.assertEqual(r["preguntas_aclaracion"], ["¿Qué marca?"])


if __name__ == "__main__":
    unittest.main()
