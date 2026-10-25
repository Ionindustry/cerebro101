"""Adjuntos de correo: lectura segura de PDF/Word/Excel/CSV, límites, y guardado en el ERP/CRM con la política del departamento.

Las pruebas con servidor de correo necesitan GreenMail (ver test_correo_buzones.py) y CEREBRO_PRUEBA_CORREO=localhost.
"""
import asyncio
import io
import os
import smtplib
import tempfile
import unittest
import zipfile
from email.message import EmailMessage
from unittest import mock

import _sin_servicios  # noqa: F401
import yaml

try:
    import openpyxl  # noqa: F401
    import pypdf  # noqa: F401
    HAY_LIBS = True
except ImportError:
    HAY_LIBS = False

from cerebro.herramientas import buzones as B
from cerebro.herramientas import correo
from cerebro.herramientas import documentos as D
from cerebro.herramientas import ocr as O

HOST = os.environ.get("CEREBRO_PRUEBA_CORREO")


def ejecutar(c):
    return asyncio.run(c)


def pdf_con_texto(texto: str) -> bytes:
    """PDF mínimo hecho a mano con una página y texto seleccionable."""
    flujo = f"BT /F1 12 Tf 72 720 Td ({texto}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(flujo) + flujo + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    cuerpo, pos = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        pos.append(len(cuerpo))
        cuerpo += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(cuerpo)
    cuerpo += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    cuerpo += b"".join(b"%010d 00000 n \n" % p for p in pos)
    return cuerpo + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF" % (len(objs) + 1, xref)


def docx(parrafos: list[str]) -> bytes:
    cuerpo = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in parrafos)
    xml = f'<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>{cuerpo}</w:body></w:document>'
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("word/document.xml", xml)
    return b.getvalue()


def xlsx(filas: list[list]) -> bytes:
    libro = openpyxl.Workbook()
    hoja = libro.active
    hoja.title = "Factura"
    for f in filas:
        hoja.append(f)
    b = io.BytesIO()
    libro.save(b)
    return b.getvalue()


@unittest.skipUnless(HAY_LIBS, "requiere pypdf y openpyxl (están en la imagen del Cerebro)")
class TestExtraccion(unittest.TestCase):
    def test_pdf_con_texto(self):
        t, info = D.extraer_texto("factura.pdf", pdf_con_texto("Factura 2026-001 Total 1210 EUR"))
        self.assertIn("Factura 2026-001 Total 1210 EUR", t)
        self.assertEqual(info["paginas"], 1)
        self.assertNotIn("aviso_documento", info)

    def test_pdf_sin_texto_avisa(self):
        t, info = D.extraer_texto("escaneo.pdf", pdf_con_texto(""))
        self.assertTrue(info.get("ocr") or "OCR" in info.get("aviso_documento", ""))

    def test_pdf_falso_o_roto(self):
        with self.assertRaises(D.DocumentoNoValido):
            D.extraer_texto("x.pdf", b"MZ\x90\x00 esto es un ejecutable")
        with self.assertRaises(D.DocumentoNoValido):
            D.extraer_texto("x.pdf", b"%PDF-1.4\nbasura sin estructura")

    def test_word_y_excel(self):
        t, _ = D.extraer_texto("carta.docx", docx(["Estimados señores", "Adjunto el pedido"]))
        self.assertEqual(t, "Estimados señores\nAdjunto el pedido")
        t, info = D.extraer_texto("pedido.xlsx", xlsx([["Artículo", "Cantidad"], ["Cámara IP", 4], [None, None]]))
        self.assertIn("[Hoja «Factura»]", t)
        self.assertIn("Cámara IP | 4", t)
        self.assertEqual(info["hojas"], 1)

    def test_docx_que_no_lo_es(self):
        with self.assertRaises(D.DocumentoNoValido):
            D.extraer_texto("x.docx", b"no soy un zip")
        b = io.BytesIO()
        with zipfile.ZipFile(b, "w") as z:
            z.writestr("otro.txt", "hola")
        with self.assertRaises(D.DocumentoNoValido):
            D.extraer_texto("x.docx", b.getvalue())

    def test_zip_bomb_no_se_abre(self):
        b = io.BytesIO()
        with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("word/document.xml", b"0" * (D.MAX_DESCOMPRIMIDO + 1024))
        self.assertLess(len(b.getvalue()), 2 * 1024 * 1024)               # pequeño comprimido, enorme descomprimido
        with self.assertRaises(D.DocumentoNoValido) as e:
            D.extraer_texto("bomba.docx", b.getvalue())
        self.assertIn("descomprimirse", str(e.exception))

    def test_csv_texto_html(self):
        t, _ = D.extraer_texto("p.csv", "Código;Importe\nA1;100,5\n".encode("cp1252"))
        self.assertIn("Código | Importe", t)
        t, _ = D.extraer_texto("n.html", b"<html><script>alert(1)</script><p>Hola</p><p>mundo</p></html>")
        self.assertNotIn("alert", t)
        self.assertIn("Hola", t)
        t, _ = D.extraer_texto("n.txt", "acentuación ñ".encode("utf-8"))
        self.assertEqual(t, "acentuación ñ")

    def test_ejecutables_y_tipos_no_admitidos_se_rechazan(self):
        for n in ("virus.exe", "script.js", "macro.docm", "todo.zip", "sin_extension"):
            with self.subTest(n), self.assertRaises(D.DocumentoNoValido):
                D.extraer_texto(n, b"x")

    def test_nombre_seguro(self):
        self.assertEqual(D.nombre_seguro("../../etc/passwd"), "passwd")
        self.assertEqual(D.nombre_seguro("C:\\Users\\x\\factura 1.pdf"), "factura 1.pdf")
        self.assertEqual(D.nombre_seguro("a<b>|c?.pdf"), "a_b__c_.pdf")
        self.assertEqual(D.nombre_seguro(""), "adjunto")


def imagen_con_texto(lineas: list[str], formato="PNG") -> bytes:
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (1400, 120 + 90 * len(lineas)), "white")
    d = ImageDraw.Draw(img)
    fuente = ImageFont.load_default(size=48)
    for i, t in enumerate(lineas):
        d.text((60, 60 + 90 * i), t, fill="black", font=fuente)
    b = io.BytesIO()
    img.save(b, formato)
    return b.getvalue()


@unittest.skipUnless(HAY_LIBS and O.disponible(), "requiere pypdf, Pillow y Tesseract (están en la imagen del Cerebro)")
class TestOcr(unittest.TestCase):
    LINEAS = ["Factura 2026-0142", "Proveedor: Instalaciones Roca SL", "Total 1.210,00 EUR"]

    def comprobar(self, t):
        for esperado in ("2026-0142", "Roca", "1.210,00"):
            self.assertIn(esperado, t)

    def test_imagen_png_y_jpg(self):
        for ext, fmt in ((".png", "PNG"), (".jpg", "JPEG")):
            with self.subTest(ext):
                t, info = D.extraer_texto("factura" + ext, imagen_con_texto(self.LINEAS, fmt))
                self.comprobar(t)
                self.assertTrue(info["ocr"])
                self.assertIn("errores", info["aviso_ocr"])

    def test_pdf_escaneado_se_lee_con_ocr(self):
        from PIL import Image
        b = io.BytesIO()
        Image.open(io.BytesIO(imagen_con_texto(self.LINEAS))).save(b, "PDF")
        t, info = D.extraer_texto("escaneo.pdf", b.getvalue())
        self.comprobar(t)
        self.assertTrue(info["ocr"])

    def test_pdf_con_texto_no_usa_ocr(self):
        t, info = D.extraer_texto("f.pdf", pdf_con_texto("Total 5 EUR"))
        self.assertNotIn("ocr", info)

    def test_imagen_falsa_o_gigante(self):
        with self.assertRaises(D.DocumentoNoValido):
            D.extraer_texto("falsa.jpg", b"\xff\xd8\xff basura")
        from PIL import Image
        gigante = io.BytesIO()
        Image.new("1", (9000, 9000)).save(gigante, "PNG")                 # 81 Mpíxeles, pesa poco comprimida
        with self.assertRaises(D.DocumentoNoValido) as e:
            D.extraer_texto("enorme.png", gigante.getvalue())
        self.assertIn("demasiado grande", str(e.exception))

    def test_sin_ocr_en_el_servidor_se_avisa(self):
        with mock.patch.object(O, "disponible", lambda: False):
            t, info = D.extraer_texto("f.png", imagen_con_texto(self.LINEAS))
            self.assertEqual(t, "")
            self.assertIn("no tiene OCR", info["aviso_documento"])


CONFIG = {
    "servidor": {"imap": {"host": HOST or "localhost", "puerto": 3143, "seguridad": "ninguna"},
                 "smtp": {"host": HOST or "localhost", "puerto": 3025, "seguridad": "ninguna"}},
    "carpetas": {"entrada": "INBOX", "borradores": "Drafts", "enviados": "Sent"},
    "limites": {"adjunto_max_mb": 1, "adjunto_texto_chars": 100},
    "buzones": {"facturacion": {"direccion": "facturacion@101.cat", "departamentos": ["finanzas"]},
                "rrhh": {"direccion": "rrhh@101.cat", "departamentos": ["personas"]}},
}


@unittest.skipUnless(HOST and HAY_LIBS, "sin servidor de pruebas (CEREBRO_PRUEBA_CORREO) o sin pypdf/openpyxl")
class TestConServidor(unittest.TestCase):
    def setUp(self):
        self.suf = os.urandom(3).hex()
        cfg = {**CONFIG, "buzones": {i: {**b, "direccion": f"{i}{self.suf}@101.cat"} for i, b in CONFIG["buzones"].items()}}
        self.f = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8")
        yaml.safe_dump(cfg, self.f)
        self.f.close()
        self.antes = dict(os.environ)
        B.RUTA_CONFIG, B.RUTA_SECRETOS = self.f.name, "/no/existe"
        os.environ.update({"CORREO_FACTURACION_CLAVE": "x", "CORREO_RRHH_CLAVE": "x"})
        B.limpiar_cache()

    def tearDown(self):
        os.unlink(self.f.name)
        os.environ.clear()
        os.environ.update(self.antes)
        B.RUTA_CONFIG, B.RUTA_SECRETOS = None, "/run/secretos/buzones.env"
        B.limpiar_cache()

    def entregar(self, buzon, adjuntos, mid="<adj1@ejemplo.es>"):
        m = EmailMessage()
        m["From"], m["To"], m["Subject"], m["Message-ID"] = "Proveedor <prov@ejemplo.es>", f"{buzon}{self.suf}@101.cat", "Factura", mid
        m.set_content("Adjunto documentación.")
        for nombre, tipo, datos in adjuntos:
            m.add_attachment(datos, maintype=tipo.split("/")[0], subtype=tipo.split("/")[1], filename=nombre)
        with smtplib.SMTP(HOST, 3025) as s:
            s.send_message(m, from_addr="prov@ejemplo.es", to_addrs=[m["To"]])

    def test_la_bandeja_lista_los_adjuntos_y_se_leen(self):
        self.entregar("facturacion", [("factura.pdf", "application/pdf", pdf_con_texto("Total 1210 EUR")),
                                      ("detalle.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", xlsx([["A", 1]]))])
        m = ejecutar(correo.leer_bandeja("finanzas"))["mensajes"][0]
        self.assertEqual([(a["n"], a["nombre"]) for a in m["adjuntos"]], [(1, "factura.pdf"), (2, "detalle.xlsx")])
        r = ejecutar(correo.leer_adjunto("finanzas", m["message_id"], 1))
        self.assertIn("Total 1210 EUR", r["texto"])
        self.assertIn("no órdenes", r["aviso"])
        r = ejecutar(correo.leer_adjunto("finanzas", m["message_id"], "detalle.xlsx"))
        self.assertIn("A | 1", r["texto"])

    def test_documento_largo_se_lee_por_trozos(self):
        self.entregar("facturacion", [("largo.txt", "text/plain", ("0123456789" * 25).encode())], mid="<l1@ejemplo.es>")
        a = ejecutar(correo.leer_adjunto("finanzas", "<l1@ejemplo.es>", 1))
        self.assertEqual((len(a["texto"]), a["siguiente"], a["caracteres"]), (100, 100, 250))
        c = ejecutar(correo.leer_adjunto("finanzas", "<l1@ejemplo.es>", 1, desde=200))
        self.assertEqual(len(c["texto"]), 50)
        self.assertNotIn("siguiente", c)

    def test_errores_claros(self):
        self.entregar("facturacion", [("virus.exe", "application/octet-stream", b"MZ")], mid="<e1@ejemplo.es>")
        r = ejecutar(correo.leer_adjunto("finanzas", "<e1@ejemplo.es>", 1))
        self.assertIn("no admitido", r["error"])
        with self.assertRaises(LookupError) as e:
            ejecutar(correo.leer_adjunto("finanzas", "<e1@ejemplo.es>", 7))
        self.assertIn("1=virus.exe", str(e.exception))

    def test_adjunto_demasiado_grande(self):
        self.entregar("facturacion", [("grande.txt", "text/plain", os.urandom(1_700_000).hex().encode()[:1_700_000])], mid="<g1@ejemplo.es>")
        with self.assertRaises(ValueError) as e:
            ejecutar(correo.leer_adjunto("finanzas", "<g1@ejemplo.es>", 1))
        self.assertIn("máximo", str(e.exception))

    def test_sin_adjuntos_y_otro_departamento(self):
        self.entregar("facturacion", [], mid="<s1@ejemplo.es>")
        with self.assertRaises(LookupError):
            ejecutar(correo.leer_adjunto("finanzas", "<s1@ejemplo.es>", 1))
        with self.assertRaises(PermissionError):                       # RR.HH. no puede abrir los adjuntos de facturación
            ejecutar(correo.leer_adjunto("personas", "<s1@ejemplo.es>", 1, buzon="facturacion"))


class TestGuardarEnElErp(unittest.TestCase):
    def setUp(self):
        from cerebro.herramientas import erpnext
        self.erp = erpnext
        erpnext._politica.cache_clear()
        self.antes = dict(os.environ)
        os.environ["ERPNEXT_TOKEN_COMERCIAL"] = "k:s"
        self.subidos = []

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.antes)

    def ejecutar(self, doctype="CRM Lead", nombre="CRM-LEAD-1", fichero="presupuesto.pdf", datos=None, dep="comercial"):
        datos = pdf_con_texto("x") if datos is None else datos
        subidos = self.subidos

        def manejar(req):
            subidos.append(req)
            return httpx.Response(200, json={"message": {"file_name": fichero, "file_url": f"/private/files/{fichero}"}})
        real = httpx.AsyncClient
        parche = mock.patch.object(self.erp.httpx, "AsyncClient", lambda **k: real(transport=httpx.MockTransport(manejar), **k))
        from types import SimpleNamespace
        aj = mock.patch.object(self.erp, "ajustes", SimpleNamespace(erpnext_url="http://erp", dir_config=self.erp.ajustes.dir_config))
        buzon = mock.patch.object(B, "resolver", lambda d, b: ("albert", {}))
        adj = mock.patch.object(correo, "obtener_adjunto", lambda *a: (fichero, "application/pdf", datos))
        with parche, buzon, adj, aj:
            return ejecutar(self.erp.adjuntar_desde_correo(doctype, nombre, "<m@x>", 1, dep))

    def test_se_guarda_privado_en_el_documento(self):
        r = self.ejecutar()
        self.assertEqual(r["url"], "/private/files/presupuesto.pdf")
        cuerpo = self.subidos[0].content
        for esperado in (b'name="doctype"', b"CRM Lead", b"CRM-LEAD-1", b'name="is_private"', b"\r\n1\r\n", b"presupuesto.pdf"):
            self.assertIn(esperado, cuerpo)
        self.assertEqual(self.subidos[0].headers["authorization"], "token k:s")        # con la clave del departamento

    def test_la_politica_manda(self):
        for dep, doc in [("comercial", "Sales Invoice"), ("comercial", "Bank Account"), ("marketing", "Customer"), ("inventado", "CRM Lead")]:
            with self.subTest(dep=dep, doc=doc), self.assertRaises(PermissionError):
                self.ejecutar(doctype=doc, dep=dep)
        self.assertEqual(self.subidos, [])

    def test_nombre_de_documento_no_puede_ser_una_ruta(self):
        with self.assertRaises(PermissionError):
            self.ejecutar(nombre="../User/Administrator")

    def test_ejecutables_y_ficheros_disfrazados_no_se_guardan(self):
        with self.assertRaises(PermissionError):
            self.ejecutar(fichero="instalador.exe", datos=b"MZ")
        with self.assertRaises(PermissionError):
            self.ejecutar(fichero="falso.pdf", datos=b"MZ\x90\x00")
        self.assertEqual(self.subidos, [])


try:
    import httpx
    assert hasattr(httpx, "MockTransport")
except (ImportError, AssertionError):
    TestGuardarEnElErp = unittest.skip("requiere httpx")(TestGuardarEnElErp)

if __name__ == "__main__":
    unittest.main()
