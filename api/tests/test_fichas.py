"""Fichas técnicas: qué enlaces se cargan, que solo se baje de dominios autorizados, que lo infectado o ilegible no se indexe y que una ficha no se repita."""
import asyncio
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import _sin_servicios  # noqa: F401

try:
    import psycopg
    from cerebro.licitaciones import fichas as F
    from cerebro.licitaciones import pliegos
except ImportError as e:      # pragma: no cover
    raise unittest.SkipTest(str(e))

URL = os.environ.get("CEREBRO_TEST_PG")
ESQUEMA = Path(__file__).resolve().parents[2] / "db" / "esquema.sql"
PDF = b"%PDF-1.4\n" + b"contenido distinto de una ficha tecnica de camara\n" * 3
HOSTS = ["milesight.com"]
CFG = {"hosts": HOSTS, "max_mb": 5, "max_diarias": 50, "max_por_carga": 10}
TEXTO = {"paginas": [{"n": 1, "texto": "Cámara domo 4 MP, lente 2,8 mm, IR 30 m, IP67, alimentación PoE 802.3af. " * 3}]}


def limpio(_datos):
    async def f(*_a, **_k):
        return pliegos.Veredicto("limpio")
    return f


class TestSugerencias(unittest.TestCase):
    def test_los_dominios_fuera_vienen_con_lo_que_se_sabe_del_fabricante(self):
        lineas = [{"ref": "A", "enlaces": {"d": "https://www.2n.com/a.pdf"}}, {"ref": "B", "enlaces": {"d": "https://www.milesight.com/b.pdf"}}, {"ref": "C", "enlaces": {"d": "https://rarisimo.example/c.pdf"}}]
        r = asyncio.run(F.revisar_lista(0, CFG | {"hosts": []}, lineas))
        por = {s["dominio"]: s for s in r["sugerencias"]}
        self.assertTrue(por["2n.com"]["comprobado"])
        self.assertFalse(por["milesight.com"]["comprobado"])
        self.assertFalse(por["rarisimo.example"]["conocido"])
        self.assertEqual(r["fichas"], 0)                                                   # nada se descarga: solo se sugiere


class TestPuros(unittest.TestCase):
    def test_candidatas_separa_autorizadas_de_fuera_y_no_repite(self):
        lineas = [{"ref": "A1", "marca": "Milesight", "enlaces": {"datasheet": "https://www.milesight.com/a.pdf", "web": "https://otra.com/x.pdf"}},
                  {"ref": "A2", "enlaces": {"datasheet": "https://www.milesight.com/a.pdf"}},
                  {"ref": "A3", "enlaces": {"pdf": "http://milesight.com/inseguro.pdf"}},
                  {"ref": "A4"}]
        c = F.candidatas(lineas, HOSTS)
        self.assertEqual([x["url"] for x in c["permitidas"]], ["https://www.milesight.com/a.pdf"])
        self.assertEqual(c["permitidas"][0]["referencia"], "A1")
        self.assertEqual(c["fuera"], {"otra.com": 1, "milesight.com": 1})
        self.assertEqual(c["sin_enlace"], 1)

    def test_sin_dominios_autorizados_no_se_descarga_nada(self):
        c = F.candidatas([{"ref": "A", "enlaces": {"d": "https://milesight.com/a.pdf"}}], [])
        self.assertEqual(c["permitidas"], [])
        self.assertEqual(c["fuera"], {"milesight.com": 1})

    def test_una_direccion_con_usuario_o_puerto_raro_no_es_valida(self):
        for u in ("https://u:p@milesight.com/a.pdf", "https://milesight.com:8443/a.pdf", "https://milesight.com.malo.com/a.pdf"):
            self.assertFalse(pliegos.host_permitido(u, HOSTS), u)

    def test_la_configuracion_por_defecto_no_autoriza_ningun_dominio(self):
        self.assertEqual(F.DEFECTO["hosts"], [])
        self.assertEqual(F.configuracion()["hosts"], [])


@unittest.skipUnless(URL and hasattr(psycopg, "AsyncConnection"), "sin CEREBRO_TEST_PG")
class TestFlujo(unittest.TestCase):
    def setUp(self):
        self.schema = f"t_fic_{time.time_ns()}"
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"CREATE SCHEMA {self.schema}")
            c.execute(f"SET search_path = {self.schema}")
            t = ESQUEMA.read_text(encoding="utf-8")
            c.execute(t[t.index("-- Fichas técnicas de producto"):])
        sep = "&" if "?" in URL else "?"
        aj = SimpleNamespace(database_url=f"{URL}{sep}options=-csearch_path%3D{self.schema}", dir_config=F.ajustes.dir_config)
        self.tmp = tempfile.TemporaryDirectory()
        self.p = [mock.patch.object(F, "ajustes", aj), mock.patch.object(F, "RAIZ", Path(self.tmp.name))]
        for p in self.p:
            p.start()
        self.indexados = []

        async def indexar(titulo, texto, fuente, depto, sens, trozo):
            self.indexados.append((titulo, texto, fuente, depto, sens))
            return 2
        self.indexar = indexar

    def tearDown(self):
        for p in self.p:
            p.stop()
        self.tmp.cleanup()
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"DROP SCHEMA {self.schema} CASCADE")

    def inc(self, datos=PDF, analizar=None, extraer=None, **kw):
        return asyncio.run(F.incorporar(datos, "ficha.pdf", "Milesight", "MS-C8", analizar=analizar or limpio(0), extraer=extraer or (lambda *a: TEXTO),
                                        indexar=self.indexar, **kw))

    def test_un_pdf_limpio_se_indexa_en_licitaciones_con_su_marca_y_referencia(self):
        r = self.inc()
        self.assertEqual((r["estado"], r["trozos"], r["paginas"]), ("indexada", 2, 1))
        titulo, texto, fuente, depto, sens = self.indexados[0]
        self.assertEqual((depto, sens), ("licitaciones", "baja"))
        self.assertIn("marca: Milesight", texto)
        self.assertIn("MS-C8", titulo)
        self.assertIn("IP67", texto)

    def test_la_misma_ficha_no_se_repite(self):
        self.inc()
        r = self.inc()
        self.assertTrue(r.get("repetida"))
        self.assertEqual(len(self.indexados), 1)

    def test_lo_que_no_es_pdf_no_se_analiza_ni_se_indexa(self):
        r = self.inc(datos=b"MZ\x90\x00 ejecutable")
        self.assertEqual(r["estado"], "no_analizable")
        self.assertEqual(self.indexados, [])

    def test_un_pdf_infectado_no_se_lee_ni_se_indexa(self):
        async def av(*_a, **_k):
            return pliegos.Veredicto("infectado", "El antivirus lo marca como dañino (Eicar)")
        extraer = mock.Mock()
        r = self.inc(analizar=av, extraer=extraer)
        self.assertEqual(r["estado"], "infectada")
        extraer.assert_not_called()
        self.assertEqual(self.indexados, [])

    def test_si_el_antivirus_no_responde_no_se_indexa(self):
        async def av(*_a, **_k):
            return pliegos.Veredicto("no_analizable", "El antivirus no ha podido analizarlo")
        self.assertEqual(self.inc(analizar=av)["estado"], "no_analizable")
        self.assertEqual(self.indexados, [])

    def test_un_pdf_escaneado_queda_como_sin_texto(self):
        r = self.inc(extraer=lambda *a: {"paginas": [{"n": 1, "texto": "  "}]})
        self.assertEqual(r["estado"], "sin_texto")
        self.assertEqual(self.indexados, [])

    def test_si_falla_el_indexado_queda_error_y_se_puede_reintentar(self):
        async def mal(*a):
            raise ConnectionError("embeddings caído")
        r = asyncio.run(F.incorporar(PDF, "f.pdf", "M", "R", analizar=limpio(0), extraer=lambda *a: TEXTO, indexar=mal))
        self.assertEqual(r["estado"], "error")
        r2 = self.inc()                                                       # el reintento con el mismo PDF funciona
        self.assertEqual(r2["estado"], "indexada")

    def test_desde_url_rechaza_un_dominio_no_autorizado_sin_descargar(self):
        baja = mock.AsyncMock()
        with self.assertRaises(F.ErrorFicha) as e:
            asyncio.run(F.desde_url("https://malo.com/a.pdf", cfg=CFG, descargar=baja))
        self.assertIn("malo.com", str(e.exception))
        baja.assert_not_called()

    def test_desde_url_descarga_e_indexa_y_traduce_los_errores_de_descarga(self):
        async def baja(url, hosts, tope):
            self.assertEqual((hosts, tope), (HOSTS, 5 << 20))
            return PDF
        r = asyncio.run(F.desde_url("https://www.milesight.com/ds/a.pdf", "Milesight", "MS-C8", cfg=CFG, descargar=baja,
                                    analizar=limpio(0), extraer=lambda *a: TEXTO, indexar=self.indexar))
        self.assertEqual((r["estado"], r["origen"]), ("indexada", "web"))

        async def falla(*a):
            raise pliegos.ErrorPliego("La plataforma responde con error 404")
        with self.assertRaises(F.ErrorFicha):
            asyncio.run(F.desde_url("https://www.milesight.com/ds/b.pdf", cfg=CFG, descargar=falla))

    def test_el_tope_diario_se_respeta(self):
        self.inc(origen="web", url="https://milesight.com/a.pdf")
        with self.assertRaises(F.ErrorFicha) as e:
            asyncio.run(F.desde_url("https://milesight.com/b.pdf", cfg={**CFG, "max_diarias": 1}, descargar=mock.AsyncMock(return_value=PDF)))
        self.assertIn("máximo", str(e.exception))

    def test_cargar_lista_informa_de_cargadas_repetidas_fallidas_y_dominios_fuera(self):
        otro = PDF + b"otra ficha"
        pdfs = {"https://milesight.com/a.pdf": PDF, "https://milesight.com/b.pdf": PDF, "https://milesight.com/c.pdf": otro}

        async def baja(url, hosts, tope):
            if url.endswith("c.pdf"):
                raise pliegos.ErrorPliego("La plataforma responde con error 404")
            return pdfs[url]
        lineas = [{"ref": "A", "marca": "M", "enlaces": {"d": "https://milesight.com/a.pdf"}}, {"ref": "B", "enlaces": {"d": "https://milesight.com/b.pdf"}},
                  {"ref": "C", "enlaces": {"d": "https://milesight.com/c.pdf"}}, {"ref": "D", "enlaces": {"d": "https://otra.com/d.pdf"}}, {"ref": "E"}]
        inf = asyncio.run(F.cargar_lista(0, "albert", CFG, lineas, baja, analizar=limpio(0), extraer=lambda *a: TEXTO, indexar=self.indexar))
        self.assertEqual((inf["cargadas"], inf["repetidas"], len(inf["fallidas"])), (1, 1, 1))
        self.assertEqual(inf["dominios_fuera"], {"otra.com": 1})
        self.assertEqual(inf["lineas_sin_enlace"], 1)
        self.assertIn("404", inf["fallidas"][0]["motivo"])

    def test_listar_cuenta_por_estado(self):
        self.inc()
        l = asyncio.run(F.listar())
        self.assertEqual(l["por_estado"], {"indexada": 1})
        self.assertNotIn("sha256", l["fichas"][0])

    def test_subir_a_mano_respeta_el_tamano(self):
        with self.assertRaises(F.ErrorFicha):
            asyncio.run(F.subir(b"x" * ((5 << 20) + 1), "f.pdf", "M", "R", "albert", CFG))


if __name__ == "__main__":
    unittest.main()
