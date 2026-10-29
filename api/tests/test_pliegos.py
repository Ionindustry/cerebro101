"""Pliegos: descarga segura por id y antivirus. Lo puro, el cliente de clamd contra un clamd falso, la descarga con un servidor simulado y el flujo con PostgreSQL real
(con CEREBRO_TEST_PG; sin ella, esa parte se omite)."""
import asyncio
import io
import os
import struct
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
    import httpx
    import psycopg
    from cerebro.herramientas import base as herramientas_base, web
    from cerebro.licitaciones import pliegos as P
except ImportError as e:      # pragma: no cover
    raise unittest.SkipTest(str(e))

URL = os.environ.get("CEREBRO_TEST_PG")
ESQUEMA = Path(__file__).resolve().parents[2] / "db" / "esquema.sql"
ID = "0b1f7a3e-1111-4222-8333-444444444444"
HOSTS = ["contrataciondelestado.es"]
AHORA = datetime(2026, 10, 28, 14, 0, tzinfo=timezone.utc)
PDF = b"%PDF-1.7\n1 0 obj<<>>endobj\n%%EOF"
CFG = {"max_mb": 1, "max_diarios": 5, "hosts": HOSTS, "timeout_s": 5, "firmas_max_horas": 48}


def ejecutar(coro):
    return asyncio.run(coro)


def zip_con(nombres: dict) -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        for n, c in nombres.items():
            z.writestr(n, c)
    return b.getvalue()


class TestPuro(unittest.TestCase):
    def test_solo_https_en_las_plataformas_de_la_lista_y_sus_subdominios(self):
        for ok in ("https://contrataciondelestado.es/FileSystem/servlet/GetDocument?DocumentIdParam=x", "https://www.contrataciondelestado.es/x", "https://CONTRATACIONDELESTADO.ES./x"):
            self.assertTrue(P.host_permitido(ok, HOSTS), ok)
        for mal in ("http://contrataciondelestado.es/x", "https://evil.com/x", "https://contrataciondelestado.es.evil.com/x", "https://evilcontrataciondelestado.es/x",
                    "https://user:pass@contrataciondelestado.es/x", "https://contrataciondelestado.es:8443/x", "ftp://contrataciondelestado.es/x", "https:///x", "", None,
                    "https://127.0.0.1/x", "https://contrataciondelestado.es@evil.com/x"):
            self.assertFalse(P.host_permitido(mal, HOSTS), str(mal))

    def test_los_documentos_de_la_ficha_se_numeran_y_no_ensenan_la_direccion(self):
        ficha = {"documentos": [{"nombre": "Pliego\n  de   cláusulas", "tipo": "legal", "url_origen": "https://contrataciondelestado.es/a"}, {"nombre": "", "url_origen": None}]}
        d = P.documentos_de(ficha)
        self.assertEqual([(x["n"], x["nombre"], x["clase"]) for x in d], [(1, "Pliego de cláusulas", "legal"), (2, "Documento 2", None)])
        self.assertEqual(P.documentos_de({}), [])

    def test_el_formato_sale_del_contenido_no_del_nombre_ni_del_servidor(self):
        self.assertEqual(P.formato_real(PDF), "pdf")
        self.assertEqual(P.formato_real(zip_con({"[Content_Types].xml": "x", "word/document.xml": "x"})), "docx")
        self.assertEqual(P.formato_real(zip_con({"[Content_Types].xml": "x", "xl/workbook.xml": "x"})), "xlsx")
        self.assertEqual(P.formato_real(zip_con({"mimetype": "application/vnd.oasis.opendocument.text", "content.xml": "x"})), "odt")
        self.assertEqual(P.formato_real(zip_con({"mimetype": "application/vnd.oasis.opendocument.spreadsheet"})), "ods")
        self.assertEqual(P.formato_real(zip_con({"datos.txt": "hola"})), "zip")
        for mal in (b"<html><script>alert(1)</script>", b"<svg xmlns='http://www.w3.org/2000/svg'/>", b"MZ\x90\x00", b"\x7fELF", b"", b"PK\x03\x04roto", b"#!/bin/sh\nrm -rf /"):
            self.assertIsNone(P.formato_real(mal), mal[:12])

    def test_la_respuesta_de_clamd_se_interpreta_y_lo_raro_no_es_limpio(self):
        casos = {"stream: OK\0": "limpio", "stream: Win.Test.EICAR_HDB-1 FOUND\0": "infectado", "stream: Heuristics.Encrypted.PDF FOUND\0": "no_analizable",
                 "stream: Heuristics.OLE2.ContainsMacros FOUND\0": "con_macros", "INSTREAM size limit exceeded. ERROR\0": "no_analizable", "": "no_analizable",
                 "algo que no es una respuesta": "no_analizable"}
        for resp, estado in casos.items():
            self.assertEqual(P.interpretar_respuesta(resp).estado, estado, resp)
        self.assertIn("EICAR", P.interpretar_respuesta("stream: Win.Test.EICAR_HDB-1 FOUND\0").motivo)

    def test_las_firmas_viejas_o_sin_fecha_no_valen(self):
        self.assertTrue(P._firmas_recientes("ClamAV 1.4.1/27456/Tue Oct 27 08:31:08 2026\0", AHORA, 48))
        self.assertFalse(P._firmas_recientes("ClamAV 1.4.1/27400/Tue Oct 20 08:31:08 2026\0", AHORA, 48))
        self.assertFalse(P._firmas_recientes("ClamAV 1.4.1\0", AHORA, 48))
        self.assertFalse(P._firmas_recientes("", AHORA, 48))


class ClamdFalso:
    """Un clamd de mentira que habla el protocolo de verdad (zVERSION y zINSTREAM por trozos)."""
    def __init__(self, version="ClamAV 1.4.1/27456/Tue Oct 28 08:31:08 2026", respuesta="stream: OK"):
        self.version, self.respuesta, self.recibido, self.servidor, self.puerto = version, respuesta, b"", None, 0

    async def _atender(self, leer, escribir):
        orden = await leer.readuntil(b"\0")
        if orden == b"zVERSION\0":
            escribir.write(self.version.encode() + b"\0")
        elif orden == b"zINSTREAM\0":
            datos = b""
            while True:
                (n,) = struct.unpack(">I", await leer.readexactly(4))
                if n == 0:
                    break
                datos += await leer.readexactly(n)
            self.recibido = datos
            escribir.write(self.respuesta.encode() + b"\0")
        await escribir.drain()
        escribir.close()

    async def __aenter__(self):
        self.servidor = await asyncio.start_server(self._atender, "127.0.0.1", 0)
        self.puerto = self.servidor.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *a):
        self.servidor.close()
        await self.servidor.wait_closed()


class TestClamd(unittest.TestCase):
    def analizar(self, datos=PDF, **kw):
        async def correr():
            async with ClamdFalso(**kw) as c:
                v = await P.analizar_con_clamd(datos, "127.0.0.1", c.puerto, AHORA, CFG)
                return v, c.recibido
        return ejecutar(correr())

    def test_limpio_y_el_contenido_llega_entero_aunque_pase_de_un_trozo(self):
        grande = PDF + os.urandom(2_500_000)
        v, recibido = self.analizar(grande, version="ClamAV 1.4.1/1/Tue Oct 27 08:31:08 2026")
        self.assertEqual(v.estado, "limpio")
        self.assertEqual(recibido, grande)

    def test_infectado_cifrado_macros_y_error(self):
        for resp, estado in (("stream: Win.Test.EICAR_HDB-1 FOUND", "infectado"), ("stream: Heuristics.Encrypted.PDF FOUND", "no_analizable"),
                             ("stream: Heuristics.OLE2.ContainsMacros FOUND", "con_macros"), ("INSTREAM size limit exceeded. ERROR", "no_analizable")):
            self.assertEqual(self.analizar(respuesta=resp, version="ClamAV 1.4.1/1/Tue Oct 27 08:31:08 2026")[0].estado, estado, resp)

    def test_con_las_firmas_viejas_no_se_fia(self):
        v, recibido = self.analizar(version="ClamAV 1.4.1/1/Mon Oct 12 08:31:08 2026")
        self.assertEqual((v.estado, recibido), ("no_analizable", b""))                      # ni siquiera se le manda el fichero

    def test_sin_servicio_falla_cerrado(self):
        v = ejecutar(P.analizar_con_clamd(PDF, "127.0.0.1", 1, AHORA, CFG))
        self.assertEqual(v.estado, "no_analizable")
        self.assertIn("no está disponible", v.motivo)


def servidor(manejar):
    """Hace que la descarga hable con un servidor simulado y que el nombre resuelva a una IP pública."""
    real = httpx.AsyncClient

    def fabrica(*a, **k):
        return real(*a, **{**k, "transport": httpx.MockTransport(manejar)})
    return mock.patch.object(P.httpx, "AsyncClient", fabrica), mock.patch.object(web, "_resolver", lambda host, puerto: ["93.184.216.34"])


class TestDescarga(unittest.TestCase):
    def bajar(self, manejar, url="https://contrataciondelestado.es/doc", max_bytes=1_000_000, resolver=None):
        p1, p2 = servidor(manejar)
        with p1, p2:
            if resolver:
                with mock.patch.object(web, "_resolver", resolver):
                    return ejecutar(P.descargar_seguro(url, HOSTS, max_bytes, 5))
            return ejecutar(P.descargar_seguro(url, HOSTS, max_bytes, 5))

    def test_baja_un_pdf_a_la_ip_comprobada_con_el_host_original(self):
        vistas = []

        def manejar(req):
            vistas.append(req)
            return httpx.Response(200, content=PDF, headers={"content-type": "application/pdf"})
        self.assertEqual(self.bajar(manejar), PDF)
        self.assertEqual((vistas[0].url.host, vistas[0].headers["host"]), ("93.184.216.34", "contrataciondelestado.es"))

    def test_rechaza_lo_que_no_es_la_plataforma_o_no_es_publico(self):
        siempre_ok = lambda req: httpx.Response(200, content=PDF)
        for url in ("http://contrataciondelestado.es/x", "https://evil.com/x", "https://contrataciondelestado.es:8443/x"):
            with self.assertRaises(P.SinPermisoDescarga, msg=url):
                self.bajar(siempre_ok, url)
        for ips in (["127.0.0.1"], ["10.0.0.5"], ["169.254.169.254"], ["93.184.216.34", "192.168.1.1"], ["::1"]):
            with self.assertRaises(P.SinPermisoDescarga, msg=str(ips)):               # el nombre de la plataforma resuelve a una dirección interna
                self.bajar(siempre_ok, resolver=lambda host, puerto, ips=ips: ips)

    def test_una_redireccion_fuera_de_la_lista_se_corta(self):
        def manejar(req):
            return httpx.Response(302, headers={"location": "https://evil.com/robo"})
        with self.assertRaises(P.SinPermisoDescarga):
            self.bajar(manejar)

    def test_una_redireccion_dentro_de_la_lista_se_sigue_pero_con_tope(self):
        pasos = []

        def manejar(req):
            pasos.append(req.url.path)
            if req.url.path == "/doc":
                return httpx.Response(302, headers={"location": "/final.pdf"})
            return httpx.Response(200, content=PDF, headers={"content-type": "application/pdf"})
        self.assertEqual(self.bajar(manejar), PDF)
        self.assertEqual(pasos, ["/doc", "/final.pdf"])
        with self.assertRaises(P.ErrorPliego):
            self.bajar(lambda req: httpx.Response(302, headers={"location": "/otra"}))

    def test_tipo_tamano_y_errores_del_servidor(self):
        with self.assertRaisesRegex(P.ErrorPliego, "no es un documento"):
            self.bajar(lambda req: httpx.Response(200, content=b"<html>", headers={"content-type": "text/html"}))
        with self.assertRaisesRegex(P.ErrorPliego, "pesa 1000 MB: el máximo es 1 MB"):
            self.bajar(lambda req: httpx.Response(200, content=PDF, headers={"content-type": "application/pdf", "content-length": "999999999"}))
        with self.assertRaisesRegex(P.ErrorPliego, "pasa de"):                                    # sin content-length, se corta en cuanto se pasa
            async def trozos():
                for _ in range(10):
                    yield b"x" * 500
            self.bajar(lambda req: httpx.Response(200, content=trozos(), headers={"content-type": "application/pdf"}), max_bytes=1000)
        with self.assertRaisesRegex(P.ErrorPliego, "404"):
            self.bajar(lambda req: httpx.Response(404))


@unittest.skipUnless(URL and hasattr(psycopg, "AsyncConnection"), "sin CEREBRO_TEST_PG")
class TestFlujo(unittest.TestCase):
    def setUp(self):
        self.schema = f"t_pliegos_{time.time_ns()}"
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"CREATE SCHEMA {self.schema}")
            c.execute(f"SET search_path = {self.schema}")
            t = ESQUEMA.read_text(encoding="utf-8")
            c.execute(t[t.index("-- Pliegos y otros documentos de una licitación"):])
        sep = "&" if "?" in URL else "?"
        self.carpeta = tempfile.TemporaryDirectory()
        self.parches = [mock.patch.object(P, "ajustes", SimpleNamespace(database_url=f"{URL}{sep}options=-csearch_path%3D{self.schema}", dir_config=".")),
                        mock.patch.object(P, "RAIZ", Path(self.carpeta.name))]
        for p in self.parches:
            p.start()
        self.bajadas = []
        self.ficha = {"documentos": [{"nombre": "Pliego administrativo", "tipo": "legal", "url_origen": "https://contrataciondelestado.es/a"},
                                     {"nombre": "Fuera", "tipo": "legal", "url_origen": "https://evil.com/b"}]}

    def tearDown(self):
        for p in self.parches:
            p.stop()
        self.carpeta.cleanup()
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"DROP SCHEMA {self.schema} CASCADE")

    async def consulta(self, ruta, params=None):
        return self.ficha

    def pedir(self, n=1, datos=PDF, veredicto=None, cfg=None):
        async def descargar(url, hosts, max_bytes, timeout):
            self.bajadas.append(url)
            return datos

        async def analizar(d):
            return veredicto or P.Veredicto("limpio")
        return ejecutar(P.obtener(ID, n, consulta=self.consulta, descargar=descargar, analizar=analizar, cfg=cfg or CFG))

    def ficheros(self):
        return sorted(str(p.relative_to(self.carpeta.name)) for p in Path(self.carpeta.name).rglob("*") if p.is_file())

    def test_un_documento_limpio_pasa_de_cuarentena_a_limpio_y_no_se_repite(self):
        r = self.pedir()
        self.assertEqual((r["estado"], r["disponible"], r["formato"], r["bytes"]), ("limpio", True, "pdf", len(PDF)))
        self.assertNotIn("ruta", r)                                                           # nadie recibe la ruta ni el contenido
        self.assertEqual(len(r["sha256"]), 64)
        self.assertEqual(self.ficheros(), [f"{ID}/limpio/{r['sha256']}.pdf"])                 # ya no está en cuarentena
        self.assertEqual(self.pedir()["id"], r["id"])                                         # el mismo contenido: no se guarda otra vez
        self.assertEqual(len(ejecutar(P.listar(ID))), 1)

    def test_infectado_se_borra_y_queda_la_huella(self):
        r = self.pedir(veredicto=P.Veredicto("infectado", "El antivirus lo marca como dañino (Win.Test.EICAR_HDB-1)"))
        self.assertEqual((r["estado"], r["disponible"]), ("infectado", False))
        self.assertEqual(self.ficheros(), [])
        self.assertEqual(self.pedir(veredicto=P.Veredicto("limpio"))["estado"], "infectado")      # lo ya decidido no se reabre

    def test_no_analizable_se_queda_en_cuarentena_y_se_reintenta(self):
        r = self.pedir(veredicto=P.Veredicto("no_analizable", "El antivirus no está disponible ahora"))
        self.assertEqual((r["estado"], r["disponible"]), ("no_analizable", False))
        self.assertEqual(self.ficheros(), [f"{ID}/cuarentena/{r['sha256']}.pdf"])
        r2 = self.pedir()                                                                      # con el antivirus de vuelta, se analiza y pasa
        self.assertEqual((r2["id"], r2["estado"]), (r["id"], "limpio"))
        self.assertEqual(self.ficheros(), [f"{ID}/limpio/{r['sha256']}.pdf"])

    def test_con_macros_se_guarda_pero_no_se_ofrece_como_original(self):
        r = self.pedir(veredicto=P.Veredicto("con_macros", "El documento lleva macros: solo se leerá su texto"))
        self.assertEqual((r["estado"], r["disponible"]), ("con_macros", True))

    def test_se_rechaza_lo_que_no_es_un_documento_o_no_es_de_la_lista_o_el_numero_no_existe(self):
        with self.assertRaisesRegex(P.ErrorPliego, "no es un PDF"):
            self.pedir(datos=b"<html><script>")
        antes = len(self.bajadas)
        with self.assertRaises(P.SinPermisoDescarga):
            self.pedir(n=2)                                                                    # su URL no es de una plataforma de la lista
        for n in (0, 3, "1", True, None):
            with self.assertRaises(P.ErrorPliego, msg=repr(n)):
                self.pedir(n=n)
        with self.assertRaises(P.ErrorPliego):
            ejecutar(P.obtener("no-es-uuid", 1, consulta=self.consulta, cfg=CFG))
        self.assertEqual((len(self.bajadas) - antes, self.ficheros()), (0, []))                # ni la URL fuera de la lista ni un número malo llegaron a bajar nada, y nada se guardó

    def test_la_cuota_diaria_se_acaba(self):
        for i in range(CFG["max_diarios"]):
            self.pedir(datos=PDF + str(i).encode())
        with self.assertRaisesRegex(P.ErrorPliego, "máximo de 5"):
            self.pedir(datos=PDF + b"otro")

    def test_documentos_lista_lo_bajado_sin_enseñar_direcciones(self):
        self.pedir()
        d = ejecutar(P.documentos(ID, consulta=self.consulta))
        self.assertEqual([x["n"] for x in d["documentos"]], [1, 2])
        self.assertEqual((d["documentos"][0]["descarga"]["estado"], d["documentos"][1]["descarga"]), ("limpio", None))
        self.assertNotIn("http", str(d))


class TestHerramienta(unittest.TestCase):
    def test_la_herramienta_existe_y_la_que_aceptaba_cualquier_url_ya_no(self):
        self.assertIn("pliegos", herramientas_base._REGISTRO)
        self.assertEqual(set(herramientas_base._REGISTRO["pliegos"].operaciones), {"documentos", "descargar", "leer", "buscar", "anotar_requisito", "requisitos", "matriz"})
        self.assertNotIn("descargar_documento", herramientas_base._REGISTRO["plataformas_contratacion"].operaciones)

    def test_la_configuracion_real_trae_las_plataformas_y_los_limites(self):
        with mock.patch.object(P, "ajustes", SimpleNamespace(dir_config=Path(__file__).resolve().parents[2] / "config")):
            c = P.configuracion()
        self.assertIn("contrataciondelestado.es", c["hosts"])
        self.assertEqual((c["max_mb"], c["max_diarios"], c["firmas_max_horas"]), (100, 40, 48))


if __name__ == "__main__":
    unittest.main()
