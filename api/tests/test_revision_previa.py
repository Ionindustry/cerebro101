"""Revisión previa de «Preparar la oferta»: solo lectura, con niveles (ok / aviso / bloqueo) y un resultado global; los datos se sustituyen por dobles."""
import asyncio
import unittest

import _sin_servicios  # noqa: F401

from cerebro.licitaciones import empresa, revision_previa as R

ID = "0b1f7a3e-1111-4222-8333-444444444444"
FICHA = {"id": ID, "documentos": [{"nombre": "PCAP", "url_origen": "https://contrataciondelestado.es/x"}, {"nombre": "PPT", "url_origen": "https://contrataciondelestado.es/y"}]}


def ejecutar(c):
    return asyncio.run(c)


def dobles(**kw):
    async def ficha(m):
        return FICHA

    async def elegir(e):
        return "101"

    async def claves(n, f, m):
        return {"disponibles": {"empresa.razon_social": "101"}, "faltan": {"empresa.nif": "Empresa › NIF (tax_id)", "oferta.precio": "lo fija una persona"}}

    async def deuc(n):
        return ("DEUC 101.docx", b"x", "docx")

    async def documentos(m):
        return {"documentos": [{"n": 1, "descarga": {"estado": "limpio"}}, {"n": 2, "descarga": None}]}

    async def requisitos(m):
        return {"requisitos": [{"estado": "confirmado", "tipo": "solvencia_economica", "resumen": "Certificado ISO 45001 de seguridad y salud en el trabajo", "valor": "", "cita": ""},
                               {"estado": "borrador", "tipo": "plazo", "resumen": "Entrega en 30 días", "valor": "", "cita": ""}]}

    async def oferta(m):
        return {"existe": True, "secciones": [{"id": 1}]}

    async def ejecucion(m):
        return None
    d = {"ficha": ficha, "elegir": elegir, "claves": claves, "deuc": deuc, "documentos": documentos, "requisitos": requisitos, "oferta": oferta, "ejecucion": ejecucion}
    d.update(kw)
    return d


def textos(r, nivel):
    return [i["texto"] for s in r["secciones"] for i in s["items"] if i["nivel"] == nivel]


class TestRevision(unittest.TestCase):
    def test_con_avisos_pero_sin_bloqueos_se_puede_lanzar(self):
        r = ejecutar(R.revisar(ID, **dobles()))
        self.assertEqual((r["resultado"], r["bloqueos"]), ("con_avisos", 0))
        avisos = " ".join(textos(r, "aviso"))
        self.assertIn("empresa.nif", avisos)
        self.assertNotIn("oferta.precio", avisos)                                  # el precio lo fija una persona: no es un dato que falte
        self.assertIn("requisitos en borrador sin revisar", avisos)
        self.assertIn("probablemente NO se cumplen", avisos)                       # la aptitud con el perfil de la empresa
        self.assertEqual([s["id"] for s in r["secciones"]], ["ficha", "sociedad", "pliegos", "requisitos", "oferta"])

    def test_sin_ficha_o_sin_sociedad_es_un_bloqueo(self):
        async def sin_ficha(m):
            return {}

        async def sin_erp(e):
            raise empresa.ErrorEmpresa("En el ERP no hay ninguna empresa (Company)")
        r = ejecutar(R.revisar(ID, **dobles(ficha=sin_ficha)))
        self.assertEqual((r["resultado"], r["bloqueos"]), ("bloqueada", 1))
        self.assertIn("no devuelve la ficha", textos(r, "bloqueo")[0])
        r = ejecutar(R.revisar(ID, **dobles(elegir=sin_erp)))
        self.assertEqual(r["resultado"], "bloqueada")
        self.assertIn("El ERP no da la sociedad", textos(r, "bloqueo")[0])

    def test_de_un_fallo_inesperado_del_erp_no_se_ensena_su_texto(self):
        async def roto(e):
            raise RuntimeError("fallo con http://erpnext-backend:8000 y el token abc123")
        r = ejecutar(R.revisar(ID, **dobles(elegir=roto)))
        texto = textos(r, "bloqueo")[0]
        self.assertIn("RuntimeError", texto)
        self.assertNotIn("erpnext-backend", texto)
        self.assertNotIn("abc123", texto)

    def test_sin_deuc_sin_pliegos_y_sin_requisitos_son_avisos_con_lo_que_hay_que_hacer(self):
        async def sin_deuc(n):
            return None

        async def sin_pliegos(m):
            return {"documentos": [{"n": 1, "descarga": None}]}

        async def sin_reqs(m):
            return {"requisitos": []}
        r = ejecutar(R.revisar(ID, **dobles(deuc=sin_deuc, documentos=sin_pliegos, requisitos=sin_reqs)))
        todo = " ".join(textos(r, "aviso"))
        self.assertIn("No hay DEUC base", todo)
        self.assertIn("Analizar los pliegos con el Analista", todo)
        self.assertIn("No hay requisitos anotados", todo)
        self.assertEqual(r["bloqueos"], 0)

    def test_varias_sociedades_y_pasada_en_curso(self):
        async def varias(e):
            raise empresa.VariasEmpresas([{"nombre": "A", "razon_social": "A S.L.", "nif": ""}, {"nombre": "B", "razon_social": "B S.L.", "nif": ""}])

        async def en_curso(m):
            return {"id": 7, "estado": "en_curso", "error": "", "pasos": [{"titulo": "Memoria", "estado": "hecho"}]}
        r = ejecutar(R.revisar(ID, **dobles(elegir=varias, ejecucion=en_curso)))
        todo = " ".join(textos(r, "aviso"))
        self.assertIn("varias empresas", todo)
        self.assertIn("en curso", todo)
        self.assertIn("Memoria: hecho", todo)

    def test_un_fallo_inesperado_de_una_comprobacion_no_tumba_la_revision(self):
        async def roto(m):
            raise RuntimeError("boom")
        r = ejecutar(R.revisar(ID, **dobles(documentos=roto, requisitos=roto, oferta=roto)))
        self.assertEqual(r["bloqueos"], 0)
        self.assertEqual(len(r["secciones"]), 5)
        self.assertIn("No se han podido comprobar los pliegos", " ".join(textos(r, "aviso")))

    def test_todo_en_orden_es_lista(self):
        async def completa(m):
            return {"id": 3, "estado": "completa", "error": "", "pasos": []}

        async def claves(n, f, m):
            return {"disponibles": {"a": "1"}, "faltan": {}}

        async def reqs(m):
            return {"requisitos": [{"estado": "confirmado", "tipo": "plazo", "resumen": "Entrega en 30 días", "valor": "", "cita": ""}]}

        async def docs(m):
            return {"documentos": [{"n": 1, "descarga": {"estado": "limpio"}}]}
        r = ejecutar(R.revisar(ID, **dobles(ejecucion=completa, claves=claves, requisitos=reqs, documentos=docs)))
        self.assertEqual((r["resultado"], r["avisos"], r["bloqueos"]), ("lista", 0, 0))


if __name__ == "__main__":
    unittest.main()
