"""Plazos de licitaciones en el calendario: el iCalendar (puro) y el flujo con PostgreSQL real (con CEREBRO_TEST_PG; sin ella, esa parte se omite). El servidor CalDAV se sustituye por funciones."""
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
    from icalendar import Calendar
    from cerebro.licitaciones import calendario_plazos as cp, embudo
    from cerebro.licitaciones.embudo import ErrorEmbudo, NoExiste
except ImportError as e:      # pragma: no cover
    raise unittest.SkipTest(str(e))

URL = os.environ.get("CEREBRO_TEST_PG")
ESQUEMA = Path(__file__).resolve().parents[2] / "db" / "esquema.sql"
AHORA = datetime(2026, 10, 28, 14, 0, tzinfo=timezone.utc)
ID = "0b1f7a3e-1111-4222-8333-444444444444"
CFG = {"duracion_min": 30, "recordatorios_dias": [3, 1], "calendario": ""}


def ejecutar(coro):
    return asyncio.run(coro)


def fila(**kw):
    f = {"motor_id": ID, "titulo": "Videovigilancia del puerto", "organismo": "Ayuntamiento de Girona", "expediente": "2026/045", "importe": 200000.0,
         "enlace": "https://contrataciondelestado.es/x/1", "fecha_limite": "2026-11-20T09:00:00+00:00", "estado": "en_estudio"}
    f.update(kw)
    return f


def leer(ics):
    c = Calendar.from_ical(ics)
    return next(x for x in c.walk() if x.name == "VEVENT")


class TestConstruirIcs(unittest.TestCase):
    def test_el_evento_termina_en_el_plazo_lleva_uid_fijo_y_recordatorios(self):
        ev = leer(cp.construir_ics(fila(), CFG, AHORA))
        self.assertEqual(str(ev["uid"]), f"plazo-licitacion-{ID}@101.cat")
        self.assertEqual((ev["dtstart"].dt, ev["dtend"].dt), (datetime(2026, 11, 20, 8, 30, tzinfo=timezone.utc), datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc)))
        self.assertEqual(str(ev["summary"]), "Plazo: Videovigilancia del puerto")
        d = str(ev["description"])
        self.assertIn("10:00 (hora de Madrid)", d)                                              # el plazo en hora local, no en UTC
        for t in ("Ayuntamiento de Girona", "2026/045", "200.000 €", "https://contrataciondelestado.es/x/1"):
            self.assertIn(t, d)
        alarmas = [a for a in ev.subcomponents if a.name == "VALARM"]
        self.assertEqual(sorted(a["trigger"].dt for a in alarmas), [timedelta(days=-3), timedelta(days=-1)])
        self.assertEqual({str(a["action"]) for a in alarmas}, {"DISPLAY"})

    def test_el_mismo_evento_siempre_con_el_mismo_uid_para_actualizar_sin_duplicar(self):
        a = leer(cp.construir_ics(fila(), CFG, AHORA))
        b = leer(cp.construir_ics(fila(fecha_limite="2026-11-25T10:00:00+01:00"), CFG, AHORA + timedelta(days=1)))
        self.assertEqual(str(a["uid"]), str(b["uid"]))
        self.assertEqual(b["dtend"].dt, datetime(2026, 11, 25, 9, 0, tzinfo=timezone.utc))       # la hora con zona se pasa a UTC

    def test_los_textos_de_terceros_van_escapados_y_no_inyectan_nada(self):
        malo = "Obras, fase 1; lote 2\r\nBEGIN:VEVENT\r\nSUMMARY:falso"
        ics = cp.construir_ics(fila(titulo=malo, organismo="A;B,C\nDESCRIPTION:x", enlace="javascript:alert(1)"), CFG, AHORA)
        c = Calendar.from_ical(ics)
        self.assertEqual(len([x for x in c.walk() if x.name == "VEVENT"]), 1)
        ev = leer(ics)
        self.assertEqual(str(ev["summary"]), "Plazo: Obras, fase 1; lote 2 BEGIN:VEVENT SUMMARY:falso")
        self.assertNotIn("javascript", str(ev["description"]))                                  # solo enlaces http(s)

    def test_sin_plazo_con_plazo_pasado_o_sin_zona_horaria_no_se_pone(self):
        for mal in (fila(fecha_limite=None), fila(fecha_limite="basura"), fila(fecha_limite="2026-10-01T09:00:00+00:00"), fila(fecha_limite="2026-11-20T09:00:00")):
            with self.assertRaises(ErrorEmbudo, msg=mal["fecha_limite"]):
                cp.construir_ics(mal, CFG, AHORA)

    def test_la_configuracion_acota_los_valores(self):
        with mock.patch.object(cp, "ajustes", SimpleNamespace(dir_config=Path(__file__).resolve().parents[2] / "config")):
            c = cp.configuracion()
        self.assertEqual((c["duracion_min"], c["recordatorios_dias"], c["calendario"]), (30, [3, 1], ""))


@unittest.skipUnless(URL and hasattr(psycopg, "AsyncConnection"), "sin CEREBRO_TEST_PG")
class TestEnBase(unittest.TestCase):
    def setUp(self):
        self.schema = f"t_calplazos_{time.time_ns()}"
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"CREATE SCHEMA {self.schema}")
            c.execute(f"SET search_path = {self.schema}")
            t = ESQUEMA.read_text(encoding="utf-8")
            c.execute(t[t.index("-- Licitaciones\nCREATE TABLE IF NOT EXISTS licitaciones"):t.index("-- Resumen diario de licitaciones")])
        sep = "&" if "?" in URL else "?"
        self.parche = mock.patch.object(embudo, "ajustes", SimpleNamespace(database_url=f"{URL}{sep}options=-csearch_path%3D{self.schema}", zona_horaria="Europe/Madrid"))
        self.parche.start()
        d = {"motor_id": ID, "motor_version": 1, "expediente": "2026/045", "organismo": "Girona", "titulo": "Videovigilancia", "cpv": ["32323500"], "importe": 100000,
             "fecha_limite": "2026-11-20T09:00:00+00:00", "enlace": None, "encaje": 80, "estado_motor": "abierta"}
        ejecutar(embudo.registrar_detectada(d, AHORA))
        self.lid = ejecutar(embudo.listar())[0]["id"]
        self.guardados, self.borrados = [], []

    def tearDown(self):
        self.parche.stop()
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"DROP SCHEMA {self.schema} CASCADE")

    def guardar(self, ics, nombre):
        self.guardados.append((ics, nombre))

    def borrar(self, uid, nombre):
        self.borrados.append((uid, nombre))

    def poner(self, **kw):
        return ejecutar(cp.poner(self.lid, guardar=kw.pop("guardar", self.guardar), ahora=AHORA, cfg=CFG))

    def test_poner_crea_el_evento_y_anota_el_plazo_y_repetirlo_actualiza(self):
        f = self.poner()
        self.assertEqual(f["calendario_plazo"], "2026-11-20T09:00:00+00:00")
        self.assertEqual(len(self.guardados), 1)
        self.assertEqual(str(leer(self.guardados[0][0])["uid"]), f"plazo-licitacion-{ID}@101.cat")
        self.poner()
        self.assertEqual([str(leer(i)["uid"]) for i, _ in self.guardados], [f"plazo-licitacion-{ID}@101.cat"] * 2)         # mismo UID: el servidor lo sustituye

    def test_si_el_calendario_falla_no_se_anota_nada_y_el_error_es_comprensible(self):
        def sin_cuenta(ics, nombre):
            raise PermissionError("No hay cuenta de calendario configurada para licitaciones")

        def caido(ics, nombre):
            raise OSError("conexión rechazada")
        with self.assertRaisesRegex(cp.ErrorCalendario, "no está configurado"):
            self.poner(guardar=sin_cuenta)
        with self.assertRaisesRegex(cp.ErrorCalendario, "No se ha podido escribir"):
            self.poner(guardar=caido)
        self.assertIsNone(ejecutar(embudo.obtener(self.lid))["calendario_plazo"])

    def test_no_se_pone_lo_resuelto_ni_lo_que_no_existe(self):
        ejecutar(embudo.cambiar_estado(self.lid, "descartada", ahora=AHORA))
        with self.assertRaises(ErrorEmbudo):
            self.poner()
        with self.assertRaises(NoExiste):
            ejecutar(cp.poner(999, guardar=self.guardar, ahora=AHORA, cfg=CFG))
        self.assertEqual(self.guardados, [])

    def test_quitar_borra_por_uid_solo_si_estaba_y_lo_anota(self):
        ejecutar(cp.quitar(self.lid, borrar=self.borrar, cfg=CFG))
        self.assertEqual(self.borrados, [])                                                    # no estaba: no se llama al calendario
        self.poner()
        f = ejecutar(cp.quitar(self.lid, borrar=self.borrar, cfg=CFG))
        self.assertEqual((self.borrados, f["calendario_plazo"]), ([(f"plazo-licitacion-{ID}@101.cat", "")], None))
        self.poner()
        ejecutar(embudo.cambiar_estado(self.lid, "descartada", ahora=AHORA))
        self.assertIsNone(ejecutar(cp.quitar(self.lid, borrar=self.borrar, cfg=CFG))["calendario_plazo"])         # también se puede quitar lo resuelto


if __name__ == "__main__":
    unittest.main()
