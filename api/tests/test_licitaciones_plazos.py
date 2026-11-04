"""Avisos de plazos urgentes de las licitaciones en estudio: un correo por umbral, solo en horario, a concursos@ con copia a notificaciones@, sin repetir."""
import asyncio
import os
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import _sin_servicios  # noqa: F401

from cerebro.licitaciones import plazos as P

try:
    import psycopg
except ImportError:      # pragma: no cover
    psycopg = None
URL = os.environ.get("CEREBRO_TEST_PG")
ESQUEMA = Path(__file__).resolve().parents[2] / "db" / "esquema.sql"

MADRID_10H = datetime(2026, 11, 4, 9, 0, tzinfo=timezone.utc)        # 10:00 en Madrid (invierno)
CFG = {"plazos": {"avisar_dias": [3, 1, 0], "desde_hora": 7, "hasta_hora": 21}}
CORREO = {"buzon": "notificaciones", "dominios": ["101.cat"], "copia": ["concursos@101.cat", "notificaciones@101.cat"]}


def ejecutar(c):
    return asyncio.run(c)


def item(i, dias, estado="en_estudio", **kw):
    lim = (MADRID_10H + timedelta(days=dias, hours=2)).isoformat() if dias is not None else None
    return {"id": i, "motor_id": f"0b1f7a3e-1111-4222-8333-44444444444{i}", "titulo": f"Licitación {i}", "organismo": "Ayto", "estado": estado, "fecha_limite": lim, "dias_plazo": dias,
            "requisitos": {"borrador": 0, "confirmado": 0}, "bloqueos": 0, **kw}


class TestPuro(unittest.TestCase):
    def test_umbral_es_el_menor_que_cubre_los_dias(self):
        u = [3, 1, 0]
        self.assertEqual([P.umbral(d, u) for d in (5, 4, 3, 2, 1, 0, -1)], [None, None, 3, 3, 1, 0, None])

    def test_configuracion_se_sanea(self):
        c = P.configuracion({"plazos": {"avisar_dias": [1, "x", 3, 3, 99, True], "desde_hora": 30, "hasta_hora": 0}})
        self.assertEqual((c["avisar_dias"], c["desde_hora"], c["hasta_hora"]), ([3, 1], 23, 1))
        self.assertEqual(P.configuracion({})["avisar_dias"], [3, 1, 0])

    def test_horario_local(self):
        c = P.configuracion(CFG)
        self.assertTrue(P.en_horario(MADRID_10H, c, "Europe/Madrid"))
        self.assertFalse(P.en_horario(datetime(2026, 11, 4, 2, 0, tzinfo=timezone.utc), c, "Europe/Madrid"))
        self.assertFalse(P.en_horario(datetime(2026, 11, 4, 21, 0, tzinfo=timezone.utc), c, "Europe/Madrid"))      # 22:00 local

    def test_redactar_ordena_por_plazo_y_dice_lo_que_hay_que_saber(self):
        asunto, cuerpo = P.redactar([item(2, 3), item(1, 0, requisitos={"borrador": 2, "confirmado": 1}, bloqueos=1)], MADRID_10H)
        self.assertIn("2 plazos próximos", asunto)
        self.assertLess(cuerpo.index("Licitación 1"), cuerpo.index("Licitación 2"))
        for x in ("HOY", "en 3 días", "2 requisitos del pliego por revisar", "1 requisitos que probablemente no se cumplen", "/licitaciones/expedientes/0b1f7a3e"):
            self.assertIn(x, cuerpo)
        self.assertIn("1 plazo próximo", P.redactar([item(1, 1)], MADRID_10H)[0])


class TestAvisar(unittest.TestCase):
    def lanzar(self, items, ya=(), ahora=MADRID_10H, correo=CORREO, enviar_falla=False, estado="ok"):
        enviados, anotados = [], []

        async def seg(a, c):
            return {"estado": estado, "total": len(items), "urgentes": 0, "items": items, "aviso": None}

        async def avisados():
            return set(ya)

        async def anotar(pares):
            anotados.extend(pares)

        def enviar(buzon, mensaje):
            if enviar_falla:
                raise OSError("smtp caído")
            enviados.append((buzon, mensaje))
        r = ejecutar(P.avisar(enviar, ahora, CFG, seg, avisados, anotar, correo))
        return r, enviados, anotados

    def test_envia_un_correo_a_concursos_con_copia_y_anota_los_umbrales(self):
        r, enviados, anotados = self.lanzar([item(1, 3), item(2, 5), item(3, 1), item(4, 0, estado="presentada")])
        self.assertEqual(r, {"estado": "enviado", "avisadas": 2})
        self.assertEqual(len(enviados), 1)
        m = enviados[0][1]
        self.assertEqual((enviados[0][0], m["To"], m["Cc"]), ("notificaciones", "concursos@101.cat", "notificaciones@101.cat"))
        self.assertEqual(sorted(anotados), [(1, 3), (3, 1)])             # la de 5 días aún no; la presentada nunca

    def test_no_repite_el_mismo_umbral_pero_si_el_siguiente(self):
        r, enviados, _ = self.lanzar([item(1, 3)], ya=[(1, 3)])
        self.assertEqual((r["estado"], enviados), ("nada", []))
        r, enviados, anotados = self.lanzar([item(1, 1)], ya=[(1, 3)])
        self.assertEqual((r["estado"], anotados), ("enviado", [(1, 1)]))

    def test_fuera_de_horario_sin_destinatarios_o_con_error_no_se_anota_nada(self):
        r, enviados, anotados = self.lanzar([item(1, 1)], ahora=datetime(2026, 11, 4, 2, 0, tzinfo=timezone.utc))
        self.assertEqual((r["estado"], enviados, anotados), ("fuera_de_horario", [], []))
        self.assertEqual(self.lanzar([item(1, 1)], correo={**CORREO, "copia": []})[0]["estado"], "sin_destinatarios")
        self.assertEqual(self.lanzar([item(1, 1)], correo={**CORREO, "copia": ["alguien@gmail.com"]})[0]["estado"], "sin_destinatarios")        # solo de la empresa
        r, enviados, anotados = self.lanzar([item(1, 1)], enviar_falla=True)
        self.assertEqual((r["estado"], anotados), ("error", []))                       # se reintenta en la próxima hora
        self.assertEqual(self.lanzar([item(1, 1)], estado="error")[0]["estado"], "error")


@unittest.skipUnless(URL and psycopg and hasattr(psycopg, "AsyncConnection"), "sin CEREBRO_TEST_PG")
class TestEnBase(unittest.TestCase):
    def setUp(self):
        self.schema = f"t_plz_{time.time_ns()}"
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"CREATE SCHEMA {self.schema}")
            c.execute(f"SET search_path = {self.schema}")
            t = ESQUEMA.read_text(encoding="utf-8")
            c.execute(t[t.index("-- Licitaciones\nCREATE TABLE IF NOT EXISTS licitaciones"):t.index("-- Resumen diario de licitaciones")])
            c.execute("INSERT INTO licitaciones (motor_id, motor_version, expediente, titulo, organismo, estado) VALUES ('0b1f7a3e-1111-4222-8333-444444444441',1,'X','T','O','en_estudio')")
        sep = "&" if "?" in URL else "?"
        self.parche = mock.patch.object(P, "ajustes", SimpleNamespace(database_url=f"{URL}{sep}options=-csearch_path%3D{self.schema}", zona_horaria="Europe/Madrid"))
        self.parche.start()

    def tearDown(self):
        self.parche.stop()
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"DROP SCHEMA {self.schema} CASCADE")

    def test_se_anota_una_vez_por_umbral_y_se_lee_de_vuelta(self):
        self.assertEqual(ejecutar(P._ya_avisados()), set())
        ejecutar(P._anotar([(1, 3), (1, 3), (1, 1)]))            # repetir no falla ni duplica
        self.assertEqual(ejecutar(P._ya_avisados()), {(1, 3), (1, 1)})


if __name__ == "__main__":
    unittest.main()
