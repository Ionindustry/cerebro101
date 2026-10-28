"""Embudo propio en PostgreSQL real. Necesita CEREBRO_TEST_PG (dirección de una base de pruebas); sin ella se omite. Cada prueba usa un esquema propio."""
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
    from cerebro.licitaciones import embudo
except ImportError as e:      # pragma: no cover
    raise unittest.SkipTest(str(e))

URL = os.environ.get("CEREBRO_TEST_PG")
ESQUEMA = Path(__file__).resolve().parents[2] / "db" / "esquema.sql"
AHORA = datetime(2026, 10, 28, 14, 0, tzinfo=timezone.utc)
ID = "0b1f7a3e-1111-4222-8333-444444444444"
CFG = {"pesos": {"cpv": 40, "zona": 20, "importe": 15, "plazo": 15, "procedimiento": 10}, "importe_max": 1_000_000,
       "cpv": [{"codigo": "32000000", "area": "Videovigilancia"}], "zona": {"prioritaria": "ES51", "pais": "ES"}}


def ejecutar(coro):
    return asyncio.run(coro)


def ficha(id=ID, **kw):
    f = {"id": id, "version_entidad": 1, "expediente": "2026/045", "titulo": "Videovigilancia", "comprador": {"nombre": "Girona"}, "estado": "abierta",
         "procedimiento": "abierto", "cpv": ["32323500"], "nuts": ["ES512"], "plazos": {"presentacion": "2026-11-20T10:00:00Z"},
         "importes": [{"valor": "200000.00", "moneda": "EUR", "impuestos": "sin_iva", "significado": "valor_estimado"}]}
    f.update(kw)
    return f


def motor_con(f):
    async def consulta(ruta, params=None):
        return f
    return consulta


@unittest.skipUnless(URL and hasattr(psycopg, "AsyncConnection"), "sin CEREBRO_TEST_PG")
class TestEmbudoEnBase(unittest.TestCase):
    def setUp(self):
        self.schema = f"t_embudo_{time.time_ns()}"
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"CREATE SCHEMA {self.schema}")
            c.execute(f"SET search_path = {self.schema}")
            texto = ESQUEMA.read_text(encoding="utf-8")
            ini = texto.index("-- Licitaciones\nCREATE TABLE IF NOT EXISTS licitaciones")
            fin = texto.index("-- Resumen diario de licitaciones")
            self.bloque = texto[ini:fin]
            c.execute(self.bloque)
        sep = "&" if "?" in URL else "?"
        self.url = f"{URL}{sep}options=-csearch_path%3D{self.schema}"
        self.parches = [mock.patch.object(embudo, "ajustes", SimpleNamespace(database_url=self.url, zona_horaria="Europe/Madrid")),
                        mock.patch.object(embudo.resumen_mod, "config", lambda: CFG)]
        for p in self.parches:
            p.start()

    def tearDown(self):
        for p in self.parches:
            p.stop()
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"DROP SCHEMA {self.schema} CASCADE")

    def estudiar(self, f=None, ahora=AHORA):
        return ejecutar(embudo.estudiar(ID, consulta=motor_con(f or ficha()), ahora=ahora))

    def test_el_esquema_se_puede_aplicar_dos_veces(self):
        with psycopg.connect(self.url, autocommit=True) as c:
            c.execute(self.bloque)
            c.execute(self.bloque)

    def test_estudiar_crea_la_fila_en_estudio_con_los_datos_del_motor(self):
        r = self.estudiar()
        self.assertEqual((r["estado"], r["motor_id"], r["expediente"], r["organismo"], r["importe"]), ("en_estudio", ID, "2026/045", "Girona", 200000.0))
        self.assertEqual((r["cpv"], r["decidida_en"], r["presentada_en"]), (["32323500"], AHORA.isoformat(), None))
        self.assertGreater(r["encaje"], 50)

    def test_estudiar_dos_veces_no_duplica_y_no_pisa_el_estado_de_la_gente(self):
        a = self.estudiar()
        ejecutar(embudo.cambiar_estado(a["id"], "presentada", ahora=AHORA + timedelta(hours=1)))
        b = self.estudiar(ficha(titulo="Videovigilancia (corregido)", version_entidad=2), AHORA + timedelta(hours=2))
        self.assertEqual((b["id"], b["estado"], b["titulo"], b["motor_version"]), (a["id"], "presentada", "Videovigilancia (corregido)", 2))
        self.assertEqual(len(ejecutar(embudo.listar())), 1)

    def test_dos_organismos_con_el_mismo_codigo_de_expediente_son_dos_filas(self):
        self.estudiar()
        otro = "11111111-2222-4333-8444-555555555555"
        ejecutar(embudo.estudiar(otro, consulta=motor_con(ficha(otro)), ahora=AHORA))
        self.assertEqual(len(ejecutar(embudo.listar())), 2)

    def test_ciclo_completo_con_fechas_y_motivo(self):
        r = self.estudiar()
        r = ejecutar(embudo.cambiar_estado(r["id"], "presentada", ahora=AHORA + timedelta(days=1)))
        self.assertEqual((r["estado"], r["presentada_en"]), ("presentada", (AHORA + timedelta(days=1)).isoformat()))
        r = ejecutar(embudo.cambiar_estado(r["id"], "perdida", "precio", ahora=AHORA + timedelta(days=9)))
        self.assertEqual((r["estado"], r["motivo_perdida"], r["resuelta_en"]), ("perdida", "precio", (AHORA + timedelta(days=9)).isoformat()))
        self.assertEqual(r["motivo_perdida_texto"], embudo.MOTIVOS_PERDIDA["precio"])

    def test_un_cambio_no_permitido_no_toca_nada(self):
        r = self.estudiar()
        with self.assertRaises(embudo.ErrorEmbudo):
            ejecutar(embudo.cambiar_estado(r["id"], "ganada"))
        with self.assertRaises(embudo.ErrorEmbudo):
            ejecutar(embudo.cambiar_estado(r["id"], "presentada", "precio"))
        self.assertEqual(ejecutar(embudo.listar())[0]["estado"], "en_estudio")
        with self.assertRaises(embudo.NoExiste):
            ejecutar(embudo.cambiar_estado(99999, "presentada"))

    def test_la_base_rechaza_un_estado_inventado(self):
        r = self.estudiar()
        with psycopg.connect(self.url, autocommit=True) as c, self.assertRaises(psycopg.errors.CheckViolation):
            c.execute("UPDATE licitaciones SET estado = 'volando' WHERE id = %s", [r["id"]])

    def test_listar_filtra_por_estado_y_por_expediente_del_motor(self):
        r = self.estudiar()
        otro = "11111111-2222-4333-8444-555555555555"
        ejecutar(embudo.estudiar(otro, consulta=motor_con(ficha(otro)), ahora=AHORA))
        ejecutar(embudo.cambiar_estado(r["id"], "descartada", ahora=AHORA))
        self.assertEqual([x["motor_id"] for x in ejecutar(embudo.listar("descartada"))], [ID])
        self.assertEqual([x["motor_id"] for x in ejecutar(embudo.listar(motor_id=otro))], [otro])
        with self.assertRaises(embudo.ErrorEmbudo):
            ejecutar(embudo.listar("volando"))
        with self.assertRaises(embudo.ErrorEmbudo):
            ejecutar(embudo.listar(motor_id="no-es-uuid"))

    def test_resumen_con_datos_reales(self):
        r = self.estudiar()
        ejecutar(embudo.cambiar_estado(r["id"], "presentada", ahora=datetime.now(timezone.utc) - timedelta(hours=2)))
        res = ejecutar(embudo.resumen(7))
        self.assertEqual(res["por_estado"]["presentada"], 1)
        self.assertEqual(res["en_periodo"]["presentadas"], 1)
        self.assertEqual(res["viabilidad"]["informes"], 0)
        with self.assertRaises(embudo.ErrorEmbudo):
            ejecutar(embudo.resumen(0))

    def test_resumen_cuenta_los_informes_de_viabilidad_y_lo_que_hizo_la_gente(self):
        r = self.estudiar()
        informe = {"recomendacion": "ir", "generado": datetime.now(timezone.utc).isoformat()}
        self.assertTrue(ejecutar(embudo.guardar_viabilidad(r["id"], informe)))
        ejecutar(embudo.cambiar_estado(r["id"], "presentada", ahora=datetime.now(timezone.utc)))
        v = ejecutar(embudo.resumen(7))["viabilidad"]
        self.assertEqual((v["informes"], v["por_recomendacion"]["ir"]["seguidos"], v["por_recomendacion"]["ir"]["pendientes"]), (1, 1, 0))

    # ---- Lo que escribe el consumidor de eventos ----

    def datos(self, **kw):
        d = embudo.datos_de_resumen({"id": ID, "version_entidad": 1, "expediente": "2026/045", "titulo": "Videovigilancia", "comprador": {"nombre": "Girona"},
                                     "estado": "abierta", "procedimiento": "abierto", "cpv": ["32323500"], "nuts": ["ES512"], "plazo_presentacion": "2026-11-20T10:00:00Z",
                                     "importe": {"valor": "200000.00", "moneda": "EUR"}}, CFG, AHORA)
        d.pop("fuera_de_importe")
        d.update(kw)
        return d

    def test_registrar_detectada_crea_y_una_reentrega_no_duplica(self):
        self.assertIs(ejecutar(embudo.registrar_detectada(self.datos(), AHORA)), True)
        self.assertIs(ejecutar(embudo.registrar_detectada(self.datos(motor_version=2, titulo="Corregido"), AHORA)), False)     # versión nueva: refresca
        self.assertIsNone(ejecutar(embudo.registrar_detectada(self.datos(motor_version=2, titulo="Otra vez"), AHORA)))         # misma versión: nada
        self.assertIsNone(ejecutar(embudo.registrar_detectada(self.datos(motor_version=1, titulo="Vieja"), AHORA)))            # anterior: nada
        filas = ejecutar(embudo.listar())
        self.assertEqual([(f["estado"], f["titulo"], f["motor_version"], f["estado_motor"]) for f in filas], [("detectada", "Corregido", 2, "abierta")])

    def test_registrar_detectada_nunca_pisa_el_estado_que_puso_una_persona(self):
        r = self.estudiar()                                                                     # una persona la pasa a estudio
        ejecutar(embudo.cambiar_estado(r["id"], "presentada", ahora=AHORA))
        ejecutar(embudo.registrar_detectada(self.datos(motor_version=5, titulo="Nueva versión"), AHORA))
        f = ejecutar(embudo.listar())[0]
        self.assertEqual((f["estado"], f["titulo"], f["motor_version"]), ("presentada", "Nueva versión", 5))

    def test_estado_del_motor_solo_si_ya_esta_en_el_embudo(self):
        self.assertIsNone(ejecutar(embudo.actualizar_estado_motor(ID, 2, "adjudicada", AHORA)))
        self.assertEqual(ejecutar(embudo.listar()), [])

    def test_una_adjudicada_se_anota_pero_no_cambia_el_estado_de_la_gente(self):
        ejecutar(embudo.registrar_detectada(self.datos(), AHORA))
        self.assertEqual(ejecutar(embudo.actualizar_estado_motor(ID, 2, "adjudicada", AHORA)), "detectada")
        f = ejecutar(embudo.listar())[0]
        self.assertEqual((f["estado"], f["estado_motor"], f["motor_version"]), ("detectada", "adjudicada", 2))

    def test_una_detectada_que_se_anula_pasa_sola_a_descartada_pero_una_en_estudio_no(self):
        ejecutar(embudo.registrar_detectada(self.datos(), AHORA))
        self.assertEqual(ejecutar(embudo.actualizar_estado_motor(ID, 2, "anulada", AHORA)), "descartada")
        otro = "11111111-2222-4333-8444-555555555555"
        ejecutar(embudo.estudiar(otro, consulta=motor_con(ficha(otro)), ahora=AHORA))
        self.assertEqual(ejecutar(embudo.actualizar_estado_motor(otro, 2, "anulada", AHORA)), "en_estudio")      # la gente decide qué hacer con ella
        self.assertEqual(ejecutar(embudo.listar(motor_id=otro))[0]["estado_motor"], "anulada")

    def test_un_evento_viejo_no_pisa_un_estado_mas_reciente(self):
        ejecutar(embudo.registrar_detectada(self.datos(), AHORA))
        ejecutar(embudo.actualizar_estado_motor(ID, 4, "formalizada", AHORA))
        self.assertIsNone(ejecutar(embudo.actualizar_estado_motor(ID, 2, "abierta", AHORA)))
        self.assertEqual(ejecutar(embudo.listar())[0]["estado_motor"], "formalizada")


if __name__ == "__main__":
    unittest.main()
