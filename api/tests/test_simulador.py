"""Simulador de ofertas: estadística, curva, recomendación, comprobación con el pasado y la búsqueda de concursos parecidos (motor simulado)."""
import asyncio
import unittest
from datetime import date

import _sin_servicios  # noqa: F401

try:
    from cerebro.licitaciones import simulador as S
except ImportError as e:      # pragma: no cover
    raise unittest.SkipTest(str(e))

ID = "0b1f7a3e-1111-4222-8333-444444444444"
HOY = date(2026, 10, 29)
C = S.configuracion(None)


def ejecutar(c):
    return asyncio.run(c)


def muestra(bajas, anormal_desde=None):
    return [{"baja": b, "baja_anormal": (b >= anormal_desde) if anormal_desde is not None else None, "ofertas": 4, "fecha": "2025-06-01"} for b in bajas]


class TestEstadistica(unittest.TestCase):
    def test_percentiles(self):
        self.assertEqual(S.percentil([], .5), None)
        self.assertEqual(S.percentil([7], .9), 7)
        self.assertEqual(S.percentil([1, 2, 3, 4, 5], .5), 3)
        self.assertAlmostEqual(S.percentil([0, 10], .25), 2.5)

    def test_wilson_acota_y_se_estrecha_con_mas_datos(self):
        lo, hi = S.wilson(5, 10)
        self.assertTrue(0.2 < lo < 0.5 < hi < 0.8)
        lo2, hi2 = S.wilson(50, 100)
        self.assertLess(hi2 - lo2, hi - lo)
        self.assertEqual(S.wilson(0, 0), (0.0, 1.0))
        self.assertEqual(S.wilson(0, 10)[0], 0.0)

    def test_probabilidad_de_ganar_cuenta_los_concursos_en_que_se_habria_ganado(self):
        bajas = [0.10, 0.20, 0.20, 0.30]
        self.assertEqual(S.p_ganar(bajas, 0.05)[0], 0.0)
        self.assertEqual(S.p_ganar(bajas, 0.25)[0], 0.75)
        self.assertEqual(S.p_ganar(bajas, 0.20)[0], (1 + 0.5 * 2) / 4)            # los empates cuentan medio
        self.assertEqual(S.p_ganar(bajas, 0.50)[0], 1.0)
        self.assertEqual(S.p_ganar([], 0.1), (0.0, 0.0, 1.0))
        p, lo, hi = S.p_ganar(bajas, 0.25)
        self.assertTrue(lo < p < hi)

    def test_riesgo_de_baja_anormal_solo_con_datos_suficientes(self):
        m = muestra([i / 100 for i in range(5, 41)], anormal_desde=0.30)               # 36 concursos; los que bajaron >= 30 % fueron anormales
        self.assertEqual(S.p_anormal(m, 0.30), 6 / 11)                                 # ganadores con baja entre 25 % y 35 %: 11, de los que 6 fueron anormales
        self.assertEqual(S.p_anormal(m, 0.05), 0.0)
        self.assertEqual(S.p_anormal(m, 0.40), 1.0)
        self.assertIsNone(S.p_anormal(m, 0.0))                                         # solo 1 concurso en esa ventana: sin dato, no 0
        self.assertIsNone(S.p_anormal(muestra([0.1] * 10), 0.1))                       # no se sabe si fueron anormales


class TestCurvaYRecomendacion(unittest.TestCase):
    def test_la_curva_sube_con_la_baja_y_el_precio_baja(self):
        m = muestra([i / 100 for i in range(5, 36)])
        f = S.curva(m, 100000, None, C)
        self.assertEqual(f[0]["baja_pct"], 0.0)
        self.assertTrue(all(a["p_ganar"] <= b["p_ganar"] for a, b in zip(f, f[1:])))
        self.assertTrue(all(a["precio"] > b["precio"] for a, b in zip(f, f[1:])))
        self.assertEqual(f[10]["precio"], 90000.0)
        self.assertNotIn("margen_esperado", f[0])

    def test_con_coste_se_recomienda_el_mejor_margen_esperado(self):
        m = muestra([i / 100 for i in range(5, 36)])
        f = S.curva(m, 100000, 70000, C)
        reco, motivo = S.recomendar(f, 70000, 0.2)
        self.assertIsNotNone(reco)
        self.assertEqual(reco["margen_esperado"], max(x["margen_esperado"] for x in f if x["precio"] > 70000))
        self.assertTrue(all(x["precio"] > 70000 for x in [reco]))
        self.assertIn("Mejor margen esperado", motivo)

    def test_sin_coste_no_se_recomienda_precio(self):
        reco, motivo = S.recomendar(S.curva(muestra([0.1] * 10), 1000, None, C), None, 0.2)
        self.assertIsNone(reco)
        self.assertIn("Indica tu coste", motivo)

    def test_un_coste_imposible_no_da_recomendacion(self):
        f = S.curva(muestra([i / 100 for i in range(5, 36)]), 100000, 99999, C)
        reco, motivo = S.recomendar(f, 99999, 0.2)
        self.assertTrue(reco is None or reco["precio"] > 99999)

    def test_el_riesgo_de_baja_anormal_descarta_precios(self):
        m = muestra([i / 100 for i in range(5, 36)], anormal_desde=0.25)
        f = S.curva(m, 100000, 50000, C)
        reco, _ = S.recomendar(f, 50000, 0.2)
        self.assertIsNotNone(reco)
        self.assertTrue(reco["p_anormal"] is None or reco["p_anormal"] <= 0.2)
        self.assertLess(reco["baja_pct"], 25)                                          # a partir de ahí todos fueron anormales; un punto sin datos más allá tampoco vale


class TestBacktest(unittest.TestCase):
    def test_con_pocos_concursos_no_se_puede_comprobar(self):
        b = S.backtest(muestra([0.1] * 5), C)
        self.assertEqual((b["apto"], b["error_calibracion"]), (False, None))

    def test_una_muestra_homogenea_sale_calibrada(self):
        bajas = [((i * 37) % 100) / 100 * 0.4 for i in range(120)]                      # reparto parejo entre 0 y 40 %
        b = S.backtest(muestra(bajas), C)
        self.assertLess(b["error_calibracion"], 0.05)
        self.assertTrue(b["apto"])
        self.assertEqual(len(b["niveles"]), 5)

    def test_una_muestra_corta_no_es_apta_aunque_cuadre(self):
        bajas = [((i * 37) % 100) / 100 * 0.4 for i in range(20)]
        b = S.backtest(muestra(bajas), C)
        self.assertFalse(b["apto"])
        self.assertIn("por debajo del mínimo", b["motivo"])


class TestFicha(unittest.TestCase):
    def test_presupuesto_base_sin_iva_o_valor_estimado(self):
        f = {"importes": [{"significado": "valor_estimado", "impuestos": "sin_iva", "valor": "500000.00"}, {"significado": "presupuesto_base", "impuestos": "sin_iva", "valor": "200000.00"},
                          {"significado": "presupuesto_base", "impuestos": "con_iva", "valor": "242000.00"}]}
        self.assertEqual(S.presupuesto_de(f), (200000.0, "presupuesto_base"))
        self.assertEqual(S.presupuesto_de({"importes": [f["importes"][0]]}), (500000.0, "valor_estimado"))
        self.assertEqual(S.presupuesto_de({"importes": [{"significado": "presupuesto_base", "impuestos": "con_iva", "valor": "5"}]}), (None, ""))
        self.assertEqual(S.presupuesto_de({}), (None, ""))

    def test_peso_del_juicio_de_valor(self):
        self.assertEqual(S.peso_juicio_de_valor({"criterios": [{"tipo": "OBJ", "peso": 60}, {"tipo": "SUBJ", "peso": 40}]}), 40)
        self.assertEqual(S.peso_juicio_de_valor({}), 0)

    def test_los_niveles_van_del_mas_parecido_al_mas_amplio(self):
        niv = S.niveles_de_busqueda({"cpv": ["32323500"], "nuts": ["ES512"]}, 100000)
        self.assertEqual([p.get("nuts") for _, p in niv], [["ES51"], ["ES"], None, None])
        self.assertEqual(niv[0][1]["cpv"], ["32323"])
        self.assertEqual((niv[0][1]["importe_min"], niv[0][1]["importe_max"]), ("50000.00", "200000.00"))
        self.assertEqual(niv[-1][1]["cpv"], ["323"])
        with self.assertRaises(S.ErrorSimulador):
            S.niveles_de_busqueda({}, 1)


def motor_falso(ficha, por_nivel):
    """Un motor que sirve la ficha y, según cuántos filtros de zona lleva la consulta, un número de adjudicaciones parecidas."""
    llamadas = []

    async def consulta(ruta, params=None):
        llamadas.append((ruta, params))
        if ruta.startswith("/tenders/"):
            return ficha
        zona = params.get("nuts", [""])[0] if params.get("nuts") else ""
        n = por_nivel.get(zona or ("cpv3" if params["cpv"][0] == "323" else "sin_zona"), 0)
        return {"items": [{"licitacion_id": f"x{i}", "baja": f"{((i * 37) % 100) / 100 * 0.4:.4f}", "baja_anormal": False, "ofertas_recibidas": 3, "fecha_adjudicacion": "2025-05-01"} for i in range(n)],
                "siguiente_cursor": None}
    consulta.llamadas = llamadas
    return consulta


FICHA = {"id": ID, "titulo": "Videovigilancia del puerto", "cpv": ["32323500"], "nuts": ["ES512"],
         "importes": [{"significado": "presupuesto_base", "impuestos": "sin_iva", "valor": "200000.00", "moneda": "EUR"}], "criterios": [{"tipo": "OBJ", "peso": 100}]}


class TestSimular(unittest.TestCase):
    def sim(self, ficha=FICHA, por_nivel=None, coste=None):
        return ejecutar(S.simular(ID, coste, consulta=motor_falso(ficha, por_nivel or {"ES51": 60}), hoy=HOY))

    def test_con_muestra_suficiente_y_solo_precio_es_apto_para_decidir(self):
        r = self.sim(coste=140000)
        self.assertEqual((r["muestra"]["n"], r["muestra"]["suficiente"]), (60, True))
        self.assertTrue(r["apto_para_decidir"])
        self.assertIsNotNone(r["recomendacion"])
        self.assertEqual(r["licitacion"]["presupuesto"], 200000.0)
        self.assertIn("ES51", r["muestra"]["mercado"])
        self.assertTrue(r["supuestos"])
        self.assertNotIn("NO es apta", r["nota"])
        self.assertEqual(r["avisos"], [])

    def test_si_hay_pocos_se_amplia_la_busqueda_y_se_dice(self):
        r = self.sim(por_nivel={"ES51": 5, "ES": 10, "sin_zona": 45})
        self.assertEqual(r["muestra"]["n"], 45)
        self.assertIn("cualquier zona", r["muestra"]["mercado"])
        self.assertTrue(any("ampliado" in a for a in r["avisos"]))

    def test_con_muestra_corta_es_orientativa(self):
        r = self.sim(por_nivel={"ES51": 12})
        self.assertFalse(r["muestra"]["suficiente"])
        self.assertFalse(r["apto_para_decidir"])
        self.assertIn("NO es apta", r["nota"])
        self.assertTrue(any("muy incierta" in a for a in r["avisos"]))

    def test_con_juicio_de_valor_el_precio_no_decide_solo(self):
        r = self.sim(ficha={**FICHA, "criterios": [{"tipo": "OBJ", "peso": 60}, {"tipo": "SUBJ", "peso": 40}]})
        self.assertFalse(r["apto_para_decidir"])
        self.assertTrue(any("juicio de valor" in a and "optimista" in a for a in r["avisos"]))

    def test_sin_historico_o_sin_presupuesto_se_explica(self):
        with self.assertRaisesRegex(S.ErrorSimulador, "no tiene adjudicaciones"):
            self.sim(por_nivel={"ninguno": 0})
        with self.assertRaisesRegex(S.ErrorSimulador, "presupuesto"):
            self.sim(ficha={**FICHA, "importes": []})

    def test_entradas_no_validas(self):
        for mal in ("../x", "", 5):
            with self.assertRaises(S.ErrorSimulador):
                ejecutar(S.simular(mal, None, consulta=motor_falso(FICHA, {}), hoy=HOY))
        for coste in ("mucho", -5, 0):
            with self.assertRaises(S.ErrorSimulador):
                ejecutar(S.simular(ID, coste, consulta=motor_falso(FICHA, {"ES51": 60}), hoy=HOY))

    def test_se_excluyen_la_propia_licitacion_y_las_bajas_imposibles(self):
        llamadas = []

        async def consulta(ruta, params=None):
            llamadas.append(params)
            if ruta.startswith("/tenders/"):
                return FICHA
            items = [{"licitacion_id": ID, "baja": "0.2"}, {"licitacion_id": "o", "baja": "0.99"}, {"licitacion_id": "p", "baja": None}] + \
                    [{"licitacion_id": f"v{i}", "baja": "0.15", "baja_anormal": False} for i in range(40)]
            return {"items": items}
        r = ejecutar(S.simular(ID, None, consulta=consulta, hoy=HOY))
        self.assertEqual(r["muestra"]["n"], 40)                                       # sin la propia, sin la del 99 % y sin la que no tiene baja
        p = llamadas[1]
        self.assertEqual((p["resultado"], p["orden"], p["limit"]), ("adjudicado", "fecha", 100))
        self.assertEqual(p["adjudicada_desde"], "2021-10-30")


if __name__ == "__main__":
    unittest.main()
