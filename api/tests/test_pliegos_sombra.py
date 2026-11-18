"""Análisis en sombra de los pliegos (sobres, fugas del precio, rectificaciones, fórmulas) contra el corpus sintético de `corpus_pliegos/`."""
import json
import os
import unittest
from pathlib import Path

import _sin_servicios  # noqa: F401

try:
    from cerebro.licitaciones import pliegos_sombra as S, reglas
except ImportError as e:      # pragma: no cover
    raise unittest.SkipTest(str(e))

CORPUS = Path(__file__).resolve().parent / "corpus_pliegos"


def casos():
    return [(p.stem, json.loads(p.read_text(encoding="utf-8"))) for p in sorted(CORPUS.glob("*.json")) if p.stem != "fugas"]


class TestCorpus(unittest.TestCase):
    def test_el_corpus_no_esta_vacio(self):
        self.assertGreaterEqual(len(casos()), 5)

    def test_cada_pliego_del_corpus_da_lo_esperado(self):
        for nombre, c in casos():
            with self.subTest(nombre):
                e, docs = c["esperado"], c["documentos"]
                pcap = "\n".join(d["texto"] for d in docs if S.clasificar_documento(d["nombre"], d["texto"]) == "pcap") or "\n".join(d["texto"] for d in docs)
                det = S.detectar_sobres(pcap)
                self.assertEqual(det["numero"], e["sobres"])
                if e.get("via"):
                    self.assertEqual(det["via"], e["via"])
                rect = S.rectificaciones(docs)
                self.assertEqual(len(rect), e["rectificaciones"])
                if rect:
                    self.assertGreaterEqual(len(rect[0]["clausulas"]), e["clausulas_min"])
                    self.assertEqual(rect[0]["fecha"], e["fecha"])
                sug = S.sugerir_formulas(pcap)
                if "formula" in e:
                    self.assertEqual(sug[0]["formula"] if sug else None, e["formula"])
                    if e["formula"]:
                        self.assertEqual(sug[0].get("puntos_precio"), e["puntos_precio"])
                        self.assertEqual(sug[0].get("baja_tope_pct"), e.get("baja_tope_pct"))

    def test_las_formulas_sugeridas_existen_en_reglas(self):
        for _, c in casos():
            for s in S.sugerir_formulas("\n".join(d["texto"] for d in c["documentos"])):
                self.assertIn(s["formula"], reglas.FORMULAS)

    def test_las_mejoras_solo_se_avisan_si_el_pliego_las_manda_al_sobre_economico(self):
        seccion = [{"sobre": "tecnico", "clave": "m", "titulo": "M", "contenido": "Se ofrecen mejoras sin coste para la administración, valoradas mediante fórmula."}]
        self.assertEqual(S.fugas_economicas(seccion), [])                                   # no se asume: depende del pliego
        self.assertFalse(S.mejoras_van_en_el_economico("Las mejoras se presentarán en el sobre B junto a la memoria."))
        self.assertTrue(S.mejoras_van_en_el_economico("Sobre C: oferta económica y las mejoras valorables mediante fórmula."))
        self.assertEqual([f["tipo"] for f in S.fugas_economicas(seccion, True)], ["mejora_automatica"])

    def test_fugas_del_precio_fuera_del_sobre_economico(self):
        for i, c in enumerate(json.loads((CORPUS / "fugas.json").read_text(encoding="utf-8"))["casos"]):
            with self.subTest(i):
                self.assertEqual([f["tipo"] for f in S.fugas_economicas(c["secciones"], c.get("mejoras_en_economico", False))], c["fugas"])


class TestAvisos(unittest.TestCase):
    def test_distinto_numero_de_sobres_avisa_y_igual_no(self):
        self.assertEqual(S.comparar_sobres({"numero": 3, "citas": []})[0]["nivel"], "ok")
        a = S.comparar_sobres({"numero": 2, "citas": ["dos sobres"]})
        self.assertEqual(a[0]["nivel"], "aviso")
        self.assertIn("2", a[0]["texto"])
        self.assertEqual(S.comparar_sobres({"numero": None})[0]["nivel"], "ok")

    def test_una_rectificacion_en_el_nombre_gana_a_pcap(self):
        self.assertEqual(S.clasificar_documento("PCAP rectificado.pdf"), "rectificacion")
        self.assertEqual(S.clasificar_documento("PPT.pdf"), "ppt")
        self.assertEqual(S.clasificar_documento("doc1.pdf", "Pliego de prescripciones técnicas particulares"), "ppt")
        self.assertEqual(S.clasificar_documento("x.pdf", ""), "otro")

    def test_sin_reglas_anotadas_sugiere_y_con_reglas_calla(self):
        sug = [{"formula": "inversa", "cita": "proporcionalidad inversa", "puntos_precio": 51.0}]
        self.assertEqual(S.avisos_formulas(sug, None)[0]["nivel"], "aviso")
        self.assertEqual(S.avisos_formulas(sug, {"formula": "inversa"}), [])

    def test_revisar_no_modifica_lo_que_recibe(self):
        docs = [{"n": 1, "nombre": "PCAP.pdf", "texto": "Tres sobres. Precio 51 puntos proporcionalidad inversa."}]
        secs = [{"sobre": "tecnico", "clave": "m", "titulo": "M", "contenido": "oferta de 1.000 euros"}]
        import copy
        antes = copy.deepcopy((docs, secs))
        out = S.revisar(docs, secs)
        self.assertEqual((docs, secs), antes)
        self.assertTrue(any(i["nivel"] == "aviso" for i in out))

    def test_el_interruptor_esta_apagado_por_defecto(self):
        os.environ.pop("PLIEGOS_ANALISIS_SOMBRA", None)
        self.assertFalse(S.activo())
        os.environ["PLIEGOS_ANALISIS_SOMBRA"] = "1"
        try:
            self.assertTrue(S.activo())
        finally:
            del os.environ["PLIEGOS_ANALISIS_SOMBRA"]


if __name__ == "__main__":
    unittest.main()
