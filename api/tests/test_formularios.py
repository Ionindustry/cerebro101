"""Plantillas administrativas: detectar huecos y rellenarlos en una copia sin tocar el resto del documento (Word y PDF con formulario)."""
import tempfile
import unittest
import zipfile
from pathlib import Path

import _sin_servicios  # noqa: F401

from cerebro.licitaciones import formularios as F

NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml" '
      'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" mc:Ignorable="w14"')


def r(t, extra=""):
    return f'<w:r>{extra}<w:t xml:space="preserve">{t}</w:t></w:r>'


def p(*runs):
    return "<w:p><w:pPr><w:jc w:val=\"both\"/></w:pPr>" + "".join(runs) + "</w:p>"


def celda(texto=""):
    return "<w:tc><w:tcPr><w:tcW w:w=\"2000\" w:type=\"dxa\"/></w:tcPr>" + (p(r(texto)) if texto else "<w:p/>") + "</w:tc>"


def fila(*celdas):
    return "<w:tr>" + "".join(celdas) + "</w:tr>"


def control(alias, marcador=True):
    pr = f'<w:sdtPr><w:alias w:val="{alias}"/>{"<w:showingPlcHdr/>" if marcador else ""}<w:text/></w:sdtPr>'
    return f'<w:sdt>{pr}<w:sdtContent><w:r><w:rPr><w:rStyle w:val="PlaceholderText"/></w:rPr><w:t>Haga clic aquí</w:t></w:r></w:sdtContent></w:sdt>'


CUERPO = (
    p(r("ANEXO I. MODELO DE DECLARACIÓN RESPONSABLE", "<w:rPr><w:b/></w:rPr>")) +
    # el hueco partido en varios trozos, como lo deja Word al editar
    p(r("D./Dª "), r("_____"), r("__________"), r(", con DNI nº "), r("__________"), r(", en representación de la empresa "), r("____________________"),
      r(", con NIF "), r("_________"), r(" y domicilio en "), r("......................................")) +
    p(r("DECLARA responsablemente que cumple los requisitos de solvencia del expediente "), r("________"), r(" (objeto: "), r("___________________"), r(").")) +
    "<w:tbl><w:tblPr/><w:tblGrid/>" + fila(celda("Razón social"), celda()) + fila(celda("Teléfono"), celda()) + fila(celda("Fax (en su caso)"), celda()) + fila(celda("Dato raro"), celda()) + "</w:tbl>" +
    p(r("Correo electrónico: "), control("Correo electrónico")) +
    p(r("☐ Microempresa   ☐ Pequeña empresa")) +
    p(r("En "), r("____________"), r(", a "), r("____"), r(" de "), r("__________"), r(" de 2026"))
)


def docx(ruta: Path, cuerpo=CUERPO):
    xml = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {NS}><w:body>{cuerpo}<w:sectPr/></w:body></w:document>'
    with zipfile.ZipFile(ruta, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", xml)
        z.writestr("word/styles.xml", "<w:styles " + NS + "><!-- estilos que no se tocan --></w:styles>")
        z.writestr("word/header1.xml", "<w:hdr " + NS + "/>")


def texto_de(ruta: Path) -> str:
    with zipfile.ZipFile(ruta) as z:
        x = z.read("word/document.xml").decode()
    return F._texto_xml(x)


DATOS = {"representante.nombre": "Ana Pérez Soler", "representante.dni": "12345678Z", "empresa.razon_social": "101 Telecomunicaciones & Seguridad, S.L.", "empresa.nif": "B12345678",
         "empresa.domicilio": "Calle Major 1, 17001 Girona", "licitacion.expediente": "2026/045", "licitacion.objeto": "Videovigilancia <urbana>", "empresa.telefono": "972 000 000",
         "empresa.email": "licitaciones@101.cat", "empresa.localidad": "Girona"}


class TestDetectar(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.ruta = Path(self.d.name) / "anexo.docx"
        docx(self.ruta)

    def tearDown(self):
        self.d.cleanup()

    def claves(self):
        return {c["id"]: c for c in F.detectar(self.ruta, "docx")["campos"]}

    def test_empareja_cada_hueco_con_su_dato(self):
        c = list(self.claves().values())
        texto = [(x["clave"], x["tipo"]) for x in c]
        self.assertEqual([k for k, t in texto if t == "texto"], ["representante.nombre", "representante.dni", "empresa.razon_social", "empresa.nif", "empresa.domicilio",
                                                                  "licitacion.expediente", "licitacion.objeto", "empresa.localidad", F.SIN_DATO, F.SIN_DATO])
        self.assertEqual([x["clave"] for x in c if x["tipo"] == "celda"], ["empresa.razon_social", "empresa.telefono", None, None])
        self.assertEqual([x["clave"] for x in c if x["tipo"] == "control"], ["empresa.email"])
        self.assertEqual(sum(1 for x in c if x["tipo"] == "casilla"), 2)

    def test_lo_opcional_y_lo_dudoso_se_distinguen(self):
        c = [x for x in F.detectar(self.ruta, "docx")["campos"] if x["tipo"] == "celda"]
        self.assertEqual([x["opcional"] for x in c], [False, False, True, False])
        self.assertEqual([x["etiqueta"] for x in c][-1], "dato raro")

    def test_el_nif_depende_de_si_ya_se_habla_de_la_empresa(self):
        self.assertEqual(F.emparejar("con NIF", "D. Ana, con NIF"), "representante.dni")
        self.assertEqual(F.emparejar("con NIF", "D. Ana, en representación de X, con NIF"), "empresa.nif")
        self.assertEqual(F.emparejar("NIF/CIF", "", en_tabla=True), "empresa.nif")
        self.assertEqual(F.emparejar("NIF del representante", "", en_tabla=True), "representante.dni")
        self.assertIsNone(F.emparejar("Observaciones", ""))

    def test_no_hay_huecos_se_dice(self):
        docx(self.ruta, p(r("Texto sin huecos.")))
        r_ = F.detectar(self.ruta, "docx")
        self.assertEqual(r_["campos"], [])
        self.assertTrue(r_["avisos"])


class TestRellenar(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.dir = Path(self.d.name)
        self.ruta = self.dir / "anexo.docx"
        docx(self.ruta)
        self.original = self.ruta.read_bytes()

    def tearDown(self):
        self.d.cleanup()

    def valores(self):
        return {c["id"]: DATOS[c["clave"]] for c in F.detectar(self.ruta, "docx")["campos"] if c["clave"] in DATOS}

    def test_rellena_una_copia_y_no_toca_el_original(self):
        destino = self.dir / "salida" / "anexo (rellenado).docx"
        res = F.rellenar(self.ruta, "docx", destino, self.valores())
        self.assertEqual(self.ruta.read_bytes(), self.original)
        self.assertEqual(len(res["rellenados"]), 11)
        t = texto_de(destino)
        for esperado in ("d./dª ana pérez soler, con dni nº 12345678z", "en representación de la empresa 101 telecomunicaciones & seguridad, s.l.".lower(),
                         "con nif b12345678 y domicilio en calle major 1, 17001 girona", "expediente 2026/045 (objeto: videovigilancia <urbana>)", "razón social 101 telecomunicaciones",
                         "teléfono 972 000 000", "correo electrónico: licitaciones@101.cat", "en girona, a ____ de __________ de 2026"):
            self.assertIn(_n(esperado), _n(t), esperado)
        self.assertNotIn("haga clic aquí", t)

    def test_el_resto_del_documento_queda_igual_y_el_xml_es_valido(self):
        destino = self.dir / "o.docx"
        F.rellenar(self.ruta, "docx", destino, self.valores())
        with zipfile.ZipFile(self.ruta) as a, zipfile.ZipFile(destino) as b:
            self.assertEqual(a.namelist(), b.namelist())
            for n in a.namelist():
                if n != "word/document.xml":
                    self.assertEqual(a.read(n), b.read(n), n)
            x = b.read("word/document.xml").decode()
        self.assertIn('mc:Ignorable="w14"', x)                                # los espacios de nombres y la estructura siguen
        self.assertIn("ANEXO I. MODELO DE DECLARACIÓN RESPONSABLE", x)
        self.assertIn("&amp;", x)                                             # el & del nombre va escapado
        self.assertNotIn("Videovigilancia <urbana>", x)
        self.assertNotIn("PlaceholderText", x)
        self.assertNotIn("showingPlcHdr", x)

    def test_lo_que_no_se_da_queda_con_su_hueco_y_las_casillas_no_se_tocan(self):
        destino = self.dir / "o.docx"
        v = self.valores()
        quitado = next(i for i, c in {c["id"]: c for c in F.detectar(self.ruta, "docx")["campos"]}.items() if c["clave"] == "representante.dni")
        v.pop(quitado)
        casilla = next(c["id"] for c in F.detectar(self.ruta, "docx")["campos"] if c["tipo"] == "casilla")
        v[casilla] = "x"
        res = F.rellenar(self.ruta, "docx", destino, v)
        self.assertIn(casilla, res["omitidos"])
        self.assertIn("☐ Microempresa", texto_de(destino).replace("  ", " ") if False else texto_de(destino).replace("☐ microempresa", "☐ Microempresa"))
        det = F.detectar(destino, "docx")
        self.assertIn("representante.dni", [c["clave"] for c in det["campos"] if c["tipo"] == "texto"])      # ese hueco sigue ahí

    def test_valores_hostiles_no_rompen_el_xml(self):
        destino = self.dir / "o.docx"
        v = {k: '</w:t></w:r><w:r><w:t>"; DROP\x00\x1f\n&<>' for k in self.valores()}
        F.rellenar(self.ruta, "docx", destino, v)
        with zipfile.ZipFile(destino) as z:
            F.ET.fromstring(z.read("word/document.xml"))                      # sigue siendo XML bien formado
            x = z.read("word/document.xml").decode()
        self.assertNotIn("</w:t></w:r><w:r><w:t>\"; DROP", x)
        self.assertNotIn("\x00", x)

    def test_un_docx_dañado_o_enorme_se_rechaza_con_un_mensaje(self):
        mal = self.dir / "mal.docx"
        mal.write_bytes(b"no es un zip")
        with self.assertRaises(F.ErrorFormulario):
            F.detectar(mal, "docx")
        sin = self.dir / "sin.docx"
        with zipfile.ZipFile(sin, "w") as z:
            z.writestr("otro.xml", "<a/>")
        with self.assertRaises(F.ErrorFormulario):
            F.detectar(sin, "docx")
        with unittest.mock.patch.object(F, "MAX_XML", 10), self.assertRaises(F.ErrorFormulario):
            F.detectar(self.ruta, "docx")

    def test_formatos_sin_soporte_se_dicen(self):
        with self.assertRaisesRegex(F.ErrorFormulario, "odt"):
            F.detectar(self.ruta, "odt")


def _n(t):
    return " ".join(F._norm(t).split())


import unittest.mock  # noqa: E402


def pdf_con_formulario(ruta: Path, campos):
    from pypdf import PdfWriter
    from pypdf.generic import ArrayObject, DictionaryObject, FloatObject, NameObject, NumberObject, TextStringObject
    w = PdfWriter()
    w.add_blank_page(612, 792)
    refs = []
    for i, (nombre, etiqueta) in enumerate(campos):
        d = DictionaryObject({NameObject("/Type"): NameObject("/Annot"), NameObject("/Subtype"): NameObject("/Widget"), NameObject("/FT"): NameObject("/Tx"),
                              NameObject("/T"): TextStringObject(nombre), NameObject("/TU"): TextStringObject(etiqueta), NameObject("/F"): NumberObject(4),
                              NameObject("/Rect"): ArrayObject([FloatObject(50), FloatObject(700 - i * 40), FloatObject(300), FloatObject(720 - i * 40)]),
                              NameObject("/DA"): TextStringObject("/Helv 10 Tf 0 g")})
        ref = w._add_object(d)
        refs.append(ref)
        w.pages[0].setdefault(NameObject("/Annots"), ArrayObject()).append(ref)
    w._root_object[NameObject("/AcroForm")] = DictionaryObject({NameObject("/Fields"): ArrayObject(refs), NameObject("/DA"): TextStringObject("/Helv 10 Tf 0 g")})
    with open(ruta, "wb") as f:
        w.write(f)


class TestPdf(unittest.TestCase):
    def test_detecta_y_rellena_los_campos_del_formulario(self):
        from pypdf import PdfReader
        with tempfile.TemporaryDirectory() as d:
            ruta, destino = Path(d) / "f.pdf", Path(d) / "salida" / "f (rellenado).pdf"
            pdf_con_formulario(ruta, [("a", "Razón social"), ("b", "NIF/CIF"), ("c", "Nombre y apellidos del representante"), ("d", "Fax (en su caso)")])
            det = F.detectar(ruta, "pdf")
            self.assertEqual([c["clave"] for c in det["campos"]], ["empresa.razon_social", "empresa.nif", "representante.nombre", None])
            self.assertTrue(det["campos"][3]["opcional"])
            res = F.rellenar(ruta, "pdf", destino, {"p1": "101 S.L.", "p2": "B12345678", "p3": "Ana Pérez", "p9": "no existe"})
            self.assertEqual(res["rellenados"], ["p1", "p2", "p3"])
            self.assertEqual(res["omitidos"], ["p9"])
            campos = {k: v.get("/V") for k, v in PdfReader(str(destino)).get_fields().items()}
            self.assertEqual(campos, {"a": "101 S.L.", "b": "B12345678", "c": "Ana Pérez", "d": None})

    def test_un_pdf_sin_formulario_dice_que_hay_que_pedirlo_en_word(self):
        from pypdf import PdfWriter
        with tempfile.TemporaryDirectory() as d:
            ruta = Path(d) / "plano.pdf"
            w = PdfWriter()
            w.add_blank_page(100, 100)
            with open(ruta, "wb") as f:
                w.write(f)
            det = F.detectar(ruta, "pdf")
            self.assertEqual(det["campos"], [])
            self.assertIn("Word", det["avisos"][0])
            malo = Path(d) / "malo.pdf"
            malo.write_bytes(b"%PDF-1.4 roto")
            with self.assertRaises(F.ErrorFormulario):
                F.detectar(malo, "pdf")


class TestAislado(unittest.TestCase):
    def test_detectar_y_rellenar_en_un_proceso_aparte(self):
        with tempfile.TemporaryDirectory() as d:
            ruta, destino = Path(d) / "a.docx", Path(d) / "b.docx"
            docx(ruta)
            det = F.ejecutar_aislado({"accion": "detectar", "ruta": str(ruta), "formato": "docx"})
            self.assertTrue(det["campos"])
            primero = det["campos"][0]["id"]
            res = F.ejecutar_aislado({"accion": "rellenar", "ruta": str(ruta), "formato": "docx", "destino": str(destino), "valores": {primero: "Ana"}})
            self.assertEqual(res["rellenados"], [primero])
            self.assertTrue(destino.exists())
            with self.assertRaises(F.ErrorFormulario):
                F.ejecutar_aislado({"accion": "detectar", "ruta": str(Path(d) / "no_existe.docx"), "formato": "docx"})


if __name__ == "__main__":
    unittest.main()
