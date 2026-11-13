"""Partidas de equipos y coste real: casar el producto con la tarifa, calcular en euros, totales honestos y que el coste (confidencial) solo llegue al modelo local."""
import asyncio
import os
import time
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import _sin_servicios  # noqa: F401

try:
    import psycopg
    from cerebro import precios
    from cerebro.licitaciones import equivalencia as Q, ofertas as O, partidas as P, redaccion as R
    from cerebro.licitaciones import redaccion_externa as X
except ImportError as e:      # pragma: no cover
    raise unittest.SkipTest(str(e))

URL = os.environ.get("CEREBRO_TEST_PG")
ESQUEMA = Path(__file__).resolve().parents[2] / "db" / "esquema.sql"
ID = "0b1f7a3e-1111-4222-8333-4444444444bb"
FICHA = {"criterios": [{"tipo": "SUBJ", "descripcion": "Memoria técnica", "peso": 30}, {"tipo": "OBJ", "descripcion": "Oferta económica (precio)", "peso": 70}]}
CFG = precios.configuracion()


def of(ref, coste="100", moneda="EUR", canal="distribuidor", marca="Milesight", stock="5", proveedor="Prov"):
    return {"proveedor": proveedor, "lista": f"Compra {proveedor}", "canal": canal, "coste": coste, "moneda": moneda, "stock": stock, "ref": ref, "desc": "x", "familia": "", "marca": marca, "pvp": None}


OFERTAS = {"MIL-MS-C8573": {"Compra A": of("MS-C8573", "100")}, "MIL-MS-C8": {"Compra A": of("MS-C8", "50")}, "AXI-P3245": {"Compra B": of("P3245-LVE", "200", proveedor="B", marca="Axis")}}


class TestEmparejar(unittest.TestCase):
    def test_casa_por_referencia_dentro_del_texto(self):
        self.assertEqual(P.emparejar("Milesight MS-C8573 domo 4MP", OFERTAS), "MIL-MS-C8573")
        self.assertEqual(P.emparejar("Axis P3245-LVE", OFERTAS), "AXI-P3245")

    def test_gana_la_referencia_mas_larga(self):
        self.assertEqual(P.emparejar("MS-C8573", OFERTAS), "MIL-MS-C8573")                 # «MSC8» también está dentro, pero la larga manda

    def test_sin_coincidencia_o_con_empate_no_se_elige_ninguno(self):
        self.assertIsNone(P.emparejar("Cámara genérica", OFERTAS))
        empate = {"A-ABCD1": {"l": of("ABCD1", marca="")}, "B-ABCD1": {"l": of("ABCD1", marca="")}}
        self.assertIsNone(P.emparejar("Cámara ABCD1", empate))
        con_marca = {"A-ABCD1": {"l": of("ABCD1", marca="Alfa")}, "B-ABCD1": {"l": of("ABCD1", marca="Beta")}}
        self.assertEqual(P.emparejar("Beta ABCD1", con_marca), "B-ABCD1")                  # la marca desempata

    def test_una_referencia_corta_no_casa(self):
        self.assertIsNone(P.emparejar("Cámara A12 domo", {"X-A12": {"l": of("A12")}}))


class TestCoste(unittest.TestCase):
    def test_el_coste_sale_en_euros_con_el_calculo_de_precios(self):
        c = P.costear("MIL-MS-C8573", OFERTAS, CFG)
        self.assertGreaterEqual(c["coste_unit_eur"], Decimal("100"))                        # con logística del canal no baja del coste de tarifa
        self.assertGreater(c["venta_unit_eur"], c["coste_unit_eur"])                       # con margen
        self.assertEqual(c["proveedor"], "Prov")

    def test_sin_tarifa_dice_que_no_esta(self):
        c = P.costear(None, OFERTAS, CFG)
        self.assertIsNone(c["coste_unit_eur"])
        self.assertIn("No está en las tarifas", c["motivo"])

    def test_las_filas_y_los_totales_solo_suman_lo_completo(self):
        partidas = [{"id": 1, "producto": "Milesight MS-C8573", "parametros": ["Resolución 4 MP"], "origen": "equivalencia", "excluida": False, "cantidad": Decimal("10")},
                    {"id": 2, "producto": "Axis P3245-LVE", "parametros": [], "origen": "manual", "excluida": False, "cantidad": None},
                    {"id": 3, "producto": "Marca X desconocida", "parametros": [], "origen": "manual", "excluida": False, "cantidad": Decimal("2")},
                    {"id": 4, "producto": "Milesight MS-C8", "parametros": [], "origen": "manual", "excluida": True, "cantidad": Decimal("99")}]
        filas = P.calcular_filas(partidas, OFERTAS, CFG)
        t = P.totales(filas)
        self.assertEqual(t["completas"], 1)
        self.assertEqual(t["sin_cantidad"], ["Axis P3245-LVE"])
        self.assertEqual(t["sin_coste"], ["Marca X desconocida"])
        self.assertFalse(t["completo"])
        unit = Decimal(filas[0]["coste_unit_eur"])
        self.assertEqual(Decimal(t["coste_eur"]), (unit * 10).quantize(Decimal("0.01")))
        self.assertNotIn("Milesight MS-C8", t["sin_cantidad"] + t["sin_coste"])           # la excluida no cuenta

    def test_el_texto_para_el_agente_marca_lo_confidencial_y_lo_que_falta(self):
        partidas = [{"id": 1, "producto": "Milesight MS-C8573", "parametros": [], "origen": "manual", "excluida": False, "cantidad": Decimal("3")},
                    {"id": 2, "producto": "Marca X", "parametros": [], "origen": "manual", "excluida": False, "cantidad": None}]
        filas = P.calcular_filas(partidas, OFERTAS, CFG)
        t = P.texto_de_partidas(filas, P.totales(filas))
        self.assertIn("CONFIDENCIAL", t)
        self.assertIn("SIN COSTE EN LAS TARIFAS", t)
        self.assertIn("TOTAL INCOMPLETO", t)
        self.assertEqual(P.texto_de_partidas([], P.totales([])), "")

    def test_una_cantidad_rara_es_un_error(self):
        for v in ("abc", "-1", "9999999999"):
            with self.assertRaises(P.ErrorPartida, msg=v):
                P._dec(v)
        self.assertEqual(P._dec("2,5"), Decimal("2.5"))
        self.assertIsNone(P._dec(""))

    def test_desde_la_tabla_de_equivalencias_agrupa_por_producto(self):
        c = {"parametros": [{"parametro": "Resolución", "valor_exigido": "4 MP", "recomendado": "MS-C8573"}, {"parametro": "IP", "valor_exigido": "IP67", "recomendado": "MS-C8573"},
                            {"parametro": "PoE", "valor_exigido": "802.3af", "recomendado": ""}, {"parametro": "Zoom", "valor_exigido": "3x", "recomendado": "Axis P3245"}]}
        r = P.desde_equivalencia(c)
        self.assertEqual([(x["producto"], len(x["parametros"])) for x in r], [("MS-C8573", 2), ("Axis P3245", 1)])


@unittest.skipUnless(URL, "sin CEREBRO_TEST_PG")
class TestFlujo(unittest.TestCase):
    def setUp(self):
        self.schema = f"t_part_{time.time_ns()}"
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"CREATE SCHEMA {self.schema}")
            c.execute(f"SET search_path = {self.schema}")
            t = ESQUEMA.read_text(encoding="utf-8")
            c.execute(t[t.index("-- Pliegos y otros documentos de una licitación"):])
        sep = "&" if "?" in URL else "?"
        aj = SimpleNamespace(database_url=f"{URL}{sep}options=-csearch_path%3D{self.schema}")
        from cerebro.licitaciones import pliegos
        self.p = [mock.patch.object(O, "ajustes", aj), mock.patch.object(pliegos, "ajustes", aj), mock.patch.object(P, "_material", mock.AsyncMock(return_value=(OFERTAS, CFG)))]
        for p in self.p:
            p.start()

    def tearDown(self):
        for p in self.p:
            p.stop()
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"DROP SCHEMA {self.schema} CASCADE")

    def run_(self, c):
        return asyncio.run(c)

    def tabla(self):
        self.run_(Q._guardar(ID, "claude", "m", {"parametros": [{"parametro": "Resolución", "valor_exigido": "4 MP", "recomendado": "Milesight MS-C8573"}]}, []))

    def test_sin_tabla_de_equivalencias_no_hay_que_costear(self):
        with self.assertRaises(P.ErrorPartida):
            self.run_(P.proponer(ID, "albert"))

    def test_proponer_ajustar_y_conservar_lo_de_la_persona(self):
        self.tabla()
        d = self.run_(P.proponer(ID, "albert"))
        self.assertEqual(len(d["partidas"]), 1)
        self.assertEqual(d["partidas"][0]["codigo"], "MIL-MS-C8573")
        self.assertIsNone(d["partidas"][0]["subtotal_eur"])                               # sin cantidad
        pid = d["partidas"][0]["id"]
        d = self.run_(P.ajustar(ID, pid, "10", None, "albert"))
        self.assertIsNotNone(d["partidas"][0]["subtotal_eur"])
        self.assertTrue(d["totales"]["completo"])
        d = self.run_(P.anadir(ID, "Axis P3245-LVE", "2", "albert"))
        self.assertEqual(len(d["partidas"]), 2)
        d = self.run_(P.proponer(ID, "albert"))                                              # repetir no pisa cantidades ni borra lo manual
        self.assertEqual({x["producto"]: x["cantidad"] for x in d["partidas"]}, {"Milesight MS-C8573": "10", "Axis P3245-LVE": "2"})
        d = self.run_(P.ajustar(ID, pid, ..., True, "albert"))
        self.assertEqual(d["totales"]["partidas"], 1)                                        # la excluida no cuenta
        d = self.run_(P.ajustar(ID, pid, None, None, "albert"))
        self.assertIsNone(d["partidas"][0]["cantidad"])
        d = self.run_(P.quitar(ID, pid))
        self.assertEqual(len(d["partidas"]), 1)
        with self.assertRaises(P.ErrorPartida):
            self.run_(P.ajustar(ID, 99999, "1", None, "albert"))

    def test_lo_que_ya_no_se_recomienda_y_no_tiene_cantidad_se_quita(self):
        self.tabla()
        self.run_(P.proponer(ID, "albert"))
        self.run_(Q._guardar(ID, "claude", "m", {"parametros": [{"parametro": "Zoom", "valor_exigido": "3x", "recomendado": "Axis P3245-LVE"}]}, []))
        d = self.run_(P.proponer(ID, "albert"))
        self.assertEqual([x["producto"] for x in d["partidas"]], ["Axis P3245-LVE"])

    def test_el_texto_confidencial_se_lo_da_solo_al_agente_local_de_costes_y_precio(self):
        self.tabla()
        d = self.run_(P.proponer(ID, "albert"))
        self.run_(P.ajustar(ID, d["partidas"][0]["id"], "10", None, "albert"))
        self.assertIn("CONFIDENCIAL", self.run_(P.texto_para(ID)))

    def test_el_coste_no_se_guarda_en_la_base(self):
        self.tabla()
        self.run_(P.proponer(ID, "albert"))
        with psycopg.connect(URL + ("&" if "?" in URL else "?") + f"options=-csearch_path%3D{self.schema}") as c:
            cols = [r[0] for r in c.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'ofertas_partidas'").fetchall()]
        self.assertFalse([c for c in cols if "coste" in c or "precio" in c or "venta" in c])


@unittest.skipUnless(URL, "sin CEREBRO_TEST_PG")
class TestNoSaleALaNube(unittest.TestCase):
    """El coste real nunca viaja a Claude ni a ChatGPT: ni en Costes con «externo» ni en los pasos de memoria."""
    def setUp(self):
        TestFlujo.setUp(self)
        self.run_ = TestFlujo.run_.__get__(self)
        from cerebro.licitaciones import pliegos
        self.p += [mock.patch.object(R, "_titulo_y_ficha", mock.AsyncMock(return_value=("Videovigilancia", FICHA))),
                   mock.patch.object(R, "_preparar_plantillas", mock.AsyncMock(return_value={"documentos": []}))]
        self.p[-2].start()
        self.p[-1].start()
        self.run_(O.plan(ID, FICHA, "albert"))
        self.tabla = lambda: TestFlujo.tabla(self)
        self.tabla()
        d = self.run_(P.proponer(ID, "albert"))
        self.run_(P.ajustar(ID, d["partidas"][0]["id"], "10", None, "albert"))

    tearDown = TestFlujo.tearDown

    def test_costes_externo_manda_a_la_nube_sin_costes_y_el_local_si_los_recibe(self):
        self.run_(R.cerrar(self.run_(R.reservar(ID, "albert"))["id"], ""))
        visto, peticiones = {}, []

        async def externo(motor_id, defin, sel, titulo, ficha, consulta=None, modelo="auto", **kw):
            visto["todo"] = repr((defin, kw))
            return None, "sin proveedor"

        async def invocar(agente, peticion):
            peticiones.append((agente, peticion))
            return {"respuesta": "ok"}
        e = self.run_(R.reservar(ID, "albert", solo="costes", modos=X.validar_modos({"costes": "externo"}, ["costes"], "albert")))
        with mock.patch.object(X, "intentar", externo):
            self.run_(R.ejecutar(e["id"], invocar))
        self.assertNotIn("CONFIDENCIAL", visto["todo"])
        self.assertNotIn("coste unitario", visto["todo"])
        local = [p for a, p in peticiones if a == "costes-licitacion"]
        self.assertTrue(local and "coste unitario" in local[0])                              # si el externo no responde, lo hace el local, que sí ve el coste

    def test_costes_local_y_el_informe_de_precio_reciben_el_coste(self):
        self.run_(R.cerrar(self.run_(R.reservar(ID, "albert"))["id"], ""))
        peticiones = {}

        async def invocar(agente, peticion):
            peticiones[agente] = peticion
            return {"respuesta": "ok"}
        for paso in ("costes", "precio"):
            e = self.run_(R.reservar(ID, "albert", solo=paso))
            self.run_(R.ejecutar(e["id"], invocar))
        self.assertIn("coste unitario", peticiones["costes-licitacion"])
        self.assertIn("coste unitario", peticiones["precio-licitacion"])
        self.assertIn("suelo del precio", peticiones["precio-licitacion"])


if __name__ == "__main__":
    unittest.main()
