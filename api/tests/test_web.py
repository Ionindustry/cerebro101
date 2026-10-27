"""Internet para Jarvis: buscar (SearXNG simulado), consulta sin datos personales, lectura de páginas públicas sin alcanzar servicios internos."""
import asyncio
import unittest
from datetime import datetime, timezone
from unittest import mock

import _sin_servicios  # noqa: F401
import httpx

from cerebro.entidades import Entidades
from cerebro.grafo.prompts import ahora_texto, sistema_agente, sistema_director_departamento, sistema_director_general
from cerebro.herramientas import web
from cerebro.registro import registro

HTTPX_REAL = hasattr(httpx, "MockTransport")


def con_transporte(manejar):
    """Hace que los httpx.AsyncClient de la herramienta usen un servidor simulado."""
    real = httpx.AsyncClient

    def fabrica(*a, **k):
        return real(*a, **{**k, "transport": httpx.MockTransport(manejar)})
    return mock.patch.object(web.httpx, "AsyncClient", fabrica)


def entidades(disponible=True):
    async def _e(cfg):
        return Entidades(personas=["Marta Puig"], organizaciones=["Comunitat Vilanova SL"], disponible=disponible)
    return mock.patch.object(web, "cargar_entidades", _e)


def ejecutar(coro):
    return asyncio.run(coro)


@unittest.skipUnless(HTTPX_REAL, "requiere httpx real (se ejecuta en el contenedor)")
class TestBuscar(unittest.TestCase):
    def buscar(self, consulta="normativa RGPD videovigilancia", respuesta=None, **kw):
        vistas = []

        def manejar(req):
            vistas.append(req)
            return httpx.Response(200, json=respuesta or {"results": [
                {"title": "AEPD", "url": "https://aepd.es/x", "content": "Guía de videovigilancia", "engine": "duckduckgo", "publishedDate": "2026-10-01"},
                {"title": "Sin enlace", "content": "descartado"}], "answers": ["Respuesta directa"]})
        with entidades(), con_transporte(manejar):
            return ejecutar(web.buscar(consulta, **kw)), vistas

    def test_devuelve_resultados_con_enlace_y_pide_json_en_castellano(self):
        r, vistas = self.buscar()
        self.assertEqual(r["resultados"], [{"titulo": "AEPD", "url": "https://aepd.es/x", "resumen": "Guía de videovigilancia",
                                           "fecha": "2026-10-01", "fuente": "duckduckgo"}])
        self.assertEqual(r["respuestas"], ["Respuesta directa"])
        q = dict(vistas[0].url.params)
        self.assertEqual((vistas[0].url.path, q["format"], q["language"], q["categories"]), ("/search", "json", "es", "general"))

    def test_noticias_y_periodo(self):
        _, vistas = self.buscar(tipo="noticias", periodo="mes")
        q = dict(vistas[0].url.params)
        self.assertEqual((q["categories"], q["time_range"]), ("news", "month"))

    def test_periodo_escrito_de_otra_forma_se_entiende_y_uno_raro_se_rechaza(self):
        _, vistas = self.buscar(periodo="último año")
        self.assertEqual(dict(vistas[0].url.params)["time_range"], "year")
        with entidades(), con_transporte(lambda req: httpx.Response(200, json={"results": []})):
            with self.assertRaisesRegex(ValueError, "periodo debe ser"):
                ejecutar(web.buscar("hora en Tokio", periodo="desde siempre"))

    def test_el_numero_de_resultados_tiene_tope(self):
        filas = [{"title": str(i), "url": f"https://x/{i}", "content": ""} for i in range(30)]
        r, _ = self.buscar(respuesta={"results": filas}, max_resultados=99)
        self.assertEqual(len(r["resultados"]), web.MAX_RESULTADOS)

    def test_sin_resultados_lo_dice(self):
        r, _ = self.buscar(respuesta={"results": []})
        self.assertEqual((r["resultados"], r["aviso"]), ([], "Sin resultados"))

    def test_si_el_buscador_cae_el_error_se_explica(self):
        with entidades(), con_transporte(lambda req: httpx.Response(500)):
            with self.assertRaisesRegex(RuntimeError, "buscador no responde"):
                ejecutar(web.buscar("hora en Tokio"))

    def test_parametros_no_validos(self):
        for kw in ({"tipo": "imagenes"}, {"periodo": "siglo"}):
            with entidades(), con_transporte(lambda req: httpx.Response(200, json={})):
                with self.assertRaises(ValueError):
                    ejecutar(web.buscar("algo", **kw))


@unittest.skipUnless(HTTPX_REAL, "requiere httpx real (se ejecuta en el contenedor)")
class TestConsultaSinDatosPersonales(unittest.TestCase):
    def comprobar(self, consulta, disponible=True):
        with entidades(disponible):
            return ejecutar(web._comprobar_consulta(consulta))

    def test_una_consulta_normal_pasa(self):
        self.assertIsNone(self.comprobar("¿Quién ganó el Mundial de 2022 y cuándo es la próxima Eurocopa?"))
        self.assertIsNone(self.comprobar("precio medio cámara IP exterior 4K"))

    def test_nombres_de_empleados_y_clientes_no_salen(self):
        for q in ("qué ha publicado Marta Puig en redes", "dirección de Comunitat Vilanova SL"):
            with self.assertRaises(PermissionError, msg=q):
                self.comprobar(q)

    def test_datos_con_formato_no_salen(self):
        for q in ("consultar 12345678Z", "buscar a juan@ejemplo.com", "ES9121000418450200051332 saldo", "llamar al 612345678"):
            with self.assertRaises(PermissionError, msg=q):
                self.comprobar(q)

    def test_sin_poder_comprobar_el_erp_no_se_busca(self):
        with self.assertRaisesRegex(PermissionError, "ERP"):
            self.comprobar("tiempo en Barcelona", disponible=False)

    def test_vacia_o_demasiado_larga(self):
        for q in ("   ", "x" * 301):
            with self.assertRaises(ValueError):
                self.comprobar(q)


@unittest.skipUnless(HTTPX_REAL, "requiere httpx real (se ejecuta en el contenedor)")
class TestLeer(unittest.TestCase):
    PUBLICA = "93.184.216.34"

    def leer(self, url, manejar=None, resuelve=None, **kw):
        manejar = manejar or (lambda req: httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"}, text=PAGINA))
        with mock.patch.object(web, "_resolver", lambda host, puerto: resuelve if resuelve is not None else [self.PUBLICA]), con_transporte(manejar):
            return ejecutar(web.leer(url, **kw))

    def test_lee_el_texto_y_no_el_codigo_de_la_pagina(self):
        r = self.leer("https://ejemplo.com/noticia")
        self.assertEqual(r["titulo"], "Novedades")
        self.assertIn("Texto útil de la noticia", r["texto"])
        self.assertNotIn("alert", r["texto"])
        self.assertNotIn("color:red", r["texto"])

    def test_la_conexion_va_a_la_ip_comprobada_con_el_nombre_en_la_cabecera(self):
        vistas = []

        def manejar(req):
            vistas.append(req)
            return httpx.Response(404) if req.url.path == "/robots.txt" else httpx.Response(200, headers={"content-type": "text/plain"}, text="hola")
        self.leer("https://ejemplo.com/a?b=1", manejar)
        pagina = [v for v in vistas if v.url.path == "/a"][0]
        self.assertEqual((pagina.url.host, pagina.headers["host"], pagina.url.query), (self.PUBLICA, "ejemplo.com", b"b=1"))

    def test_nunca_llega_a_servicios_internos(self):
        casos = [("http://localhost/x", ["127.0.0.1"]), ("http://127.0.0.1/", ["127.0.0.1"]), ("http://erpnext/", ["172.18.0.5"]),
                 ("http://metadata/", ["169.254.169.254"]), ("http://casa/", ["192.168.1.10"]), ("http://v6/", ["::1"]),
                 ("http://mixto/", [self.PUBLICA, "10.0.0.8"])]
        for url, ips in casos:
            with self.assertRaisesRegex(PermissionError, "no es una página pública", msg=url):
                self.leer(url, resuelve=ips)

    def test_puertos_y_esquemas_no_admitidos(self):
        for url, error in (("http://ejemplo.com:8080/", PermissionError), ("https://ejemplo.com:22/", PermissionError),
                           ("ftp://ejemplo.com/", ValueError), ("file:///etc/passwd", ValueError), ("https://usuario:clave@ejemplo.com/", ValueError)):
            with self.assertRaises(error, msg=url):
                self.leer(url)

    def test_una_redireccion_a_una_direccion_interna_se_corta(self):
        def manejar(req):
            if req.url.path == "/robots.txt":
                return httpx.Response(404)
            return httpx.Response(302, headers={"location": "http://interno/admin"})
        resolver = lambda host, puerto: ["10.0.0.5"] if host == "interno" else [self.PUBLICA]
        with mock.patch.object(web, "_resolver", resolver), con_transporte(manejar):
            with self.assertRaisesRegex(PermissionError, "no es una página pública"):
                ejecutar(web.leer("https://ejemplo.com/ir"))

    def test_demasiadas_redirecciones(self):
        def manejar(req):
            return httpx.Response(404) if req.url.path == "/robots.txt" else httpx.Response(302, headers={"location": "https://ejemplo.com/otra"})
        with self.assertRaisesRegex(RuntimeError, "Demasiadas redirecciones"):
            self.leer("https://ejemplo.com/a", manejar)

    def test_solo_texto_y_con_tope_de_tamano(self):
        pdf = lambda req: httpx.Response(404) if req.url.path == "/robots.txt" else httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF")
        with self.assertRaisesRegex(ValueError, "páginas de texto"):
            self.leer("https://ejemplo.com/x.pdf", pdf)
        grande = lambda req: httpx.Response(404) if req.url.path == "/robots.txt" else httpx.Response(
            200, headers={"content-type": "text/plain"}, content=b"a" * (web.MAX_BYTES + 5000))
        r = self.leer("https://ejemplo.com/enorme", grande, max_caracteres=20000)
        self.assertLessEqual(len(r["texto"]), 20000)
        self.assertTrue(r["recortado"])

    def test_se_respeta_robots_txt(self):
        def manejar(req):
            if req.url.path == "/robots.txt":
                return httpx.Response(200, headers={"content-type": "text/plain"}, text="User-agent: *\nDisallow: /privado")
            return httpx.Response(200, headers={"content-type": "text/plain"}, text="hola")
        with self.assertRaisesRegex(PermissionError, "robots.txt"):
            self.leer("https://ejemplo.com/privado/x", manejar)
        self.assertEqual(self.leer("https://ejemplo.com/publico", manejar)["texto"], "hola")

    def test_error_http_de_la_pagina(self):
        with self.assertRaisesRegex(RuntimeError, "error 500"):
            self.leer("https://ejemplo.com/x", lambda req: httpx.Response(404) if req.url.path == "/robots.txt" else httpx.Response(500))


PAGINA = """<html><head><title>Novedades</title><style>p{color:red}</style></head>
<body><script>alert('x')</script><nav>Menú</nav><h1>Titular</h1><p>Texto útil de la noticia</p><form>no</form></body></html>"""


class TestFechaYAgente(unittest.TestCase):
    def test_fecha_y_hora_en_horario_de_madrid_con_el_dia_de_la_semana(self):
        t = datetime(2026, 10, 25, 17, 41, tzinfo=timezone.utc)      # el 25 de octubre de 2026 acaba el horario de verano
        self.assertEqual(ahora_texto(t), "domingo 25 de octubre de 2026, 18:41 (hora de Europe/Madrid)")
        self.assertEqual(ahora_texto(datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc)), "miércoles 1 de julio de 2026, 12:00 (hora de Europe/Madrid)")

    def test_los_agentes_reciben_la_fecha_y_hora(self):
        r = registro()
        texto = sistema_agente(r.fichas["director-general"], {})
        self.assertIn("Fecha y hora actuales:", texto)
        self.assertRegex(texto, r"\d{4}, \d{2}:\d{2}")

    def test_el_asistente_general_existe_y_solo_usa_datos_publicos(self):
        from cerebro.herramientas import base
        r = registro()
        f = r.fichas["asistente-general"]
        self.assertEqual((f.departamento, f.sensibilidad, f.aprobacion, "web" in f.herramientas), ("direccion", "baja", "libre", True))
        self.assertIn("web", sistema_agente(f, base.disponibles_para(f)))
        self.assertIn("web", base._REGISTRO)

    def test_el_director_general_manda_las_dudas_generales_a_direccion(self):
        r = registro()
        texto = sistema_director_general(r.departamentos)
        self.assertIn("dudas generales", texto)
        self.assertIn("Asistente general", texto)
        self.assertIn("aunque trate del sector", texto)

    def test_el_director_de_departamento_manda_lo_de_internet_a_quien_puede_buscar(self):
        r = registro()
        direccion = [f for f in r.fichas.values() if f.departamento == "direccion"]
        self.assertIn("elige asistente-general", sistema_director_departamento("Dirección", direccion))
        finanzas = [f for f in r.fichas.values() if f.departamento == "finanzas"]
        self.assertNotIn("buscar en internet", sistema_director_departamento("Finanzas", finanzas))

    def test_las_fichas_con_datos_sensibles_no_pueden_usar_internet(self):
        r = registro()
        for f in r.fichas.values():
            if "web" in f.herramientas:
                self.assertEqual(f.sensibilidad, "baja", f.id)


if __name__ == "__main__":
    unittest.main()
