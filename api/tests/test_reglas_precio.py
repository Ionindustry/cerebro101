"""Reglas de puntuación del precio: validación, fórmulas, guardado en PostgreSQL (con CEREBRO_TEST_PG) y su uso en el simulador."""
import asyncio
import os
import time
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import _sin_servicios  # noqa: F401

try:
    import psycopg
    from cerebro.licitaciones import reglas as R, simulador as S
except ImportError as e:      # pragma: no cover
    raise unittest.SkipTest(str(e))

URL = os.environ.get("CEREBRO_TEST_PG")
ESQUEMA = Path(__file__).resolve().parents[2] / "db" / "esquema.sql"
ID = "0b1f7a3e-1111-4222-8333-444444444444"
OTRO = "1c2f7a3e-1111-4222-8333-444444444444"


def ejecutar(c):
    return asyncio.run(c)


def regla(**kw):
    return {"formula": "inversa", "puntos_precio": 51, "puntos_total": 100, "baja_tope_pct": None, "baja_anormal_pct": None, **kw}


class TestValidar(unittest.TestCase):
    def test_normaliza_y_acepta_coma_decimal(self):
        v = R.validar({"formula": "lineal_umbral", "puntos_precio": "51,5", "baja_tope_pct": "20", "baja_anormal_pct": " 25 ", "nota": "  Cláusula\n 12 "})
        self.assertEqual((v["puntos_precio"], v["puntos_total"], v["baja_tope_pct"], v["baja_anormal_pct"], v["nota"]), (51.5, 100.0, 20.0, 25.0, "Cláusula 12"))

    def test_el_tope_solo_se_guarda_con_lineal(self):
        self.assertIsNone(R.validar({"formula": "inversa", "puntos_precio": 40, "baja_tope_pct": 20})["baja_tope_pct"])

    def test_rechaza_lo_incoherente(self):
        malos = [{"formula": "rara", "puntos_precio": 40}, {"formula": "inversa"}, {"formula": "inversa", "puntos_precio": 0}, {"formula": "inversa", "puntos_precio": "mucho"},
                 {"formula": "inversa", "puntos_precio": 60, "puntos_total": 50}, {"formula": "lineal_umbral", "puntos_precio": 40},
                 {"formula": "inversa", "puntos_precio": 40, "baja_anormal_pct": 120}, {"formula": "inversa", "puntos_precio": True}, {"formula": "inversa", "puntos_precio": float("nan")}]
        for m in malos:
            with self.assertRaises(R.ErrorReglas, msg=str(m)):
                R.validar(m)


class TestFormulas(unittest.TestCase):
    def test_inversa(self):
        r = regla()
        self.assertAlmostEqual(R.puntos_precio(r, 0.20, 0.10), 51)             # la más baja se lleva todo
        self.assertAlmostEqual(R.puntos_precio(r, 0.10, 0.20), 51 * 0.8 / 0.9)
        self.assertIsNone(R.puntos_precio(r, 0.10, None))                      # necesita la rival

    def test_proporcional_baja(self):
        r = regla(formula="proporcional_baja", puntos_precio=60)
        self.assertAlmostEqual(R.puntos_precio(r, 0.10, 0.20), 30)
        self.assertAlmostEqual(R.puntos_precio(r, 0.25, 0.20), 60)
        self.assertAlmostEqual(R.puntos_precio(r, 0.0, 0.0), 60)                # nadie baja: sin dividir por cero

    def test_lineal_no_necesita_rival_y_satura_en_el_tope(self):
        r = regla(formula="lineal_umbral", puntos_precio=40, baja_tope_pct=20)
        self.assertAlmostEqual(R.puntos_precio(r, 0.10, None), 20)
        self.assertAlmostEqual(R.puntos_precio(r, 0.35, None), 40)
        self.assertAlmostEqual(R.puntos_precio(r, -0.1, None), 0)


class TestEnElSimulador(unittest.TestCase):
    MUESTRA = [{"baja": b / 100, "baja_anormal": False, "ofertas": 4, "fecha": "2025-06-01"} for b in range(5, 25)]

    def test_la_curva_lleva_los_puntos_de_precio(self):
        c = S.configuracion(None)
        filas = S.curva(self.MUESTRA, 100000, None, c, regla(), 0.15)
        f10 = next(f for f in filas if f["baja_pct"] == 10)
        self.assertAlmostEqual(f10["puntos_precio"], 51 * 0.85 / 0.90, places=1)
        self.assertNotIn("puntos_precio", S.curva(self.MUESTRA, 100000, None, c)[0])

    def test_el_umbral_del_pliego_manda_sobre_lo_estimado(self):
        c = S.configuracion(None)
        filas = S.curva(self.MUESTRA, 100000, 50000, c, regla(baja_anormal_pct=20), 0.15)
        self.assertEqual({f["baja_pct"]: f["p_anormal"] for f in filas if f["baja_pct"] in (19, 20, 21)}, {19: 0.0, 20: 1.0, 21: 1.0})
        reco, _ = S.recomendar(filas, 50000, 0.2)
        self.assertLess(reco["baja_pct"], 20)                                    # nunca recomienda por encima del umbral

    def test_simular_completo_usa_las_reglas_y_el_coste_del_erp(self):
        ficha = {"titulo": "X", "cpv": ["35125300"], "nuts": ["ES512"], "importes": [{"significado": "presupuesto_base", "impuestos": "sin_iva", "moneda": "EUR", "valor": "100000"}]}
        awards = {"items": [{"licitacion_id": f"id{i}", "baja": str(b / 100), "baja_anormal": False, "ofertas_recibidas": 4, "fecha_adjudicacion": "2026-03-01"} for i, b in enumerate(range(5, 45))],
                  "siguiente_cursor": None}

        async def consulta(ruta, params=None):
            return ficha if ruta.startswith("/tenders/") else awards
        erp = {"presupuesto": "QTN-1", "coste": 62000.0, "completo": False, "lineas": [{"articulo": "A"}], "sin_coste": [{"articulo": "B", "cantidad": 2}]}
        with mock.patch.object(S.motor, "_get", consulta), \
                mock.patch.object(S.reglas_mod, "leer", mock.AsyncMock(return_value=regla(baja_anormal_pct=30))), \
                mock.patch.object(S.coste_erp, "coste_de_presupuesto", mock.AsyncMock(return_value=erp)):
            r = ejecutar(S.simular_completo(ID, None, "QTN-1"))
            self.assertEqual(r["coste"], 62000.0)
            self.assertFalse(r["apto_para_decidir"])                              # coste incompleto: nunca apto
            self.assertTrue(any("INCOMPLETO" in a for a in r["avisos"]))
            self.assertEqual(r["coste_erp"]["presupuesto"], "QTN-1")
            self.assertEqual(r["reglas"]["formula"], "inversa")
            with self.assertRaises(S.ErrorSimulador):                             # o coste o presupuesto
                ejecutar(S.simular_completo(ID, 5000, "QTN-1"))
            with self.assertRaises(S.ErrorSimulador):
                ejecutar(S.simular_completo("x", None, None))

    def test_si_no_se_pueden_leer_las_reglas_se_simula_y_se_avisa(self):
        ficha = {"titulo": "X", "cpv": ["35125300"], "importes": [{"significado": "presupuesto_base", "impuestos": "sin_iva", "moneda": "EUR", "valor": "100000"}]}
        awards = {"items": [{"licitacion_id": f"id{i}", "baja": str(b / 100), "ofertas_recibidas": 4, "fecha_adjudicacion": "2026-03-01"} for i, b in enumerate(range(5, 45))], "siguiente_cursor": None}

        async def consulta(ruta, params=None):
            return ficha if ruta.startswith("/tenders/") else awards
        with mock.patch.object(S.motor, "_get", consulta), mock.patch.object(S.reglas_mod, "leer", mock.AsyncMock(side_effect=RuntimeError("bd caída"))):
            r = ejecutar(S.simular_completo(ID))
        self.assertIsNone(r["reglas"])
        self.assertTrue(any("reglas de puntuación" in a for a in r["avisos"]))


@unittest.skipUnless(URL and hasattr(psycopg, "AsyncConnection"), "sin CEREBRO_TEST_PG")
class TestBaseDeDatos(unittest.TestCase):
    def setUp(self):
        self.schema = f"t_reglas_{time.time_ns()}"
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"CREATE SCHEMA {self.schema}")
            c.execute(f"SET search_path = {self.schema}")
            t = ESQUEMA.read_text(encoding="utf-8")
            i = t.index("-- Reglas de puntuación del precio")
            c.execute(t[i:t.index("\n\n", i) if "\n\n" in t[i:] else len(t)])
        sep = "&" if "?" in URL else "?"
        self.p = mock.patch.object(R, "ajustes", SimpleNamespace(database_url=f"{URL}{sep}options=-csearch_path%3D{self.schema}"))
        self.p.start()

    def tearDown(self):
        self.p.stop()
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"DROP SCHEMA {self.schema} CASCADE")

    def test_guardar_leer_actualizar_y_borrar(self):
        self.assertIsNone(ejecutar(R.leer(ID)))
        g = ejecutar(R.guardar(ID, {"formula": "inversa", "puntos_precio": 51, "baja_anormal_pct": 25}, "albert"))
        self.assertEqual((g["formula"], g["puntos_precio"], g["puntos_total"], g["baja_anormal_pct"], g["por"]), ("inversa", 51.0, 100.0, 25.0, "albert"))
        g = ejecutar(R.guardar(ID.upper(), {"formula": "lineal_umbral", "puntos_precio": 40, "baja_tope_pct": 20}, "marta"))
        self.assertEqual((g["formula"], g["por"], g["baja_anormal_pct"]), ("lineal_umbral", "marta", None))
        self.assertEqual(ejecutar(R.leer(ID))["baja_tope_pct"], 20.0)
        self.assertIsNone(ejecutar(R.leer(OTRO)))
        with self.assertRaises(R.ErrorReglas):
            ejecutar(R.guardar(ID, {"formula": "rara", "puntos_precio": 1}, "albert"))
        self.assertTrue(ejecutar(R.borrar(ID)))
        self.assertFalse(ejecutar(R.borrar(ID)))
        with self.assertRaises(R.ErrorReglas):
            ejecutar(R.leer("no-es-uuid"))


if __name__ == "__main__":
    unittest.main()
