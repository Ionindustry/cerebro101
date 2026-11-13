"""Descubrimiento en internet: las pistas son por verificar; la dirección la pone el código y el valor declarado debe figurar en el resultado."""
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
    from cerebro.licitaciones import descubrimiento as D
    from cerebro.licitaciones import equivalencia as Q
    from cerebro.licitaciones import ofertas as O
except ImportError as e:      # pragma: no cover
    raise unittest.SkipTest(str(e))

URL = os.environ.get("CEREBRO_TEST_PG")
ESQUEMA = Path(__file__).resolve().parents[2] / "db" / "esquema.sql"
ID = "0b1f7a3e-1111-4222-8333-444444444477"
HOSTS = ["milesight.com"]
RES = [{"id": "W1", "parametro": "Alcance IR", "titulo": "Milesight MS-C8 · IR 40 m", "url": "https://www.milesight.com/ds/ms-c8.pdf", "resumen": "Cámara domo 8 MP con IR de 40 m y grado IP67."},
       {"id": "W2", "parametro": "Alcance IR", "titulo": "Tienda X · cámara", "url": "https://tienda.example.com/c", "resumen": "Cámara con IR 50 m."}]


class TestPuros(unittest.TestCase):
    def test_solo_se_busca_lo_que_no_esta_cubierto_y_con_tope(self):
        ps = [{"parametro": "A", "valor_exigido": "1 m", "cubierto": True}] + [{"parametro": f"P{i}", "valor_exigido": "2 MP", "requisito": "[R1] Cámara domo", "cubierto": False} for i in range(10)]
        c = D.consultas_de(ps, "Titulo")
        self.assertEqual(len(c), D.MAX_PARAMETROS)
        self.assertNotIn("A", [x["parametro"] for x in c])
        self.assertNotIn("[R1]", c[0]["consulta"])
        self.assertIn("datasheet", c[0]["consulta"])

    def test_los_resultados_se_numeran_sin_repetir_ni_aceptar_http(self):
        r = D.numerar([{"parametro": "A", "resultados": [{"url": "https://a.com/x", "titulo": "t"}, {"url": "http://b.com/y"}, {"url": "https://a.com/x"}]},
                       {"parametro": "B", "resultados": [{"url": "https://c.com/z"}]}])
        self.assertEqual([(x["id"], x["url"]) for x in r], [("W1", "https://a.com/x"), ("W2", "https://c.com/z")])

    def pistas(self, **kw):
        return {"pistas": [{"parametro": "Alcance IR", "producto": "MS-C8", "marca": "Milesight", "valor_declarado": "40 m", "fuente": "W1", **kw}]}

    def test_la_direccion_la_pone_el_codigo_y_se_marca_el_dominio_autorizado(self):
        r = D.verificar(self.pistas(), RES, HOSTS)
        p = r["pistas"][0]
        self.assertEqual((p["url"], p["dominio_autorizado"], p["es_pdf"], p["valor_comprobado"]), ("https://www.milesight.com/ds/ms-c8.pdf", True, True, True))
        r = D.verificar(self.pistas(fuente="W2", valor_declarado="50 m"), RES, HOSTS)
        self.assertFalse(r["pistas"][0]["dominio_autorizado"])
        self.assertEqual(r["dominios_sin_autorizar"], {"tienda.example.com": 1})

    def test_un_id_inventado_se_descarta(self):
        r = D.verificar(self.pistas(fuente="W9"), RES, HOSTS)
        self.assertEqual((r["pistas"], r["comprobacion"]["descartadas"]), ([], 1))

    def test_un_valor_que_no_figura_en_el_resultado_se_borra(self):
        r = D.verificar(self.pistas(valor_declarado="100 m"), RES, HOSTS)
        p = r["pistas"][0]
        self.assertEqual((p["valor_declarado"], p["valor_comprobado"]), ("", False))
        self.assertEqual(r["comprobacion"]["valores_sin_comprobar"], 1)

    def test_basura_no_rompe_y_no_hay_duplicados(self):
        r = D.verificar({"pistas": ["x", self.pistas()["pistas"][0], self.pistas()["pistas"][0]]}, RES, HOSTS)
        self.assertEqual(len(r["pistas"]), 1)


@unittest.skipUnless(URL and hasattr(psycopg, "AsyncConnection"), "sin CEREBRO_TEST_PG")
class TestFlujo(unittest.TestCase):
    def setUp(self):
        self.schema = f"t_des_{time.time_ns()}"
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"CREATE SCHEMA {self.schema}")
            c.execute(f"SET search_path = {self.schema}")
            t = ESQUEMA.read_text(encoding="utf-8")
            c.execute(t[t.index("-- Pliegos y otros documentos de una licitación"):])
        sep = "&" if "?" in URL else "?"
        aj = SimpleNamespace(database_url=f"{URL}{sep}options=-csearch_path%3D{self.schema}", dir_config=O.ajustes.dir_config)
        self.p = [mock.patch.object(O, "ajustes", aj), mock.patch.object(D.fichas, "configuracion", lambda: {"hosts": HOSTS})]
        for p in self.p:
            p.start()

    def tearDown(self):
        for p in self.p:
            p.stop()
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"DROP SCHEMA {self.schema} CASCADE")

    def tabla(self, cubierto=False):
        asyncio.run(Q._guardar(ID, "claude", "m", {"parametros": [{"parametro": "Alcance IR", "operador": ">=", "valor_exigido": "40 m", "requisito": "[R2] Visión nocturna", "cubierto": cubierto, "candidatos": []}]}, []))

    def ejecutar(self, **kw):
        asyncio.run(D.iniciar(ID, "albert"))
        return asyncio.run(D.ejecutar(ID, "Videovigilancia", **kw))

    def test_sin_tabla_de_equivalencias_dice_que_falta(self):
        self.assertEqual(self.ejecutar()["estado"], "error")
        self.assertIn("equivalencias", asyncio.run(D.leer(ID))["error"])

    def test_todo_cubierto_no_busca(self):
        self.tabla(cubierto=True)
        buscar = mock.AsyncMock()
        self.assertEqual(self.ejecutar(buscar=buscar)["estado"], "hecha")
        buscar.assert_not_called()
        self.assertIn("no hace falta", asyncio.run(D.leer(ID))["contenido"]["aviso"])

    def test_busca_pregunta_al_modelo_y_guarda_pistas_verificadas(self):
        self.tabla()
        res = [{"titulo": RES[0]["titulo"], "url": RES[0]["url"], "resumen": RES[0]["resumen"]}]
        buscar = mock.AsyncMock(return_value={"resultados": res})

        async def consulta(agente, mensajes, esquema, **kw):
            self.assertIn("[W1]", mensajes[1]["content"])
            self.assertIn("TEXTO DE TERCEROS", mensajes[0]["content"])
            return {"pistas": [{"parametro": "Alcance IR", "producto": "MS-C8", "valor_declarado": "40 m", "fuente": "W1"}, {"parametro": "x", "producto": "Falso", "fuente": "W7"}]}, "claude"
        with mock.patch.object(D.externos, "modelo_elegido", mock.AsyncMock(return_value="opus")):
            self.assertEqual(self.ejecutar(buscar=buscar, consulta=consulta)["estado"], "hecha")
        d = asyncio.run(D.leer(ID))
        self.assertEqual((d["estado"], d["proveedor"], d["modelo"]), ("hecha", "claude", "opus"))
        self.assertEqual([p["producto"] for p in d["contenido"]["pistas"]], ["MS-C8"])
        self.assertEqual(d["contenido"]["comprobacion"]["descartadas"], 1)

    def test_si_la_busqueda_falla_queda_el_motivo(self):
        self.tabla()
        self.assertEqual(self.ejecutar(buscar=mock.AsyncMock(side_effect=RuntimeError("El buscador no responde")))["estado"], "error")
        self.assertIn("resultados", asyncio.run(D.leer(ID))["error"])

    def test_si_no_hay_modelo_externo_queda_el_motivo_y_no_se_queda_en_curso(self):
        self.tabla()
        buscar = mock.AsyncMock(return_value={"resultados": [{"titulo": "t", "url": "https://a.com/x", "resumen": "r"}]})
        mal = mock.AsyncMock(side_effect=D.externos.ErrorExterno("sin proveedor"))
        self.assertEqual(self.ejecutar(buscar=buscar, consulta=mal)["estado"], "error")
        self.assertEqual(asyncio.run(D.leer(ID))["estado"], "error")

    def test_no_se_lanzan_dos_busquedas_a_la_vez(self):
        asyncio.run(D.iniciar(ID, "albert"))
        with self.assertRaises(O.ErrorOferta):
            asyncio.run(D.iniciar(ID, "otra"))


if __name__ == "__main__":
    unittest.main()
