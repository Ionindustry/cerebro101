"""Precios de la competencia y estrategias de precio: validar la referencia, estadísticas, estrategias con suelo de margen y el flujo con la propuesta de precios de venta."""
import asyncio
import os
import tempfile
import time
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import _sin_servicios  # noqa: F401

try:
    import psycopg
    from cerebro import listas_precios as LP, mercado as M, precios, precios_venta as V
except ImportError as e:      # pragma: no cover
    raise unittest.SkipTest(str(e))

URL = os.environ.get("CEREBRO_TEST_PG")
ESQUEMA = Path(__file__).resolve().parents[2] / "db" / "esquema.sql"
HOY = date(2026, 11, 9)


def ejecutar(c):
    return asyncio.run(c)


def cfg():
    return precios.configuracion({"margen": {"por_defecto": 0.5, "minimo": 0.1}, "canales": {"fabricante": {"moneda": "USD", "logistica_pct": 0.15}, "distribuidor": {"moneda": "EUR", "logistica_pct": 0}},
                                  "cambio_a_eur": {"USD": 0.9}})


class TestValidar(unittest.TestCase):
    def v(self, **kw):
        a = dict(tipo="tienda", precio="299,00", fuente="Tienda X", hoy=HOY)
        a.update(kw)
        return M.validar(**a)

    def test_un_precio_de_tienda_lleva_iva_y_se_quita(self):
        r = self.v()
        self.assertEqual((r["precio"], r["iva_incluido_pct"], r["precio_sin_iva"], r["fecha"]), ("299.00", "21", "247.11", "2026-11-09"))

    def test_una_tarifa_va_sin_iva_salvo_que_se_diga(self):
        self.assertEqual(self.v(tipo="tarifa", precio="100")["precio_sin_iva"], "100.00")
        self.assertEqual(self.v(tipo="distribuidor", precio="121", iva_incluido_pct=21)["precio_sin_iva"], "100.00")

    def test_sin_fuente_o_con_datos_raros_no_se_anota(self):
        for kw, texto in (({"fuente": " "}, "fuente"), ({"tipo": "foro"}, "tipo"), ({"precio": "gratis"}, "precio"), ({"precio": "0"}, "mayor"), ({"url": "http://tienda.es/x"}, "https"),
                          ({"url": "javascript:alert(1)"}, "https"), ({"fecha": "2027-01-01"}, "futura"), ({"fecha": "ayer"}, "aaaa-mm-dd"), ({"moneda": "USD"}, "euros"), ({"iva_incluido_pct": 90}, "IVA")):
            with self.assertRaisesRegex(M.ErrorMercado, texto, msg=str(kw)):
                self.v(**kw)


def ref(tipo, sin_iva, fecha="2026-11-01"):
    return {"tipo": tipo, "precio_sin_iva": sin_iva, "fecha": fecha}


class TestEstadisticasYEstrategias(unittest.TestCase):
    def test_minimo_mediana_maximo_sin_contar_viejas_ni_adjudicaciones(self):
        e = M.estadisticas([ref("tienda", "200"), ref("tienda", "220"), ref("tarifa", "260"), ref("tienda", "100", "2026-01-01"), ref("adjudicacion", "50000")], 90, HOY)
        self.assertEqual((e["n"], e["minimo"], e["mediana"], e["maximo"], e["antiguas"], e["contexto"], e["mas_reciente"]), (3, "200.00", "220.00", "260.00", 1, 1, "2026-11-01"))

    def test_sin_referencias_no_hay_estadisticas_y_solo_viejas_se_dice(self):
        self.assertIsNone(M.estadisticas([], 90, HOY))
        self.assertEqual(M.estadisticas([ref("tienda", "100", "2026-01-01")], 90, HOY), {"n": 0, "antiguas": 1, "contexto": 0})

    def test_las_estrategias_parten_de_la_competencia(self):
        e = precios.estrategias_de_precio(Decimal("100"), {"minimo": "180", "mediana": "200", "maximo": "230"}, cfg())
        self.assertEqual({k: v["precio"] for k, v in e.items()}, {"competitivo": "174.60", "alineado": "200.00", "premium": "210.00"})
        self.assertFalse(any(v["limitada"] for v in e.values()))

    def test_nunca_bajan_del_margen_minimo(self):
        e = precios.estrategias_de_precio(Decimal("100"), {"minimo": "105", "mediana": "110", "maximo": "230"}, cfg())
        self.assertEqual((e["competitivo"]["precio"], e["competitivo"]["margen"], e["competitivo"]["limitada"]), ("111.11", "0.1000", True))   # 100 ÷ 0,9
        self.assertFalse(e["premium"]["limitada"])
        self.assertEqual(precios.estrategias_de_precio(Decimal("100"), None, cfg()), {})

    def test_el_redondeo_se_aplica_a_las_estrategias(self):
        c = precios.configuracion({"redondeo": {"modo": "terminar_en", "terminacion": 0.90}})
        e = precios.estrategias_de_precio(Decimal("100"), {"minimo": "180", "mediana": "200", "maximo": "230"}, c)
        self.assertEqual(e["competitivo"]["precio"], "174.90")

    def test_estrategias_mal_configuradas_son_un_error_claro(self):
        with self.assertRaises(precios.ErrorPrecios):
            precios.configuracion({"estrategias": {"x": {"base": "inventada", "ajuste": 0}}})
        with self.assertRaises(precios.ErrorPrecios):
            precios.configuracion({"estrategias": {"x": {"base": "minimo", "ajuste": 5}}})

    def test_la_propuesta_lleva_mercado_y_estrategias_por_articulo(self):
        of = {"A": {"a": {"proveedor": "Milesight", "lista": "Compra Milesight", "canal": "fabricante", "coste": "100", "moneda": "USD", "stock": None, "ref": "A", "desc": "Cam", "familia": "Camaras",
                          "marca": "Milesight", "pvp": "400"}},
              "B": {"a": {"proveedor": "Milesight", "lista": "Compra Milesight", "canal": "fabricante", "coste": "100", "moneda": "USD", "stock": None, "ref": "B", "desc": "Cam", "familia": "Camaras",
                          "marca": "Milesight", "pvp": None}}}
        lineas, _ = V.calcular_lineas(of, cfg(), {}, referencias={"A": [ref("tienda", "300"), ref("tienda", "330")]}, hoy=HOY)
        a, b = lineas
        self.assertEqual((a["mercado"]["n"], a["estrategias"]["alineado"]["precio"], a["pvp_fabricante"]), (2, "315.00", "400"))
        self.assertEqual((b["mercado"], b["estrategias"]), (None, {}))
        self.assertEqual(a["venta"], "207.00")                                             # el precio de partida sigue siendo el del margen objetivo


@unittest.skipUnless(URL and hasattr(psycopg, "AsyncConnection"), "sin CEREBRO_TEST_PG")
class TestFlujoMercado(unittest.TestCase):
    def setUp(self):
        from psycopg.types.json import Jsonb
        self.schema = f"t_mercado_{time.time_ns()}"
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"CREATE SCHEMA {self.schema}")
            c.execute(f"SET search_path = {self.schema}")
            t = ESQUEMA.read_text(encoding="utf-8")
            c.execute(t[t.index("-- Importaciones de listas de precios de proveedores"):t.index("-- DEUC base de cada sociedad")])
        sep = "&" if "?" in URL else "?"
        dsn = f"{URL}{sep}options=-csearch_path%3D{self.schema}"
        self.carpeta = tempfile.TemporaryDirectory()
        from test_listas_precios import ErpFalso
        self.erp = ErpFalso()
        self.p = [mock.patch.object(LP, "ajustes", SimpleNamespace(database_url=dsn, dir_config=self.carpeta.name)), mock.patch.object(LP, "erpnext", self.erp),
                  mock.patch.object(LP.cambio, "configuracion_de_precios", mock.AsyncMock(return_value=cfg()))]
        for p in self.p:
            p.start()
        lin = [{"codigo": "MILESI-MS-C1", "ref": "MS-C1", "desc": "Camara", "precio": "100.0000", "familia": "Camaras", "marca": "Milesight", "stock": None, "pvp": "400"},
               {"codigo": "MILESI-MS-C2", "ref": "MS-C2", "desc": "Camara 2", "precio": "250.0000", "familia": "Accesorios", "marca": "Milesight", "stock": None, "pvp": None}]
        with psycopg.connect(dsn, autocommit=True) as c:
            c.execute("INSERT INTO importaciones_precios (agente, departamento, estado, proveedor, moneda, lista, lineas, resumen) VALUES ('a','operaciones','aplicada',%s,'USD','Compra Milesight',%s,%s)",
                      [Jsonb({"nombre": "Milesight"}), Jsonb(lin), Jsonb({"tarifa": True, "canal": "fabricante"})])

    def tearDown(self):
        for p in self.p:
            p.stop()
        self.carpeta.cleanup()
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"DROP SCHEMA {self.schema} CASCADE")

    def test_anotar_listar_retirar_y_codigo_desconocido(self):
        r = ejecutar(M.anotar("MILESI-MS-C1", "tienda", 299, "Tienda X", "precio", url="https://tienda.example/x"))
        self.assertEqual((r["precio_sin_iva"], r["codigo"]), ("247.11", "MILESI-MS-C1"))
        with self.assertRaisesRegex(M.ErrorMercado, "no tiene coste cargado"):
            ejecutar(M.anotar("NO-EXISTE", "tienda", 299, "Tienda X", "precio"))
        l = ejecutar(M.listar("MILESI-MS-C1"))
        self.assertEqual((len(l["referencias"]), l["estadisticas"]["n"], l["estadisticas"]["minimo"]), (1, 1, "247.11"))
        ejecutar(M.retirar(r["referencia"]))
        self.assertEqual(ejecutar(M.listar("MILESI-MS-C1"))["referencias"], [])
        with self.assertRaises(M.ErrorMercado):
            ejecutar(M.retirar(r["referencia"]))

    def test_proponer_con_competencia_y_elegir_una_estrategia(self):
        ejecutar(M.anotar("MILESI-MS-C1", "tienda", 363, "Tienda X", "precio"))                 # 363 con IVA = 300 sin IVA
        ejecutar(M.anotar("MILESI-MS-C1", "tarifa", 330, "Tarifa de otro distribuidor", "precio"))
        ejecutar(M.anotar("MILESI-MS-C1", "adjudicacion", 90000, "Licitación X (contrato completo)", "precio"))
        r = ejecutar(V.proponer("precio", "operaciones"))
        self.assertEqual((r["articulos"], r["con_mercado"]), (2, 1))
        a = ejecutar(V.elegir_estrategia(r["propuesta"], "alineado", familia="Camaras"))
        self.assertEqual((a["articulos"], a["ajustados"]), (1, 1))
        f = ejecutar(V.vista_aplicar(r["propuesta"], "operaciones"))
        self.assertIn("1 artículos con precios de la competencia", "\n".join(f"{k}: {x}" for k, x in f["campos"]))
        res = ejecutar(V.aplicar(r["propuesta"], "operaciones"))
        precios_erp = {v["item_code"]: v["price_list_rate"] for v in self.erp.precios.values()}
        self.assertEqual(precios_erp["MILESI-MS-C1"], 315.0)                                   # la mediana de 300 y 330
        self.assertEqual(precios_erp["MILESI-MS-C2"], 517.5)                                   # sin competencia: el margen del 50 %
        self.assertEqual(res["precios_nuevos"], 2)

    def test_elegir_estrategia_errores_claros(self):
        r = ejecutar(V.proponer("precio", "operaciones"))
        with self.assertRaisesRegex(V.ErrorVenta, "faltan precios de la competencia"):
            ejecutar(V.elegir_estrategia(r["propuesta"], "alineado"))


if __name__ == "__main__":
    unittest.main()
