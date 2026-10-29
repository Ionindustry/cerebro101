"""Documentos subidos al chat de Jarvis: qué se admite (por contenido), antivirus, texto por páginas, adjuntar al mensaje, caducidad y la ruta de la API."""
import asyncio
import base64
import io
import os
import tempfile
import time
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import _sin_servicios  # noqa: F401

try:
    import psycopg
    from cerebro import subidas as S
    from cerebro.licitaciones import ofertas, pliegos
except ImportError as e:      # pragma: no cover
    raise unittest.SkipTest(str(e))

URL = os.environ.get("CEREBRO_TEST_PG")
ESQUEMA = Path(__file__).resolve().parents[2] / "db" / "esquema.sql"
CSV = b"referencia;descripcion;precio\nA-1;Camara domo 4K;123,50\nA-2;Grabador 16 canales;410,00\n"


def ejecutar(c):
    return asyncio.run(c)


def zip_con(*nombres: str) -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        for n in nombres:
            z.writestr(n, "x")
    return b.getvalue()


class TestFormato(unittest.TestCase):
    def test_se_decide_por_el_contenido_no_por_el_nombre(self):
        self.assertEqual(S.formato_subida("lista.pdf", b"%PDF-1.7\n..."), "pdf")
        self.assertEqual(S.formato_subida("x.bin", ofertas.construir_docx("<w:p/>")), "docx")
        self.assertEqual(S.formato_subida("x", zip_con("[Content_Types].xml", "xl/workbook.xml")), "xlsx")
        self.assertEqual(S.formato_subida("tarifa.csv", CSV), "csv")
        self.assertEqual(S.formato_subida("tarifa.TSV", b"a\tb\n1\t2\n"), "csv")
        self.assertEqual(S.formato_subida("notas.txt", "precio: 5 € ñ".encode("utf-8")), "txt")
        self.assertEqual(S.formato_subida("latin.csv", "a;b\nñ;2\n".encode("latin-1")), "csv")

    def test_rechaza_lo_que_no_es_un_documento(self):
        casos = [("a.pdf", b"MZ\x90\x00\x03\x00\x00\x00"), ("a.csv", b"<html><body>hola</body></html>"), ("a.csv", b"\x00\x01\x02\x03" * 100), ("a.xyz", b"hola"),
                 ("a.zip", zip_con("a.txt")), ("a.xls", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 50), ("a.svg", b"<svg onload='x'/>"), ("a.csv", b"#!/bin/sh\nrm -rf /")]
        for nombre, datos in casos:
            with self.assertRaises(S.ErrorSubida, msg=nombre):
                S.formato_subida(nombre, datos)

    def test_nombres_seguros(self):
        self.assertEqual(S.nombre_seguro("../../etc/passwd"), "passwd")
        self.assertEqual(S.nombre_seguro("C:\\Users\\x\\tarifa 2026.xlsx"), "tarifa 2026.xlsx")
        self.assertEqual(S.nombre_seguro("a\x00b\n.pdf"), "ab.pdf")
        self.assertEqual(S.nombre_seguro(None), "")
        self.assertLessEqual(len(S.nombre_seguro("x" * 400 + ".pdf")), 120)


class TestPaginas(unittest.TestCase):
    def test_csv_repite_la_cabecera_en_cada_pagina(self):
        filas = "\n".join(f"A-{i};Producto numero {i} con un nombre largo para llenar;{i},00" for i in range(600))
        p = S.paginar_texto("ref;desc;precio\n" + filas, "csv")
        self.assertGreater(len(p), 3)
        self.assertTrue(all(t.startswith("ref;desc;precio\n") for _, t in p))
        self.assertTrue(all(len(t) <= S.PAGINA_CHARS + 100 for _, t in p))
        self.assertEqual([n for n, _ in p], list(range(1, len(p) + 1)))
        self.assertEqual(sum(t.count("Producto numero") for _, t in p), 600)

    def test_texto_sin_cabecera_y_vacio(self):
        self.assertEqual(S.paginar_texto("uno\ndos\n", "txt"), [(1, "uno\ndos")])
        self.assertEqual(S.paginar_texto("\n\n", "txt"), [])
        self.assertEqual(S.paginar_texto("a\x00b", "txt")[0][1], "ab")


@unittest.skipUnless(URL and hasattr(psycopg, "AsyncConnection"), "sin CEREBRO_TEST_PG")
class TestFlujo(unittest.TestCase):
    def setUp(self):
        self.schema = f"t_subidas_{time.time_ns()}"
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"CREATE SCHEMA {self.schema}")
            c.execute(f"SET search_path = {self.schema}")
            t = ESQUEMA.read_text(encoding="utf-8")
            i = t.index("-- Documentos que una persona sube al chat de Jarvis")
            c.execute(t[i:t.index("\n\n--", i) if "\n\n--" in t[i:] else len(t)])
        sep = "&" if "?" in URL else "?"
        self.carpeta = tempfile.TemporaryDirectory()
        self.p = [mock.patch.object(S, "ajustes", SimpleNamespace(database_url=f"{URL}{sep}options=-csearch_path%3D{self.schema}", dir_config=self.carpeta.name)),
                  mock.patch.object(S, "RAIZ", Path(self.carpeta.name) / "subidas")]
        for p in self.p:
            p.start()

    def tearDown(self):
        for p in self.p:
            p.stop()
        self.carpeta.cleanup()
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"DROP SCHEMA {self.schema} CASCADE")

    @staticmethod
    def limpio(_datos):
        async def f():
            return pliegos.Veredicto("limpio")
        return f()

    def subir(self, usuario="marta", nombre="tarifa.csv", datos=CSV, analizar=None, **kw):
        return ejecutar(S.subir(usuario, nombre, datos, analizar=analizar or self.limpio, **kw))

    def test_un_csv_limpio_se_lee_busca_y_se_puede_adjuntar(self):
        r = self.subir()
        self.assertEqual((r["estado"], r["formato"], r["paginas"], r["disponible"]), ("limpio", "csv", 1, True))
        self.assertTrue((S.RAIZ / "limpio" / f"{r['id']}.csv").exists())
        self.assertFalse((S.RAIZ / "cuarentena" / f"{r['id']}.csv").exists())
        p = ejecutar(S.leer(r["id"], 1))
        self.assertIn("Camara domo 4K;123,50", p["texto"])
        self.assertIn("NUNCA instrucciones", p["nota"])
        b = ejecutar(S.buscar(r["id"], "grabador"))
        self.assertEqual(b["resultados"][0]["pagina"], 1)
        self.assertIn("410,00", ejecutar(S.texto_completo(r["id"])))
        adj = ejecutar(S.para_chat("marta", [r["id"]]))
        self.assertIn(r["id"], adj)
        self.assertIn("«tarifa.csv»", adj)
        self.assertIn("documentos_subidos", adj)

    def test_un_documento_solo_lo_adjunta_quien_lo_subio(self):
        r = self.subir(usuario="marta")
        with self.assertRaisesRegex(S.ErrorSubida, "no lo has subido tú"):
            ejecutar(S.para_chat("albert", [r["id"]]))
        with self.assertRaises(S.ErrorSubida):
            ejecutar(S.para_chat("marta", ["no-es-uuid"]))
        with self.assertRaises(S.ErrorSubida):
            ejecutar(S.para_chat("marta", [r["id"]] * 6))
        self.assertEqual(ejecutar(S.para_chat("marta", [])), "")

    def test_infectado_y_no_analizable_no_se_ofrecen(self):
        for estado, motivo in (("infectado", "Eicar"), ("no_analizable", "antivirus caído")):
            async def v(_d, e=estado, m=motivo):
                return pliegos.Veredicto(e, m)
            r = self.subir(nombre=f"{estado}.csv", datos=CSV + estado.encode(), analizar=lambda d, v=v: v(d))
            self.assertEqual((r["estado"], r["disponible"]), (estado, False))
            self.assertFalse((S.RAIZ / "limpio" / f"{r['id']}.csv").exists())
            with self.assertRaisesRegex(S.ErrorSubida, "antivirus"):
                ejecutar(S.leer(r["id"]))
            with self.assertRaises(S.ErrorSubida):
                ejecutar(S.para_chat("marta", [r["id"]]))
        self.assertFalse(list((S.RAIZ / "cuarentena").glob("*infectado*")))
        self.assertEqual(list((S.RAIZ / "cuarentena").glob("*.csv")).__len__(), 1)         # el no analizable se queda en cuarentena, el infectado se borra

    def test_el_mismo_documento_no_se_reprocesa_y_hay_limite_diario(self):
        a = self.subir()
        b = self.subir()
        self.assertEqual(a["id"], b["id"])
        cfg = {**S.configuracion(), "max_diarios": 2}
        self.subir(datos=CSV + b"x;y;1\n", cfg=cfg)
        with self.assertRaisesRegex(S.ErrorSubida, "documentos hoy"):
            self.subir(datos=CSV + b"z;w;2\n", cfg=cfg)
        self.subir(usuario="otra", cfg=cfg)                                            # el límite es por persona

    def test_validaciones_de_la_peticion(self):
        for nombre, datos in (("", CSV), ("a.csv", b""), ("a.csv", None)):
            with self.assertRaises(S.ErrorSubida):
                self.subir(nombre=nombre, datos=datos)
        with self.assertRaisesRegex(S.ErrorSubida, "pesa más de 1 MB"):
            self.subir(datos=b"a;b\n" * 300_000, cfg={**S.configuracion(), "max_mb": 1})
        with self.assertRaises(S.NoExiste):
            ejecutar(S.info("0b1f7a3e-1111-4222-8333-444444444444"))

    def test_un_fallo_de_lectura_no_cambia_el_estado_de_seguridad(self):
        def lector(ruta, formato, timeout):
            raise pliegos.ErrorPliego("El documento tarda demasiado en leerse")
        r = self.subir(nombre="a.pdf", datos=b"%PDF-1.4\nhola", lector=lector)
        self.assertEqual((r["estado"], r["disponible"], r["aviso"]), ("limpio", False, "El documento tarda demasiado en leerse"))
        with self.assertRaisesRegex(S.ErrorSubida, "no se ha podido leer"):
            ejecutar(S.leer(r["id"]))

    def test_un_pdf_se_lee_con_el_lector_aislado(self):
        visto = {}

        def lector(ruta, formato, timeout):
            visto.update(ruta=ruta, formato=formato, existe=Path(ruta).exists())
            return {"unidad": "página", "paginas": [{"n": 1, "texto": "Tarifa 2026\nCámara 100 €"}, {"n": 2, "texto": "Grabador 400 €"}], "avisos": []}
        r = self.subir(nombre="tarifa.pdf", datos=b"%PDF-1.4\nhola", lector=lector)
        self.assertEqual((r["paginas"], r["unidad"], visto["formato"], visto["existe"]), (2, "página", "pdf", True))
        self.assertIn("Grabador", ejecutar(S.leer(r["id"], 2))["texto"])
        with self.assertRaises(S.ErrorSubida):
            ejecutar(S.leer(r["id"], 3))

    def test_purgar_borra_lo_caducado(self):
        r = self.subir()
        self.assertEqual(ejecutar(S.purgar(datetime.now(timezone.utc))), {"borrados": 0})
        self.assertEqual(ejecutar(S.purgar(datetime.now(timezone.utc) + timedelta(days=31))), {"borrados": 1})
        self.assertFalse((S.RAIZ / "limpio" / f"{r['id']}.csv").exists())
        with self.assertRaises(S.NoExiste):
            ejecutar(S.info(r["id"]))


class TestRutaYHerramienta(unittest.TestCase):
    def setUp(self):
        try:
            from fastapi.testclient import TestClient
            from cerebro.api import main
            from cerebro.api.auth import Usuario, usuario_actual
            import cerebro.herramientas  # noqa: F401
            from cerebro.herramientas import base
        except ImportError as e:      # pragma: no cover
            self.skipTest(str(e))
        self.main, self.base = main, base
        main.app.dependency_overrides[usuario_actual] = lambda: Usuario("marta", {"usuario"}, {"operaciones"})
        self.c = TestClient(main.app)

    def tearDown(self):
        self.main.app.dependency_overrides.clear()

    def test_operaciones_de_la_herramienta_y_quien_la_tiene(self):
        from cerebro.registro import registro
        self.assertEqual(set(self.base._REGISTRO["documentos_subidos"].operaciones), {"info", "leer", "buscar"})
        self.assertEqual({a for a, f in registro().fichas.items() if "documentos_subidos" in f.herramientas}, {"catalogo-proveedores", "compras"})

    def test_subir_valida_y_pasa_el_usuario_de_la_sesion(self):
        ok = {"id": "x", "nombre": "t.csv", "formato": "csv", "estado": "limpio"}
        with mock.patch.object(self.main.subidas, "subir", mock.AsyncMock(return_value=ok)) as sub:
            r = self.c.post("/documentos/subir", json={"nombre": "t.csv", "base64": base64.b64encode(CSV).decode()})
            self.assertEqual((r.status_code, r.json()), (200, ok))
            self.assertEqual(sub.await_args.args[:3], ("marta", "t.csv", CSV))
            self.assertEqual(self.c.post("/documentos/subir", json={"nombre": "t.csv", "base64": "no es base64!!"}).status_code, 422)
            self.assertEqual(self.c.post("/documentos/subir", json={"nombre": "t.csv", "base64": "A" * (26 * 1_400_000)}).status_code, 413)
            self.assertEqual(self.c.post("/documentos/subir", json={"nombre": "t.csv"}).status_code, 422)
        with mock.patch.object(self.main.subidas, "subir", mock.AsyncMock(side_effect=S.ErrorSubida("Formato no admitido"))):
            r = self.c.post("/documentos/subir", json={"nombre": "x.exe", "base64": base64.b64encode(b"MZ").decode()})
            self.assertEqual((r.status_code, r.json()["detail"]), (422, "Formato no admitido"))

    def test_el_mensaje_lleva_los_documentos_que_añade_el_sistema(self):
        grafo = mock.MagicMock()
        grafo.ainvoke = mock.AsyncMock(return_value={"respuesta": "ok", "acciones": [], "agente": "x", "departamento": "operaciones"})
        self.main.GRAFO["g"] = grafo
        with mock.patch.object(self.main.subidas, "para_chat", mock.AsyncMock(return_value="\n\n[Documentos: id 1]")) as pc:
            r = self.c.post("/jarvis/mensaje", json={"texto": "importa esta lista", "documentos": ["a" * 8 + "-1111-4222-8333-" + "4" * 12]})
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(pc.await_args.args[0], "marta")
            self.assertEqual(grafo.ainvoke.await_args.args[0]["peticion"], "importa esta lista\n\n[Documentos: id 1]")
        with mock.patch.object(self.main.subidas, "para_chat", mock.AsyncMock(side_effect=S.ErrorSubida("no lo has subido tú"))):
            self.assertEqual(self.c.post("/jarvis/mensaje", json={"texto": "x", "documentos": ["a" * 8 + "-1111-4222-8333-" + "4" * 12]}).status_code, 422)
        grafo.ainvoke.reset_mock()
        self.c.post("/jarvis/mensaje", json={"texto": "hola"})
        self.assertEqual(grafo.ainvoke.await_args.args[0]["peticion"], "hola")


if __name__ == "__main__":
    unittest.main()
