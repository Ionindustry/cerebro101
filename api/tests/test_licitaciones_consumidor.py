"""Consumidor de eventos del motor: lectura del mensaje, decisiones (con el motor y la base simulados) y gestión de los reintentos."""
import json
import unittest
from datetime import datetime, timezone
from unittest import mock

import _sin_servicios  # noqa: F401

try:
    from cerebro.licitaciones import consumidor, embudo
    from cerebro.licitaciones.consumidor import AunNoProyectado, ErrorPermanente, Evento, atender, decodificar, encaje_minimo, espera, procesar
except ImportError as e:      # pragma: no cover
    raise unittest.SkipTest(str(e))

AHORA = datetime(2026, 10, 28, 14, 0, tzinfo=timezone.utc)
ID = "0b1f7a3e-1111-4222-8333-444444444444"
ORIGEN = "https://contrataciondelestado.es/sindicacion/licitacionesPerfilContratante/12345"
CFG = {"pesos": {"cpv": 40, "zona": 20, "importe": 15, "plazo": 15, "procedimiento": 10}, "importe_max": 1_000_000,
       "cpv": [{"codigo": "32000000", "area": "Videovigilancia"}], "zona": {"prioritaria": "ES51", "pais": "ES"}, "embudo": {"encaje_min": 60}}


def mensaje(tipo="licitacion.nueva", version=1, **kw):
    d = {"id": "e1", "tipo": tipo, "fuente": "placsp-643", "id_origen": ORIGEN, "version": version, "sha256_original": "ab", "clave_original": "k"}
    d.update(kw)
    return json.dumps(d).encode()


def item(**kw):
    x = {"id": ID, "version_entidad": 1, "expediente": "2026/045", "titulo": "Videovigilancia del puerto", "comprador": {"nombre": "Girona"},
         "estado": "abierta", "procedimiento": "abierto", "cpv": ["32323500"], "nuts": ["ES512"], "plazo_presentacion": "2026-11-20T10:00:00Z",
         "importe": {"valor": "200000.00", "moneda": "EUR"}, "url_origen": "https://contrataciondelestado.es/x"}
    x.update(kw)
    return x


def motor_con(*items):
    llamadas = []

    async def consulta(ruta, params=None):
        llamadas.append((ruta, params))
        return {"items": list(items)}
    consulta.llamadas = llamadas
    return consulta


class TestMensaje(unittest.TestCase):
    def test_se_lee_lo_que_publica_el_motor(self):
        self.assertEqual(decodificar(mensaje("licitacion.adjudicada", 3)), Evento("e1", "adjudicada", "placsp-643", ORIGEN, 3))

    def test_un_mensaje_roto_es_permanente(self):
        for mal in (b"no es json", b"{}", b"[]", mensaje(version=0), mensaje(fuente="boe"), mensaje(id_origen=""), mensaje(tipo=""), b'{"id":"a","tipo":"x","fuente":"ted","id_origen":"i","version":"v"}'):
            with self.assertRaises(ErrorPermanente, msg=mal):
                decodificar(mal)


class TestUmbral(unittest.TestCase):
    def test_variable_o_configuracion(self):
        with mock.patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("LICITACIONES_ENCAJE_MIN", None)
            self.assertEqual(encaje_minimo(CFG), 60)
        with mock.patch.dict("os.environ", {"LICITACIONES_ENCAJE_MIN": " 75 "}):
            self.assertEqual(encaje_minimo(CFG), 75)
        for mal in ("mucho", "101", "-1"):
            with mock.patch.dict("os.environ", {"LICITACIONES_ENCAJE_MIN": mal}), self.assertRaises(ValueError, msg=mal):
                encaje_minimo(CFG)

    def test_esperas_crecientes_y_acotadas(self):
        self.assertEqual([espera(n) for n in (0, 1, 2, 3, 4, 5, 6, 50)], [10, 10, 60, 300, 1800, 7200, 7200, 7200])


class TestProcesar(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.reg = mock.patch.object(embudo, "registrar_detectada", mock.AsyncMock(return_value=True))
        self.act = mock.patch.object(embudo, "actualizar_estado_motor", mock.AsyncMock(return_value="detectada"))
        self.reg_m, self.act_m = self.reg.start(), self.act.start()

    def tearDown(self):
        self.reg.stop()
        self.act.stop()

    async def lanzar(self, ev, *items, minimo=60):
        return await procesar(ev, consulta=motor_con(*items), cfg=CFG, minimo=minimo, ahora=AHORA)

    async def test_pide_el_expediente_al_motor_con_la_fuente_y_el_id_de_origen(self):
        c = motor_con(item())
        await procesar(decodificar(mensaje()), consulta=c, cfg=CFG, minimo=60, ahora=AHORA)
        self.assertEqual(c.llamadas, [("/tenders", {"fuente": "placsp", "id_origen": ORIGEN, "limit": 1})])

    async def test_una_nueva_con_buen_encaje_entra_como_detectada(self):
        r = await self.lanzar(decodificar(mensaje()), item())
        self.assertTrue(r.startswith("detectada"), r)
        datos = self.reg_m.await_args.args[0]
        self.assertEqual((datos["motor_id"], datos["motor_version"], datos["organismo"], datos["estado_motor"]), (ID, 1, "Girona", "abierta"))
        self.assertNotIn("fuera_de_importe", datos)
        self.assertEqual(str(datos["importe"]), "200000.00")

    async def test_no_entra_si_no_cumple(self):
        casos = {
            "encaje bajo": item(cpv=["45000000"], nuts=["FR101"], procedimiento="negociado_sin_publicidad"),
            "ya adjudicada": item(estado="adjudicada"),
            "fuera de importe": item(importe={"valor": "5000000.00", "moneda": "EUR"}),
        }
        for nombre, x in casos.items():
            self.reg_m.reset_mock()
            r = await self.lanzar(decodificar(mensaje()), x)
            self.assertTrue(r.startswith("ignorada"), (nombre, r))
            self.reg_m.assert_not_awaited()

    async def test_el_umbral_se_respeta(self):
        self.assertTrue((await self.lanzar(decodificar(mensaje()), item(), minimo=0)).startswith("detectada"))
        self.assertTrue((await self.lanzar(decodificar(mensaje()), item(), minimo=100)).startswith("ignorada"))

    async def test_un_cambio_de_estado_se_anota_pero_no_da_de_alta(self):
        self.act_m.return_value = None
        r = await self.lanzar(decodificar(mensaje("licitacion.adjudicada", 2)), item(estado="adjudicada", version_entidad=2))
        self.assertEqual(r, "no está en el embudo")
        self.act_m.assert_awaited_once_with(ID, 2, "adjudicada", AHORA)
        self.reg_m.assert_not_awaited()

    async def test_una_anulada_se_anota_con_el_estado_del_motor(self):
        self.act_m.return_value = "descartada"
        r = await self.lanzar(decodificar(mensaje("licitacion.anulada", 3)), item(estado="anulada", version_entidad=3))
        self.assertIn("descartada", r)

    async def test_si_el_motor_aun_no_lo_tiene_se_espera(self):
        with self.assertRaises(AunNoProyectado):
            await self.lanzar(decodificar(mensaje()))
        with self.assertRaises(AunNoProyectado):            # lo tiene, pero en una versión anterior a la del evento
            await self.lanzar(decodificar(mensaje(version=3)), item(version_entidad=2))
        self.reg_m.assert_not_awaited()

    async def test_un_evento_viejo_con_el_motor_mas_adelantado_usa_lo_ultimo(self):
        r = await self.lanzar(decodificar(mensaje(version=1)), item(version_entidad=4))
        self.assertTrue(r.startswith("detectada"))
        self.assertEqual(self.reg_m.await_args.args[0]["motor_version"], 4)

    async def test_otros_tipos_se_ignoran(self):
        r = await self.lanzar(decodificar(mensaje("licitacion.modificada")), item())
        self.assertTrue(r.startswith("ignorada"))


class FalsoMensaje:
    def __init__(self, datos, entregas=1):
        self.data = datos
        self.metadata = type("M", (), {"num_delivered": entregas})()
        self.log = []

    async def ack(self): self.log.append("ack")
    async def term(self): self.log.append("term")
    async def nak(self, delay=None): self.log.append(("nak", delay))


class TestAtender(unittest.IsolatedAsyncioTestCase):
    async def lanzar(self, m, efecto):
        with mock.patch.object(consumidor, "procesar", mock.AsyncMock(**efecto)):
            return await atender(m)

    async def test_bien_se_confirma(self):
        m = FalsoMensaje(mensaje())
        self.assertEqual(await self.lanzar(m, {"return_value": "detectada"}), "ok")
        self.assertEqual(m.log, ["ack"])

    async def test_un_mensaje_roto_se_da_por_terminado_sin_llamar_a_nada(self):
        m = FalsoMensaje(b"basura")
        with mock.patch.object(consumidor, "procesar", mock.AsyncMock()) as p:
            self.assertEqual(await atender(m), "descartado")
        self.assertEqual(m.log, ["term"])
        p.assert_not_awaited()

    async def test_si_el_motor_aun_no_lo_tiene_se_devuelve_con_espera_creciente(self):
        for entregas, segundos in ((1, 10), (2, 60), (4, 1800)):
            m = FalsoMensaje(mensaje(), entregas)
            self.assertEqual(await self.lanzar(m, {"side_effect": AunNoProyectado("x")}), "reintento")
            self.assertEqual(m.log, [("nak", segundos)])

    async def test_un_fallo_inesperado_o_del_motor_se_reintenta_no_se_pierde(self):
        for exc in (motor_caido(), RuntimeError("la base no responde"), OSError("red")):
            m = FalsoMensaje(mensaje(), 2)
            self.assertEqual(await self.lanzar(m, {"side_effect": exc}), "reintento")
            self.assertEqual(m.log, [("nak", 60)])


def motor_caido():
    return consumidor.motor.MotorNoDisponible("El motor no responde")


if __name__ == "__main__":
    unittest.main()
