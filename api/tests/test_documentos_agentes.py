"""Documentos que redactan los agentes de una licitación: se reúnen, se ven como texto y se bajan en Word."""
import io
import unittest
import zipfile

import _sin_servicios  # noqa: F401

try:
    from cerebro.licitaciones import documentos_agentes as D
except ImportError as e:      # pragma: no cover
    raise unittest.SkipTest(str(e))


def sec(sobre, clave, titulo, contenido, estado="borrador", por="agente:redactor-memoria"):
    return {"id": 1, "sobre": sobre, "clave": clave, "titulo": titulo, "contenido": contenido, "estado": estado, "por": por, "actualizado": "2026-11-15T10:00:00"}


OFERTA = {"existe": True, "secciones": [
    sec("tecnico", "descripcion-solucion", "Descripción de la solución", "Solución con cámaras IP.", por="agente:arquitecto-solucion"),
    sec("tecnico", "crit-1", "Criterio 1", "Memoria del criterio uno.\n\n- punto a\n- punto b", "aprobada"),
    sec("tecnico", "crit-2", "Criterio 2", "Memoria del criterio dos.", "revisada"),
    sec("tecnico", "crit-3", "Criterio 3", "", "vacia"),
    sec("administrativo", "declaracion", "Declaración responsable", "Texto administrativo.", por="agente:administrativo-licitaciones"),
    sec("economico", "justificacion-precio", "Justificación del precio", "Costes y justificación.", por="agente:costes-licitacion"),
    sec("economico", "proposicion-economica", "Proposición económica", "SECRETO DE PRECIO", por="persona"),
]}
EJEC = {"pasos": [{"id": "precio", "estado": "hecho", "resumen": "Precio recomendado 120.000 €.", "fin": "2026-11-15T11:00:00"},
                  {"id": "evaluacion", "estado": "error", "resumen": "a medias", "fin": None}]}
COMP = {"proveedor": "claude", "actualizado": "2026-11-15T12:00:00", "contenido": {"estrategia": "Ganar por calidad.", "requisitos": [{"requisito": "R1", "recomendado": "Cámara X", "brecha": ""}], "ventajas": [], "pendientes": []}}
EQUIV = {"proveedor": "chatgpt", "actualizado": "2026-11-15T13:00:00", "contenido": {"parametros": [
    {"parametro": "Resolución", "operador": ">=", "valor_exigido": "4 MP", "recomendado": "Cámara X", "candidatos": [{"producto": "Cámara X", "valor_producto": "8 MP", "veredicto": "supera"}]},
    {"parametro": "Grado IP", "operador": "texto", "valor_exigido": "IP67", "recomendado": "", "candidatos": []}],
    "solucion": {"productos": [{"producto": "Cámara X", "cubre": ["Resolución"], "supera": 1}], "sin_cubrir": ["Grado IP"]}, "pendientes": ["Ficha de Cámara Y"]}}
ENC = [{"agente": "redactor-memoria", "nombre": "Redactor de Memoria", "contenido": "Escribe con foco en seguridad.", "por": "agente:director-oferta", "actualizado": "2026-11-15T09:00:00"},
       {"agente": "costes-licitacion", "nombre": "Costes", "contenido": "", "por": None, "actualizado": None}]
FUENTES = {"oferta": OFERTA, "ejecucion": EJEC, "comparativa": COMP, "equivalencia": EQUIV, "encargos": ENC}


class TestConstruir(unittest.TestCase):
    def docs(self, **kw):
        return {d["id"]: d for d in D.construir({**FUENTES, **kw})}

    def test_salen_los_documentos_que_hay_y_en_orden(self):
        ids = list(self.docs())
        self.assertEqual(ids, ["solucion", "memoria", "administrativo", "costes", "precio", "comparativa", "equivalencia", "encargos"])   # el informe del evaluador dio error: no sale

    def test_la_memoria_no_incluye_la_solucion_ni_las_secciones_vacias_y_marca_borradores(self):
        m = self.docs()["memoria"]
        textos = [str(v) for _t, v in m["bloques"]]
        self.assertTrue(any("Memoria del criterio uno" in t for t in textos))
        self.assertFalse(any("Solución con cámaras" in t for t in textos))
        self.assertFalse(any(t == "Criterio 3" for t in textos))
        self.assertIn("[REVISADA — pendiente de aprobación]", textos)
        self.assertNotIn("[BORRADOR — pendiente de revisión]", textos)               # la sección 1 está aprobada
        self.assertEqual(m["estado"], "revisada")                                      # el estado del conjunto es el más bajo

    def test_la_proposicion_economica_nunca_sale(self):
        for d in self.docs().values():
            self.assertNotIn("SECRETO DE PRECIO", D.a_texto(d))

    def test_informes_y_estados(self):
        d = self.docs()
        self.assertEqual(d["precio"]["bloques"], [("texto", "Precio recomendado 120.000 €.")])
        self.assertEqual(d["precio"]["estado"], "informe")
        self.assertNotIn("evaluacion", d)

    def test_equivalencia_tabla_y_solucion(self):
        t = D.a_texto(self.docs()["equivalencia"])
        self.assertIn("Solución mínima de productos", t)
        self.assertIn("Cámara X: 8 MP (supera)", t)
        self.assertIn("SIN PRODUCTO QUE LO CUMPLA ACREDITADO", t)
        self.assertIn("Ficha de Cámara Y", t)

    def test_encargos_solo_los_que_tienen_texto(self):
        t = D.a_texto(self.docs()["encargos"])
        self.assertIn("Encargo a Redactor de Memoria", t)
        self.assertNotIn("Encargo a Costes", t)

    def test_sin_fuentes_no_hay_documentos(self):
        self.assertEqual(D.construir({}), [])
        self.assertEqual(D.construir({"oferta": {"existe": True, "secciones": []}, "comparativa": {"contenido": {}}, "equivalencia": {"contenido": {"parametros": []}}}), [])

    def test_publico_cuenta_caracteres_y_no_trae_contenido(self):
        p = D.publico(self.docs()["precio"])
        self.assertEqual(p["caracteres"], len("Precio recomendado 120.000 €."))
        self.assertNotIn("bloques", p)
        self.assertEqual(p["estado_texto"], "informe del agente")


class TestWord(unittest.TestCase):
    def test_el_word_es_valido_marca_borrador_y_lleva_el_texto_y_la_tabla(self):
        doc = {d["id"]: d for d in D.construir(FUENTES)}["equivalencia"]
        datos = D.a_docx(doc, "Suministro de cámaras")
        z = zipfile.ZipFile(io.BytesIO(datos))
        xml = z.read("word/document.xml").decode("utf-8")
        self.assertIn("BORRADOR", xml)
        self.assertIn("Suministro de cámaras", xml)
        self.assertIn("<w:tbl>", xml)
        self.assertIn("Cámara X", xml)

    def test_nombre_de_fichero_es_seguro(self):
        self.assertEqual(D.nombre_fichero({"id": "memoria"}, "EXP 12/2026"), "memoria-EXP-12-2026.docx")
        self.assertEqual(D.nombre_fichero({"id": "memoria"}), "memoria.docx")


class TestListar(unittest.TestCase):
    def test_lista_documentos_y_plantillas_rellenadas(self):
        import asyncio
        from unittest import mock

        async def reunir(_m):
            return {**FUENTES, "plantillas": {"documentos": [
                {"id": 7, "nombre": "Anexo II", "fichero": "anexo-ii.docx", "estado": "lista_para_firma", "formato": "docx", "por": "agente:administrativo-licitaciones", "creado": "2026-11-15T10:00:00", "pendientes": []},
                {"id": 8, "nombre": "Sin fichero", "fichero": None, "estado": "error", "formato": "pdf", "por": "x", "creado": "2026-11-15T10:00:00", "pendientes": []}]}}
        with mock.patch.object(D, "reunir", reunir):
            r = asyncio.run(D.listar("x"))
        self.assertEqual([d["id"] for d in r["documentos"]][:2], ["solucion", "memoria"])
        self.assertEqual([p["id"] for p in r["plantillas"]], [7])                      # solo las que tienen fichero que bajar
        self.assertIn("BORRADOR", r["nota"])


class TestObtener(unittest.TestCase):
    def test_id_inexistente_y_documento_sin_redactar(self):
        import asyncio
        from unittest import mock

        async def reunir(_m):
            return {}
        with mock.patch.object(D, "reunir", reunir):
            with self.assertRaises(D.NoExisteDocumento):
                asyncio.run(D.obtener("x", "no-existe"))
            with self.assertRaisesRegex(D.NoExisteDocumento, "aún no han redactado"):
                asyncio.run(D.obtener("x", "memoria"))

    def test_obtener_devuelve_el_documento(self):
        import asyncio
        from unittest import mock

        async def reunir(_m):
            return FUENTES
        with mock.patch.object(D, "reunir", reunir):
            d = asyncio.run(D.obtener("x", "precio"))
        self.assertEqual(d["id"], "precio")


if __name__ == "__main__":
    unittest.main()
