"""Actualización periódica de tarifas: configuración, JSON→CSV, cambios y sospechas, descarga segura y que cada fichero nuevo deje UNA propuesta sin aplicar nada."""
import asyncio
import json
import os
import tempfile
import time
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import _sin_servicios  # noqa: F401

try:
    import httpx
    import psycopg
    from cerebro import listas_precios as LP
    from cerebro import tarifas_auto as T
except ImportError as e:      # pragma: no cover
    raise unittest.SkipTest(str(e))

URL = os.environ.get("CEREBRO_TEST_PG")
ESQUEMA = Path(__file__).resolve().parents[2] / "db" / "esquema.sql"
PROV = {"id": "milesight", "proveedor": {"nombre": "Milesight"}, "canal": "fabricante", "origen": "carpeta"}
PROV_URL = {"id": "dist-x", "proveedor": {"nombre": "Distribuidor X"}, "canal": "distribuidor", "origen": "url", "url": "https://api.dist-x.com/v1/tarifa", "hosts": ["dist-x.com"], "formato": "csv",
            "clave_secreto": "DIST_X", "cabecera": "Authorization", "cabecera_formato": "Bearer {clave}"}


def ejecutar(c):
    return asyncio.run(c)


class TestConfig(unittest.TestCase):
    def test_un_proveedor_de_carpeta_valido(self):
        v = T.validar_proveedor({**PROV, "moneda": "usd"})
        self.assertEqual((v["id"], v["moneda"], v["origen"]), ("milesight", "USD", "carpeta"))

    def test_errores_que_dicen_que_falta(self):
        malos = [({**PROV, "id": "Mal Id"}, "id"), ({**PROV, "proveedor": {}}, "nombre"), ({**PROV, "canal": "otro"}, "canal"), ({**PROV, "origen": "ftp"}, "origen"),
                 ({**PROV_URL, "url": "http://api.dist-x.com/t"}, "https"), ({**PROV_URL, "url": "https://otro.com/t"}, "dominios"), ({**PROV_URL, "formato": "pdf"}, "formato"),
                 ({**PROV_URL, "formato": "json", "json": {"columnas": {"referencia": "sku"}}}, "coste"), "no es un bloque"]
        for p, palabra in [(m if isinstance(m, tuple) else (m, "bloque")) for m in malos]:
            with self.assertRaises(T.ErrorTarifaAuto, msg=str(p)) as e:
                T.validar_proveedor(p)
            self.assertIn(palabra, str(e.exception))

    def test_un_proveedor_mal_configurado_no_tumba_a_los_demas_y_no_se_repite_el_id(self):
        ok, errores = T.proveedores_validos({"proveedores": [PROV, {**PROV, "canal": "x"}, PROV, {**PROV, "id": "otro"}], "carpeta_base": "/x", "max_mb": 5})
        self.assertEqual([p["id"] for p in ok], ["milesight", "otro"])
        self.assertEqual(len(errores), 2)

    def test_por_defecto_no_hay_proveedores(self):
        self.assertEqual(T.configuracion()["proveedores"], [])

    def test_la_clave_sale_del_fichero_de_secretos_no_de_la_configuracion(self):
        with tempfile.TemporaryDirectory() as d:
            ruta = Path(d) / "tarifas.env"
            ruta.write_text("# c\nDIST_X='abc123'\nOTRA=zzz\n", encoding="utf-8")
            with mock.patch.object(T, "RUTA_SECRETOS", str(ruta)):
                self.assertEqual(T.secreto("DIST_X"), "abc123")
                self.assertEqual(T.secreto("NO_EXISTE"), "")
            with mock.patch.object(T, "RUTA_SECRETOS", str(Path(d) / "no.env")):
                self.assertEqual(T.secreto("DIST_X"), "")


class TestJson(unittest.TestCase):
    J = {"lista": "data.items", "columnas": {"referencia": "sku", "coste": "price", "marca": "brand"}}

    def test_json_a_csv_con_la_ruta_y_las_columnas(self):
        datos = json.dumps({"data": {"items": [{"sku": "A1", "price": 10.5, "brand": "X"}, {"sku": "B2", "price": None}, "basura"]}}).encode()
        filas = T.json_a_csv(datos, self.J).decode().splitlines()
        self.assertEqual(filas, ["referencia;coste;marca", "A1;10.5;X", "B2;;"])

    def test_json_malo_o_sin_lista_es_un_error_claro(self):
        for datos in (b"no json", json.dumps({"data": {}}).encode(), json.dumps({"data": {"items": []}}).encode()):
            with self.assertRaises(T.ErrorTarifaAuto):
                T.json_a_csv(datos, self.J)


def l(codigo, coste):
    return {"codigo": codigo, "precio": str(coste), "coste_eur": str(coste)}


class TestCambios(unittest.TestCase):
    def test_nuevos_retirados_suben_bajan(self):
        ant = [l("A", 100), l("B", 100), l("C", 100), l("D", 100)]
        nue = [l("A", 110), l("B", 95), l("C", 100), l("E", 50)]
        c = T.comparar(ant, nue)
        self.assertEqual((c["nuevos"], c["retirados"], c["suben"], c["bajan"], c["iguales"]), (1, 1, 1, 1, 1))
        self.assertEqual(c["mayores"][0], {"codigo": "A", "variacion_pct": "10.0"})
        self.assertFalse(c["sospechosa"])

    def test_la_primera_tarifa_no_se_compara(self):
        c = T.comparar(None, [l("A", 1)])
        self.assertTrue(c["primera"])
        self.assertFalse(c["sospechosa"])

    def test_si_desaparece_media_tarifa_es_sospechosa(self):
        c = T.comparar([l(str(i), 10) for i in range(10)], [l(str(i), 10) for i in range(5)])
        self.assertTrue(c["sospechosa"])
        self.assertIn("Desaparecen 5 de 10", c["avisos"][0])

    def test_si_casi_todo_cambia_mucho_es_sospechosa(self):
        c = T.comparar([l(str(i), 10) for i in range(10)], [l(str(i), 20) for i in range(10)])
        self.assertTrue(c["sospechosa"])
        self.assertIn("columna", c["avisos"][0])

    def test_un_cambio_normal_no_es_sospechoso(self):
        self.assertFalse(T.comparar([l(str(i), 100) for i in range(10)], [l(str(i), 103) for i in range(10)])["sospechosa"])


class TestCarpeta(unittest.TestCase):
    def test_lee_solo_excel_y_csv_ya_copiados_del_mas_nuevo_al_mas_viejo(self):
        with tempfile.TemporaryDirectory() as d:
            c = Path(d) / "milesight"
            c.mkdir()
            ahora = time.time()
            for nombre, edad in (("viejo.csv", 5000), ("nuevo.xlsx", 3000), ("copiandose.csv", 5), ("nota.txt", 9000), ("tarifa.pdf", 9000)):
                f = c / nombre
                f.write_bytes(b"x")
                os.utime(f, (ahora - edad, ahora - edad))
            (c / "enlace.csv").symlink_to(c / "viejo.csv")
            self.assertEqual([n for n, _ in T.ficheros_de_carpeta(d, "milesight", ahora)], ["nuevo.xlsx", "viejo.csv"])
            self.assertEqual(T.ficheros_de_carpeta(d, "no-existe", ahora), [])


class TestDescarga(unittest.TestCase):
    def llamar(self, handler, p=PROV_URL, **kw):
        async def resolver(url):
            return ("https", "api.dist-x.com", 443, ["93.184.216.34"])
        with tempfile.TemporaryDirectory() as d:
            ruta = Path(d) / "t.env"
            ruta.write_text("DIST_X=secreto-de-prueba\n", encoding="utf-8")
            with mock.patch.object(T, "RUTA_SECRETOS", str(ruta)):
                return ejecutar(T.descargar(p, kw.get("max_bytes", 1_000_000), httpx.MockTransport(handler), resolver))

    def test_baja_el_fichero_con_la_clave_en_la_cabecera_sin_mostrarla_en_ningun_lado(self):
        vistos = {}

        def h(req):
            vistos["auth"], vistos["host"] = req.headers.get("authorization"), req.headers.get("host")
            return httpx.Response(200, content=b"referencia;coste\nA;1\n", headers={"content-type": "text/csv"})
        nombre, datos = self.llamar(h)
        self.assertEqual((vistos["auth"], vistos["host"]), ("Bearer secreto-de-prueba", "api.dist-x.com"))
        self.assertTrue(nombre.startswith("dist-x-") and nombre.endswith(".csv"))
        self.assertIn(b"A;1", datos)

    def test_errores_http_tipo_raro_y_tamano(self):
        with self.assertRaisesRegex(T.ErrorTarifaAuto, "error 500"):
            self.llamar(lambda r: httpx.Response(500))
        with self.assertRaisesRegex(T.ErrorTarifaAuto, "no es una tarifa"):
            self.llamar(lambda r: httpx.Response(200, content=b"<html>", headers={"content-type": "text/html"}))
        with self.assertRaisesRegex(T.ErrorTarifaAuto, "pasa de"):
            self.llamar(lambda r: httpx.Response(200, content=b"x" * 5000, headers={"content-type": "text/csv"}), max_bytes=1000)

    def test_una_redireccion_a_otro_dominio_se_rechaza(self):
        with self.assertRaisesRegex(T.ErrorTarifaAuto, "dominio"):
            self.llamar(lambda r: httpx.Response(302, headers={"location": "https://malo.com/x"}))

    def test_sin_la_clave_en_secretos_no_se_pide(self):
        async def resolver(url):
            return ("https", "api.dist-x.com", 443, ["93.184.216.34"])
        with mock.patch.object(T, "RUTA_SECRETOS", "/no/existe"):
            with self.assertRaisesRegex(T.ErrorTarifaAuto, "Falta la clave"):
                ejecutar(T.descargar(PROV_URL, 1000, httpx.MockTransport(lambda r: httpx.Response(200)), resolver))

    def test_un_json_se_convierte_a_csv(self):
        p = {**PROV_URL, "formato": "json", "json": {"lista": "", "columnas": {"referencia": "sku", "coste": "price"}}}
        _n, datos = self.llamar(lambda r: httpx.Response(200, content=json.dumps([{"sku": "A", "price": 3}]).encode(), headers={"content-type": "application/json"}), p)
        self.assertEqual(datos.decode().splitlines(), ["referencia;coste", "A;3"])


@unittest.skipUnless(URL, "sin CEREBRO_TEST_PG")
class TestFlujo(unittest.TestCase):
    def setUp(self):
        self.schema = f"t_tauto_{time.time_ns()}"
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"CREATE SCHEMA {self.schema}")
            c.execute(f"SET search_path = {self.schema}")
            t = ESQUEMA.read_text(encoding="utf-8")
            c.execute(t[t.index("-- Pliegos y otros documentos de una licitación"):])
        sep = "&" if "?" in URL else "?"
        self.aj = SimpleNamespace(database_url=f"{URL}{sep}options=-csearch_path%3D{self.schema}", dir_config=T.ajustes.dir_config)
        self.p = [mock.patch.object(T, "ajustes", self.aj), mock.patch.object(LP, "ajustes", self.aj)]
        for p in self.p:
            p.start()
        self.llamadas = []

        async def subir(usuario, nombre, datos):
            self.llamadas.append(("subir", usuario, nombre))
            return {"id": "0b1f7a3e-1111-4222-8333-444444444401", "estado": "limpio"}

        async def proponer(documento, proveedor, canal, agente, departamento, moneda=None):
            self.llamadas.append(("proponer", canal, agente, moneda))
            async with await T._conectar() as conn:
                cur = await conn.execute("INSERT INTO importaciones_precios (documento_id, agente, departamento, proveedor, moneda, lista, lineas, resumen) VALUES (%s,%s,%s,%s,'EUR','Compra X',%s,%s) RETURNING id",
                                         [documento, agente, departamento, psycopg.types.json.Jsonb(proveedor), psycopg.types.json.Jsonb(self.lineas), psycopg.types.json.Jsonb({"tarifa": True, "canal": canal})])
                return {"importacion": (await cur.fetchone())["id"]}
        self.subir, self.proponer = subir, proponer
        self.lineas = [l("A", 100), l("B", 50)]

    def tearDown(self):
        for p in self.p:
            p.stop()
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"DROP SCHEMA {self.schema} CASCADE")

    def cfg(self, d):
        return {"carpeta_base": d, "max_mb": 5, "proveedores": [PROV]}

    def poner(self, d, nombre, contenido):
        c = Path(d) / "milesight"
        c.mkdir(exist_ok=True)
        f = c / nombre
        f.write_bytes(contenido)
        os.utime(f, (time.time() - 600, time.time() - 600))

    def test_un_fichero_nuevo_deja_una_propuesta_pendiente_y_no_se_repite(self):
        with tempfile.TemporaryDirectory() as d:
            self.poner(d, "tarifa-1.csv", b"referencia;coste\nA;100\n")
            r = ejecutar(T.ejecutar(self.cfg(d), subir=self.subir, proponer=self.proponer))
            self.assertEqual((len(r["novedades"]), r["fallos"]), (1, []))
            n = r["novedades"][0]
            self.assertEqual((n["estado"], n["cambios"]["primera"]), ("pendiente", True))
            self.assertEqual(self.llamadas[0][:2], ("subir", "sistema:tarifas"))
            r2 = ejecutar(T.ejecutar(self.cfg(d), subir=self.subir, proponer=self.proponer))
            self.assertEqual(r2["novedades"], [])                                         # el mismo contenido no se vuelve a procesar
            self.assertEqual(len([x for x in self.llamadas if x[0] == "proponer"]), 1)
            self.poner(d, "tarifa-2.csv", b"referencia;coste\nA;110\n")
            self.assertEqual(len(ejecutar(T.ejecutar(self.cfg(d), subir=self.subir, proponer=self.proponer))["novedades"]), 1)
        l_ = ejecutar(T.listar(cfg={"carpeta_base": "/x", "max_mb": 5, "proveedores": [PROV]}))
        self.assertEqual([a["estado"] for a in l_["actualizaciones"]], ["pendiente", "pendiente"])
        self.assertEqual(l_["proveedores"][0]["error"], "")
        self.assertIsNotNone(l_["proveedores"][0]["ultimo_ok"])

    def test_nada_se_aplica_solo(self):
        with tempfile.TemporaryDirectory() as d:
            self.poner(d, "t.csv", b"referencia;coste\nA;100\n")
            with mock.patch.object(LP, "aplicar", mock.AsyncMock()) as ap:
                ejecutar(T.ejecutar(self.cfg(d), subir=self.subir, proponer=self.proponer))
                ap.assert_not_awaited()
        self.assertEqual(len(ejecutar(T.pendientes())), 1)

    def test_los_cambios_se_comparan_con_la_ultima_aplicada(self):
        with tempfile.TemporaryDirectory() as d:
            self.poner(d, "t1.csv", b"1")
            r = ejecutar(T.ejecutar(self.cfg(d), subir=self.subir, proponer=self.proponer))
            ejecutar(T._decidir(r["novedades"][0]["actualizacion"], "aplicada", "albert"))
            with psycopg.connect(self.aj.database_url, autocommit=True) as c:
                c.execute("UPDATE importaciones_precios SET estado = 'aplicada'")
            self.lineas = [l("A", 120), l("B", 50), l("C", 5)]
            self.poner(d, "t2.csv", b"2")
            r = ejecutar(T.ejecutar(self.cfg(d), subir=self.subir, proponer=self.proponer))
            c = r["novedades"][0]["cambios"]
            self.assertEqual((c["primera"], c["nuevos"], c["suben"], c["iguales"]), (False, 1, 1, 1))

    def test_un_fichero_inseguro_queda_rechazado_y_no_se_lee(self):
        async def infectado(usuario, nombre, datos):
            return {"id": "x", "estado": "infectado", "motivo": "El antivirus lo marca como dañino"}
        proponer = mock.AsyncMock()
        with tempfile.TemporaryDirectory() as d:
            self.poner(d, "t.csv", b"x")
            r = ejecutar(T.ejecutar(self.cfg(d), subir=infectado, proponer=proponer))
        self.assertEqual(r["novedades"][0]["estado"], "rechazada")
        proponer.assert_not_awaited()
        self.assertEqual(ejecutar(T.pendientes()), [])

    def test_un_error_de_lectura_queda_anotado(self):
        async def mal(*a, **k):
            raise LP.ErrorImportacion("La tarifa no tiene ningún producto cargable")
        with tempfile.TemporaryDirectory() as d:
            self.poner(d, "t.csv", b"x")
            r = ejecutar(T.ejecutar(self.cfg(d), subir=self.subir, proponer=mal))
        self.assertEqual((r["novedades"][0]["estado"], "producto cargable" in r["novedades"][0]["motivo"]), ("error", True))

    def test_un_proveedor_que_falla_no_frena_a_los_demas_y_queda_su_error(self):
        async def descarga(p, tope):
            raise T.ErrorTarifaAuto("El servicio responde con error 500")
        with tempfile.TemporaryDirectory() as d:
            self.poner(d, "t.csv", b"referencia;coste\nA;1\n")
            cfg = {"carpeta_base": d, "max_mb": 5, "proveedores": [PROV_URL, PROV]}
            r = ejecutar(T.ejecutar(cfg, descargar_=descarga, subir=self.subir, proponer=self.proponer))
        self.assertEqual([f["proveedor"] for f in r["fallos"]], ["dist-x"])
        self.assertEqual(len(r["novedades"]), 1)
        por = {p["id"]: p for p in ejecutar(T.listar(cfg=cfg))["proveedores"]}
        self.assertIn("error 500", por["dist-x"]["error"])
        self.assertEqual(por["milesight"]["error"], "")

    def test_aplicar_y_descartar_cambian_el_estado_y_quien_lo_hizo(self):
        with tempfile.TemporaryDirectory() as d:
            self.poner(d, "t.csv", b"referencia;coste\nA;1\n")
            n = ejecutar(T.ejecutar(self.cfg(d), subir=self.subir, proponer=self.proponer))["novedades"][0]
        with mock.patch.object(LP, "aplicar", mock.AsyncMock(return_value={"articulos_creados": 2})) as ap:
            r = ejecutar(T.aplicar(n["actualizacion"], "albert"))
            ap.assert_awaited_once_with(n["importacion"], "operaciones")
        a = ejecutar(T.listar())["actualizaciones"][0]
        self.assertEqual((a["estado"], a["decidido_por"]), ("aplicada", "albert"))
        with self.assertRaises(T.ErrorTarifaAuto):
            ejecutar(T.aplicar(n["actualizacion"], "albert"))                           # no se aplica dos veces
        with self.assertRaises(T.ErrorTarifaAuto):
            ejecutar(T.descartar(n["actualizacion"], "albert"))


class TestHoyYRutas(unittest.TestCase):
    def test_hoy_avisa_de_tarifas_pendientes_y_es_urgente_si_alguna_es_sospechosa(self):
        from cerebro import hoy
        self.assertEqual(hoy.de_tarifas([]), [])
        a = hoy.de_tarifas([{"proveedor_id": "milesight", "cambios": {"sospechosa": False}}])[0]
        self.assertEqual((a["nivel"], a["categoria"], a["href"]), ("aviso", "precios", "/precios"))
        self.assertIn("1 tarifa nueva", a["titulo"])
        u = hoy.de_tarifas([{"proveedor_id": "a", "cambios": {}}, {"proveedor_id": "b", "cambios": {"sospechosa": True}}])[0]
        self.assertEqual(u["nivel"], "urgente")
        self.assertIn("sospechosos", u["detalle"])

    def test_solo_direccion_toca_las_tarifas_y_aplicar_exige_confirmar(self):
        try:
            from fastapi.testclient import TestClient
            from cerebro.api import main
            from cerebro.api.auth import Usuario, usuario_actual
            import cerebro.herramientas  # noqa: F401
        except ImportError as e:      # pragma: no cover
            self.skipTest(str(e))
        c = TestClient(main.app)
        try:
            main.app.dependency_overrides[usuario_actual] = lambda: Usuario("marta", {"usuario"}, {"operaciones", "licitaciones"})
            for r in (c.get("/precios/tarifas"), c.post("/precios/tarifas/comprobar"), c.get("/precios/tarifas/1"), c.post("/precios/tarifas/1/aplicar", json={"confirmo": True}), c.post("/precios/tarifas/1/descartar")):
                self.assertEqual(r.status_code, 403, r.request.url)
            main.app.dependency_overrides[usuario_actual] = lambda: Usuario("albert", {"direccion"}, set())
            with mock.patch.object(main.tarifas_automaticas, "aplicar", mock.AsyncMock()) as ap, mock.patch.object(main.tarifas_automaticas, "vista", mock.AsyncMock(return_value={"vista": {"titulo": "t"}})):
                self.assertEqual(c.post("/precios/tarifas/1/aplicar", json={}).status_code, 422)
                ap.assert_not_awaited()
            with mock.patch.object(main.tarifas_automaticas, "aplicar", mock.AsyncMock(return_value={"ok": 1})) as ap, mock.patch.object(main.tarifas_automaticas, "vista", mock.AsyncMock(return_value={"vista": {"titulo": "Cargar tarifa"}})), \
                    mock.patch.object(main.constancia, "dejar_constancia", mock.AsyncMock(return_value="ok")) as cons:
                r = c.post("/precios/tarifas/4/aplicar", json={"confirmo": True})
                self.assertEqual(r.status_code, 200, r.text)
                ap.assert_awaited_once_with(4, "albert")
                self.assertEqual(cons.await_args.args[1:4], ("usuario:albert", "listas_precios", "aplicar"))
        finally:
            main.app.dependency_overrides.clear()


if __name__ == "__main__":
    unittest.main()
