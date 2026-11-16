"""Cotizaciones a proveedores: el correo lleva SOLO referencia, cantidad y plazo; dos modos; la respuesta alimenta el coste de la partida; ERP como borrador."""
import asyncio
import os
import re
import time
import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import _sin_servicios  # noqa: F401

try:
    import psycopg

    from cerebro import cotizaciones as C
    from cerebro import precios
except ImportError as e:      # pragma: no cover
    raise unittest.SkipTest(str(e))

URL = os.environ.get("CEREBRO_TEST_PG")
ESQUEMA = Path(__file__).resolve().parents[2] / "db" / "esquema.sql"
HOY = date(2026, 11, 16)


def ejecutar(c):
    return asyncio.run(c)


class TestRedaccion(unittest.TestCase):
    def test_el_correo_lleva_solo_referencia_cantidad_y_plazo(self):
        asunto, cuerpo = C.redactar("DS-2CD2143G2-I", 12, "dias", "15")
        self.assertEqual(asunto, "Solicitud de cotización · DS-2CD2143G2-I")
        self.assertIn("Referencia: DS-2CD2143G2-I", cuerpo)
        self.assertIn("Cantidad: 12 uds.", cuerpo)
        self.assertIn("Plazo de entrega requerido: 15 días", cuerpo)
        for prohibido in ("licitaci", "cliente", "precio de venta", "margen", "ayuntamiento", "{", "}"):
            self.assertNotIn(prohibido, cuerpo.lower(), prohibido)
        self.assertIn("precio unitario", cuerpo)                         # lo único que se les pide

    def test_plazo_por_fecha_y_un_dia(self):
        self.assertIn("antes del 10/12/2026", C.redactar("REF-1", 1, "fecha", "2026-12-10")[1])
        self.assertIn("1 día\n", C.redactar("REF-1", 1, "dias", "1")[1])

    def test_validaciones(self):
        for ref in ("", "A", "x" * 81, "REF\nBcc: x@y.com", "<script>", None):
            with self.assertRaises(C.ErrorCotizacion, msg=str(ref)):
                C.validar_referencia(ref)
        for cant in (0, -1, "x", 2.5, True, 100001, None):
            with self.assertRaises(C.ErrorCotizacion, msg=str(cant)):
                C.validar_cantidad(cant)
        self.assertEqual(C.validar_cantidad("12"), 12)
        for tipo, valor in (("dias", "0"), ("dias", "366"), ("dias", "x"), ("fecha", "2026-11-15"), ("fecha", "mañana"), ("fecha", "2028-01-01"), ("meses", "3")):
            with self.assertRaises(C.ErrorCotizacion, msg=f"{tipo} {valor}"):
                C.validar_plazo(tipo, valor, hoy=HOY)
        self.assertEqual(C.validar_plazo("fecha", "2026-11-16", hoy=HOY), ("fecha", "2026-11-16"))

    def test_el_correo_del_proveedor_no_puede_ser_de_la_propia_empresa(self):
        self.assertEqual(C.validar_email(" ventas@distribuidor.com "), "ventas@distribuidor.com")
        for malo in ("", "sin-arroba", "a@b", "albert@101.cat"):
            with self.assertRaises(C.ErrorCotizacion, msg=malo):
                C.validar_email(malo)

    def test_respuesta_validada(self):
        r = C.validar_respuesta({"precio": "1234.5", "moneda": "usd", "plazo_dias": "10", "validez_hasta": "2026-12-31", "nota": " hola   mundo "}, HOY)
        self.assertEqual(r, {"precio": "1234.5", "moneda": "USD", "plazo_dias": 10, "validez_hasta": "2026-12-31", "nota": "hola mundo"})
        self.assertEqual(C.validar_respuesta({"precio": "99,90"}, HOY)["precio"], "99.90")
        for malo in ({"precio": "0"}, {"precio": "-3"}, {"precio": "abc"}, {"precio": "1.00001"}, {"precio": "5", "moneda": "JPY"}, {"precio": "5", "plazo_dias": "x"},
                     {"precio": "5", "plazo_dias": 9999}, {"precio": "5", "validez_hasta": "2026-01-01"}, {"precio": "5", "validez_hasta": "pronto"}, {}):
            with self.assertRaises(C.ErrorCotizacion, msg=str(malo)):
                C.validar_respuesta(malo, HOY)

    def test_sin_respuesta_a_los_n_dias(self):
        ahora = datetime(2026, 11, 16, tzinfo=timezone.utc)
        c = {"estado": "enviada", "enviado_en": ahora - timedelta(days=4)}
        self.assertTrue(C.sin_respuesta(c, ahora, {"dias_sin_respuesta": 3}))
        self.assertFalse(C.sin_respuesta({**c, "enviado_en": ahora - timedelta(days=2)}, ahora, {"dias_sin_respuesta": 3}))
        self.assertFalse(C.sin_respuesta({**c, "estado": "respondida"}, ahora, {"dias_sin_respuesta": 3}))


CFG_PRECIOS = {"canales": {"distribuidor": {"moneda": "EUR", "logistica_pct": Decimal("0")}}, "cambio_a_eur": {"USD": Decimal("0.9")}, "cambio_info": {}, "cambio_online": {"activo": False},
               "provisional": [], "margen": {"por_defecto": Decimal("0.5"), "familias": {}, "minimo": Decimal("0.1")}, "redondeo": {"modo": "centimo", "terminacion": Decimal("0.90")}}


class TestCoste(unittest.TestCase):
    def cot(self, **kw):
        return {"id": 5, "estado": "respondida", "referencia": "DS-2CD2143G2-I", "marca": "Hikvision", "proveedor": "A-Secur", "partida": None,
                "respuesta": {"precio": "100", "moneda": "EUR", "plazo_dias": 7, "validez_hasta": "2026-12-31"}, **kw}

    def test_emparejar_por_partida_o_por_referencia_en_el_texto(self):
        a, b = self.cot(), self.cot(id=9, referencia="OTRA-REF-1")
        self.assertEqual(C.emparejar("Cámara domo DS-2CD2143G2-I 4MP", 1, [a, b])["id"], 5)
        self.assertIsNone(C.emparejar("Grabador NVR", 1, [a, b]))
        self.assertEqual(C.emparejar("Lo que sea", 7, [{**b, "partida": 7}, a])["id"], 9)                    # la ligada a la partida manda
        self.assertIsNone(C.emparejar("DS-2CD2143G2-I", 1, [self.cot(estado="enviada")]))                     # solo las respondidas
        self.assertEqual(C.emparejar("DS-2CD2143G2-I", 1, [a, self.cot(id=8)])["id"], 8)       # a igualdad, la de id más alto gana (8 > 5)

    def test_coste_en_euros_con_cambio_y_caducidad(self):
        q = C.coste_de_cotizacion(self.cot(respuesta={"precio": "100", "moneda": "USD"}), CFG_PRECIOS, HOY)
        self.assertEqual(q["coste_unit_eur"], Decimal("90.00"))
        self.assertIn("cotización de proveedor", q["avisos"])
        self.assertIsNone(C.coste_de_cotizacion(self.cot(respuesta={"precio": "100", "moneda": "EUR", "validez_hasta": "2026-11-01"}), CFG_PRECIOS, HOY))    # caducada
        self.assertIsNone(C.coste_de_cotizacion(self.cot(estado="enviada"), CFG_PRECIOS, HOY))

    def test_partidas_usan_la_cotizacion_solo_si_no_hay_tarifa(self):
        from cerebro.licitaciones import partidas as P
        partidas = [{"id": 1, "producto": "Cámara DS-2CD2143G2-I", "parametros": [], "cantidad": 2, "origen": "equivalencia", "excluida": False}]
        sin = P.calcular_filas(partidas, {}, CFG_PRECIOS)
        self.assertIsNone(sin[0]["coste_unit_eur"])
        con = P.calcular_filas(partidas, {}, CFG_PRECIOS, [self.cot()])
        self.assertEqual((con[0]["coste_unit_eur"], con[0]["subtotal_eur"], con[0]["origen_coste"], con[0]["proveedor"]), ("100.00", "200.00", "cotizacion", "A-Secur"))
        self.assertEqual(P.totales(con)["completo"], True)


class TestDoc(unittest.TestCase):
    def test_rfq_lleva_lo_mismo_que_el_correo(self):
        c = {"cuerpo": "TEXTO DEL CORREO", "cantidad": 3, "plazo_tipo": "dias", "plazo_valor": "10"}
        d = C.doc_rfq(c, "ITEM-1", "A-Secur", HOY)
        self.assertEqual(d["items"], [{"item_code": "ITEM-1", "qty": 3, "schedule_date": "2026-11-26"}])
        self.assertEqual(d["suppliers"], [{"supplier": "A-Secur"}])
        self.assertEqual(d["message_for_supplier"], "TEXTO DEL CORREO")
        self.assertEqual(C.doc_rfq({**c, "plazo_tipo": "fecha", "plazo_valor": "2026-12-10"}, "I", "P", HOY)["items"][0]["schedule_date"], "2026-12-10")


@unittest.skipUnless(URL, "sin CEREBRO_TEST_PG")
class TestEnBase(unittest.TestCase):
    def setUp(self):
        self.schema = f"t_cot_{time.time_ns()}"
        t = ESQUEMA.read_text(encoding="utf-8")
        tablas = t[t.index("CREATE TABLE IF NOT EXISTS proveedores_contactos ("):]
        tablas = tablas[:tablas.index("CREATE INDEX IF NOT EXISTS cotizaciones_estado_idx")]
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"CREATE SCHEMA {self.schema}")
            c.execute(f"SET search_path = {self.schema}")
            c.execute(tablas)
        sep = "&" if "?" in URL else "?"
        self.parche = mock.patch.object(C, "ajustes", SimpleNamespace(database_url=f"{URL}{sep}options=-csearch_path%3D{self.schema}", dir_config=C.ajustes.dir_config))
        self.parche.start()
        ejecutar(C.guardar_contacto("A-Secur", "ventas@a-secur.com", "Marta", "", "albert"))

    def tearDown(self):
        self.parche.stop()
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"DROP SCHEMA {self.schema} CASCADE")

    def nueva(self, **kw):
        datos = {"referencia": "DS-2CD2143G2-I", "cantidad": 12, "plazo_tipo": "dias", "plazo_valor": 15, "proveedor": "A-Secur", "modo": "manual", "marca": "Hikvision", **kw}
        return ejecutar(C.crear(datos, "ana", hoy=HOY))

    def test_se_crea_en_borrador_con_el_correo_ya_redactado_y_el_contacto_del_proveedor(self):
        c = self.nueva(licitacion="ab54b97a-5012-4a4c-92dc-b4d99908f0fd")
        self.assertEqual((c["estado"], c["email"], c["modo"]), ("borrador", "ventas@a-secur.com", "manual"))
        self.assertIn("Cantidad: 12 uds.", c["cuerpo"])
        self.assertNotIn("ab54b97a", c["cuerpo"])                                   # la licitación NUNCA sale en el correo
        self.assertNotIn("Hikvision", c["cuerpo"])                                  # ni la marca

    def test_errores_al_crear(self):
        for kw, texto in (({"modo": "otro"}, "Elige el modo"), ({"proveedor": "Sin Contacto SL"}, "No hay correo"), ({"proveedor": ""}, "Elige el proveedor"), ({"licitacion": "no-es-uuid"}, "licitación"),
                          ({"email": "x@101.cat"}, "propia empresa"), ({"plazo_valor": 0}, "entre 1")):
            with self.assertRaisesRegex(C.ErrorCotizacion, texto):
                self.nueva(**kw)

    def test_modo_manual_se_marca_enviada_y_no_se_envia_por_el_sistema(self):
        c = self.nueva()
        with self.assertRaisesRegex(C.ErrorCotizacion, "modo «manual»"):
            ejecutar(C.enviar(c["id"], "albert"))
        e = ejecutar(C.marcar_enviada(c["id"], "ana"))
        self.assertEqual((e["estado"], e["enviado_por"]), ("enviada", "ana"))
        with self.assertRaisesRegex(C.ErrorCotizacion, "no se puede"):
            ejecutar(C.marcar_enviada(c["id"], "ana"))

    def test_modo_enviar_manda_el_correo_redactado_con_el_buzon_del_departamento(self):
        c = self.nueva(modo="enviar")
        enviados = []

        async def envio(buzon, para, asunto, cuerpo, *a):
            enviados.append((buzon, para, asunto, cuerpo))
        with self.assertRaisesRegex(C.ErrorCotizacion, "modo «enviar»"):
            ejecutar(C.marcar_enviada(c["id"], "ana"))
        e = ejecutar(C.enviar(c["id"], "albert", envio))
        self.assertEqual(e["estado"], "enviada")
        self.assertEqual(enviados, [("operaciones", ["ventas@a-secur.com"], c["asunto"], c["cuerpo"])])             # exactamente el redactado
        with self.assertRaisesRegex(C.ErrorCotizacion, "ya no se puede enviar"):
            ejecutar(C.enviar(c["id"], "albert", envio))
        self.assertEqual(len(enviados), 1)

    def test_si_el_envio_falla_sigue_en_borrador_y_se_puede_reintentar(self):
        c = self.nueva(modo="enviar")

        async def cae(*a):
            raise OSError("smtp caído")
        with self.assertRaisesRegex(C.ErrorCotizacion, "Sigue en borrador"):
            ejecutar(C.enviar(c["id"], "albert", cae))
        self.assertEqual(ejecutar(C.leer(c["id"]))["estado"], "borrador")

    def test_respuesta_cancelar_y_estados(self):
        c = self.nueva()
        r = ejecutar(C.registrar_respuesta(c["id"], {"precio": "55,5", "plazo_dias": 7}, "ana", HOY))
        self.assertEqual((r["estado"], r["respuesta"]["precio"], r["respuesta"]["por"]), ("respondida", "55.5", "ana"))
        self.assertEqual(ejecutar(C.registrar_respuesta(c["id"], {"precio": "50"}, "ana", HOY))["respuesta"]["precio"], "50")          # se puede corregir
        with self.assertRaisesRegex(C.ErrorCotizacion, "no se puede cancelar"):
            ejecutar(C.cancelar(c["id"], "ana"))
        d = self.nueva(referencia="OTRA-REF")
        self.assertEqual(ejecutar(C.cancelar(d["id"], "ana"))["estado"], "cancelada")
        with self.assertRaises(C.ErrorCotizacion):
            ejecutar(C.registrar_respuesta(d["id"], {"precio": "5"}, "ana", HOY))                                                       # cancelada: ya no
        self.assertEqual([x["id"] for x in ejecutar(C.listar("respondida"))], [c["id"]])
        self.assertEqual({x["id"] for x in ejecutar(C.listar())}, {c["id"], d["id"]})
        with self.assertRaises(C.NoExiste):
            ejecutar(C.leer(99999))
        with self.assertRaises(C.ErrorCotizacion):
            ejecutar(C.listar("raro"))

    def test_las_respondidas_alimentan_el_coste(self):
        c = self.nueva()
        ejecutar(C.registrar_respuesta(c["id"], {"precio": "80"}, "ana", HOY))
        self.nueva(referencia="SIN-RESPUESTA-1")
        self.assertEqual([x["referencia"] for x in ejecutar(C.respondidas())], ["DS-2CD2143G2-I"])

    def test_erp_borrador_si_el_articulo_y_el_proveedor_existen(self):
        c = self.nueva()
        creados = []

        async def leer_ok(doctype, nombre, dep):
            return {"name": nombre}

        async def crear(doctype, datos, dep):
            creados.append((doctype, datos, dep))
            return {"name": "RFQ-0001"}
        r = ejecutar(C.enviar_al_erp(c["id"], "ITEM-1", "ana", crear, leer_ok, leer_ok))
        self.assertEqual((r["erp"]["estado"], r["erp"]["nombre"]), ("creada", "RFQ-0001"))
        self.assertEqual((creados[0][0], creados[0][2], creados[0][1]["items"][0]["item_code"]), ("Request for Quotation", "operaciones", "ITEM-1"))
        self.assertNotIn("licitaci", str(creados[0][1]).lower())

    def test_erp_dice_por_que_no_y_no_bloquea(self):
        c = self.nueva()

        async def no_existe(*a):
            raise LookupError("404")

        async def lee_ok(*a):
            return {}

        async def crear_mal(*a):
            raise RuntimeError("el ERP dice no")
        self.assertEqual(ejecutar(C.enviar_al_erp(c["id"], "", "ana", None, None, None))["erp"]["estado"], "sin_articulo")
        self.assertEqual(ejecutar(C.enviar_al_erp(c["id"], "ITEM-X", "ana", None, no_existe, lee_ok))["erp"]["estado"], "sin_articulo")
        self.assertEqual(ejecutar(C.enviar_al_erp(c["id"], "ITEM-X", "ana", None, lee_ok, no_existe))["erp"]["estado"], "sin_proveedor")
        r = ejecutar(C.enviar_al_erp(c["id"], "ITEM-X", "ana", crear_mal, lee_ok, lee_ok))
        self.assertEqual(r["erp"]["estado"], "error")
        self.assertEqual(r["estado"], "borrador")                                   # la cotización sigue válida

    def test_endpoints_permisos_y_confirmacion(self):
        from cerebro.api import main
        from cerebro.api.main import Usuario, usuario_actual
        from fastapi.testclient import TestClient
        cl = TestClient(main.app)
        body = {"referencia": "DS-2CD2143G2-I", "cantidad": 3, "plazo_tipo": "dias", "plazo_valor": 10, "proveedor": "A-Secur", "modo": "enviar"}
        enviados = []

        async def envio(*a):
            enviados.append(a)
        try:
            main.app.dependency_overrides[usuario_actual] = lambda: Usuario("pepe", {"usuario"}, {"finanzas"})
            self.assertEqual(cl.get("/cotizaciones").status_code, 403)
            self.assertEqual(cl.post("/cotizaciones", json=body).status_code, 403)
            main.app.dependency_overrides[usuario_actual] = lambda: Usuario("ana", {"usuario"}, {"licitaciones"})
            r = cl.post("/cotizaciones", json=body)
            self.assertEqual(r.status_code, 200, r.text)
            cid = r.json()["id"]
            self.assertEqual(cl.post(f"/cotizaciones/{cid}/enviar", json={"confirmo": True}).status_code, 403)          # enviar es de Dirección
            self.assertEqual(cl.post("/cotizaciones/contactos", json={"proveedor": "X SL", "email": "x@x.com"}).status_code, 403)
            main.app.dependency_overrides[usuario_actual] = lambda: Usuario("albert", {"direccion"}, set())
            self.assertEqual(cl.post(f"/cotizaciones/{cid}/enviar", json={}).status_code, 422)                          # sin confirmación expresa
            with mock.patch("cerebro.herramientas.correo.enviar", envio), mock.patch.object(main.constancia, "dejar_constancia", mock.AsyncMock(return_value="ok")) as cons:
                r = cl.post(f"/cotizaciones/{cid}/enviar", json={"confirmo": True})
                self.assertEqual((r.status_code, r.json()["estado"]), (200, "enviada"), r.text)
                self.assertIn("firmado en el panel por albert", cons.call_args.args[5])
            self.assertEqual(len(enviados), 1)
            self.assertEqual(cl.post(f"/cotizaciones/{cid}/enviar", json={"confirmo": True}).status_code, 422)         # ya enviada
            self.assertEqual(cl.get("/cotizaciones/99999").status_code, 404)
            self.assertEqual(cl.post(f"/cotizaciones/{cid}/respuesta", json={"precio": "12,5", "plazo_dias": 5}).status_code, 200)
            self.assertEqual(cl.get("/cotizaciones?estado=respondida").json()["cotizaciones"][0]["respuesta"]["precio"], "12.5")
            self.assertEqual(cl.post("/cotizaciones/contactos", json={"proveedor": "X SL", "email": "x@x.com"}).status_code, 200)
            self.assertEqual(cl.post("/cotizaciones/contactos", json={"proveedor": "Y SL", "email": "y@101.cat"}).status_code, 422)
        finally:
            main.app.dependency_overrides.clear()


if __name__ == "__main__":
    unittest.main()
