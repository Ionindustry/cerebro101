"""Avisos de alertas por correo: el texto (puro) y el envío con PostgreSQL real (con CEREBRO_TEST_PG; sin ella, esa parte se omite). El servidor SMTP se sustituye por una función."""
import asyncio
import os
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import _sin_servicios  # noqa: F401

try:
    import psycopg
    from cerebro.herramientas import buzones as B
    from cerebro.licitaciones import alertas, avisos_correo as ac
except ImportError as e:      # pragma: no cover
    raise unittest.SkipTest(str(e))

URL = os.environ.get("CEREBRO_TEST_PG")
ESQUEMA = Path(__file__).resolve().parents[2] / "db" / "esquema.sql"
AHORA = datetime(2026, 10, 28, 14, 0, tzinfo=timezone.utc)
ID = "0b1f7a3e-1111-4222-8333-444444444444"
ALBERT = SimpleNamespace(id="albert", roles={"usuario"}, departamentos={"licitaciones"})
CFG = {"buzon": "notificaciones", "dominios": ["101.cat"], "max_por_correo": 2, "max_intentos": 3, "max_antiguedad_horas": 48}
BUZONES = {"avisos": CFG, "buzones": {"notificaciones": {"direccion": "notificaciones@101.cat", "departamentos": []}}}


def ejecutar(coro):
    return asyncio.run(coro)


def aviso(**kw):
    d = {"tipo": "licitacion.nueva", "titulo": "Videovigilancia del puerto", "organismo": "Ayuntamiento de Girona", "encaje": 82, "importe": 200000.0,
         "fecha_limite": datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc), "enlace": "https://contrataciondelestado.es/x/1"}
    d.update(kw)
    return d


class TestRedactar(unittest.TestCase):
    def test_un_aviso_lleva_titulo_organismo_importe_encaje_plazo_en_hora_de_madrid_y_enlace(self):
        asunto, cuerpo = ac.redactar({"nombre": "Videovigilancia en Girona"}, [aviso()])
        self.assertEqual(asunto, "Alerta «Videovigilancia en Girona»: 1 aviso · Videovigilancia del puerto")
        for trozo in ("• [Nueva] Videovigilancia del puerto", "Ayuntamiento de Girona · 200.000 € · encaje 82 · plazo 20/11/2026 10:00", "https://contrataciondelestado.es/x/1",
                      "Aviso automático", "ha encontrado 1 licitación:"):
            self.assertIn(trozo, cuerpo)

    def test_varios_avisos_y_datos_que_faltan(self):
        asunto, cuerpo = ac.redactar({"nombre": "N"}, [aviso(tipo="licitacion.adjudicada", organismo=None, importe=None, encaje=None, fecha_limite=None, enlace=None), aviso()])
        self.assertEqual(asunto, "Alerta «N»: 2 avisos")
        self.assertIn("ha encontrado 2 licitaciones:", cuerpo)
        self.assertIn("• [Adjudicada] Videovigilancia del puerto\n\n", cuerpo)             # sin detalle ni enlace no quedan líneas vacías de más

    def test_un_aviso_de_competencia_dice_quien_ha_ganado(self):
        d = {"ganadores": [{"nombre": "Seguridad SL", "nif": "B12345678", "lote": "2", "importe": "90000.00"}, {"nombre": "Pedro Pérez", "nif": None, "lote": "1", "importe": None}]}
        _, cuerpo = ac.redactar({"nombre": "Rivales"}, [aviso(tipo="competencia.adjudicada", detalle=d)])
        self.assertIn("• [Competencia]", cuerpo)
        self.assertIn("  Ganó: Seguridad SL · B12345678 · 90.000 € sin IVA · lote 2", cuerpo)
        self.assertIn("  Ganó: Pedro Pérez\n", cuerpo)

    def test_el_texto_de_terceros_no_rompe_el_correo(self):
        asunto, cuerpo = ac.redactar({"nombre": "Mala\r\nBcc: x@y.com"}, [aviso(titulo="Obras\r\nBcc: x@y.com\x00" + "z" * 500)])
        self.assertNotIn("\n", asunto)
        self.assertNotIn("\r", cuerpo)
        m = ac.construir_mensaje("notificaciones@101.cat", "a@101.cat", asunto, cuerpo)                  # EmailMessage rechazaría una cabecera con saltos de línea
        self.assertEqual((m["To"], m["Auto-Submitted"], m["Bcc"]), ("a@101.cat", "auto-generated", None))


@unittest.skipUnless(URL and hasattr(psycopg, "AsyncConnection"), "sin CEREBRO_TEST_PG")
class TestEnvioEnBase(unittest.TestCase):
    def setUp(self):
        self.schema = f"t_avisos_correo_{time.time_ns()}"
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"CREATE SCHEMA {self.schema}")
            c.execute(f"SET search_path = {self.schema}")
            t = ESQUEMA.read_text(encoding="utf-8")
            c.execute(t[t.index("-- Alertas de licitaciones"):t.index("-- Resumen diario de licitaciones")])
        sep = "&" if "?" in URL else "?"
        self.url = f"{URL}{sep}options=-csearch_path%3D{self.schema}"
        aj = SimpleNamespace(database_url=self.url, zona_horaria="Europe/Madrid")
        self.parches = [mock.patch.object(alertas, "ajustes", aj), mock.patch.object(ac, "ajustes", aj), mock.patch.object(B, "cargar", lambda: BUZONES)]
        for p in self.parches:
            p.start()
        self.enviados = []

    def tearDown(self):
        for p in self.parches:
            p.stop()
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"DROP SCHEMA {self.schema} CASCADE")

    def enviar(self, buzon, mensaje):
        self.enviados.append((buzon, mensaje))

    def alerta(self, canal="correo", destino="albert@101.cat"):
        extra = {"correo_destino": destino} if canal == "correo" else {}
        return ejecutar(alertas.crear(ALBERT, {"nombre": "Girona", "ambito": "personal", "filtro": {"cpv": ["32323500"]}, "eventos": ["licitacion.nueva"], "canal": canal, **extra}))

    def aviso(self, alerta, n, creado=AHORA):
        d = {"motor_id": ID, "titulo": f"Licitación {n}", "organismo": "Girona", "encaje": 80, "importe": 1000, "fecha_limite": None, "enlace": None, "estado_motor": "abierta"}
        ejecutar(alertas.registrar_aviso(alerta["id"], f"ev{n}", "licitacion.nueva", d, creado))

    def estado(self):
        with psycopg.connect(self.url) as c:
            return c.execute("SELECT titulo, correo_enviado IS NOT NULL, correo_intentos, correo_error FROM licitaciones_avisos ORDER BY id").fetchall()

    def test_envia_agrupado_por_alerta_en_lotes_y_no_repite(self):
        a, panel = self.alerta(), self.alerta("panel")
        for n in (1, 2, 3):
            self.aviso(a, n)
        self.aviso(panel, 4)
        r = ejecutar(ac.enviar_pendientes(self.enviar, AHORA))
        self.assertEqual(r, {"correos": 2, "avisos": 3, "fallidos": 0, "omitidos": 0})         # 3 avisos con máximo 2 por correo → 2 correos; el de «panel» no se envía
        self.assertEqual([(b, m["To"], m["From"]) for b, m in self.enviados], [("notificaciones", "albert@101.cat", "notificaciones@101.cat")] * 2)
        self.assertEqual([x[1] for x in self.estado()], [True, True, True, False])
        self.assertEqual(ejecutar(ac.enviar_pendientes(self.enviar, AHORA))["correos"], 0)     # idempotente
        self.assertEqual(len(self.enviados), 2)

    def test_un_fallo_se_anota_se_reintenta_y_al_agotar_los_intentos_se_deja(self):
        a = self.alerta()
        self.aviso(a, 1)

        def falla(buzon, mensaje):
            raise OSError("servidor caído")
        for i in range(3):
            self.assertEqual(ejecutar(ac.enviar_pendientes(falla, AHORA))["fallidos"], 1, i)
        titulo, enviado, intentos, error = self.estado()[0]
        self.assertEqual((enviado, intentos), (False, 3))
        self.assertIn("servidor caído", error)
        self.assertEqual(ejecutar(ac.enviar_pendientes(self.enviar, AHORA)), {"correos": 0, "avisos": 0, "fallidos": 0, "omitidos": 0})      # sin intentos: ya no se envía

    def test_tras_un_fallo_el_siguiente_ciclo_lo_envia(self):
        a = self.alerta()
        self.aviso(a, 1)

        def falla(buzon, mensaje):
            raise OSError("x")
        ejecutar(ac.enviar_pendientes(falla, AHORA))
        self.assertEqual(ejecutar(ac.enviar_pendientes(self.enviar, AHORA))["avisos"], 1)
        self.assertEqual(self.estado()[0][1:3], (True, 1))

    def test_no_envia_de_alertas_en_pausa_ni_avisos_viejos(self):
        a, b = self.alerta(), self.alerta()
        self.aviso(a, 1, AHORA - timedelta(hours=49))                                          # más viejo que max_antiguedad_horas
        self.aviso(b, 2)
        ejecutar(alertas.cambiar(ALBERT, b["id"], {"activa": False}))
        self.assertEqual(ejecutar(ac.enviar_pendientes(self.enviar, AHORA))["correos"], 0)
        self.assertEqual(self.enviados, [])

    def test_un_destino_que_ya_no_vale_no_se_envia_aunque_estuviera_en_la_base(self):
        a = self.alerta()
        self.aviso(a, 1)
        with psycopg.connect(self.url, autocommit=True) as c:
            c.execute("UPDATE licitaciones_alertas SET correo_destino = 'fuera@gmail.com' WHERE id = %s", [a["id"]])
        r = ejecutar(ac.enviar_pendientes(self.enviar, AHORA))
        self.assertEqual((r["correos"], r["fallidos"], self.enviados), (0, 1, []))

    def test_sin_buzon_configurado_no_gasta_intentos(self):
        a = self.alerta()
        self.aviso(a, 1)
        with mock.patch.object(B, "activo", return_value=False):
            r = ejecutar(ac.enviar_pendientes(None, AHORA))
        self.assertEqual((r["omitidos"], self.estado()[0][2]), (1, 0))


if __name__ == "__main__":
    unittest.main()
