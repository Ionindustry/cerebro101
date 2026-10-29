"""Ofertas de licitación: esqueleto desde el pliego, reglas de los agentes, historial, precio, cobertura y Word (con CEREBRO_TEST_PG para la parte de base de datos)."""
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
    from cerebro.herramientas import documentos
    from cerebro.licitaciones import ofertas as O, pliegos
except ImportError as e:      # pragma: no cover
    raise unittest.SkipTest(str(e))

URL = os.environ.get("CEREBRO_TEST_PG")
ESQUEMA = Path(__file__).resolve().parents[2] / "db" / "esquema.sql"
ID = "0b1f7a3e-1111-4222-8333-444444444444"
OTRO = "1c2f7a3e-1111-4222-8333-444444444444"


def ejecutar(c):
    return asyncio.run(c)


def req(i, tipo, resumen="Algo", pagina=3, **kw):
    return {"id": i, "tipo": tipo, "resumen": resumen, "pagina": pagina, "estado": "confirmado", "documento": 1, "cumplimiento": "pendiente", **kw}


FICHA = {"criterios": [{"tipo": "SUBJ", "descripcion": "Memoria técnica y plan de trabajo", "peso": 30}, {"tipo": "SUBJ", "descripcion": "Mejoras propuestas", "peso": 10},
                       {"tipo": "OBJ", "descripcion": "Oferta económica (precio)", "peso": 51}, {"tipo": "OBJ", "descripcion": "Ampliación de la garantía", "peso": 9}]}


class TestEsqueleto(unittest.TestCase):
    def test_sale_del_pliego(self):
        sec = O.esqueleto(FICHA, [req(1, "tecnico", "Cámaras 4K"), req(2, "solvencia_economica"), req(3, "administrativo", "Estar al corriente de pago")])
        por_sobre = {s: [x["clave"] for x in sec if x["sobre"] == s] for s in O.SOBRES}
        self.assertEqual(por_sobre["tecnico"], ["descripcion-solucion", "crit-1", "crit-2"])
        self.assertEqual(por_sobre["economico"], ["proposicion-economica", "criterios-automaticos", "justificacion-precio"])
        self.assertEqual(por_sobre["administrativo"], ["declaracion-responsable", "solvencia", "otros-documentos"])
        crit = next(s for s in sec if s["clave"] == "crit-1")
        self.assertIn("30 puntos", crit["guia"])
        self.assertIn("[1] Cámaras 4K", next(s for s in sec if s["clave"] == "descripcion-solucion")["guia"])
        auto = next(s for s in sec if s["clave"] == "criterios-automaticos")["guia"]
        self.assertIn("garantía", auto)
        self.assertNotIn("precio", auto.lower())                                      # el precio no es un criterio automático más

    def test_sin_criterios_hay_secciones_por_defecto_y_sin_pliego_no_falla(self):
        sec = O.esqueleto({}, [])
        self.assertEqual([s["clave"] for s in sec if s["sobre"] == "tecnico"], ["descripcion-solucion", "plan-de-trabajo", "equipo-y-medios", "mantenimiento-y-garantia"])
        self.assertEqual([s["orden"] for s in sec if s["sobre"] == "tecnico"], [1, 2, 3, 4])
        self.assertNotIn("criterios-automaticos", [s["clave"] for s in sec])


class TestCobertura(unittest.TestCase):
    def test_lo_no_citado_queda_a_la_vista(self):
        reqs = [req(1, "tecnico"), req(2, "criterio_juicio_valor"), req(3, "administrativo")]
        c = O.cobertura([{"citas": [1]}, {"citas": []}], reqs)
        self.assertEqual((c["requisitos_tecnicos"], [x["id"] for x in c["sin_cubrir"]]), (2, [2]))


class TestPrecioYWord(unittest.TestCase):
    def test_proposicion(self):
        self.assertIn("PRECIO PENDIENTE", O.proposicion_texto({"precio_sin_iva": None}))
        t = O.proposicion_texto({"precio_sin_iva": 100000.0, "iva_pct": 21})
        self.assertIn("100.000,00 €", t)
        self.assertIn("121.000,00 €", t)

    def test_docx_se_lee_de_vuelta_y_escapa_el_xml(self):
        x = O._p("Oferta <& \x00 'prueba'>", "Title") + O._p("Texto con ñ y acentos áéí") + "".join(O._parrafos("- uno\n- dos\n\nOtro párrafo\ncontinúa")) + O._tabla([["R", "C"], ["x", "y"]])
        texto, _ = documentos.extraer_texto("oferta.docx", O.construir_docx(x))
        for esperado in ("Oferta <&  'prueba'>", "ñ y acentos áéí", "• uno", "• dos", "Otro párrafo continúa", "R", "y"):
            self.assertIn(esperado, texto)


@unittest.skipUnless(URL and hasattr(psycopg, "AsyncConnection"), "sin CEREBRO_TEST_PG")
class TestBaseDeDatos(unittest.TestCase):
    def setUp(self):
        self.schema = f"t_ofertas_{time.time_ns()}"
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"CREATE SCHEMA {self.schema}")
            c.execute(f"SET search_path = {self.schema}")
            t = ESQUEMA.read_text(encoding="utf-8")
            c.execute(t[t.index("-- Pliegos y otros documentos de una licitación"):])
            d = c.execute("INSERT INTO pliegos_documentos (motor_id, n, nombre, formato, bytes, sha256, estado) VALUES (%s,1,'PCAP','pdf',1,'aa','limpio') RETURNING id", [ID]).fetchone()[0]
            self.ids = {}
            for k, tipo, estado in (("tec", "tecnico", "confirmado"), ("jv", "criterio_juicio_valor", "confirmado"), ("adm", "administrativo", "confirmado"), ("borr", "tecnico", "borrador")):
                self.ids[k] = c.execute("INSERT INTO pliegos_requisitos (documento_id, pagina, tipo, resumen, cita, estado) VALUES (%s,2,%s,%s,%s,%s) RETURNING id", [d, tipo, f"Requisito {k}", f"cita {k}", estado]).fetchone()[0]
        sep = "&" if "?" in URL else "?"
        ajustes = SimpleNamespace(database_url=f"{URL}{sep}options=-csearch_path%3D{self.schema}")
        self.p = [mock.patch.object(O, "ajustes", ajustes), mock.patch.object(pliegos, "ajustes", ajustes)]
        for p in self.p:
            p.start()

    def tearDown(self):
        for p in self.p:
            p.stop()
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"DROP SCHEMA {self.schema} CASCADE")

    def preparar(self):
        return ejecutar(O.plan(ID, FICHA, "albert"))

    def test_plan_es_idempotente_y_no_toca_el_contenido(self):
        o = self.preparar()
        n = len(o["secciones"])
        self.assertTrue(o["existe"])
        ejecutar(O.escribir_seccion(ID, "tecnico", "crit-1", "Texto del agente", agente="redactor-memoria"))
        o = self.preparar()
        self.assertEqual(len(o["secciones"]), n)
        self.assertEqual(next(s for s in o["secciones"] if s["clave"] == "crit-1")["contenido"], "Texto del agente")
        self.assertFalse(ejecutar(O.leer(OTRO))["existe"])

    def test_el_agente_escribe_borradores_con_citas_reales(self):
        self.preparar()
        s = ejecutar(O.escribir_seccion(ID, "tecnico", "descripcion-solucion", "Memoria\n\nSegundo párrafo", citas=[self.ids["tec"], self.ids["jv"]], agente="arquitecto-solucion"))
        self.assertEqual((s["estado"], s["version"], s["por"]), ("borrador", 1, "agente:arquitecto-solucion"))
        self.assertEqual(s["citas"], sorted([self.ids["tec"], self.ids["jv"]]))
        for malas in ([999999], [self.ids["borr"]], ["x"], True):
            with self.assertRaises(O.ErrorOferta, msg=str(malas)):                      # inventadas, sin confirmar o mal formadas
                ejecutar(O.escribir_seccion(ID, "tecnico", "crit-1", "x", citas=malas, agente="a"))
        c = ejecutar(O.leer(ID))["cobertura"]
        self.assertEqual([x["id"] for x in c["sin_cubrir"]], [])                         # los dos requisitos técnicos están citados

    def test_limites_del_agente(self):
        self.preparar()
        with self.assertRaisesRegex(O.ErrorOferta, "proposición económica"):
            ejecutar(O.escribir_seccion(ID, "economico", O.PROPOSICION, "x", agente="precio-licitacion"))
        with self.assertRaisesRegex(O.ErrorOferta, "económico solo"):
            ejecutar(O.escribir_seccion(ID, "economico", "nueva", "x", titulo="Nueva", agente="precio-licitacion"))
        with self.assertRaisesRegex(O.ErrorOferta, "indica un titulo"):
            ejecutar(O.escribir_seccion(ID, "tecnico", "anexo", "x", agente="redactor-memoria"))
        n = ejecutar(O.escribir_seccion(ID, "tecnico", "anexo", "x", titulo="Anexo técnico", agente="redactor-memoria"))
        self.assertEqual(n["titulo"], "Anexo técnico")
        with self.assertRaises(O.ErrorOferta):
            ejecutar(O.escribir_seccion(ID, "tecnico", "Mal Clave", "x", agente="a"))
        with self.assertRaises(O.ErrorOferta):
            ejecutar(O.escribir_seccion(ID, "tecnico", "crit-1", "x" * (O.CONTENIDO_MAX + 1), agente="a"))
        with self.assertRaises(O.ErrorOferta):
            ejecutar(O.escribir_seccion(ID, "tecnico", "crit-1", "x"))                  # sin autor
        with self.assertRaises(O.NoExiste):
            ejecutar(O.escribir_seccion(OTRO, "tecnico", "crit-1", "x", agente="a"))     # oferta sin preparar

    def test_el_agente_no_pisa_a_una_persona_ni_lo_revisado(self):
        self.preparar()
        ejecutar(O.escribir_seccion(ID, "tecnico", "crit-1", "Versión del agente", agente="redactor-memoria"))
        p = ejecutar(O.escribir_seccion(ID, "tecnico", "crit-1", "Versión de Marta", usuario="marta"))
        self.assertEqual((p["version"], p["por"]), (2, "marta"))
        with self.assertRaisesRegex(O.ErrorOferta, "editado una persona"):
            ejecutar(O.escribir_seccion(ID, "tecnico", "crit-1", "Otra del agente", agente="redactor-memoria"))
        ejecutar(O.escribir_seccion(ID, "tecnico", "crit-2", "Borrador", agente="redactor-memoria"))
        sid = next(s["id"] for s in ejecutar(O.leer(ID))["secciones"] if s["clave"] == "crit-2")
        r = ejecutar(O.revisar_seccion(sid, "revisada", "albert"))
        self.assertEqual((r["estado"], r["revisado_por"]), ("revisada", "albert"))
        with self.assertRaisesRegex(O.ErrorOferta, "ya está revisada"):
            ejecutar(O.escribir_seccion(ID, "tecnico", "crit-2", "Cambio del agente", agente="redactor-memoria"))
        # una persona que edita una sección aprobada la devuelve a borrador: hay que volver a revisarla
        ejecutar(O.revisar_seccion(sid, "aprobada", "albert"))
        e = ejecutar(O.escribir_seccion(ID, "tecnico", "crit-2", "Retoque", usuario="albert"))
        self.assertEqual((e["estado"], e["revisado_por"]), ("borrador", None))

    def test_sin_cambios_no_sube_version_ni_pierde_la_revision(self):
        self.preparar()
        ejecutar(O.escribir_seccion(ID, "tecnico", "crit-1", "Texto", agente="a"))
        sid = next(s["id"] for s in ejecutar(O.leer(ID))["secciones"] if s["clave"] == "crit-1")
        ejecutar(O.revisar_seccion(sid, "aprobada", "albert"))
        s = ejecutar(O.escribir_seccion(ID, "tecnico", "crit-1", "Texto", usuario="albert"))
        self.assertEqual((s["estado"], s["version"]), ("aprobada", 1))

    def test_revisar_exige_contenido_y_el_historial_guarda_las_versiones(self):
        self.preparar()
        sid = next(s["id"] for s in ejecutar(O.leer(ID))["secciones"] if s["clave"] == "crit-1")
        with self.assertRaisesRegex(O.ErrorOferta, "vacía"):
            ejecutar(O.revisar_seccion(sid, "aprobada", "albert"))
        with self.assertRaises(O.ErrorOferta):
            ejecutar(O.revisar_seccion(sid, "rara", "albert"))
        with self.assertRaises(O.NoExiste):
            ejecutar(O.revisar_seccion(999999, "revisada", "albert"))
        ejecutar(O.escribir_seccion(ID, "tecnico", "crit-1", "v1", agente="a"))
        ejecutar(O.escribir_seccion(ID, "tecnico", "crit-1", "v2", agente="a"))
        h = ejecutar(O.historial(sid))
        self.assertEqual([x["version"] for x in h], [2, 1])

    def test_precio_solo_lo_fija_una_persona_y_alimenta_la_proposicion(self):
        self.preparar()
        o = ejecutar(O.fijar_precio(ID, "125.000,50".replace(".", "").replace(",", "."), 21, "albert"))
        self.assertEqual((o["precio_sin_iva"], o["iva_pct"], o["precio_por"]), (125000.5, 21.0, "albert"))
        for malo in (0, -5, "abc", None, True, 1e12):
            with self.assertRaises(O.ErrorOferta, msg=str(malo)):
                ejecutar(O.fijar_precio(ID, malo, 21, "albert"))
        with self.assertRaises(O.ErrorOferta):
            ejecutar(O.fijar_precio(ID, 100, 150, "albert"))
        with self.assertRaises(O.NoExiste):
            ejecutar(O.fijar_precio(OTRO, 100, 21, "albert"))

    def test_exportar_word_marca_lo_no_aprobado_y_trae_la_relacion_de_requisitos(self):
        self.preparar()
        ejecutar(O.escribir_seccion(ID, "tecnico", "descripcion-solucion", "Instalaremos 40 cámaras.\n\n- Cámara A\n- Cámara B", agente="redactor-memoria"))
        sid = next(s["id"] for s in ejecutar(O.leer(ID))["secciones"] if s["clave"] == "descripcion-solucion")
        ejecutar(O.fijar_precio(ID, 90000, 21, "albert"))
        texto, _ = documentos.extraer_texto("o.docx", ejecutar(O.exportar_docx(ID, "Videovigilancia del puerto", datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc))))
        for esperado in ("Videovigilancia del puerto", "Sobre técnico", "[BORRADOR — pendiente de revisión]", "Instalaremos 40 cámaras.", "• Cámara A", "[SECCIÓN SIN REDACTAR]",
                         "90.000,00 €", "108.900,00 €", "Relación de requisitos administrativos", "Requisito adm", "pendiente"):
            self.assertIn(esperado, texto)
        ejecutar(O.revisar_seccion(sid, "aprobada", "albert"))
        texto, _ = documentos.extraer_texto("o.docx", ejecutar(O.exportar_docx(ID)))
        self.assertNotIn("Instalaremos 40 cámaras.\n[BORRADOR", texto)
        with self.assertRaises(O.NoExiste):
            ejecutar(O.exportar_docx(OTRO))


if __name__ == "__main__":
    unittest.main()


class TestHerramienta(unittest.TestCase):
    def setUp(self):
        try:
            import cerebro.herramientas  # noqa: F401 - registra todas
            from cerebro.herramientas import base
            from cerebro.registro import registro
        except ImportError as e:      # pragma: no cover
            self.skipTest(str(e))
        self.base, self.registro = base, registro()

    def test_operaciones_y_agentes_con_acceso(self):
        self.assertEqual(set(self.base._REGISTRO["ofertas"].operaciones), {"plan", "leer", "seccion", "guardar_seccion"})
        con = {a for a, f in self.registro.fichas.items() if "ofertas" in f.herramientas}
        self.assertEqual(con, {"administrativo-licitaciones", "arquitecto-solucion", "redactor-memoria", "costes-licitacion", "precio-licitacion"})

    def test_el_agente_que_escribe_lo_pone_el_sistema_y_no_el_modelo(self):
        from cerebro.grafo import nodos
        ficha = self.registro.fichas["redactor-memoria"]
        recibido = {}

        async def falsa(licitacion, sobre, clave, contenido, citas=None, titulo=None, agente=None):
            recibido["agente"] = agente
            return {}
        args = nodos.inyectar(ficha, {}, "ofertas", {"licitacion": ID, "sobre": "tecnico", "clave": "crit-1", "contenido": "x", "agente": "director-licitaciones"})
        self.assertNotIn("agente", args)
        with mock.patch.dict(self.base._REGISTRO["ofertas"].operaciones, {"guardar_seccion": falsa}):
            ejecutar(self.base.usar(ficha, "ofertas", "guardar_seccion", **args))
            self.assertEqual(recibido["agente"], "redactor-memoria")
            # aunque el modelo lo intente colar y llegue a `usar`, el sistema lo pisa con el agente real
            recibido.clear()
            ejecutar(self.base.usar(ficha, "ofertas", "guardar_seccion", **{**args, "agente": "director-licitaciones"}))
            self.assertEqual(recibido["agente"], "redactor-memoria")
        self.assertNotIn("agente", self.base._REGISTRO["ofertas"].ayuda.get("guardar_seccion", "").split("(")[0])

    def test_el_agente_no_tiene_operaciones_para_aprobar_ni_fijar_el_precio(self):
        ops = set(self.base._REGISTRO["ofertas"].operaciones)
        self.assertFalse(ops & {"revisar", "aprobar", "fijar_precio", "exportar"})
