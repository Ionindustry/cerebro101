"""Catálogo de proveedores: buscar, comparar costes (calculados por el código), fichas y tarifas pendientes; y que tras usar una herramienta confidencial el agente solo use modelos locales."""
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
    from cerebro import herramientas as H
    from cerebro.herramientas import catalogo as C
    from cerebro.herramientas.esquemas import validar
    from cerebro.grafo import nodos
    from cerebro.registro import registro
except ImportError as e:      # pragma: no cover
    raise unittest.SkipTest(str(e))

URL = os.environ.get("CEREBRO_TEST_PG")
ESQUEMA = Path(__file__).resolve().parents[2] / "db" / "esquema.sql"
CFG = precios.configuracion()


def of(ref, coste, marca="Milesight", familia="Cámaras", desc="Cámara domo 4 MP", proveedor="Prov", canal="distribuidor", stock="5", moneda="EUR", enlaces=None):
    return {"proveedor": proveedor, "lista": f"Compra {proveedor}", "canal": canal, "coste": coste, "moneda": moneda, "stock": stock, "ref": ref, "desc": desc, "familia": familia, "marca": marca, "pvp": None,
            "enlaces": enlaces or {}}


OFERTAS = {"MIL-MS-C8573": {"Compra A": of("MS-C8573", "100", proveedor="A"), "Compra B": of("MS-C8573", "90", proveedor="B", stock="0")},
           "MIL-MS-N1008": {"Compra A": of("MS-N1008", "300", desc="Grabador NVR 8 canales", familia="Grabadores", enlaces={"datasheet": "https://x.com/a.pdf"})},
           "AXI-P3245": {"Compra B": of("P3245-LVE", "200", marca="Axis", proveedor="B")}}


class TestBuscar(unittest.TestCase):
    def test_busca_por_todas_las_palabras_sin_acentos(self):
        r = C.buscar_en(OFERTAS, CFG, "camara domo")
        self.assertEqual([a["codigo"] for a in r["articulos"]], ["AXI-P3245", "MIL-MS-C8573"])
        self.assertEqual(C.buscar_en(OFERTAS, CFG, "grabador 8 canales")["articulos"][0]["ref"], "MS-N1008")
        self.assertEqual(C.buscar_en(OFERTAS, CFG, "inexistente")["encontrados"], 0)

    def test_filtra_por_marca_y_familia_y_pide_algo_que_buscar(self):
        self.assertEqual([a["marca"] for a in C.buscar_en(OFERTAS, CFG, marca="axis")["articulos"]], ["Axis"])
        self.assertEqual([a["familia"] for a in C.buscar_en(OFERTAS, CFG, familia="grabadores")["articulos"]], ["Grabadores"])
        with self.assertRaises(ValueError):
            C.buscar_en(OFERTAS, CFG)

    def test_el_mejor_coste_es_en_euros_y_prefiere_el_que_tiene_stock(self):
        a = C.buscar_en(OFERTAS, CFG, "MS-C8573")["articulos"][0]
        self.assertEqual((a["proveedores"], a["mejor_proveedor"]), (2, "A"))              # B es más barato pero sin stock
        self.assertGreaterEqual(Decimal(a["coste_eur"]), Decimal("100"))

    def test_limita_los_resultados_y_avisa(self):
        grande = {f"X-{i}": {"l": of(f"REF{i:03d}", "10", proveedor="A")} for i in range(30)}
        r = C.buscar_en(grande, CFG, "camara", limite=500)
        self.assertEqual((r["mostrados"], r["encontrados"]), (C.MAX_RESULTADOS, 30))
        self.assertIn("Hay 30", r["aviso"])

    def test_indica_si_trae_enlace_de_ficha(self):
        self.assertTrue(C.buscar_en(OFERTAS, CFG, "MS-N1008")["articulos"][0]["con_enlace_de_ficha"])
        self.assertFalse(C.buscar_en(OFERTAS, CFG, "MS-C8573")["articulos"][0]["con_enlace_de_ficha"])


class TestProveedores(unittest.TestCase):
    def test_ordena_por_coste_en_euros_y_enseña_stock(self):
        r = C.proveedores_en(OFERTAS, CFG, referencia="ms-c8573")
        self.assertEqual([o["proveedor"] for o in r["ofertas"]], ["B", "A"])
        self.assertEqual([o["stock"] for o in r["ofertas"]], ["0", "5"])
        self.assertIn("lo decide Dirección", r["nota"])

    def test_por_codigo_y_con_error_claro_si_no_existe(self):
        self.assertEqual(C.proveedores_en(OFERTAS, CFG, codigo="AXI-P3245")["marca"], "Axis")
        with self.assertRaises(LookupError):
            C.proveedores_en(OFERTAS, CFG, referencia="no-existe")

    def test_un_coste_que_no_se_puede_calcular_sale_sin_cifra_en_vez_de_inventarla(self):
        malo = {"X-1": {"l": of("ABCD1", "10", moneda="ZZZ", canal="fabricante")}}
        r = C.proveedores_en(malo, CFG, codigo="X-1")
        self.assertIsNone(r["ofertas"][0]["coste_eur"])
        self.assertTrue(r["ofertas"][0]["avisos"])


class TestHerramienta(unittest.TestCase):
    def test_esta_registrada_es_de_solo_lectura_y_confidencial(self):
        h = H.base._REGISTRO["catalogo"]
        self.assertTrue(h.confidencial)
        self.assertEqual(h.externas, frozenset())
        self.assertEqual(set(h.operaciones), {"buscar", "proveedores_de", "ficha", "fichas_pendientes", "tarifas_pendientes"})
        self.assertTrue(H.es_confidencial("listas_precios"))                                   # la que ya enseñaba costes también
        self.assertFalse(H.es_confidencial("web"))

    def test_el_agente_de_catalogo_la_tiene_y_el_resto_no(self):
        quien = {a for a, f in registro().fichas.items() if "catalogo" in f.herramientas}
        self.assertEqual(quien, {"catalogo-proveedores"})

    def test_cada_operacion_tiene_ayuda_y_ejemplo_valido(self):
        h = H.base._REGISTRO["catalogo"]
        for op in h.operaciones:
            self.assertIn(op, h.ayuda)
        for op, args in h.ejemplos.items():
            validar(h, op, args)


class TestSoloLocal(unittest.TestCase):
    """Una vez que el agente ha usado una herramienta confidencial, el resto de la petición solo va a modelos locales."""
    def correr(self, herramienta, ok=True):
        vistos = []

        async def paso(ficha, estado, mensajes):
            vistos.append(bool(estado.get("solo_local")))
            if len(vistos) == 1:
                return {"tipo": "herramienta", "herramienta": herramienta, "operacion": "buscar", "argumentos": {}}
            return {"tipo": "respuesta", "respuesta": "ok"}

        async def usar(ficha, h, op, **kw):
            return {"ok": True} if ok else {"error": "falló"}

        async def nada(*a, **k):
            return None
        ficha = registro().fichas["catalogo-proveedores"]
        with mock.patch.object(nodos, "_paso_del_agente", paso), mock.patch.object(nodos.H, "usar", usar), mock.patch.object(nodos.actividad, "marcar", nada), \
                mock.patch.object(nodos.actividad, "contar", nada), mock.patch.object(nodos, "inyectar", lambda f, e, h, a: a):
            asyncio.run(nodos._ejecutar_agente({"peticion": "busca la MS-C8573"}, ficha))
        return vistos

    def test_tras_usar_catalogo_con_exito_los_pasos_siguientes_son_solo_locales(self):
        self.assertEqual(self.correr("catalogo"), [False, True])

    def test_si_la_herramienta_falla_no_hay_datos_confidenciales_y_no_cambia_nada(self):
        self.assertEqual(self.correr("catalogo", ok=False), [False, False])

    def test_una_herramienta_normal_no_lo_activa(self):
        self.assertEqual(self.correr("conocimiento"), [False, False])

    def test_el_paso_no_consulta_a_la_nube_si_es_solo_local(self):
        ext = mock.AsyncMock(return_value={"tipo": "respuesta", "respuesta": "nube"})
        local = mock.AsyncMock(return_value={"tipo": "respuesta", "respuesta": "local"})
        ficha = registro().fichas["catalogo-proveedores"]
        with mock.patch.object(nodos.modelos_externos, "es_compleja", return_value=True), mock.patch.object(nodos.modelos_externos, "consultar", ext), \
                mock.patch.object(nodos, "chat", local), mock.patch.object(nodos, "asignar", lambda *a, **k: "m"):
            d = asyncio.run(nodos._paso_del_agente(ficha, {"peticion": "analiza", "sensibilidad": "baja", "solo_local": True}, [{"role": "system", "content": "s"}, {"role": "user", "content": "x"}]))
        self.assertEqual(d["respuesta"], "local")
        ext.assert_not_awaited()


@unittest.skipUnless(URL, "sin CEREBRO_TEST_PG")
class TestBD(unittest.TestCase):
    def setUp(self):
        self.schema = f"t_cat_{time.time_ns()}"
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"CREATE SCHEMA {self.schema}")
            c.execute(f"SET search_path = {self.schema}")
            t = ESQUEMA.read_text(encoding="utf-8")
            c.execute(t[t.index("-- Pliegos y otros documentos de una licitación"):])
            c.execute("INSERT INTO fichas_tecnicas (sha256, marca, referencia, nombre, origen, formato, bytes, estado, url) VALUES ('a','Milesight','MS-C8573','ms-c8573.pdf','web','pdf',1,'indexada','https://x.com/a.pdf'),"
                      "('b','Axis','P3245-LVE','p3245.pdf','manual','pdf',1,'error','')")
        sep = "&" if "?" in URL else "?"
        aj = SimpleNamespace(database_url=f"{URL}{sep}options=-csearch_path%3D{self.schema}", dir_config=C.fichas.ajustes.dir_config)
        self.p = [mock.patch.object(C.fichas, "ajustes", aj), mock.patch.object(C.tarifas_auto, "ajustes", aj), mock.patch.object(C, "_material", mock.AsyncMock(return_value=(OFERTAS, CFG)))]
        for p in self.p:
            p.start()

    def tearDown(self):
        for p in self.p:
            p.stop()
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"DROP SCHEMA {self.schema} CASCADE")

    def test_ficha_encuentra_las_cargadas_y_no_las_fallidas(self):
        r = asyncio.run(C.ficha("MS-C8573"))
        self.assertEqual([f["marca"] for f in r["fichas"]], ["Milesight"])
        self.assertEqual(asyncio.run(C.ficha("P3245-LVE"))["fichas"], [])                       # la de «error» no cuenta
        self.assertEqual(asyncio.run(C.ficha("ms c8573", "Axis"))["fichas"], [])               # otra marca
        with self.assertRaises(ValueError):
            asyncio.run(C.ficha("ab"))

    def test_fichas_pendientes_cuenta_enlaces_y_dominios_sin_autorizar(self):
        with mock.patch.object(C.fichas, "configuracion", lambda: {"hosts": []}):
            r = asyncio.run(C.fichas_pendientes())
        self.assertEqual((r["fichas_por_cargar"], r["dominios_sin_autorizar"]), (0, {"x.com": 1}))
        with mock.patch.object(C.fichas, "configuracion", lambda: {"hosts": ["x.com"]}):
            self.assertEqual(asyncio.run(C.fichas_pendientes())["fichas_por_cargar"], 1)

    def test_tarifas_pendientes_resume_lo_pendiente_y_los_errores(self):
        with psycopg.connect(URL + ("&" if "?" in URL else "?") + f"options=-csearch_path%3D{self.schema}", autocommit=True) as c:
            c.execute("INSERT INTO tarifas_actualizaciones (proveedor_id, origen, nombre, sha256, estado, cambios) VALUES ('milesight','carpeta','t.csv','s1','pendiente', "
                      "'{\"articulos\": 10, \"nuevos\": 2, \"sospechosa\": true, \"avisos\": [\"Desaparecen 5 de 10\"]}')")
        with mock.patch.object(C.tarifas_auto, "proveedores_validos", lambda cfg=None: ([], [])):
            r = asyncio.run(C.tarifas_pendientes())
        self.assertEqual(r["pendientes"][0]["proveedor"], "milesight")
        self.assertTrue(r["pendientes"][0]["cambios"]["sospechosa"])
        self.assertIn("Dirección", r["nota"])


if __name__ == "__main__":
    unittest.main()
