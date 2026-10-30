"""Conversión de .doc, .odt y .rtf a Word: cliente del servicio (con un servicio de mentira), validaciones y, si hay LibreOffice, la conversión real."""
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import _sin_servicios  # noqa: F401

try:
    import httpx
except ImportError as e:      # pragma: no cover
    raise unittest.SkipTest(str(e))
from cerebro.licitaciones import conversion as C, conversion_local as L, formularios as F


def docx_minimo(ruta: Path) -> bytes:
    with zipfile.ZipFile(ruta, "w") as z:
        z.writestr("word/document.xml", "<w:document/>")
    return ruta.read_bytes()


class TestCliente(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.t = Path(self.tmp.name)
        (self.t / "m.odt").write_bytes(b"PK\x03\x04odt")
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.dict("os.environ", {"CONVERSOR_URL": "http://conversor:8080"})
        p.start()
        self.addCleanup(p.stop)

    def con(self, respuesta=None, error=None):
        def post(url, **kw):
            self.llamada = (url, kw)
            if error:
                raise error
            return respuesta
        return mock.patch.object(C.httpx, "post", post)

    def test_manda_el_documento_al_servicio_y_guarda_el_word(self):
        word = docx_minimo(self.t / "w.docx")
        with self.con(httpx.Response(200, content=word)):
            salida = C.a_docx(self.t / "m.odt", self.t / "sub" / "o.docx", "odt")
        self.assertEqual(salida.read_bytes(), word)
        self.assertEqual(self.llamada[0], "http://conversor:8080/convertir")
        self.assertEqual((self.llamada[1]["params"], self.llamada[1]["content"]), ({"formato": "odt"}, b"PK\x03\x04odt"))

    def test_lo_que_vuelve_tiene_que_ser_un_word_de_verdad(self):
        with self.con(httpx.Response(200, content=b"<html>no soy un docx</html>")):
            with self.assertRaises(F.ErrorFormulario):
                C.a_docx(self.t / "m.odt", self.t / "o.docx", "odt")
        self.assertFalse((self.t / "o.docx").exists())

    def test_errores_del_servicio_llegan_con_su_mensaje(self):
        with self.con(httpx.Response(422, json={"error": "El contenido del documento no es odt"})):
            with self.assertRaisesRegex(F.ErrorFormulario, "no es odt"):
                C.a_docx(self.t / "m.odt", self.t / "o.docx", "odt")
        with self.con(httpx.Response(500, content=b"boom")):
            with self.assertRaisesRegex(F.ErrorFormulario, "rellenarlo a mano"):
                C.a_docx(self.t / "m.odt", self.t / "o.docx", "odt")

    def test_servicio_caido(self):
        with self.con(error=httpx.ConnectError("sin red")):
            with self.assertRaisesRegex(F.ErrorFormulario, "no responde"):
                C.a_docx(self.t / "m.odt", self.t / "o.docx", "odt")

    def test_formatos_que_no_se_convierten(self):
        with self.assertRaises(F.ErrorFormulario):
            C.a_docx(self.t / "m.odt", self.t / "o.docx", "xlsx")

    def test_sin_servicio_ni_libreoffice_se_dice_con_claridad(self):
        with mock.patch.dict("os.environ", {"CONVERSOR_URL": ""}), mock.patch.object(L, "disponible", lambda: False):
            with self.assertRaisesRegex(F.ErrorFormulario, "no está disponible"):
                C.a_docx(self.t / "m.odt", self.t / "o.docx", "odt")


class TestZip(unittest.TestCase):
    def test_los_modelos_convertibles_de_un_zip_se_extraen_si_su_contenido_es_el_que_dice(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            with zipfile.ZipFile(t / "p.zip", "w") as z:
                z.writestr("Anexo I.odt", b"PK\x03\x04xx")
                z.writestr("Anexo II.doc", b"\xd0\xcf\x11\xe0xx")
                z.writestr("Anexo III.rtf", b"{\\rtf1 hola}")
                z.writestr("Falso.odt", b"esto es texto")
                z.writestr("Hoja.xlsx", b"PK\x03\x04")
            r = F.extraer_zip(t / "p.zip", t / "x")
        self.assertEqual(sorted((m["miembro"], m["formato"]) for m in r["miembros"]), [("Anexo I.odt", "odt"), ("Anexo II.doc", "doc"), ("Anexo III.rtf", "rtf")])
        self.assertTrue(any("Falso.odt" in a and "no es odt" in a for a in r["avisos"]))
        self.assertTrue(any("Hoja.xlsx" in a for a in r["avisos"]))


@unittest.skipUnless(L.disponible(), "sin LibreOffice")
class TestReal(unittest.TestCase):
    def test_un_rtf_se_convierte_y_se_detectan_sus_huecos(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            (t / "m.rtf").write_bytes(b"{\\rtf1\\ansi D./D\\'aa ____________________, con DNI n\\'ba __________ y NIF _________.\\par}")
            with mock.patch.dict("os.environ", {"CONVERSOR_URL": ""}):
                salida = C.a_docx(t / "m.rtf", t / "o.docx", "rtf")
            self.assertTrue(L.es_docx(salida))
            self.assertGreaterEqual(len(F.detectar(salida, "docx")["campos"]), 2)

    def test_un_contenido_que_no_es_del_formato_se_rechaza(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            (t / "m.odt").write_bytes(b"esto no es un odt")
            with mock.patch.dict("os.environ", {"CONVERSOR_URL": ""}):
                with self.assertRaises(F.ErrorFormulario):
                    C.a_docx(t / "m.odt", t / "o.docx", "odt")



class TestComoWord(unittest.TestCase):
    def test_un_modelo_odt_pasa_a_word_y_avisa_y_un_docx_se_deja_igual(self):
        import asyncio
        from cerebro.licitaciones import plantillas as PL
        visto = {}

        def convertir(origen, destino, formato):
            visto.update(origen=str(origen), formato=formato, destino=str(destino))
            return destino
        doc = {"n": 1, "nombre": "Anexo I.odt", "formato": "odt", "sha256": "ab" * 32, "ruta": "/tmp/x/001.odt", "sub": 3}
        with mock.patch.object(PL.C, "a_docx", convertir):
            nuevo = asyncio.run(PL._como_word("0b1f7a3e-1111-4222-8333-444444444444", doc))
            igual = asyncio.run(PL._como_word("0b1f7a3e-1111-4222-8333-444444444444", {**doc, "formato": "docx"}))
        self.assertEqual((nuevo["formato"], visto["formato"], visto["origen"]), ("docx", "odt", "/tmp/x/001.odt"))
        self.assertTrue(nuevo["ruta"].endswith(f"{doc['sha256']}-3.docx"))
        self.assertIn("convertido de odt a Word", nuevo["conversion"])
        self.assertEqual(igual["formato"], "docx")
        self.assertNotIn("conversion", igual)


if __name__ == "__main__":
    unittest.main()
