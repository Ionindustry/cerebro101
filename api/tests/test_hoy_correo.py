"""Resumen de «Hoy» por correo: solo en día laborable y dentro de la ventana, una vez al día, solo si hay algo urgente o por mirar, a concursos@ con copia a notificaciones@."""
import asyncio
import os
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import _sin_servicios  # noqa: F401

try:
    import psycopg
    from cerebro import hoy_correo as HC
except ImportError as e:      # pragma: no cover
    raise unittest.SkipTest(str(e))

URL = os.environ.get("CEREBRO_TEST_PG")
ESQUEMA = Path(__file__).resolve().parents[2] / "db" / "esquema.sql"
JUEVES_09H = datetime(2026, 11, 5, 8, 0, tzinfo=timezone.utc)        # 09:00 en Madrid
CFG = {"resumen_hoy": {"desde": "08:30", "hasta_hora": 12, "url_panel": "http://localhost:3000"}}
CORREO = {"buzon": "notificaciones", "dominios": ["101.cat"], "copia": ["concursos@101.cat", "notificaciones@101.cat"]}


def ejecutar(c):
    return asyncio.run(c)


def it(nivel, titulo, detalle="", href="/licitaciones"):
    return {"nivel": nivel, "categoria": "licitaciones", "titulo": titulo, "detalle": detalle, "href": href}


def lista(*items):
    return {"items": list(items), "urgentes": sum(1 for i in items if i["nivel"] == "urgente"), "avisos": [], "secciones": {}}


class TestPuros(unittest.TestCase):
    def test_ventana_solo_laborables_y_entre_la_hora_y_el_limite(self):
        c = HC.configuracion(CFG)
        z = "Europe/Madrid"
        self.assertTrue(HC.toca(JUEVES_09H, c, z))
        self.assertFalse(HC.toca(datetime(2026, 11, 5, 7, 0, tzinfo=timezone.utc), c, z))        # 08:00 local: aún no
        self.assertFalse(HC.toca(datetime(2026, 11, 5, 11, 0, tzinfo=timezone.utc), c, z))       # 12:00 local: ya no
        self.assertFalse(HC.toca(datetime(2026, 11, 7, 8, 0, tzinfo=timezone.utc), c, z))        # sábado
        self.assertTrue(HC.toca(datetime(2026, 11, 5, 7, 30, tzinfo=timezone.utc), c, z))        # 08:30 en punto

    def test_configuracion_se_sanea(self):
        c = HC.configuracion({"resumen_hoy": {"desde": "basura", "hasta_hora": 99, "url_panel": "javascript:x"}})
        self.assertEqual((c["_minutos"], c["hasta_hora"], c["url_panel"]), (8 * 60 + 30, 24, "http://localhost:3000"))
        self.assertEqual(HC.configuracion({"resumen_hoy": {"url_panel": "https://jarvis.101.cat/"}})["url_panel"], "https://jarvis.101.cat")

    def test_redactar_agrupa_por_urgencia_con_enlaces_y_sin_marcas_de_terceros(self):
        asunto, cuerpo = HC.redactar(lista(it("urgente", "Plazo mañana: Obra X", "Ayto", "/licitaciones/expedientes/abc"), it("aviso", "5 requisitos por revisar"), it("info", "7 oportunidades nuevas")),
                                     JUEVES_09H, HC.configuracion(CFG))
        self.assertEqual(asunto, "Licitaciones hoy: 1 urgente y 1 por mirar")
        self.assertLess(cuerpo.index("URGENTE"), cuerpo.index("HAY QUE MIRARLO"))
        self.assertLess(cuerpo.index("HAY QUE MIRARLO"), cuerpo.index("PARA TU INFORMACIÓN"))
        self.assertIn("http://localhost:3000/licitaciones/expedientes/abc", cuerpo)
        self.assertIn("(05/11/2026)", cuerpo)
        self.assertEqual(HC.redactar(lista(it("aviso", "a")), JUEVES_09H, HC.configuracion(CFG))[0], "Licitaciones hoy: 1 cosa por mirar")
        self.assertEqual(HC.redactar(lista(it("aviso", "a"), it("aviso", "b")), JUEVES_09H, HC.configuracion(CFG))[0], "Licitaciones hoy: 2 cosas por mirar")


class TestEnviar(unittest.TestCase):
    def lanzar(self, items, ahora=JUEVES_09H, ya=False, correo=CORREO, cfg=CFG, falla=False):
        enviados, anotados = [], []

        async def l():
            return lista(*items)

        async def ya_enviado(a, z):
            return ya

        async def anotar(a, d):
            anotados.append(d)

        def enviar(buzon, mensaje):
            if falla:
                raise OSError("smtp caído")
            enviados.append((buzon, mensaje))
        r = ejecutar(HC.enviar(enviar, ahora, cfg, l, ya_enviado, anotar, correo))
        return r, enviados, anotados

    def test_envia_a_concursos_con_copia_y_anota(self):
        r, enviados, anotados = self.lanzar([it("urgente", "Plazo HOY: X"), it("info", "novedad")])
        self.assertEqual(r, {"estado": "enviado", "urgentes": 1})
        m = enviados[0][1]
        self.assertEqual((enviados[0][0], m["To"], m["Cc"]), ("notificaciones", "concursos@101.cat", "notificaciones@101.cat"))
        self.assertIn("1 urgente", m["Subject"])
        self.assertEqual(len(anotados), 1)

    def test_no_envia_si_solo_hay_novedades_o_nada_ni_fuera_de_ventana_ni_dos_veces_ni_desactivado(self):
        self.assertEqual(self.lanzar([it("info", "n")])[0]["estado"], "nada")
        self.assertEqual(self.lanzar([])[0]["estado"], "nada")
        self.assertEqual(self.lanzar([it("urgente", "a")], ahora=datetime(2026, 11, 7, 8, 0, tzinfo=timezone.utc))[0]["estado"], "fuera_de_ventana")
        self.assertEqual(self.lanzar([it("urgente", "a")], ya=True)[0]["estado"], "ya_enviado")
        self.assertEqual(self.lanzar([it("urgente", "a")], cfg={"resumen_hoy": {"activo": False}})[0]["estado"], "desactivado")

    def test_sin_destinatarios_validos_o_con_el_correo_caido_no_se_anota(self):
        self.assertEqual(self.lanzar([it("urgente", "a")], correo={**CORREO, "copia": []})[0]["estado"], "sin_destinatarios")
        self.assertEqual(self.lanzar([it("urgente", "a")], correo={**CORREO, "copia": ["alguien@gmail.com"]})[0]["estado"], "sin_destinatarios")        # solo de la empresa
        r, enviados, anotados = self.lanzar([it("urgente", "a")], falla=True)
        self.assertEqual((r["estado"], anotados), ("error", []))                          # se reintenta a la hora siguiente


@unittest.skipUnless(URL and hasattr(psycopg, "AsyncConnection"), "sin CEREBRO_TEST_PG")
class TestEnBase(unittest.TestCase):
    def setUp(self):
        self.schema = f"t_hc_{time.time_ns()}"
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"CREATE SCHEMA {self.schema}")
            c.execute(f"SET search_path = {self.schema}")
            t = ESQUEMA.read_text(encoding="utf-8")
            c.execute(t[t.index("-- Avisos de vigilancia del sistema (api/cerebro/antivirus.py)"):t.index("-- Resumen diario de licitaciones")])
        sep = "&" if "?" in URL else "?"
        self.parche = mock.patch.object(HC, "ajustes", SimpleNamespace(database_url=f"{URL}{sep}options=-csearch_path%3D{self.schema}", zona_horaria="Europe/Madrid"))
        self.parche.start()

    def tearDown(self):
        self.parche.stop()
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"DROP SCHEMA {self.schema} CASCADE")

    def test_se_anota_por_dia_local(self):
        self.assertFalse(ejecutar(HC._enviado_hoy(JUEVES_09H, "Europe/Madrid")))
        ejecutar(HC._anotar(JUEVES_09H, "asunto"))
        self.assertTrue(ejecutar(HC._enviado_hoy(datetime(2026, 11, 5, 10, 30, tzinfo=timezone.utc), "Europe/Madrid")))
        self.assertFalse(ejecutar(HC._enviado_hoy(datetime(2026, 11, 6, 8, 0, tzinfo=timezone.utc), "Europe/Madrid")))          # otro día
        ejecutar(HC._anotar(datetime(2026, 11, 6, 8, 0, tzinfo=timezone.utc), "otro"))                                           # repetir actualiza, no duplica


if __name__ == "__main__":
    unittest.main()
