"""Análisis técnico del pliego: el texto que se envía, la comprobación de las citas y las reglas de envío (sin red ni base de datos)."""
import asyncio
import os
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import _sin_servicios  # noqa: F401

try:
    import psycopg
    from cerebro.licitaciones import analisis_tecnico as A
    from cerebro.licitaciones import pliegos as P
except ImportError as e:      # pragma: no cover
    raise unittest.SkipTest(str(e))

URL = os.environ.get("CEREBRO_TEST_PG")
ESQUEMA = Path(__file__).resolve().parents[2] / "db" / "esquema.sql"
MOTOR = "0b1f7a3e-1111-4222-8333-444444444441"

DOCS = [{"n": 1, "nombre": "Pliego de prescripciones técnicas", "paginas": [(1, "El adjudicatario deberá suministrar equipos con garantía de cinco años como mínimo."), (2, "El plazo de entrega será de 30 días naturales desde la firma del contrato.")]}]


class TestTexto(unittest.TestCase):
    def test_cada_pagina_lleva_su_marca_para_poder_citarla(self):
        t, avisos = A.construir_texto(DOCS)
        self.assertIn("[Documento 1 «Pliego de prescripciones técnicas» · página 2]", t)
        self.assertEqual(avisos, [])

    def test_si_no_cabe_se_recorta_y_se_avisa(self):
        largo = [{"n": 3, "nombre": "PCAP", "paginas": [(i, "x" * 900) for i in range(1, 30)]}]
        t, avisos = A.construir_texto(largo, maximo=5000)
        self.assertLessEqual(len(t), 5000)
        self.assertEqual(len(avisos), 1)
        self.assertIn("documento 3", avisos[0])

    def test_sin_documentos_no_hay_texto(self):
        self.assertEqual(A.construir_texto([]), ("", []))

    def test_el_pliego_va_marcado_como_datos_y_sin_datos_de_la_empresa(self):
        m = A.construir_mensajes("Suministro de cámaras", "Ayto", "texto")
        self.assertEqual([x["role"] for x in m], ["system", "user"])
        self.assertIn("TEXTO DE TERCEROS", m[0]["content"])
        self.assertIn("NO inventes", m[0]["content"])
        self.assertIn("««««\ntexto\n»»»»", m[1]["content"])


class TestVerificar(unittest.TestCase):
    def informe(self, **extra):
        base = {"resumen": "r", "criterios_tecnicos": [], "puntos_fuertes": [], "puntos_debiles": []}
        return {**base, **extra}

    def test_una_cita_real_se_verifica_y_una_inventada_se_marca(self):
        r = A.verificar(self.informe(
            puntos_fuertes=[{"punto": "Garantía clara", "detalle": "d", "documento": 1, "pagina": 1, "cita": "deberá suministrar equipos con garantía de cinco años"}],
            puntos_debiles=[{"punto": "Plazo", "tipo": "plazo_ajustado", "detalle": "d", "documento": 1, "pagina": 2, "cita": "El plazo de entrega será de 90 días hábiles"}]), DOCS)
        self.assertTrue(r["puntos_fuertes"][0]["cita_verificada"])
        self.assertFalse(r["puntos_debiles"][0]["cita_verificada"])
        self.assertEqual(r["citas"], {"total": 2, "verificadas": 1, "sin_verificar": 1})

    def test_documento_o_pagina_que_no_existen_no_se_verifican(self):
        r = A.verificar(self.informe(puntos_fuertes=[{"punto": "a", "detalle": "d", "documento": 9, "pagina": 1, "cita": "deberá suministrar equipos con garantía de cinco años"},
                                                      {"punto": "b", "detalle": "d", "documento": "uno", "pagina": None, "cita": "deberá suministrar equipos con garantía de cinco años"}]), DOCS)
        self.assertEqual([x["cita_verificada"] for x in r["puntos_fuertes"]], [False, False])
        self.assertEqual([x["documento"] for x in r["puntos_fuertes"]], [9, None])

    def test_tipos_desconocidos_y_basura_se_limpian(self):
        r = A.verificar(self.informe(puntos_debiles=[{"punto": "x", "tipo": "inventado", "detalle": "d"}, "no soy un dict", {"punto": "  ", "tipo": "riesgo", "detalle": "d"}],
                                     criterios_tecnicos=[{"criterio": "Calidad", "tipo": "raro"}], preguntas_aclaracion=["¿Qué marca?", "", "  "]), DOCS)
        self.assertEqual([x["tipo"] for x in r["puntos_debiles"]], ["otro"])
        self.assertEqual(r["criterios_tecnicos"][0]["tipo"], "desconocido")
        self.assertEqual(r["preguntas_aclaracion"], ["¿Qué marca?"])


@unittest.skipUnless(URL and hasattr(psycopg, "AsyncConnection"), "sin CEREBRO_TEST_PG")
class TestFlujo(unittest.TestCase):
    def setUp(self):
        self.schema = f"t_atec_{time.time_ns()}"
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"CREATE SCHEMA {self.schema}")
            c.execute(f"SET search_path = {self.schema}")
            t = ESQUEMA.read_text(encoding="utf-8")
            c.execute(t[t.index("-- Pliegos y otros documentos de una licitación"):t.index("CREATE INDEX IF NOT EXISTS pliegos_paginas_tsv")])
            c.execute(t[t.index("CREATE TABLE IF NOT EXISTS analisis_tecnico_pliego"):])
            did = c.execute("INSERT INTO pliegos_documentos (motor_id, n, nombre, formato, bytes, sha256, estado, unidad, paginas) VALUES (%s, 1, 'Pliego de prescripciones técnicas', 'pdf', 10, 'a', 'limpio', 'página', 2) RETURNING id", [MOTOR]).fetchone()[0]
            for pag, texto in DOCS[0]["paginas"]:
                c.execute("INSERT INTO pliegos_paginas (documento_id, pagina, texto) VALUES (%s, %s, %s)", [did, pag, texto])
        sep = "&" if "?" in URL else "?"
        aj = SimpleNamespace(database_url=f"{URL}{sep}options=-csearch_path%3D{self.schema}", dir_config=".")
        self.parches = [mock.patch.object(A, "ajustes", aj), mock.patch.object(P, "ajustes", aj)]
        for p in self.parches:
            p.start()

    def tearDown(self):
        for p in self.parches:
            p.stop()
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"DROP SCHEMA {self.schema} CASCADE")

    def test_reservar_ejecutar_y_leer_el_informe(self):
        def uno(c):
            return asyncio.run(c)
        self.assertIsNone(uno(A.leer(MOTOR)))
        self.assertIsNone(uno(A.reservar(MOTOR, "ana")))
        self.assertEqual(uno(A.reservar(MOTOR, "luis")), "en_curso")                         # dos clics no lo lanzan dos veces
        self.assertEqual(uno(A.leer(MOTOR))["estado"], "en_curso")
        enviado = {}

        async def modelo(agente, mensajes, esquema):
            enviado["texto"] = mensajes[1]["content"]
            return ({"resumen": "Suministro con garantía de cinco años.", "criterios_tecnicos": [{"criterio": "Garantía", "peso": "10 puntos", "tipo": "automatico"}],
                     "puntos_fuertes": [{"punto": "Garantía clara", "detalle": "d", "documento": 1, "pagina": 1, "cita": "deberá suministrar equipos con garantía de cinco años"}],
                     "puntos_debiles": [{"punto": "Plazo", "tipo": "plazo_ajustado", "detalle": "d", "documento": 1, "pagina": 2, "cita": "plazo de entrega de 90 días hábiles"}]}, "claude")
        with mock.patch.object(A.externos, "modelo", lambda p: "claude-prueba"):
            r = uno(A.ejecutar(MOTOR, "Suministro de cámaras", "Ayto", consulta=modelo))
        self.assertEqual(r, {"estado": "hecho", "proveedor": "claude"})
        self.assertIn("[Documento 1", enviado["texto"])
        self.assertNotIn("ana", enviado["texto"])
        a = uno(A.leer(MOTOR))
        self.assertEqual((a["estado"], a["proveedor"], a["modelo"], a["pedido_por"]), ("hecho", "claude", "claude-prueba", "ana"))
        self.assertEqual(a["informe"]["citas"], {"total": 3, "verificadas": 1, "sin_verificar": 2})   # la del plazo es inventada; el criterio no trae cita
        self.assertEqual(a["documentos"], [{"n": 1, "nombre": "Pliego de prescripciones técnicas", "paginas": 2}])
        self.assertEqual(uno(A.reservar(MOTOR, "ana")), "reciente")                           # enfriamiento

    def test_si_no_hay_modelo_conectado_queda_el_motivo_legible(self):
        async def sin_modelo(agente, mensajes, esquema):
            raise A.externos.ErrorExterno("Claude y ChatGPT están desconectados: Dirección los conecta en Agentes → Modelos externos")
        asyncio.run(A.reservar(MOTOR, "ana"))
        r = asyncio.run(A.ejecutar(MOTOR, "t", "o", consulta=sin_modelo))
        self.assertEqual(r["estado"], "error")
        a = asyncio.run(A.leer(MOTOR))
        self.assertEqual(a["estado"], "error")
        self.assertIn("desconectados", a["error"])

    def test_sin_pliegos_descargados_lo_dice(self):
        otro = "0b1f7a3e-1111-4222-8333-444444444442"
        asyncio.run(A.reservar(otro, "ana"))
        r = asyncio.run(A.ejecutar(otro, "t", "o", consulta=None))
        self.assertEqual(r["estado"], "error")
        self.assertIn("pliegos descargados", asyncio.run(A.leer(otro))["error"])


if __name__ == "__main__":
    unittest.main()
