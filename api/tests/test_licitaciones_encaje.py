"""Puntuación de encaje de las licitaciones: explicable, con la jerarquía de CPV, la zona, el importe y el plazo."""
import unittest
from datetime import datetime, timezone
from pathlib import Path

import yaml

from cerebro.licitaciones import encaje

CFG = yaml.safe_load((Path(__file__).resolve().parents[2] / "config" / "licitaciones.yaml").read_text(encoding="utf-8"))
AHORA = datetime(2026, 10, 28, 14, 0, tzinfo=timezone.utc)


def lic(**kw):
    base = {"cpv": ["35125300"], "nuts": ["ES512"], "estado": "abierta", "procedimiento": "abierto",
            "importe": {"valor": "100000.00", "moneda": "EUR"}, "plazo_presentacion": "2026-11-20T10:00:00Z"}
    return {**base, **kw}


class TestEncaje(unittest.TestCase):
    def test_el_perfil_suma_100_y_tiene_los_20_cpv_decididos(self):
        self.assertEqual(sum(CFG["pesos"].values()), 100)
        self.assertEqual(len(CFG["cpv"]), 20)
        self.assertEqual(CFG["importe_max"], 1000000)
        self.assertEqual(CFG["zona"]["prioritaria"], "ES51")

    def test_lo_perfecto_puntua_100(self):
        r = encaje.puntuar(lic(), CFG, AHORA)
        self.assertEqual(r["encaje"], 100)
        self.assertIn("CPV 35125300 (Videovigilancia)", r["razones"])
        self.assertIn("Cataluña", r["razones"])
        self.assertFalse(r["fuera_de_importe"])

    def test_cpv_exacto_descendiente_ascendente_y_ajeno(self):
        p = lambda cpv: encaje.puntuar(lic(cpv=cpv), CFG, AHORA)["encaje"]       # noqa: E731
        exacto, hijo, padre, ajeno = p(["72262000"]), p(["72261000"]), p(["72000000"]), p(["15000000"])
        self.assertEqual(exacto, 100)
        self.assertTrue(exacto > hijo > ajeno, (exacto, hijo, ajeno))
        self.assertEqual(padre, 100)         # 72000000 está en la lista: exacto
        self.assertTrue(p(["35100000"]) < exacto)  # más general que 35120000/35125300
        self.assertIn("dentro de 72000000", encaje.puntuar(lic(cpv=["72261000"]), CFG, AHORA)["razones"][0])

    def test_la_jerarquia_cubre_los_descendientes(self):
        self.assertEqual(encaje.prefijo("72000000"), "72")
        self.assertEqual(encaje.prefijo("35125300"), "351253")
        self.assertEqual(encaje.prefijo("63712710"), "6371271")

    def test_zona_cataluna_espana_y_extranjero(self):
        z = lambda nuts: encaje.puntuar(lic(nuts=nuts), CFG, AHORA)["encaje"]    # noqa: E731
        self.assertTrue(z(["ES512"]) > z(["ES300"]) > z([]) > z(["FR101"]))
        self.assertEqual(z(["ES511", "ES300"]), z(["ES511"]))                    # basta una zona prioritaria

    def test_importe_por_encima_del_limite_se_marca(self):
        r = encaje.puntuar(lic(importe={"valor": "1000000.01", "moneda": "EUR"}), CFG, AHORA)
        self.assertTrue(r["fuera_de_importe"])
        self.assertFalse(encaje.puntuar(lic(importe={"valor": "1000000.00", "moneda": "EUR"}), CFG, AHORA)["fuera_de_importe"])
        self.assertFalse(encaje.puntuar(lic(importe=None), CFG, AHORA)["fuera_de_importe"])
        self.assertFalse(encaje.puntuar(lic(importe={"valor": "5000000", "moneda": "USD"}), CFG, AHORA)["fuera_de_importe"])   # otra moneda: no se compara

    def test_plazo_justo_puntua_menos_y_el_terminado_nada(self):
        p = lambda plazo: encaje.puntuar(lic(plazo_presentacion=plazo), CFG, AHORA)       # noqa: E731
        holgado, justo, muy_justo, terminado = p("2026-11-20T10:00:00Z"), p("2026-11-01T10:00:00Z"), p("2026-10-29T10:00:00Z"), p("2026-10-20T10:00:00Z")
        self.assertTrue(holgado["encaje"] > justo["encaje"] > muy_justo["encaje"] > terminado["encaje"])
        self.assertIn("plazo terminado", terminado["razones"])
        self.assertEqual(muy_justo["dias_plazo"], 0.8)

    def test_en_lo_adjudicado_el_plazo_no_resta(self):
        abierta = encaje.puntuar(lic(plazo_presentacion="2026-10-29T10:00:00Z"), CFG, AHORA)["encaje"]
        adjudicada = encaje.puntuar(lic(estado="adjudicada", plazo_presentacion="2026-10-01T10:00:00Z"), CFG, AHORA)["encaje"]
        self.assertGreater(adjudicada, abierta)
        self.assertEqual(adjudicada, 100)

    def test_procedimiento_abierto_mejor_que_negociado_sin_publicidad(self):
        p = lambda proc: encaje.puntuar(lic(procedimiento=proc), CFG, AHORA)["encaje"]   # noqa: E731
        self.assertTrue(p("abierto") > p("negociado_con_publicidad") > p("menor") > p("negociado_sin_publicidad"))
        self.assertTrue(p("desconocido") > p("negociado_sin_publicidad"))

    def test_datos_raros_no_rompen(self):
        r = encaje.puntuar({"estado": "abierta", "importe": {"valor": "no-es-numero"}, "cpv": None, "nuts": None}, CFG, AHORA)
        self.assertTrue(0 <= r["encaje"] <= 100)
        self.assertIsNone(encaje.importe_en_euros({"valor": "x"}))


if __name__ == "__main__":
    unittest.main()
