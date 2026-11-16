"""Qué marcas distribuye cada proveedor: se agrupan las variantes de las tarifas, se guarda y se consulta por marca."""
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
    from psycopg.types.json import Jsonb

    from cerebro import proveedores_marcas as M
except ImportError as e:      # pragma: no cover
    raise unittest.SkipTest(str(e))

URL = os.environ.get("CEREBRO_TEST_PG")
ESQUEMA = Path(__file__).resolve().parents[2] / "db" / "esquema.sql"


def ejecutar(c):
    return asyncio.run(c)


def lineas(*marcas):
    return [{"ref": f"R{i}", "codigo": f"C{i}", "marca": m, "precio": "1"} for i, m in enumerate(marcas)]


class TestCanonica(unittest.TestCase):
    def test_variantes_de_a_secur_se_juntan_bajo_el_fabricante(self):
        for crudo in ("HIKVISION PRO", "HIKVISION PRO NO CCTV", "HIKVISION PRO INTRUSION", "hikvision", "Hikvision Pro Software"):
            self.assertEqual(M.canonica(crudo), ("Hikvision", "hikvision"), crudo)
        self.assertEqual(M.canonica("MOVOK ACCESSORIES"), ("Movok", "movok"))
        self.assertEqual(M.canonica("ZKTeco")[0], "ZKTeco")

    def test_lineas_propias_del_proveedor(self):
        for crudo in ("A-CCTV", "A-SMARTHOME", "A-FIRE", "A-ELECTRICITY", "A-LARM", "A-CCESS", "A-TIME", "a cctv"):
            self.assertEqual(M.canonica(crudo)[0], "A-Secur (líneas propias)", crudo)

    def test_sin_marca_y_marcas_desconocidas(self):
        for crudo in ("", None, "  ", "Sin Fabricante Asignado", "N/A"):
            self.assertEqual(M.canonica(crudo), (M.SIN_MARCA, ""), str(crudo))
        self.assertEqual(M.canonica("Marca Rara SL"), ("Marca Rara SL", "marca rara sl"))

    def test_no_confunde_prefijos_de_letras(self):
        self.assertEqual(M.canonica("AJAXIS")[0], "AJAXIS")                 # «ajax» solo cuenta como palabra entera
        self.assertEqual(M.canonica("Ajax Systems")[0], "Ajax")

    def test_resumir_cuenta_y_guarda_las_variantes(self):
        r = M.resumir(lineas("HIKVISION PRO", "HIKVISION PRO", "HIKVISION", "AJAX", "", "A-CCTV"))
        self.assertEqual((r["hikvision"]["marca"], r["hikvision"]["articulos"]), ("Hikvision", 3))
        self.assertEqual(r["hikvision"]["variantes"], {"HIKVISION PRO": 2})            # lo que ya es el nombre limpio no es variante
        self.assertEqual(r[""]["articulos"], 1)
        self.assertEqual(M.resumir(["basura", None]), {})


@unittest.skipUnless(URL, "sin CEREBRO_TEST_PG")
class TestEnBase(unittest.TestCase):
    def setUp(self):
        import re
        self.schema = f"t_pm_{time.time_ns()}"
        t = ESQUEMA.read_text(encoding="utf-8")
        tabla = re.search(r"CREATE TABLE IF NOT EXISTS proveedores_marcas \(.*?\n\);", t, re.S).group(0)
        imp = t[t.index("CREATE TABLE IF NOT EXISTS importaciones_precios ("):t.index("-- Propuestas de precios de VENTA")]
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"CREATE SCHEMA {self.schema}")
            c.execute(f"SET search_path = {self.schema}")
            c.execute(imp)
            c.execute(tabla)
        sep = "&" if "?" in URL else "?"
        self.parche = mock.patch.object(M, "ajustes", SimpleNamespace(database_url=f"{URL}{sep}options=-csearch_path%3D{self.schema}", dir_config=M.ajustes.dir_config))
        self.parche.start()

    def tearDown(self):
        self.parche.stop()
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"DROP SCHEMA {self.schema} CASCADE")

    def importar(self, proveedor, lista, marcas, estado="aplicada", tarifa=True):
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"SET search_path = {self.schema}")
            c.execute("INSERT INTO importaciones_precios (agente, departamento, estado, proveedor, lista, lineas, resumen) VALUES ('a','operaciones',%s,%s,%s,%s,%s)",
                      [estado, Jsonb({"nombre": proveedor}), lista, Jsonb(lineas(*marcas)), Jsonb({"tarifa": tarifa})])

    def test_registrar_sustituye_lo_de_tarifa_y_no_toca_lo_manual(self):
        ejecutar(M.anadir_manual("A-Secur", "Bosch", "albert"))
        self.assertEqual(ejecutar(M.registrar("A-Secur", lineas("AJAX", "AJAX", "HIKVISION PRO"))), 2)
        ejecutar(M.registrar("A-Secur", lineas("AJAX")))                            # una tarifa nueva trae menos marcas
        r = ejecutar(M.listar())["proveedores"]
        marcas = {m["marca"]: m for m in r[0]["marcas"]}
        self.assertEqual(set(marcas), {"Ajax", "Bosch"})
        self.assertEqual(marcas["Bosch"]["fuentes"], ["manual"])
        self.assertEqual(marcas["Ajax"]["articulos"], 1)

    def test_reconstruir_usa_la_ultima_de_cada_lista_y_solo_tarifas_vivas(self):
        self.importar("A-Secur", "Compra A-Secur", ["AJAX", "OPTEX"])
        self.importar("A-Secur", "Compra A-Secur", ["AJAX", "HIKVISION PRO", "HIKVISION"])           # la última de esa lista manda
        self.importar("Milesight", "Compra Milesight", ["MILESIGHT"], estado="propuesta")
        self.importar("Otro", "Compra Otro", ["X"], estado="descartada")
        self.importar("Lista", "Lista simple", ["Y"], tarifa=False)
        r = ejecutar(M.reconstruir())
        self.assertEqual(sorted(r["marcas"]), ["A-Secur", "Milesight"])
        lst = {p["proveedor"]: {m["marca"]: m["articulos"] for m in p["marcas"]} for p in ejecutar(M.listar())["proveedores"]}
        self.assertEqual(lst["A-Secur"], {"Hikvision": 2, "Ajax": 1})
        self.assertEqual(lst["Milesight"], {"Milesight": 1})
        self.assertEqual(ejecutar(M.reconstruir())["marcas"], r["marcas"])                          # idempotente

    def test_quien_distribuye_una_marca(self):
        ejecutar(M.registrar("A-Secur", lineas("HIKVISION PRO NO CCTV", "AJAX")))
        ejecutar(M.registrar("Otro SL", lineas("HIKVISION", "DAHUA")))
        ejecutar(M.anadir_manual("Tercero", "hikvision", "albert"))
        r = ejecutar(M.listar("Hikvision"))
        self.assertEqual([p["proveedor"] for p in r["proveedores"]], ["A-Secur", "Otro SL", "Tercero"])
        self.assertTrue(all([m["marca"] for m in p["marcas"]] == ["Hikvision"] for p in r["proveedores"]))
        self.assertEqual([p["proveedor"] for p in ejecutar(M.listar("dahua"))["proveedores"]], ["Otro SL"])
        self.assertEqual(ejecutar(M.listar("Inexistente"))["proveedores"], [])
        with self.assertRaises(ValueError):
            ejecutar(M.listar("N/A"))

    def test_manual_se_anade_y_se_quita_pero_la_de_tarifa_no(self):
        ejecutar(M.registrar("A-Secur", lineas("AJAX")))
        ejecutar(M.anadir_manual("A-Secur", "Ajax", "albert"))                      # también de tarifa: salen juntas
        m = ejecutar(M.listar())["proveedores"][0]["marcas"][0]
        self.assertEqual(sorted(m["fuentes"]), ["manual", "tarifa"])
        self.assertTrue(ejecutar(M.quitar_manual("A-Secur", "AJAX")))
        self.assertFalse(ejecutar(M.quitar_manual("A-Secur", "AJAX")))
        self.assertEqual(ejecutar(M.listar())["proveedores"][0]["marcas"][0]["fuentes"], ["tarifa"])     # la de tarifa sigue
        with self.assertRaises(ValueError):
            ejecutar(M.anadir_manual("A", "x", "albert"))
        with self.assertRaises(ValueError):
            ejecutar(M.anadir_manual("A-Secur", "  ", "albert"))

    def test_endpoints_solo_direccion(self):
        from cerebro.api import main
        from cerebro.api.main import Usuario, usuario_actual
        from fastapi.testclient import TestClient
        cl = TestClient(main.app)
        try:
            main.app.dependency_overrides[usuario_actual] = lambda: Usuario("ana", {"usuario"}, {"licitaciones"})
            self.assertEqual(cl.get("/precios/proveedores-marcas").status_code, 403)
            self.assertEqual(cl.post("/precios/proveedores-marcas/reconstruir").status_code, 403)
            self.assertEqual(cl.post("/precios/proveedores-marcas/manual", json={"proveedor": "A-Secur", "marca": "Ajax"}).status_code, 403)
            main.app.dependency_overrides[usuario_actual] = lambda: Usuario("albert", {"direccion"}, set())
            self.importar("A-Secur", "Compra A-Secur", ["HIKVISION PRO", "AJAX"])
            self.assertEqual(cl.post("/precios/proveedores-marcas/reconstruir").json()["proveedores"], 1)
            r = cl.post("/precios/proveedores-marcas/manual", json={"proveedor": "A-Secur", "marca": "Bosch"})
            self.assertEqual((r.status_code, r.json()["estado"]), (200, "anadida"))
            self.assertEqual(cl.post("/precios/proveedores-marcas/manual", json={"proveedor": "A-Secur", "marca": "Bosch", "accion": "quitar"}).json()["estado"], "quitada")
            self.assertEqual(cl.post("/precios/proveedores-marcas/manual", json={"proveedor": "A-Secur", "marca": "Bosch", "accion": "borrar"}).status_code, 422)
            g = cl.get("/precios/proveedores-marcas?marca=hikvision").json()
            self.assertEqual([m["marca"] for m in g["proveedores"][0]["marcas"]], ["Hikvision"])
            self.assertEqual(cl.get("/precios/proveedores-marcas?marca=n/a").status_code, 422)
        finally:
            main.app.dependency_overrides.clear()


if __name__ == "__main__":
    unittest.main()
