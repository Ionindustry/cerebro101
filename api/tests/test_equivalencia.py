"""Tabla de equivalencias: la aritmética «iguala o supera» (con unidades) y que el código mande sobre el modelo."""
import asyncio
import os
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import _sin_servicios  # noqa: F401

try:
    import psycopg
    from cerebro.licitaciones import equivalencia as E
    from cerebro.licitaciones import ofertas as O
except ImportError as e:      # pragma: no cover
    raise unittest.SkipTest(str(e))

URL = os.environ.get("CEREBRO_TEST_PG")
ESQUEMA = Path(__file__).resolve().parents[2] / "db" / "esquema.sql"
ID = "0b1f7a3e-1111-4222-8333-444444444499"
TEXTOS = {"P1": "Cámara domo MS-C8: sensor 8 MP, lente 2,8 mm, IR 40 m, IP67, IK10.", "P2": "Cámara bala X2: 4 MP, IR 30 m, IP66, almacenamiento 256 GB."}


class TestNumeros(unittest.TestCase):
    def test_lee_valores_con_unidad_y_familia(self):
        self.assertEqual(E.numero("2,8 mm"), (0.0028, "longitud"))
        self.assertEqual(E.numero("IP67"), (67.0, "ip"))
        self.assertEqual(E.numero("4 MP"), (4.0, "megapixel"))
        self.assertEqual(E.numero("1.000 GB"), (1e12, "datos"))
        self.assertEqual(E.numero("2 TB")[1], "datos")
        self.assertIsNone(E.numero("no consta"))

    def test_iguala_supera_o_no_cumple_segun_el_operador(self):
        self.assertEqual(E.comparar(">=", "4 MP", "8 MP"), "supera")
        self.assertEqual(E.comparar(">=", "4 MP", "4 MP"), "iguala")
        self.assertEqual(E.comparar(">=", "4 MP", "2 MP"), "no_cumple")
        self.assertEqual(E.comparar("<=", "30 W", "12 W"), "supera")                 # con un máximo, menos es mejor
        self.assertEqual(E.comparar("<=", "30 W", "45 W"), "no_cumple")
        self.assertEqual(E.comparar("=", "24 V", "12 V"), "no_cumple")
        self.assertEqual(E.comparar(">=", "IP66", "IP67"), "supera")

    def test_convierte_unidades_de_la_misma_familia(self):
        self.assertEqual(E.comparar(">=", "30 m", "3000 cm"), "iguala")
        self.assertEqual(E.comparar(">=", "1 TB", "512 GB"), "no_cumple")
        self.assertEqual(E.comparar(">=", "1 TB", "2000 GB"), "supera")

    def test_no_compara_lo_que_no_se_puede_comparar(self):
        self.assertIsNone(E.comparar(">=", "30 m", "4 MP"))                           # familias distintas
        self.assertIsNone(E.comparar(">=", "30 m", "mucho"))
        self.assertIsNone(E.comparar("texto", "H.265", "H.265"))

    def test_el_valor_tiene_que_estar_en_la_evidencia(self):
        self.assertTrue(E.valor_en_evidencia("2,8 mm", [TEXTOS["P1"]]))
        self.assertTrue(E.valor_en_evidencia("IP67", [TEXTOS["P1"]]))
        self.assertTrue(E.valor_en_evidencia("8 megapíxeles", [TEXTOS["P1"]]))        # otra forma de escribir la unidad
        self.assertFalse(E.valor_en_evidencia("IP68", [TEXTOS["P1"]]))
        self.assertFalse(E.valor_en_evidencia("18 MP", [TEXTOS["P1"]]))               # «8» dentro de «18» no vale
        self.assertFalse(E.valor_en_evidencia("", [TEXTOS["P1"]]))


def dato(**c):
    return {"parametros": [{"requisito": "[R1] Resolución", "parametro": "Resolución", "operador": ">=", "valor_exigido": "4 MP", "cita": "mínimo 4 megapíxeles",
                            "candidatos": [{"producto": "MS-C8", "valor_producto": "8 MP", "veredicto": "supera", "evidencia": ["P1"], **c}]}]}


class TestVerificar(unittest.TestCase):
    def cand(self, datos, **kw):
        return E.verificar(datos, TEXTOS, **kw)["parametros"][0]["candidatos"][0]

    def test_un_valor_comprobado_se_mantiene_y_queda_verificado(self):
        c = self.cand(dato())
        self.assertEqual((c["veredicto"], c["verificado"]), ("supera", True))

    def test_el_codigo_corrige_al_modelo(self):
        c = self.cand(dato(veredicto="iguala"))
        self.assertEqual(c["veredicto"], "supera")
        self.assertIn("Corregido por el código", c["nota"])
        c2 = self.cand(dato(producto="X2", valor_producto="4 MP", veredicto="supera", evidencia=["P2"]))
        self.assertEqual(c2["veredicto"], "iguala")

    def test_un_valor_que_no_esta_en_la_evidencia_pasa_a_sin_datos(self):
        r = E.verificar(dato(valor_producto="16 MP"), TEXTOS)
        c = r["parametros"][0]["candidatos"][0]
        self.assertEqual((c["veredicto"], c["valor_producto"]), ("sin_datos", ""))
        self.assertEqual(r["comprobacion"]["degradados_a_sin_datos"], 1)
        self.assertFalse(r["parametros"][0]["cubierto"])

    def test_sin_evidencia_valida_no_hay_cumple(self):
        self.assertEqual(self.cand(dato(evidencia=["P9"]))["veredicto"], "sin_datos")
        self.assertEqual(self.cand(dato(evidencia=[]))["veredicto"], "sin_datos")

    def test_no_comparable_se_deja_sin_verificar_y_se_cuenta(self):
        datos = dato(valor_producto="H.265")
        datos["parametros"][0].update(operador="texto", valor_exigido="H.265")
        r = E.verificar(datos, {"P1": "Compresión H.265 y H.264"})
        c = r["parametros"][0]["candidatos"][0]
        self.assertEqual((c["veredicto"], c["verificado"]), ("supera", False))
        self.assertEqual(r["comprobacion"]["sin_verificar"], 1)
        self.assertEqual(r["parametros"][0]["recomendado"], "")                       # lo no verificado no se recomienda

    def test_recomienda_el_que_supera_y_ordena_primero_los_buenos(self):
        datos = dato()
        datos["parametros"][0]["candidatos"].insert(0, {"producto": "Malo", "valor_producto": "2,8 mm", "veredicto": "no_cumple", "evidencia": ["P1"]})
        datos["parametros"][0]["candidatos"].append({"producto": "X2", "valor_producto": "4 MP", "veredicto": "iguala", "evidencia": ["P2"]})
        p = E.verificar(datos, TEXTOS)["parametros"][0]
        self.assertEqual(p["recomendado"], "MS-C8")
        self.assertEqual([c["producto"] for c in p["candidatos"]], ["MS-C8", "X2", "Malo"])

    def test_la_cita_se_comprueba_contra_el_pliego(self):
        r = E.verificar(dato(), TEXTOS, "El equipo tendrá un mínimo 4 megapíxeles de resolución")
        self.assertTrue(r["parametros"][0]["cita_en_pliego"])
        r = E.verificar(dato(), TEXTOS, "Otro texto sin la frase")
        self.assertFalse(r["parametros"][0]["cita_en_pliego"])

    def test_basura_del_modelo_no_rompe(self):
        r = E.verificar({"parametros": ["x", {"parametro": "", "valor_exigido": ""}, {"parametro": "P", "valor_exigido": "1 m", "operador": "raro", "candidatos": "no"}]}, TEXTOS)
        self.assertEqual(len(r["parametros"]), 1)
        self.assertEqual(r["parametros"][0]["operador"], "texto")

    def test_texto_para_otros_agentes(self):
        t = E.texto_equivalencia(E.verificar(dato(), TEXTOS))
        self.assertIn("Resolución >= 4 MP → MS-C8", t)
        self.assertIn("SIN PRODUCTO", E.texto_equivalencia({"parametros": [{"parametro": "IP", "operador": ">=", "valor_exigido": "IP68", "recomendado": ""}]}))


def par(nombre, *cands):
    """Un parámetro con candidatos [(producto, veredicto, verificado)]."""
    return {"parametro": nombre, "candidatos": [{"producto": p, "veredicto": v, "verificado": ver} for p, v, ver in cands]}


class TestSolucion(unittest.TestCase):
    def test_un_producto_que_cubre_varios_gana_a_uno_por_parametro(self):
        r = E.seleccionar_solucion([par("Resolución", ("X", "iguala", True), ("Y", "iguala", True)), par("IP", ("X", "supera", True))])
        self.assertEqual([p["producto"] for p in r["productos"]], ["X"])
        self.assertEqual(r["asignacion"], {0: "X", 1: "X"})
        self.assertTrue(r["minimo"])

    def test_elige_el_menor_numero_de_productos_que_lo_cubre_todo(self):
        r = E.seleccionar_solucion([par("A", ("P1", "iguala", True), ("P2", "iguala", True)), par("B", ("P2", "iguala", True), ("P3", "iguala", True)), par("C", ("P3", "iguala", True))])
        self.assertEqual(len(r["productos"]), 2)
        self.assertEqual(set(r["asignacion"]), {0, 1, 2})
        self.assertEqual(r["sin_cubrir"], [])

    def test_entre_empates_gana_el_que_mas_supera_y_es_determinista(self):
        pars = [par("A", ("P1", "iguala", True), ("P2", "supera", True)), par("B", ("P1", "iguala", True), ("P2", "supera", True))]
        r = E.seleccionar_solucion(pars)
        self.assertEqual([p["producto"] for p in r["productos"]], ["P2"])
        self.assertEqual(E.seleccionar_solucion(pars), r)

    def test_el_mismo_producto_escrito_de_dos_formas_cuenta_como_uno(self):
        r = E.seleccionar_solucion([par("A", ("MS-C8573", "iguala", True)), par("B", ("Milesight MS-C8573", "iguala", True))])
        self.assertEqual(len(r["productos"]), 1)
        self.assertEqual(r["productos"][0]["producto"], "Milesight MS-C8573")                 # se muestra el nombre más completo
        self.assertEqual(r["asignacion"], {0: "Milesight MS-C8573", 1: "Milesight MS-C8573"})

    def test_lo_no_verificado_o_que_no_cumple_no_cuenta(self):
        r = E.seleccionar_solucion([par("A", ("X", "iguala", False), ("Y", "no_cumple", True), ("Z", "sin_datos", True)), par("B", ("W", "supera", True))])
        self.assertEqual([p["producto"] for p in r["productos"]], ["W"])
        self.assertEqual(r["sin_cubrir"], ["A"])

    def test_sin_ningun_candidato_no_hay_solucion_y_todo_queda_sin_cubrir(self):
        r = E.seleccionar_solucion([par("A"), par("B", ("X", "no_cumple", True))])
        self.assertEqual((r["productos"], r["asignacion"], r["sin_cubrir"]), ([], {}, ["A", "B"]))

    def test_si_no_cabe_en_seis_productos_elige_lo_que_mas_cubre(self):
        pars = [par(f"P{i}", (f"PROD{i:02d}", "iguala", True)) for i in range(8)]
        r = E.seleccionar_solucion(pars)
        self.assertFalse(r["minimo"])
        self.assertEqual((len(r["productos"]), len(r["asignacion"])), (8, 8))

    def test_verificar_recomienda_la_solucion_y_conserva_el_individual(self):
        textos = {"P1": "Cámara X: 8 MP, IP67", "P2": "Cámara Y: 4 MP"}
        datos = {"parametros": [
            {"parametro": "Resolución", "operador": ">=", "valor_exigido": "4 MP", "candidatos": [{"producto": "Y", "valor_producto": "4 MP", "veredicto": "iguala", "evidencia": ["P2"]},
                                                                                              {"producto": "X", "valor_producto": "8 MP", "veredicto": "supera", "evidencia": ["P1"]}]},
            {"parametro": "IP", "operador": ">=", "valor_exigido": "IP66", "candidatos": [{"producto": "X", "valor_producto": "IP67", "veredicto": "supera", "evidencia": ["P1"]}]}]}
        r = E.verificar(datos, textos)
        self.assertEqual([p["recomendado"] for p in r["parametros"]], ["X", "X"])
        self.assertEqual([p["producto"] for p in r["solucion"]["productos"]], ["X"])
        self.assertEqual(r["parametros"][0]["recomendado_individual"], "X")
        self.assertNotIn("asignacion", r["solucion"])


@unittest.skipUnless(URL and hasattr(psycopg, "AsyncConnection"), "sin CEREBRO_TEST_PG")
class TestPaso(unittest.TestCase):
    def setUp(self):
        self.schema = f"t_eqv_{time.time_ns()}"
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"CREATE SCHEMA {self.schema}")
            c.execute(f"SET search_path = {self.schema}")
            t = ESQUEMA.read_text(encoding="utf-8")
            c.execute(t[t.index("-- Pliegos y otros documentos de una licitación"):])
        sep = "&" if "?" in URL else "?"
        aj = SimpleNamespace(database_url=f"{URL}{sep}options=-csearch_path%3D{self.schema}", dir_config=E.O.ajustes.dir_config)
        from cerebro.licitaciones import pliegos
        self.p = [mock.patch.object(O, "ajustes", aj), mock.patch.object(pliegos, "ajustes", aj)]
        for p in self.p:
            p.start()

    def tearDown(self):
        for p in self.p:
            p.stop()
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"DROP SCHEMA {self.schema} CASCADE")

    def test_sin_pliegos_se_omite_y_se_guarda_y_se_lee_lo_hecho(self):
        r = asyncio.run(E.preparar(ID, "Videovigilancia", {}))
        self.assertEqual(r["estado"], "omitida")
        self.assertIn("pliegos", r["resumen"])
        self.assertIsNone(asyncio.run(E.leer(ID)))
        asyncio.run(E._guardar(ID, "claude", "m", {"parametros": []}, [{"id": "P1", "origen": "ficha", "titulo": "t", "fuente": "f", "texto": "no se guarda"}]))
        g = asyncio.run(E.leer(ID))
        self.assertEqual(g["proveedor"], "claude")
        self.assertNotIn("texto", g["evidencias"][0])


if __name__ == "__main__":
    unittest.main()
