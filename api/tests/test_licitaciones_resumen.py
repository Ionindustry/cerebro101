"""Resumen diario de licitaciones de las 16:00: ventana, clasificación, orden por encaje, y lo que dice cuando no sabe."""
import asyncio
import unittest
from datetime import datetime, timezone
from unittest import mock

import _sin_servicios  # noqa: F401

from cerebro.herramientas import licitaciones as motor
from cerebro.licitaciones import resumen

CFG = resumen.config()
AHORA = datetime(2026, 10, 28, 15, 0, tzinfo=timezone.utc)        # las 16:00 en Madrid (CET, UTC+1)


def ejecutar(coro):
    return asyncio.run(coro)


def lic(n, estado="abierta", cpv="35125300", nuts="ES512", valor="100000", version=1, plazo="2026-11-20T10:00:00Z", proc="abierto", **kw):
    return {"id": f"id-{n}", "titulo": f"Licitación {n}", "expediente": f"EXP-{n}", "estado": estado, "cpv": [cpv], "nuts": [nuts], "procedimiento": proc,
            "importe": {"valor": valor, "moneda": "EUR", "impuestos": "sin_iva", "significado": "valor_estimado"} if valor else None,
            "plazo_presentacion": plazo, "version_entidad": version, "comprador": {"nombre": "Ayuntamiento de Girona"},
            "url_origen": "https://contrataciondelestado.es/x", **kw}


class Motor:
    """Un motor simulado: sirve páginas de a `pagina` elementos y un estado."""
    def __init__(self, items, estado="ok", antiguedad=600, pagina=100, falla=None):
        self.items, self.estado, self.antiguedad, self.pagina, self.falla, self.llamadas = items, estado, antiguedad, pagina, falla, []

    async def __call__(self, ruta, params):
        self.llamadas.append((ruta, params))
        if self.falla and (self.falla[0] == ruta):
            raise self.falla[1]
        if ruta == "/ops/status":
            return {"estado": self.estado, "fuentes": [{"fuente": "placsp", "antiguedad_s": self.antiguedad}]}
        desde = int((params or {}).get("cursor", "0"))
        trozo = self.items[desde: desde + self.pagina]
        sig = str(desde + self.pagina) if desde + self.pagina < len(self.items) else None
        return {"items": trozo, "siguiente_cursor": sig, "total": {"valor": len(self.items), "relacion": "eq"}}


class TestVentana(unittest.TestCase):
    def test_desde_las_16_de_ayer_a_las_16_de_hoy(self):
        d, h = resumen.ventana(AHORA, "Europe/Madrid")
        self.assertEqual(d, datetime(2026, 10, 27, 15, 0, tzinfo=timezone.utc))
        self.assertEqual(h, AHORA)

    def test_con_el_cambio_de_hora_se_respeta_la_hora_local(self):
        # 29/03/2026: empieza el horario de verano. Las 16:00 locales del 29 (CEST, UTC+2) y las del 28 (CET, UTC+1): 23 horas de reloj.
        d, h = resumen.ventana(datetime(2026, 3, 29, 14, 0, tzinfo=timezone.utc), "Europe/Madrid")
        self.assertEqual(d, datetime(2026, 3, 28, 15, 0, tzinfo=timezone.utc))
        self.assertEqual((h - d).total_seconds() / 3600, 23)

    def test_pedido_a_otra_hora_son_las_24_horas_anteriores_de_reloj_de_pared(self):
        d, h = resumen.ventana(datetime(2026, 10, 28, 8, 30, tzinfo=timezone.utc), "Europe/Madrid")
        self.assertEqual(d, datetime(2026, 10, 27, 8, 30, tzinfo=timezone.utc))


class TestConstruir(unittest.TestCase):
    def construir(self, motor_sim):
        return ejecutar(resumen.construir(AHORA, motor_sim))

    def test_consulta_con_la_ventana_y_los_cpv_de_interes(self):
        m = Motor([lic(1)])
        self.construir(m)
        ruta, params = m.llamadas[0]
        self.assertEqual(ruta, "/tenders")
        self.assertEqual(params["actualizada_desde"], "2026-10-27T15:00:00Z")
        self.assertEqual(params["orden"], "actualizacion")
        self.assertEqual(params["limit"], 100)
        self.assertIn("72", params["cpv"])
        self.assertLessEqual(len(params["cpv"]), 20)

    def test_clasifica_y_ordena_por_encaje(self):
        items = [
            lic(1, cpv="15000000", nuts="FR101", proc="negociado_sin_publicidad"),                 # encaje bajo
            lic(2),                                                                                # encaje alto
            lic(3, cpv="72261000", nuts="ES300"),                                                  # medio
            lic(4, estado="adjudicada"), lic(5, estado="desierta"), lic(6, estado="anulada"), lic(7, estado="cerrada"),
        ]
        r = self.construir(Motor(items))
        self.assertEqual([o["id"] for o in r["oportunidades"]], ["id-2", "id-3", "id-1"])
        self.assertEqual([o["encaje"] for o in r["oportunidades"]], sorted((o["encaje"] for o in r["oportunidades"]), reverse=True))
        self.assertEqual({a["id"] for a in r["adjudicaciones"]}, {"id-4", "id-5"})
        self.assertEqual([a["id"] for a in r["anuladas"]], ["id-6"])
        self.assertEqual(r["totales"], {"novedades": 7, "oportunidades": 3, "adjudicaciones": 2, "anuladas": 1, "fuera_de_importe": 0, "otras": 1, "truncado": False})
        self.assertEqual(r["estado"], "ok")
        self.assertIsNone(r["aviso"])

    def test_lo_que_supera_el_importe_se_cuenta_pero_no_se_detalla(self):
        r = self.construir(Motor([lic(1), lic(2, valor="2500000"), lic(3, valor="1000000")]))
        self.assertEqual({o["id"] for o in r["oportunidades"]}, {"id-1", "id-3"})
        self.assertEqual(r["totales"]["fuera_de_importe"], 1)

    def test_nueva_o_actualizada(self):
        r = self.construir(Motor([lic(1, version=1), lic(2, version=3)]))
        self.assertEqual({o["id"]: o["nueva"] for o in r["oportunidades"]}, {"id-1": True, "id-2": False})

    def test_detalla_como_mucho_20_oportunidades_pero_las_cuenta_todas(self):
        r = self.construir(Motor([lic(i) for i in range(35)]))
        self.assertEqual(len(r["oportunidades"]), 20)
        self.assertEqual(r["totales"]["oportunidades"], 35)

    def test_pagina_y_avisa_si_hay_mas_de_lo_que_se_lee(self):
        m = Motor([lic(i) for i in range(1200)], pagina=100)
        r = self.construir(m)
        self.assertEqual(r["totales"]["novedades"], 500)         # 5 páginas de 100
        self.assertTrue(r["totales"]["truncado"])
        self.assertIn("500 novedades", r["aviso"])
        # y con menos novedades que el tope no hay aviso
        self.assertIsNone(self.construir(Motor([lic(i) for i in range(250)], pagina=100))["aviso"])

    def test_si_el_motor_no_responde_el_resumen_lo_dice_en_vez_de_salir_vacio(self):
        r = self.construir(Motor([], falla=("/tenders", motor.MotorNoDisponible("El motor de licitaciones no responde ahora"))))
        self.assertEqual(r["estado"], "sin_datos")
        self.assertIn("no significa que no haya novedades", r["aviso"])
        self.assertEqual((r["oportunidades"], r["adjudicaciones"], r["anuladas"]), ([], [], []))

    def test_un_motor_atrasado_lleva_aviso_con_las_horas(self):
        r = self.construir(Motor([lic(1)], estado="caido", antiguedad=11 * 3600))
        self.assertEqual(r["estado"], "ok")
        self.assertIn("no está al día", r["aviso"])
        self.assertIn("11 h", r["aviso"])
        self.assertEqual(r["motor"], {"estado": "caido", "antiguedad_h": 11.0, "sin_ingesta_completa": False})

    def test_si_no_se_puede_comprobar_el_estado_del_motor_tambien_avisa(self):
        r = self.construir(Motor([lic(1)], falla=("/ops/status", motor.MotorNoDisponible("x"))))
        self.assertEqual(r["motor"]["estado"], "desconocido")
        self.assertIn("No se ha podido comprobar", r["aviso"])

    def test_enlaces_solo_http_y_textos_acotados(self):
        r = self.construir(Motor([lic(1, url_origen="javascript:alert(1)", titulo="x" * 900)]))
        o = r["oportunidades"][0]
        self.assertIsNone(o["url_origen"])
        self.assertLessEqual(len(o["titulo"]), 300)

    def test_lo_mas_cerca_del_cierre_desempata(self):
        r = self.construir(Motor([lic(1, plazo="2026-11-25T10:00:00Z"), lic(2, plazo="2026-11-20T10:00:00Z")]))
        # mismo encaje máximo: el plazo más próximo primero
        self.assertEqual(r["oportunidades"][0]["encaje"], r["oportunidades"][1]["encaje"])
        self.assertEqual(r["oportunidades"][0]["id"], "id-2")


class TestConsultaDeCpv(unittest.TestCase):
    def test_los_20_cpv_de_direccion_se_reducen_a_prefijos_que_cubren_a_los_descendientes(self):
        p = resumen.prefijos_de_consulta(CFG)
        self.assertEqual(sorted(p), sorted(["72", "323235", "32235", "32234", "3512", "3497", "34923", "6371271", "4531621", "42961", "3242", "324411"]))
        self.assertFalse(any(a != b and a.startswith(b) for a in p for b in p), "ningún prefijo debe cubrir a otro")


class TestGenerar(unittest.TestCase):
    def test_genera_y_guarda_con_el_origen_pedido(self):
        guardado = []

        async def guardar(r, origen, zona=None):
            guardado.append((r["estado"], origen))
            return 7
        with mock.patch.object(resumen, "construir", mock.AsyncMock(return_value={"estado": "ok", "totales": {"oportunidades": 2}, "ventana": {}})), \
                mock.patch.object(resumen, "guardar", guardar), mock.patch.object(resumen, "_manual_reciente", mock.AsyncMock(return_value=None)):
            r = ejecutar(resumen.generar("manual"))
        self.assertEqual((r["id"], r["estado"]), (7, "ok"))
        self.assertEqual(guardado, [("ok", "manual")])
        with self.assertRaises(ValueError):
            ejecutar(resumen.generar("otro"))

    def test_un_manual_repetido_en_menos_de_un_minuto_reutiliza_el_anterior(self):
        previo = {"id": 3, "estado": "ok", "contenido": {"totales": {"oportunidades": 5}}}
        construir = mock.AsyncMock()
        with mock.patch.object(resumen, "_manual_reciente", mock.AsyncMock(return_value=previo)), mock.patch.object(resumen, "construir", construir):
            r = ejecutar(resumen.generar("manual"))
        self.assertEqual((r["id"], r["reutilizado"]), (3, True))
        construir.assert_not_called()          # no se vuelve a consultar al motor


if __name__ == "__main__":
    unittest.main()
