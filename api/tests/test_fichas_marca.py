"""Fichas de toda una marca: solo PDF de dominios autorizados que nombran el modelo, sin repetir y reanudable."""
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
    from cerebro.licitaciones import fichas as F
    from cerebro.licitaciones import fichas_marca as M
    from cerebro.licitaciones import pliegos
except ImportError as e:      # pragma: no cover
    raise unittest.SkipTest(str(e))

URL = os.environ.get("CEREBRO_TEST_PG")
ESQUEMA = Path(__file__).resolve().parents[2] / "db" / "esquema.sql"
HOSTS = ["hikvision.com", "milesight.com"]
CFG = {"hosts": HOSTS, "max_mb": 5, "max_diarias": 50, "max_por_carga": 10}
TEXTO = {"paginas": [{"n": 1, "texto": "Cámara domo 4 MP, lente 2,8 mm, IR 30 m, IP67, alimentación PoE 802.3af. " * 3}]}
REFS = [{"modelo": "DS-2CD1143G0-I", "ref": "DS-2CD1143G0-I(2.8mm)(C)", "nombre": "Cámara"}, {"modelo": "DS-2DE5432IWG1-E", "ref": "DS-2DE5432IWG1-E", "nombre": "PTZ"}]


class TestPuros(unittest.TestCase):
    def test_modelo_base_quita_las_opciones(self):
        self.assertEqual(M.modelo_base("DS-2CD1143G0-I(2.8mm)(C)"), "DS-2CD1143G0-I")
        self.assertEqual(M.modelo_base("MS-CQ4431-HYPG1/2.8mm"), "MS-CQ4431-HYPG1")
        self.assertEqual(M.modelo_base("DS-2DE5432IWG1-E"), "DS-2DE5432IWG1-E")
        for no in ("", "Cable", "A1", "(2.8mm)", None):
            self.assertEqual(M.modelo_base(no), "")

    def test_dominios_de_la_marca(self):
        self.assertEqual(M.dominios_de_marca("Hikvision", HOSTS + ["axis.com"]), ["hikvision.com"])
        self.assertEqual(M.dominios_de_marca("Axis", HOSTS + ["axis.com"]), ["axis.com"])
        self.assertEqual(M.dominios_de_marca("Marca rara", HOSTS), [])

    def test_elegir_enlace_solo_pdf_autorizado_que_nombra_el_modelo(self):
        res = [{"url": "https://www.hikvision.com/es/products/DS-2CD1143G0-I", "titulo": "DS-2CD1143G0-I", "resumen": ""},                    # página, no PDF
               {"url": "https://tienda.example.com/DS-2CD1143G0-I.pdf", "titulo": "DS-2CD1143G0-I", "resumen": ""},                          # dominio no autorizado
               {"url": "https://www.hikvision.com/doc/otro.pdf", "titulo": "Otro producto", "resumen": "DS-2CD9999"},                       # otro modelo
               {"url": "http://www.hikvision.com/DS-2CD1143G0-I.pdf", "titulo": "x", "resumen": ""},                                         # sin https
               {"url": "https://www.hikvision.com/doc/ds-2cd1143g0-i-datasheet.pdf", "titulo": "Datasheet DS-2CD1143G0-I", "resumen": ""}]
        self.assertEqual(M.elegir_enlace("DS-2CD1143G0-I", res, HOSTS), ("https://www.hikvision.com/doc/ds-2cd1143g0-i-datasheet.pdf", ""))
        url, motivo = M.elegir_enlace("DS-2CD1143G0-I", res[:1], HOSTS)
        self.assertIsNone(url)
        self.assertIn("sin PDF", motivo)
        self.assertIn("no aparece", M.elegir_enlace("DS-2CD1143G0-I", [], HOSTS)[1])


@unittest.skipUnless(URL and hasattr(psycopg, "AsyncConnection"), "sin CEREBRO_TEST_PG")
class TestFlujo(unittest.TestCase):
    def setUp(self):
        self.schema = f"t_fm_{time.time_ns()}"
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"CREATE SCHEMA {self.schema}")
            c.execute(f"SET search_path = {self.schema}")
            t = ESQUEMA.read_text(encoding="utf-8")
            c.execute(t[t.index("-- Fichas técnicas de producto"):t.index("-- Tabla de equivalencias")])
            c.execute("CREATE TABLE importaciones_precios (id serial PRIMARY KEY, estado text, proveedor jsonb, lista text, lineas jsonb)")
            c.execute("INSERT INTO importaciones_precios (estado, proveedor, lista, lineas) VALUES ('aplicada', '{\"nombre\": \"Visiotech\"}', 'L', %s::jsonb)",
                      ['[{"ref": "DS-2CD1143G0-I(2.8mm)(C)", "marca": "HIKVISION", "desc": "Cámara"}, {"ref": "DS-2CD1143G0-I(4mm)(C)", "marca": "HIKVISION"}, {"ref": "DS-2DE5432IWG1-E", "marca": "Hikvision"}, {"ref": "MS-C8", "marca": "Milesight"}]'])
        sep = "&" if "?" in URL else "?"
        self.aj = SimpleNamespace(database_url=f"{URL}{sep}options=-csearch_path%3D{self.schema}")
        self.p = [mock.patch.object(F, "ajustes", self.aj), mock.patch.object(F, "RAIZ", Path(__import__("tempfile").mkdtemp()))]
        for p in self.p:
            p.start()
        self.indexadas = []

        async def indexar(titulo, texto, url, dep, sens, trozo):
            self.indexadas.append(titulo)
            return 1
        self.kw = dict(analizar=self.limpio, extraer=lambda *a: TEXTO, indexar=indexar)

    def tearDown(self):
        for p in self.p:
            p.stop()
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"DROP SCHEMA {self.schema} CASCADE")

    @staticmethod
    async def limpio(_d):
        return pliegos.Veredicto("limpio")

    def test_los_modelos_salen_de_las_tarifas_sin_opciones_ni_otras_marcas(self):
        r = asyncio.run(M.referencias_de_marca("hikvision"))
        self.assertEqual(sorted(x["modelo"] for x in r), ["DS-2CD1143G0-I", "DS-2DE5432IWG1-E"])

    def test_carga_lo_que_encuentra_anota_lo_que_no_y_es_reanudable(self):
        async def buscar(q, max_resultados=5):
            if "DS-2CD1143G0-I" in q:
                return {"resultados": [{"url": "https://www.hikvision.com/doc/DS-2CD1143G0-I_datasheet.pdf", "titulo": "Datasheet", "resumen": ""}]}
            return {"resultados": []}

        async def descargar(url, hosts, maximo):
            return b"%PDF-1.4\n" + b"ficha distinta del DS-2CD1143G0-I de camara\n" * 3
        asyncio.run(M.iniciar("Hikvision", "albert"))
        r = asyncio.run(M.ejecutar("Hikvision", "albert", buscar=buscar, cfg=CFG, descargar=descargar, **self.kw))
        self.assertEqual((r["estado"], r["cargadas"], r["sin_enlace"], r["intentados"]), ("terminada", 1, 1, 2))
        e = asyncio.run(M.estado("Hikvision"))
        self.assertEqual((e["modelos"], e["con_ficha"], e["sin_ficha"], e["no_encontradas"]), (2, 1, 1, 1))
        self.assertEqual(e["carga"]["estado"], "terminada")
        self.assertEqual(len(self.indexadas), 1)
        # una segunda pulsación no repite nada (el no encontrado espera 14 días)
        buscar2 = mock.AsyncMock(return_value={"resultados": []})
        asyncio.run(M.iniciar("Hikvision", "albert"))
        r2 = asyncio.run(M.ejecutar("Hikvision", "albert", buscar=buscar2, cfg=CFG, descargar=descargar, **self.kw))
        self.assertEqual(r2["intentados"], 0)
        buscar2.assert_not_called()

    def test_sin_dominio_autorizado_no_se_busca_nada(self):
        buscar = mock.AsyncMock()
        asyncio.run(M.iniciar("Marca rara", "albert"))
        r = asyncio.run(M.ejecutar("Marca rara", "albert", buscar=buscar, cfg=CFG))
        self.assertEqual(r["estado"], "error")
        buscar.assert_not_called()
        self.assertIn("autorizado", asyncio.run(M.estado("Marca rara"))["carga"]["informe"]["error"])

    def test_no_se_lanzan_dos_cargas_a_la_vez_y_una_perdida_se_marca(self):
        asyncio.run(M.iniciar("Hikvision", "albert"))
        with self.assertRaises(F.ErrorFicha):
            asyncio.run(M.iniciar("Hikvision", "otra"))
        with psycopg.connect(self.aj.database_url, autocommit=True) as c:
            c.execute("UPDATE fichas_marca_cargas SET actualizada = now() - interval '40 minutes'")
        self.assertEqual(asyncio.run(M.estado("Hikvision"))["carga"]["estado"], "error")
        asyncio.run(M.iniciar("Hikvision", "albert"))                                       # y se puede volver a lanzar

    def test_el_tope_diario_para_la_carga_sin_marcarla_como_fallo(self):
        async def buscar(q, max_resultados=5):
            m = "DS-2CD1143G0-I" if "DS-2CD1143G0-I" in q else "DS-2DE5432IWG1-E"
            return {"resultados": [{"url": f"https://www.hikvision.com/doc/{m}.pdf", "titulo": m, "resumen": ""}]}

        async def descargar(url, hosts, maximo):
            return b"%PDF-1.4\n" + url.encode() * 3
        asyncio.run(M.iniciar("Hikvision", "albert"))
        r = asyncio.run(M.ejecutar("Hikvision", "albert", buscar=buscar, cfg=CFG | {"max_diarias": 1}, descargar=descargar, **self.kw))
        self.assertEqual((r["estado"], r["cargadas"], r["tope_diario"], r["intentados"]), ("terminada", 1, True, 1))
        self.assertEqual(asyncio.run(M.estado("Hikvision"))["con_ficha"], 1)


if __name__ == "__main__":
    unittest.main()
