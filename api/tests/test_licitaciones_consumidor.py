"""Consumidor de eventos del motor: lectura del mensaje, decisiones (con el motor y la base simulados) y gestión de los reintentos."""
import json
import unittest
from datetime import datetime, timezone
from unittest import mock

import _sin_servicios  # noqa: F401

try:
    from cerebro.licitaciones import alertas, consumidor, embudo
    from cerebro.licitaciones.consumidor import AunNoProyectado, ErrorPermanente, Evento, atender, decodificar, encaje_minimo, espera, procesar, procesar_alertas
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


class TestProcesarAlertas(unittest.IsolatedAsyncioTestCase):
    """Las alertas con la base y el motor simulados: el motor hace de juez del filtro."""

    def alerta(self, id, **filtro):
        return {"id": id, "filtro": filtro or {"cpv": ["32"]}}

    def preparar(self, pedidas, ya=(), cumplen=(), rechaza=()):
        self.registrados = []
        parches = [
            mock.patch.object(alertas, "activas_para", mock.AsyncMock(return_value=pedidas)),
            mock.patch.object(alertas, "ya_avisada", mock.AsyncMock(side_effect=lambda a, e: a in ya)),
            mock.patch.object(alertas, "registrar_aviso", mock.AsyncMock(side_effect=lambda a, e, t, d, ahora: self.registrados.append((a, e, t, d["motor_id"])) or True)),
        ]
        for p in parches:
            p.start()
            self.addCleanup(p.stop)
        self.preguntas = []

        async def consulta(ruta, params=None):
            if set(params) == {"fuente", "id_origen", "limit"}:                 # buscar el expediente del evento
                return {"items": [self.item]}
            self.preguntas.append(params)
            cpv = params["cpv"][0] if "cpv" in params else None
            if cpv in rechaza:
                raise ValueError("El motor rechaza la consulta")
            return {"items": [self.item] if cpv in cumplen else []}
        return consulta

    def setUp(self):
        self.item = item(actualizada_en="2026-10-27T10:00:00Z")

    async def lanzar(self, consulta, tipo="licitacion.nueva", **kw):
        return await procesar_alertas(decodificar(mensaje(tipo, **kw)), consulta=consulta, cfg={**CFG, "alertas": {"max_antiguedad_dias": 7}}, ahora=AHORA)

    async def test_avisa_a_las_alertas_cuyo_filtro_cumple_el_expediente(self):
        c = self.preparar([self.alerta(1, cpv=["32"]), self.alerta(2, cpv=["45"])], cumplen=("32",))
        r = await self.lanzar(c)
        self.assertEqual(r, "1 aviso(s) de 2 alerta(s)")
        self.assertEqual(self.registrados, [(1, "e1", "licitacion.nueva", ID)])
        self.assertEqual([p["id_origen"] for p in self.preguntas], [ORIGEN, ORIGEN])           # el motor evalúa el filtro sobre ESTE expediente
        self.assertEqual(self.preguntas[0], {"cpv": ["32"], "fuente": "placsp", "id_origen": ORIGEN, "limit": 1})

    async def test_si_ninguna_alerta_pide_el_evento_no_se_molesta_al_motor(self):
        llamadas = []

        async def consulta(ruta, params=None):
            llamadas.append(params)
            return {"items": []}
        self.preparar([])
        self.assertEqual(await self.lanzar(consulta), "ninguna alerta pide este evento")
        self.assertEqual(llamadas, [])

    async def test_una_alerta_ya_avisada_del_mismo_evento_se_salta(self):
        c = self.preparar([self.alerta(1), self.alerta(2, cpv=["32", ])], ya=(1,), cumplen=("32",))
        await self.lanzar(c)
        self.assertEqual([r[0] for r in self.registrados], [2])
        self.assertEqual(len(self.preguntas), 1)

    async def test_lo_antiguo_no_avisa_para_no_inundar_con_el_historico(self):
        self.item = item(actualizada_en="2026-09-01T10:00:00Z")
        c = self.preparar([self.alerta(1)], cumplen=("32",))
        self.assertTrue((await self.lanzar(c)).startswith("ignorada: actualizada hace más de 7 días"))
        self.assertEqual(self.registrados, [])

    async def test_una_nueva_que_no_esta_abierta_no_avisa_pero_una_adjudicada_si(self):
        self.item = item(estado="adjudicada", actualizada_en="2026-10-27T10:00:00Z", version_entidad=2)
        c = self.preparar([self.alerta(1)], cumplen=("32",))
        self.assertTrue((await self.lanzar(c, "licitacion.nueva")).startswith("ignorada: no está abierta"))
        self.assertTrue((await self.lanzar(c, "licitacion.adjudicada", version=2)).startswith("1 aviso"))

    async def test_un_filtro_que_el_motor_rechaza_se_salta_sin_perder_el_evento(self):
        c = self.preparar([self.alerta(1, cpv=["99"]), self.alerta(2, cpv=["32"])], cumplen=("32",), rechaza=("99",))
        self.assertEqual(await self.lanzar(c), "1 aviso(s) de 2 alerta(s)")
        self.assertEqual([r[0] for r in self.registrados], [2])

    async def test_si_el_motor_aun_no_lo_tiene_se_espera(self):
        async def vacio(ruta, params=None):
            return {"items": []}
        self.preparar([self.alerta(1)])
        with self.assertRaises(AunNoProyectado):
            await self.lanzar(vacio)


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

    async def test_se_puede_atender_con_otra_funcion_las_alertas(self):
        m = FalsoMensaje(mensaje())
        otra = mock.AsyncMock(return_value="1 aviso(s)")
        self.assertEqual(await atender(m, otra, cfg=CFG), "ok")
        otra.assert_awaited_once()
        self.assertEqual(m.log, ["ack"])

    async def test_un_fallo_inesperado_o_del_motor_se_reintenta_no_se_pierde(self):
        for exc in (motor_caido(), RuntimeError("la base no responde"), OSError("red")):
            m = FalsoMensaje(mensaje(), 2)
            self.assertEqual(await self.lanzar(m, {"side_effect": exc}), "reintento")
            self.assertEqual(m.log, [("nak", 60)])


def motor_caido():
    return consumidor.motor.MotorNoDisponible("El motor no responde")


class TestAlertasDeCompetencia(unittest.IsolatedAsyncioTestCase):
    """Una alerta de competencia avisa de una adjudicación cuando el expediente cumple el filtro y la ha ganado un competidor de la lista (o cualquiera)."""
    FICHA = {"id": ID, "adjudicaciones": [
        {"lote": "1", "resultado": "adjudicado", "adjudicatario": {"nombre": "Seguridad SL", "nif": "B12345678"}, "importes": [{"valor": "90000.00", "moneda": "EUR", "impuestos": "sin_iva"}]},
        {"lote": "2", "resultado": "adjudicado", "adjudicatario": {"nombre": "Pedro Pérez", "nif": "12345678Z"}, "importes": []},
        {"lote": "3", "resultado": "desierto"}]}

    def preparar(self, pedidas, ya_expediente=()):
        self.registrados = []
        self.rutas = []
        parches = [
            mock.patch.object(alertas, "activas_para", mock.AsyncMock(return_value=pedidas)),
            mock.patch.object(alertas, "ya_avisada", mock.AsyncMock(return_value=False)),
            mock.patch.object(alertas, "ya_avisada_expediente", mock.AsyncMock(side_effect=lambda a, m, t: a in ya_expediente)),
            mock.patch.object(alertas, "registrar_aviso", mock.AsyncMock(side_effect=lambda a, e, t, d, ahora, detalle=None: self.registrados.append((a, t, detalle)) or True)),
        ]
        for p in parches:
            p.start()
            self.addCleanup(p.stop)
        it = item(estado="adjudicada", actualizada_en="2026-10-27T10:00:00Z", version_entidad=2)

        async def consulta(ruta, params=None):
            self.rutas.append(ruta)
            if ruta == f"/tenders/{ID}":
                return self.FICHA
            return {"items": [it]}
        return consulta

    def alerta(self, id, competidores=(), **filtro):
        return {"id": id, "tipo": "competencia", "competidores": list(competidores), "filtro": filtro}

    async def lanzar(self, consulta):
        return await procesar_alertas(decodificar(mensaje("licitacion.adjudicada", version=2)), consulta=consulta, cfg={**CFG, "alertas": {"max_antiguedad_dias": 7}}, ahora=AHORA)

    async def test_avisa_si_gana_un_competidor_de_la_lista_con_quien_y_cuanto(self):
        c = self.preparar([self.alerta(1, ["B12345678"], cpv=["32"])])
        self.assertEqual(await self.lanzar(c), "1 aviso(s) de 1 alerta(s)")
        (a, tipo, detalle), = self.registrados
        self.assertEqual((a, tipo), (1, "competencia.adjudicada"))
        self.assertEqual(detalle["ganadores"], [{"nombre": "Seguridad SL", "nif": "B12345678", "lote": "1", "importe": "90000.00", "moneda": "EUR"}])

    async def test_si_gana_otro_no_avisa_ni_pide_la_ficha_de_mas(self):
        c = self.preparar([self.alerta(1, ["A08000143"], cpv=["32"])])
        self.assertEqual(await self.lanzar(c), "0 aviso(s) de 1 alerta(s)")
        self.assertEqual(self.registrados, [])

    async def test_sin_lista_avisa_de_cualquier_adjudicado_pero_no_enseña_el_nif_de_una_persona(self):
        c = self.preparar([self.alerta(1, [], cpv=["32"])])
        await self.lanzar(c)
        g = self.registrados[0][2]["ganadores"]
        self.assertEqual([(x["nombre"], x["nif"]) for x in g], [("Seguridad SL", "B12345678"), ("Pedro Pérez", None)])       # el desierto no cuenta

    async def test_una_sola_vez_por_expediente_y_la_ficha_solo_se_lee_si_hace_falta(self):
        c = self.preparar([self.alerta(1, ["B12345678"], cpv=["32"])], ya_expediente=(1,))
        self.assertEqual(await self.lanzar(c), "0 aviso(s) de 1 alerta(s)")
        self.assertNotIn(f"/tenders/{ID}", self.rutas)
        self.assertEqual(self.registrados, [])

    async def test_una_alerta_normal_y_una_de_competencia_conviven(self):
        c = self.preparar([{"id": 2, "filtro": {"cpv": ["32"]}}, self.alerta(1, ["B12345678"], cpv=["32"])])
        self.assertEqual(await self.lanzar(c), "2 aviso(s) de 2 alerta(s)")
        self.assertEqual([(a, t) for a, t, _ in self.registrados], [(2, "licitacion.adjudicada"), (1, "competencia.adjudicada")])


class TestSoloNuevos(TestAlertasDeCompetencia):
    """«Solo empresas nuevas en el mercado»: avisa si quien gana no había ganado antes nada en ese mercado, y solo con historia suficiente en el motor."""
    test_avisa_si_gana_un_competidor_de_la_lista_con_quien_y_cuanto = test_si_gana_otro_no_avisa_ni_pide_la_ficha_de_mas = None
    test_sin_lista_avisa_de_cualquier_adjudicado_pero_no_enseña_el_nif_de_una_persona = test_una_sola_vez_por_expediente_y_la_ficha_solo_se_lee_si_hace_falta = None
    test_una_alerta_normal_y_una_de_competencia_conviven = None

    def con_awards(self, c0, cobertura=True, previos=(), propia_licitacion=False):
        self.awards = []

        async def consulta(ruta, params=None):
            if ruta == "/awards":
                self.awards.append(params)
                if "adjudicatario" not in params:
                    return {"items": [{"licitacion_id": "antigua"}] if cobertura else []}
                nif = params["adjudicatario"].split(":")[1]
                if propia_licitacion:
                    return {"items": [{"licitacion_id": ID}]}                      # otro lote de ESTA misma licitación: no cuenta como haber ganado antes
                return {"items": [{"licitacion_id": "otra"}] if nif in previos else []}
            return await c0(ruta, params)
        return consulta

    def nueva(self, id=1, **filtro):
        return {**self.alerta(id, [], **filtro), "solo_nuevos": True}

    async def test_avisa_solo_de_los_nuevos_y_no_guarda_nifs_de_personas(self):
        c = self.con_awards(self.preparar([self.nueva(cpv=["32"])]), previos=("12345678Z",))          # la persona ya había ganado; la empresa no
        self.assertEqual(await self.lanzar(c), "1 aviso(s) de 1 alerta(s)")
        (a, tipo, detalle), = self.registrados
        self.assertEqual([g["nombre"] for g in detalle["ganadores"]], ["Seguridad SL"])
        self.assertTrue(detalle["nuevos"])
        self.assertTrue(all("_nif" not in g for g in detalle["ganadores"]))                              # el NIF entero solo servía para comparar

    async def test_la_consulta_al_motor_acota_por_mercado_nif_y_fecha(self):
        c = self.con_awards(self.preparar([self.nueva(cpv=["32"], nuts=["ES512"])]))
        await self.lanzar(c)
        por_nif = [p for p in self.awards if "adjudicatario" in p]
        self.assertEqual(sorted(p["adjudicatario"] for p in por_nif), ["nif:12345678Z", "nif:B12345678"])
        for p in por_nif:
            self.assertEqual((p["cpv"], p["nuts"], p["resultado"]), (["32"], ["ES512"], "adjudicado"))
            self.assertRegex(p["adjudicada_hasta"], r"^\d{4}-\d{2}-\d{2}$")
        cobertura = [p for p in self.awards if "adjudicatario" not in p]
        self.assertEqual(len(cobertura), 1)
        self.assertLess(cobertura[0]["adjudicada_hasta"], "2025-11-01")                                    # hace unos 12 meses

    async def test_sin_historia_suficiente_no_se_avisa_de_nadie(self):
        c = self.con_awards(self.preparar([self.nueva(cpv=["32"])]), cobertura=False)
        self.assertEqual(await self.lanzar(c), "0 aviso(s) de 1 alerta(s)")
        self.assertEqual(self.registrados, [])
        self.assertEqual([p for p in self.awards if "adjudicatario" in p], [])                           # ni siquiera se pregunta por cada empresa

    async def test_si_todos_ya_habian_ganado_no_se_avisa(self):
        c = self.con_awards(self.preparar([self.nueva(cpv=["32"])]), previos=("B12345678", "12345678Z"))
        self.assertEqual(await self.lanzar(c), "0 aviso(s) de 1 alerta(s)")

    async def test_otro_lote_de_la_misma_licitacion_no_cuenta_como_haber_ganado_antes(self):
        c = self.con_awards(self.preparar([self.nueva(cpv=["32"])]), propia_licitacion=True)
        self.assertEqual(await self.lanzar(c), "1 aviso(s) de 1 alerta(s)")
        self.assertEqual(len(self.registrados[0][2]["ganadores"]), 2)

    async def test_una_alerta_sin_solo_nuevos_no_toca_el_motor_de_adjudicaciones(self):
        c = self.con_awards(self.preparar([self.alerta(1, [], cpv=["32"])]))
        await self.lanzar(c)
        self.assertEqual(self.awards, [])
        self.assertNotIn("nuevos", self.registrados[0][2])


if __name__ == "__main__":
    unittest.main()
