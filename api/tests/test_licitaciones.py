"""Herramienta «licitaciones»: consulta del motor (API interna) con un servidor simulado."""
import asyncio
import os
import unittest
from unittest import mock

import _sin_servicios  # noqa: F401
import httpx

from cerebro.herramientas import base, licitaciones
from cerebro.herramientas.esquemas import ArgumentosNoValidos, validar

HTTPX_REAL = hasattr(httpx, "MockTransport")
ID = "0b1f7a3e-1111-4222-8333-444444444444"
TOKEN = "t" * 40


def ejecutar(coro):
    return asyncio.run(coro)


def con_motor(manejar):
    """Hace que los httpx.AsyncClient de la herramienta hablen con un motor simulado."""
    real = httpx.AsyncClient

    def fabrica(*a, **k):
        return real(*a, **{**k, "transport": httpx.MockTransport(manejar)})
    return mock.patch.object(licitaciones.httpx, "AsyncClient", fabrica)


def entorno(**extra):
    return mock.patch.dict(os.environ, {"LICITACIONES_API_TOKEN": TOKEN, "LICITACIONES_API_URL": "http://motor:8080", **extra})


PAGINA = {
    "items": [{"id": ID, "titulo": "Mantenimiento de  videovigilancia\n municipal", "expediente": "EXP-1", "estado": "abierta",
               "comprador": {"id": "x", "nombre": "Ayuntamiento de Girona", "nif": "P1708500E"},
               "importe": {"valor": "100000.50", "moneda": "EUR", "impuestos": "sin_iva", "significado": "valor_estimado"},
               "plazo_presentacion": "2026-11-10T10:00:00Z", "actualizada_en": "2026-10-27T10:00:00Z", "cpv": ["35125300"], "nuts": ["ES512"],
               "url_origen": "https://contrataciondelestado.es/x", "campo_inesperado": "no debe pasar"}],
    "siguiente_cursor": "CURSOR.FIRMA", "total": {"valor": 42, "relacion": "eq"},
}


@unittest.skipUnless(HTTPX_REAL, "requiere httpx real (se ejecuta en el contenedor)")
class TestBuscar(unittest.TestCase):
    def buscar(self, respuesta=None, codigo=200, **kw):
        vistas = []

        def manejar(req):
            vistas.append(req)
            return httpx.Response(codigo, json=respuesta if respuesta is not None else PAGINA)
        with entorno(), con_motor(manejar):
            return ejecutar(licitaciones.buscar(**kw)), vistas

    def test_traduce_los_argumentos_y_manda_la_credencial(self):
        r, vistas = self.buscar(texto=" videovigilancia ", cpv=["35125"], nuts=["es512"], estado=["abierta"], importe_min=1000, importe_max=250000.5,
                                orden="plazo", limite=5)
        req = vistas[0]
        self.assertEqual((req.url.host, req.url.path), ("motor", "/api/v1/tenders"))
        self.assertEqual(req.headers["Authorization"], "Bearer " + TOKEN)
        q = req.url.params
        self.assertEqual((q["q"], q["cpv"], q["nuts"], q["estado"], q["importe_min"], q["importe_max"], q["orden"], q["limit"]),
                         ("videovigilancia", "35125", "ES512", "abierta", "1000.00", "250000.50", "plazo", "5"))
        self.assertEqual(r["total"], 42)

    def test_recorta_el_resultado_y_no_deja_pasar_campos_inesperados(self):
        r, _ = self.buscar()
        x = r["resultados"][0]
        self.assertEqual(x["titulo"], "Mantenimiento de videovigilancia municipal")
        self.assertEqual(x["importe"], "100000.50 EUR (sin iva; valor estimado)")
        self.assertEqual(x["comprador"], "Ayuntamiento de Girona")
        self.assertNotIn("campo_inesperado", x)
        self.assertNotIn("nif", str(x))

    def test_avisa_de_que_hay_mas_y_como_pedirlo(self):
        r, vistas = self.buscar(cursor="C")
        self.assertEqual(r["siguiente_cursor"], "CURSOR.FIRMA")
        self.assertIn("cursor", r["nota"])
        self.assertEqual(vistas[0].url.params["cursor"], "C")

    def test_el_limite_se_acota(self):
        _, v = self.buscar(limite=1000)
        self.assertEqual(v[0].url.params["limit"], "25")
        _, v = self.buscar(limite=0)
        self.assertEqual(v[0].url.params["limit"], "1")

    def test_total_aproximado(self):
        r, _ = self.buscar(respuesta={**PAGINA, "siguiente_cursor": None, "total": {"valor": 10000, "relacion": "gte"}})
        self.assertTrue(r["total_aproximado"])
        self.assertNotIn("siguiente_cursor", r)

    def test_rechaza_argumentos_malos_antes_de_llamar(self):
        for kw in ({"estado": ["rara"]}, {"orden": "encaje"}, {"importe_min": -1}, {"importe_max": True}, {"plazo_desde": "mañana"}):
            vistas = []
            with entorno(), con_motor(lambda r: vistas.append(r) or httpx.Response(200, json=PAGINA)):
                with self.assertRaises(ValueError, msg=str(kw)):
                    ejecutar(licitaciones.buscar(**kw))
            self.assertEqual(vistas, [], f"{kw} no debe llegar al motor")


@unittest.skipUnless(HTTPX_REAL, "requiere httpx real (se ejecuta en el contenedor)")
class TestErrores(unittest.TestCase):
    def llamar(self, estado, cuerpo=None, **extra):
        with entorno(**extra), con_motor(lambda r: httpx.Response(estado, json=cuerpo or {})):
            return ejecutar(licitaciones.buscar(texto="x" * 3))

    def test_traduce_los_errores_del_motor_a_mensajes_para_el_agente(self):
        with self.assertRaises(ValueError) as c:
            self.llamar(400, {"detail": "Algún parámetro no es válido.", "errores": [{"campo": "cpv", "mensaje": "2 a 8 cifras"}]})
        self.assertIn("cpv: 2 a 8 cifras", str(c.exception))
        with self.assertRaises(licitaciones.MotorNoDisponible) as c:
            self.llamar(401, {"detail": "Falta el token"})
        self.assertIn("credencial", str(c.exception))
        with self.assertRaises(licitaciones.MotorNoDisponible):
            self.llamar(500, {"detail": "boom con 10.0.0.5"})

    def test_ningun_error_enseña_direcciones_internas_ni_la_credencial(self):
        for estado in (401, 500):
            try:
                self.llamar(estado, {"detail": "fallo en 10.0.0.5:5432 con " + TOKEN})
            except Exception as e:  # noqa: BLE001
                self.assertNotIn("10.0.0.5", str(e))
                self.assertNotIn(TOKEN, str(e))

    def test_sin_credencial_ni_se_llama(self):
        vistas = []
        with mock.patch.dict(os.environ, {"LICITACIONES_API_TOKEN": ""}), con_motor(lambda r: vistas.append(r) or httpx.Response(200, json={})):
            with self.assertRaises(licitaciones.MotorNoDisponible):
                ejecutar(licitaciones.buscar())
        self.assertEqual(vistas, [])

    def test_un_reintento_si_no_se_pudo_conectar(self):
        llamadas = []

        def manejar(req):
            llamadas.append(req)
            if len(llamadas) == 1:
                raise httpx.ConnectError("sin conexión")
            return httpx.Response(200, json=PAGINA)
        with entorno(), con_motor(manejar):
            r = ejecutar(licitaciones.buscar())
        self.assertEqual((len(llamadas), r["total"]), (2, 42))

    def test_si_sigue_sin_conectar_avisa_sin_dar_la_direccion(self):
        def manejar(req):
            raise httpx.ConnectError("no route to motor:8080")
        with entorno(), con_motor(manejar):
            with self.assertRaises(licitaciones.MotorNoDisponible) as c:
                ejecutar(licitaciones.buscar())
        self.assertNotIn("motor:8080", str(c.exception))

    def test_un_tiempo_de_espera_no_se_reintenta(self):
        llamadas = []

        def manejar(req):
            llamadas.append(req)
            raise httpx.ReadTimeout("lento")
        with entorno(), con_motor(manejar):
            with self.assertRaises(licitaciones.MotorNoDisponible):
                ejecutar(licitaciones.buscar())
        self.assertEqual(len(llamadas), 1)


@unittest.skipUnless(HTTPX_REAL, "requiere httpx real (se ejecuta en el contenedor)")
class TestFichaNovedadesYEstado(unittest.TestCase):
    def test_ficha_valida_el_id_y_no_deja_meter_rutas(self):
        vistas = []
        for malo in ("../ops/status", ID + "/history", "x", "", ID + "?a=b", None):
            with entorno(), con_motor(lambda r: vistas.append(r) or httpx.Response(200, json={})):
                with self.assertRaises(ValueError):
                    ejecutar(licitaciones.ficha(malo))
        self.assertEqual(vistas, [])

    def test_ficha_resumida(self):
        cuerpo = {**PAGINA["items"][0], "estado_origen": "PUB", "procedimiento": "abierto",
                  "importes": [{"valor": "1", "moneda": "EUR", "impuestos": "sin_iva", "significado": "valor_estimado"}],
                  "lotes": [{"numero": "1", "objeto": "Lote único", "cpv": ["35125300"], "importes": []}],
                  "criterios": [{"tipo": "otro", "descripcion": "Precio", "peso": 60.0}],
                  "documentos": [{"nombre": "Pliego", "tipo": "pliego_tecnico", "url_origen": "https://x.test/p.pdf", "descargado": False}],
                  "adjudicaciones": [{"lote": "1", "resultado": "adjudicado", "adjudicatario": {"nombre": "Constructora SA", "nif": "A12345678"},
                                      "importes": [], "baja": 0.1, "ofertas_recibidas": 4, "fecha_adjudicacion": "2026-10-20"}],
                  "evidencia": {"fuente": "placsp", "url_origen": "https://x.test/e", "sha256": "ab" * 32, "capturado_en": "2026-10-27T10:00:00Z", "clave_raw": "interna/k"}}
        vistas = []
        with entorno(), con_motor(lambda r: vistas.append(r) or httpx.Response(200, json=cuerpo)):
            r = ejecutar(licitaciones.ficha(ID.upper()))
        self.assertEqual(vistas[0].url.path, f"/api/v1/tenders/{ID}")
        self.assertEqual((r["lotes"][0]["objeto"], r["criterios"][0]["peso"], r["adjudicaciones"][0]["adjudicatario"]), ("Lote único", 60.0, "Constructora SA"))
        self.assertEqual(r["evidencia"]["sha256"], "ab" * 32)
        self.assertNotIn("clave_raw", str(r))                    # la clave interna del almacén no sale hacia el modelo

    def test_ficha_inexistente(self):
        with entorno(), con_motor(lambda r: httpx.Response(404, json={"detail": "x"})):
            with self.assertRaises(LookupError):
                ejecutar(licitaciones.ficha(ID))

    def test_novedades_desde(self):
        vistas = []
        with entorno(), con_motor(lambda r: vistas.append(r) or httpx.Response(200, json=PAGINA)):
            ejecutar(licitaciones.novedades_desde("2026-10-27T00:00:00Z", cpv=["72"], limite=3))
        q = vistas[0].url.params
        self.assertEqual((q["actualizada_desde"], q["orden"], q["cpv"], q["limit"]), ("2026-10-27T00:00:00Z", "actualizacion", "72", "3"))
        with entorno(), con_motor(lambda r: httpx.Response(200, json=PAGINA)):
            with self.assertRaises(ValueError):
                ejecutar(licitaciones.novedades_desde("ayer"))

    def test_estado_motor_resumido(self):
        cuerpo = {"estado": "degradado", "calculado_en": "2026-10-27T10:00:00Z", "motivos": [{"mensaje": "La última ingesta supera el objetivo de frescura (2 horas)."}],
                  "fuentes": [{"fuente": "placsp", "estado": "degradado", "antiguedad_s": 9000, "expedientes": 149}], "componentes": []}
        with entorno(), con_motor(lambda r: httpx.Response(200, json=cuerpo)):
            r = ejecutar(licitaciones.estado_motor())
        self.assertEqual((r["estado"], r["fuentes"][0]["horas_desde_la_ultima_ingesta"]), ("degradado", 2.5))
        self.assertIn("desactualizadas", r["aviso"])


ADJUDICACIONES = {
    "items": [{"id": ID, "licitacion_id": ID, "expediente": "EXP-1", "titulo": "Cámaras\n de   vigilancia", "lote": "1", "resultado": "adjudicado",
               "comprador": {"id": "x", "nombre": "Ayuntamiento de Girona", "nif": "P1708500E"},
               "adjudicatario": {"id": "y", "nombre": "Uno Sistemas SL", "nif": "B11111111", "dato_inesperado": "no pasa"},
               "importes": [{"valor": "90000.00", "moneda": "EUR", "impuestos": "sin_iva", "significado": "adjudicado"}], "baja": 0.1,
               "ofertas_recibidas": 4, "baja_anormal": False, "fecha_adjudicacion": "2026-09-01", "cpv": ["35125300"],
               "evidencia": {"url_origen": "https://contrataciondelestado.es/x", "sha256": "no pasa"}}],
    "siguiente_cursor": "C.F", "total": {"valor": 12000, "relacion": "gte"},
}
COMPETIDORES = {
    "items": [{"organizacion": {"id": "y", "nombre": "Uno Sistemas SL", "nif": "B11111111"}, "contratos_ganados": 3,
               "importe_adjudicado": {"valor": "600000.00", "moneda": "EUR", "impuestos": "sin_iva", "significado": "adjudicado"}, "cuota": 0.6667,
               "baja_media": 0.2, "baja_p50": 0.2, "tendencia": "sube", "ultima_adjudicacion": "2026-09-01"}],
    "siguiente_cursor": None, "total": {"valor": 1, "relacion": "eq"}, "muestra": {"adjudicaciones": 6, "desde": "2025-02-01", "hasta": "2026-09-01"},
}


@unittest.skipUnless(HTTPX_REAL, "requiere httpx real (se ejecuta en el contenedor)")
class TestAdjudicacionesYCompetidores(unittest.TestCase):
    def llamar(self, operacion, cuerpo, **kw):
        vistas = []

        def manejar(req):
            vistas.append(req)
            return httpx.Response(200, json=cuerpo)
        with entorno(), con_motor(manejar):
            return ejecutar(operacion(**kw)), vistas

    def test_adjudicaciones_traduce_los_argumentos_y_resume(self):
        r, vistas = self.llamar(licitaciones.adjudicaciones, ADJUDICACIONES, texto=" cámaras ", cpv=["35125"], nuts=["es512"], adjudicatario_nif="b11111111",
                                comprador_nif="P1708500E", resultado="adjudicado", importe_min=1000, desde="2025-01-01", hasta="2026-10-27", orden="baja", limite=500)
        req = vistas[0]
        self.assertEqual((req.url.host, req.url.path), ("motor", "/api/v1/awards"))
        q = req.url.params
        self.assertEqual((q["q"], q["cpv"], q["nuts"], q["adjudicatario"], q["comprador"], q["resultado"], q["importe_min"]),
                         ("cámaras", "35125", "ES512", "nif:B11111111", "nif:P1708500E", "adjudicado", "1000.00"))
        self.assertEqual((q["adjudicada_desde"], q["adjudicada_hasta"], q["orden"], q["limit"]), ("2025-01-01", "2026-10-27", "baja", "25"))
        self.assertEqual(req.headers["authorization"], f"Bearer {TOKEN}")
        a = r["adjudicaciones"][0]
        self.assertEqual((a["titulo"], a["adjudicatario"], a["baja"], a["fecha_adjudicacion"]), ("Cámaras de vigilancia", {"nombre": "Uno Sistemas SL", "nif": "B11111111"}, 0.1, "2026-09-01"))
        self.assertEqual(a["importes"], ["90000.00 EUR (sin iva; adjudicado)"])
        self.assertNotIn("sha256", str(r))
        self.assertNotIn("dato_inesperado", str(r))
        self.assertTrue(r["total_aproximado"])
        self.assertEqual(r["siguiente_cursor"], "C.F")

    def test_adjudicaciones_valida_antes_de_llamar(self):
        for kw in ({"desde": "ayer"}, {"desde": "2026-13-45"}, {"adjudicatario_nif": "B1"}, {"resultado": "ganado"}, {"orden": "plazo"}, {"importe_max": -1}):
            with self.subTest(kw), entorno(), con_motor(lambda r: self.fail("no debe llamar al motor")):
                with self.assertRaises(ValueError):
                    ejecutar(licitaciones.adjudicaciones(**kw))

    def test_competidores_exige_acotar_el_mercado(self):
        with entorno(), con_motor(lambda r: self.fail("no debe llamar al motor")):
            with self.assertRaises(ValueError):
                ejecutar(licitaciones.competidores(desde="2025-01-01"))

    def test_competidores_resume_y_avisa_de_la_muestra(self):
        r, vistas = self.llamar(licitaciones.competidores, COMPETIDORES, cpv=["35125"], desde="2025-01-01", orden="contratos", limite=3)
        q = vistas[0].url.params
        self.assertEqual((vistas[0].url.path, q["cpv"], q["desde"], q["orden"], q["limit"]), ("/api/v1/competitors", "35125", "2025-01-01", "contratos", "3"))
        c = r["competidores"][0]
        self.assertEqual((c["empresa"]["nombre"], c["contratos_ganados"], c["cuota"], c["baja_mediana"], c["tendencia"]), ("Uno Sistemas SL", 3, 0.6667, 0.2, "sube"))
        self.assertEqual(r["muestra"], {"adjudicaciones": 6, "desde": "2025-02-01", "hasta": "2026-09-01"})
        self.assertIn("muestra", r["aviso"])
        self.assertNotIn("siguiente_cursor", r)


class TestRegistro(unittest.TestCase):
    def test_esta_registrada_y_es_de_solo_lectura(self):
        h = base._REGISTRO["licitaciones"]
        self.assertEqual(set(h.operaciones), {"buscar", "ficha", "novedades_desde", "adjudicaciones", "competidores", "estado_motor"})
        self.assertEqual(h.externas, frozenset())             # ninguna operación tiene impacto fuera: no necesita aprobación
        self.assertEqual(set(h.ayuda), set(h.operaciones))

    def test_los_ejemplos_del_prompt_son_validos(self):
        h = base._REGISTRO["licitaciones"]
        for op, args in h.ejemplos.items():
            validar(h, op, args)

    def test_el_modelo_no_puede_inventar_argumentos(self):
        h = base._REGISTRO["licitaciones"]
        with self.assertRaises(ArgumentosNoValidos):
            validar(h, "buscar", {"consulta": "x"})
        with self.assertRaises(ArgumentosNoValidos):
            validar(h, "ficha", {})


if __name__ == "__main__":
    unittest.main()
