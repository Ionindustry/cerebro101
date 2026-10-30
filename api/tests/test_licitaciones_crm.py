"""Seguimiento de las licitaciones en el CRM: los textos y los datos del trato (puros) y el flujo con PostgreSQL real (con CEREBRO_TEST_PG; sin ella, esa parte se omite). El CRM se sustituye por un doble."""
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
    from cerebro.licitaciones import crm, embudo
except ImportError as e:      # pragma: no cover
    raise unittest.SkipTest(str(e))

URL = os.environ.get("CEREBRO_TEST_PG")
ESQUEMA = Path(__file__).resolve().parents[2] / "db" / "esquema.sql"
AHORA = datetime(2026, 10, 28, 14, 0, tzinfo=timezone.utc)
ID = "0b1f7a3e-1111-4222-8333-444444444444"
CFG = {**crm.DEFECTO}


def ejecutar(coro):
    return asyncio.run(coro)


def fila(**kw):
    f = {"id": 1, "motor_id": ID, "titulo": "Videovigilancia del puerto", "organismo": "Ayuntamiento de Girona", "expediente": "2026/045", "importe": 200000.0,
         "enlace": "https://contrataciondelestado.es/x/1", "fecha_limite": "2026-11-20T09:00:00+00:00", "estado": "en_estudio"}
    f.update(kw)
    return f


class TestPuros(unittest.TestCase):
    def test_el_trato_lleva_organismo_etapa_importe_y_plazo(self):
        d = crm.datos_trato(fila(), CFG, "Ayuntamiento de Girona")
        self.assertEqual((d["organization"], d["status"], d["expected_deal_value"], d["expected_closure_date"]),
                         ("Ayuntamiento de Girona", "Proposal/Quotation", 200000.0, "2026-11-20"))
        self.assertIn("2026-11-20", d["next_step"])

    def test_sin_importe_ni_plazo_no_se_inventan(self):
        d = crm.datos_trato(fila(importe=None, fecha_limite=None), CFG, "X")
        self.assertEqual(set(d), {"organization", "status"})

    def test_cada_estado_del_embudo_tiene_etapa(self):
        for e in embudo.ESTADOS:
            self.assertTrue(crm.datos_trato(fila(estado=e), CFG, "X")["status"], e)

    def test_las_etapas_se_pueden_cambiar_por_configuracion(self):
        with mock.patch.object(crm, "ajustes", SimpleNamespace(dir_config=Path(__file__).resolve().parents[2] / "config")):
            c = crm.configuracion()
        self.assertEqual((c["etapas"]["ganada"], c["activo"], c["crear_detectadas"]), ("Won", True, False))

    def test_las_notas_escapan_el_texto_de_terceros(self):
        h = crm.cuerpo_nota("Obras <script>alert(1)</script>\n\nsegunda línea & más")
        self.assertEqual(h, "<p>Obras &lt;script&gt;alert(1)&lt;/script&gt;</p><p>segunda línea &amp; más</p>")

    def test_la_nota_de_alta_lleva_los_datos_de_la_licitacion_y_solo_enlaces_http(self):
        t = crm.nota_de_alta(fila())
        for x in ("Videovigilancia del puerto", "2026/045", "200.000 €", "https://contrataciondelestado.es/x/1"):
            self.assertIn(x, t)
        self.assertNotIn("javascript", crm.nota_de_alta(fila(enlace="javascript:alert(1)")))

    def test_notas_de_cada_hito(self):
        self.assertEqual(crm.nota_de_estado("perdida", "Precio (oferta más cara)", "albert")[0], "Licitación perdida")
        self.assertIn("Motivo: Precio", crm.nota_de_estado("perdida", "Precio (oferta más cara)", "albert")[1])
        titulo, texto = crm.nota_de_redaccion({"estado": "parcial", "error": "", "pasos": [{"id": "memoria", "titulo": "Memoria", "estado": "hecho"}, {"id": "costes", "estado": "error"}]})
        self.assertIn("parte", titulo)
        self.assertIn("- Memoria: hecho", texto)
        self.assertIn("- costes: con error", texto)
        self.assertIn("revisión y aprobación de una persona", texto)
        self.assertIn("125000", crm.nota_de_precio(125000, 21, "albert")[1])

    def test_enlace_al_trato(self):
        self.assertEqual(crm.url_del_trato("CRM-DEAL-2026-00001", {"url_publica": "http://localhost:8081/crm/"}), "http://localhost:8081/crm/deals/CRM-DEAL-2026-00001")
        self.assertIsNone(crm.url_del_trato(None))
        self.assertIsNone(crm.url_del_trato("X", {"url_publica": "javascript:x"}))


class ErpDoble:
    """El ERP/CRM de mentira: guarda lo que se le escribe."""
    def __init__(self, falla=False):
        self.organizaciones, self.tratos, self.notas, self.cambios, self.falla = {}, {}, [], [], falla

    async def listar(self, doctype, dep, filtros=None, campos=None, limite=50):
        assert (doctype, dep) == ("CRM Organization", "licitaciones")
        n = filtros[0][2]
        return [{"name": n}] if n in self.organizaciones else []

    async def crear_maestro(self, doctype, datos, dep):
        if self.falla:
            raise RuntimeError("el CRM no responde")
        if doctype == "CRM Organization":
            self.organizaciones[datos["organization_name"]] = datos
            return {"name": datos["organization_name"]}
        nombre = f"CRM-DEAL-{len(self.tratos) + 1}"
        self.tratos[nombre] = datos
        return {"name": nombre}

    async def modificar(self, doctype, nombre, datos, dep):
        self.cambios.append((doctype, nombre, datos))
        self.tratos[nombre].update(datos)
        return {}

    async def crear_borrador(self, doctype, datos, dep):
        assert doctype == "FCRM Note"
        self.notas.append(datos)
        return {"name": f"N{len(self.notas)}"}


@unittest.skipUnless(URL and hasattr(psycopg, "AsyncConnection"), "sin CEREBRO_TEST_PG")
class TestEnBase(unittest.TestCase):
    def setUp(self):
        self.schema = f"t_crm_{time.time_ns()}"
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"CREATE SCHEMA {self.schema}")
            c.execute(f"SET search_path = {self.schema}")
            t = ESQUEMA.read_text(encoding="utf-8")
            c.execute(t[t.index("-- Licitaciones\nCREATE TABLE IF NOT EXISTS licitaciones"):t.index("-- Resumen diario de licitaciones")])
        sep = "&" if "?" in URL else "?"
        ajustes = SimpleNamespace(database_url=f"{URL}{sep}options=-csearch_path%3D{self.schema}", zona_horaria="Europe/Madrid", dir_config=ESQUEMA.parent.parent / "config")
        self.parches = [mock.patch.object(embudo, "ajustes", ajustes), mock.patch.object(crm, "ajustes", ajustes)]
        for p in self.parches:
            p.start()
        d = {"motor_id": ID, "motor_version": 1, "expediente": "2026/045", "organismo": "Girona", "titulo": "Videovigilancia", "cpv": ["32323500"], "importe": 100000,
             "fecha_limite": "2026-11-20T09:00:00+00:00", "enlace": None, "encaje": 80, "estado_motor": "abierta"}
        ejecutar(embudo.registrar_detectada(d, AHORA))
        self.lid = ejecutar(embudo.listar())[0]["id"]
        self.erp = ErpDoble()
        self.p_erp = mock.patch.object(crm, "_erp", lambda: self.erp)
        self.p_erp.start()

    def tearDown(self):
        self.p_erp.stop()
        for p in self.parches:
            p.stop()
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"DROP SCHEMA {self.schema} CASCADE")

    def test_una_detectada_no_crea_trato_pero_una_en_estudio_si_y_una_sola_vez(self):
        self.assertIsNone(ejecutar(crm.anotar(self.lid, "Hola")))
        self.assertEqual((self.erp.tratos, self.erp.notas), ({}, []))
        ejecutar(embudo.cambiar_estado(self.lid, "en_estudio", ahora=AHORA))
        t = ejecutar(crm.anotar(self.lid, "Se decide estudiarla", "Decidido por: albert"))
        self.assertEqual(t, "CRM-DEAL-1")
        self.assertEqual(self.erp.tratos[t]["status"], "Proposal/Quotation")
        self.assertIn("Girona", self.erp.organizaciones)
        self.assertEqual([n["title"] for n in self.erp.notas], ["Licitación en seguimiento", "Se decide estudiarla"])
        self.assertTrue(all((n["reference_doctype"], n["reference_docname"]) == ("CRM Deal", t) for n in self.erp.notas))
        self.assertEqual(ejecutar(crm.anotar(self.lid, "Otra cosa")), t)               # no se duplica el trato
        self.assertEqual(len(self.erp.tratos), 1)
        self.assertEqual(ejecutar(embudo.obtener(self.lid))["crm"], {"trato": t, "etapa": "Proposal/Quotation"})

    def test_al_cambiar_de_estado_el_trato_cambia_de_etapa(self):
        ejecutar(embudo.cambiar_estado(self.lid, "en_estudio", ahora=AHORA))
        t = ejecutar(crm.anotar(self.lid, ""))
        ejecutar(embudo.cambiar_estado(self.lid, "presentada", ahora=AHORA))
        ejecutar(crm.anotar(self.lid, "Oferta presentada"))
        ejecutar(embudo.cambiar_estado(self.lid, "ganada", ahora=AHORA))
        ejecutar(crm.anotar(self.lid, "Licitación ganada"))
        self.assertEqual([c[2]["status"] for c in self.erp.cambios], ["Negotiation", "Won"])
        self.assertEqual(ejecutar(embudo.obtener(self.lid))["crm"]["etapa"], "Won")
        self.assertEqual(len(self.erp.tratos), 1, t)

    def test_descartada_sin_estudiar_no_crea_trato(self):
        ejecutar(embudo.cambiar_estado(self.lid, "descartada", ahora=AHORA))
        self.assertIsNone(ejecutar(crm.anotar(self.lid, "Descartada")))
        self.assertEqual(self.erp.tratos, {})

    def test_si_el_crm_falla_no_falla_nada_y_se_reintenta_despues(self):
        ejecutar(embudo.cambiar_estado(self.lid, "en_estudio", ahora=AHORA))
        self.erp.falla = True
        self.assertIsNone(ejecutar(crm.anotar(self.lid, "Se decide estudiarla")))
        self.assertIsNone(ejecutar(embudo.obtener(self.lid))["crm"])
        self.erp.falla = False
        self.assertEqual(ejecutar(crm.anotar(self.lid, "Se decide estudiarla")), "CRM-DEAL-1")

    def test_apagado_por_configuracion_no_toca_el_crm(self):
        ejecutar(embudo.cambiar_estado(self.lid, "en_estudio", ahora=AHORA))
        self.assertIsNone(ejecutar(crm.anotar(self.lid, "x", cfg={**CFG, "activo": False})))
        self.assertEqual(self.erp.tratos, {})

    def test_por_identificador_del_motor(self):
        ejecutar(embudo.cambiar_estado(self.lid, "en_estudio", ahora=AHORA))
        self.assertEqual(ejecutar(crm.anotar_por_oferta(ID, "Precio de la oferta fijado", "Precio sin IVA: 1 €")), "CRM-DEAL-1")
        self.assertIsNone(ejecutar(crm.anotar_por_oferta("11111111-1111-4111-8111-111111111111", "x")))      # no está en el embudo: nada


if __name__ == "__main__":
    unittest.main()
