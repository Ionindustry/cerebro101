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


def sub(texto):
    """Un hueco hecho con espacios subrayados, como lo dejan Word y LibreOffice en las plantillas de las administraciones."""
    return f'<w:r><w:rPr><w:u w:val="single"/></w:rPr><w:t xml:space="preserve">{texto}</w:t></w:r>'


def campo_antiguo(nombre="Texto1", ayuda="", resultado="\u2003\u2003\u2003"):
    estado = f'<w:statusText w:type="text" w:val="{ayuda}"/>' if ayuda else ""
    return (f'<w:r><w:fldChar w:fldCharType="begin"><w:ffData><w:name w:val="{nombre}"/><w:enabled/>{estado}<w:textInput/></w:ffData></w:fldChar></w:r>'
            '<w:r><w:instrText xml:space="preserve"> FORMTEXT </w:instrText></w:r><w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            + (f'<w:r><w:rPr><w:noProof/></w:rPr><w:t>{resultado}</w:t></w:r>' if resultado else "") + '<w:r><w:fldChar w:fldCharType="end"/></w:r>')


CASILLA_ANTIGUA = ('<w:r><w:fldChar w:fldCharType="begin"><w:ffData><w:name w:val="Casilla1"/><w:checkBox><w:sizeAuto/><w:default w:val="0"/></w:checkBox></w:ffData></w:fldChar></w:r>'
                   '<w:r><w:instrText xml:space="preserve"> FORMCHECKBOX </w:instrText></w:r><w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r>')


class TestHuecosHabituales(unittest.TestCase):
    """Los dos patrones más comunes en las plantillas reales de las administraciones: espacios subrayados y campos de formulario antiguos de Word."""

    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.dir = Path(self.d.name)

    def tearDown(self):
        self.d.cleanup()

    def test_espacios_subrayados_son_huecos_y_se_rellenan_conservando_el_formato(self):
        ruta = self.dir / "a.docx"
        docx(ruta, p(r("D./Dª "), sub("                    "), r(", con DNI nº "), sub("      "), sub("      "), r(", en representación de la empresa "), sub("                              "),
                     r(" y un texto normal con  dos  espacios y "), r("   ", "<w:rPr><w:b/></w:rPr>"), r("sin subrayar.")))
        det = F.detectar(ruta, "docx")["campos"]
        self.assertEqual([c["clave"] for c in det], ["representante.nombre", "representante.dni", "empresa.razon_social"])    # los espacios normales no son huecos; dos trozos seguidos son uno
        destino = self.dir / "o.docx"
        F.rellenar(ruta, "docx", destino, {c["id"]: DATOS[c["clave"]] for c in det})
        self.assertIn("d./da ana perez soler, con dni no 12345678z, en representacion de la empresa 101 telecomunicaciones & seguridad, s.l. y un texto normal", texto_original_n(destino))
        with zipfile.ZipFile(destino) as z:
            x = z.read("word/document.xml").decode()
        self.assertGreaterEqual(x.count('<w:u w:val="single"/>'), 3)                      # el subrayado sigue: el dato queda sobre su línea

    def test_campos_de_formulario_antiguos_texto_y_casilla(self):
        ruta = self.dir / "b.docx"
        docx(ruta, p(r("Razón social: "), campo_antiguo("Texto1")) + p(r("Datos del licitador "), campo_antiguo("Texto2", ayuda="NIF/CIF")) + p(r("Fax "), campo_antiguo("Texto3", resultado="")) +
             p(r("Pequeña empresa "), CASILLA_ANTIGUA) + p(r("Lista: "), '<w:r><w:fldChar w:fldCharType="begin"><w:ffData><w:name w:val="Lista1"/><w:ddList/></w:ffData></w:fldChar></w:r>'))
        det = F.detectar(ruta, "docx")["campos"]
        self.assertEqual([(c["tipo"], c["clave"]) for c in det], [("campo", "empresa.razon_social"), ("campo", "empresa.nif"), ("campo", None), ("casilla", None)])    # la lista desplegable no se toca
        self.assertTrue(det[2]["opcional"])
        destino = self.dir / "o.docx"
        res = F.rellenar(ruta, "docx", destino, {det[0]["id"]: "101 Telecom, S.L.", det[1]["id"]: "B12345678", det[2]["id"]: "972 000 000", det[3]["id"]: "x"})
        self.assertEqual(res["rellenados"], [det[0]["id"], det[1]["id"], det[2]["id"]])
        self.assertEqual(res["omitidos"], [det[3]["id"]])                                   # una casilla no se marca sola
        with zipfile.ZipFile(destino) as z:
            x = z.read("word/document.xml").decode()
        F.ET.fromstring(x)
        self.assertEqual(x.count("FORMTEXT"), 3)                                           # siguen siendo campos de formulario (se pueden volver a editar)
        t = texto_original_n(destino)
        for esperado in ("razon social: 101 telecom, s.l.", "datos del licitador b12345678", "fax 972 000 000"):
            self.assertIn(esperado, t)
        self.assertNotIn("\u2003", x.split("Razón social")[1].split("FORMTEXT")[1].split("</w:p>")[0])      # el resultado antiguo (espacios) ya no está

    def test_un_campo_de_formulario_roto_no_estropea_el_documento(self):
        ruta = self.dir / "c.docx"
        # empieza y no termina: no se toca y no falla
        docx(ruta, p(r("Nombre: "), campo_antiguo().replace('<w:r><w:fldChar w:fldCharType="end"/></w:r>', "")))
        self.assertEqual(F.detectar(ruta, "docx")["campos"], [])


def texto_original_n(ruta):
    return " ".join(F._texto_xml(zipfile.ZipFile(ruta).read("word/document.xml").decode()).split())


class TestAnexosYZip(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.dir = Path(self.d.name)

    def tearDown(self):
        self.d.cleanup()

    def test_cada_hueco_sabe_a_que_anexo_pertenece(self):
        ruta = self.dir / "doc.docx"
        docx(ruta, p(r("Cláusula 1. El licitador presentará su oferta en tiempo y forma.")) + p(r("ANEXO I. DECLARACIÓN RESPONSABLE")) +
              p(r("D./Dª "), r("__________"), r(", con DNI nº "), r("________")) + p(r("ANEXO II. MODELO DE PROPOSICIÓN ECONÓMICA")) +
              p(r("En representación de la empresa "), r("____________________"), r(", con NIF "), r("_________")) + p(r("Modelo de declaración de grupo empresarial")) + p(r("Razón social: "), r("______")))
        det = F.detectar(ruta, "docx")["campos"]
        self.assertEqual([(c["clave"], c["anexo"]) for c in det], [("representante.nombre", "ANEXO I. DECLARACIÓN RESPONSABLE"), ("representante.dni", "ANEXO I. DECLARACIÓN RESPONSABLE"),
                                                                    ("empresa.razon_social", "ANEXO II. MODELO DE PROPOSICIÓN ECONÓMICA"), ("empresa.nif", "ANEXO II. MODELO DE PROPOSICIÓN ECONÓMICA"),
                                                                    ("empresa.razon_social", "Modelo de declaración de grupo empresarial")])

    def test_una_frase_larga_que_empieza_por_modelo_no_es_un_titulo(self):
        ruta = self.dir / "doc.docx"
        docx(ruta, p(r("Modelo " + "muy largo " * 30)) + p(r("Razón social: "), r("______")))
        self.assertEqual(F.detectar(ruta, "docx")["campos"][0]["anexo"], "")

    def paquete(self, miembros):
        ruta = self.dir / "paquete.zip"
        with zipfile.ZipFile(ruta, "w", zipfile.ZIP_DEFLATED) as z:
            for nombre, datos in miembros:
                z.writestr(nombre, datos)
        return ruta

    def test_el_zip_deja_los_anexos_en_word_y_pdf_y_avisa_del_resto(self):
        d1, d2 = self.dir / "a.docx", self.dir / "b.pdf"
        docx(d1)
        pdf_con_formulario(d2, [("a", "Razón social")])
        zip_ = self.paquete([("Documentación administrativa/Anexo I.docx", d1.read_bytes()), ("Documentación administrativa/Anexo II.pdf", d2.read_bytes()),
                             ("Documentación administrativa/Anexo III.doc", b"binario"), ("Sobre 1/Anexo IV.odt", b"x"), ("leeme.txt", b"hola"),
                             ("../escapa.docx", d1.read_bytes()), ("/absoluta.docx", d1.read_bytes()), ("falso.docx", b"esto no es un word")])
        r = F.extraer_zip(zip_, self.dir / "fuera")
        self.assertEqual([(m["miembro"], m["formato"]) for m in r["miembros"]], [("Documentación administrativa/Anexo I.docx", "docx"), ("Documentación administrativa/Anexo II.pdf", "pdf")])
        for m in r["miembros"]:
            self.assertTrue(Path(m["ruta"]).resolve().parent == (self.dir / "fuera").resolve())          # nada se escribe fuera de la carpeta de destino
            self.assertTrue(F.detectar(Path(m["ruta"]), m["formato"])["campos"])
        avisos = " ".join(r["avisos"])
        for esperado in ("Anexo III.doc", "Anexo IV.odt", "escapa.docx", "absoluta.docx", "falso.docx"):
            self.assertIn(esperado, avisos)
        self.assertEqual(sorted(x.name for x in (self.dir / "fuera").iterdir()), ["001.docx", "002.pdf"])
        self.assertFalse((self.dir / "escapa.docx").exists())

    def test_zip_roto_enorme_o_con_demasiados_ficheros(self):
        mal = self.dir / "mal.zip"
        mal.write_bytes(b"no es un zip")
        with self.assertRaises(F.ErrorFormulario):
            F.extraer_zip(mal, self.dir / "x")
        muchos = self.paquete([(f"f{i}.txt", b"x") for i in range(6)])
        with unittest.mock.patch.object(F, "MAX_MIEMBROS", 5), self.assertRaises(F.ErrorFormulario):
            F.extraer_zip(muchos, self.dir / "x")
        with unittest.mock.patch.object(F, "MAX_TOTAL", 3), self.assertRaises(F.ErrorFormulario):
            F.extraer_zip(muchos, self.dir / "x")
        bomba = self.paquete([("bomba.docx", b"PK" + b"\0" * 5_000_000)])
        r = F.extraer_zip(bomba, self.dir / "y")
        self.assertEqual(r["miembros"], [])
        self.assertIn("sospechoso", r["avisos"][0])                                           # una razón de compresión enorme no se abre

    def test_extraer_en_proceso_aparte(self):
        d1 = self.dir / "a.docx"
        docx(d1)
        zip_ = self.paquete([("Anexo I.docx", d1.read_bytes())])
        r = F.ejecutar_aislado({"accion": "extraer_zip", "ruta": str(zip_), "formato": "zip", "destino": str(self.dir / "o")})
        self.assertEqual([m["miembro"] for m in r["miembros"]], ["Anexo I.docx"])


class TestModeloDeProposicion(unittest.TestCase):
    def test_las_etiquetas_del_precio_se_emparejan_con_su_dato(self):
        casos = [("D. Ana se compromete a ejecutar el contrato por el precio de", "oferta.precio"), ("Precio ofertado (sin IVA)", "oferta.precio"), ("Importe de la oferta:", "oferta.precio"),
                 ("por un importe de", "oferta.precio"), ("IVA (21 %):", "oferta.iva"), ("Importe del IVA", "oferta.iva"), ("Tipo de IVA", "oferta.iva_pct"),
                 ("Importe total (IVA incluido):", "oferta.precio_con_iva"), ("Precio con IVA", "oferta.precio_con_iva"), ("(en letra)", "oferta.precio_letras"),
                 ("Importe total", None), ("Observaciones", None)]
        for etiqueta, clave in casos:
            self.assertEqual(F.emparejar(etiqueta, etiqueta, en_tabla=True), clave, etiqueta)

    def test_si_euros_va_detras_del_hueco_la_letra_no_repite_la_unidad(self):
        self.assertEqual(F.emparejar("(en letra", "", despues=" euros)"), "oferta.precio_letras_sin_unidad")
        self.assertEqual(F.emparejar("(en letra", "", despues=" € )"), "oferta.precio_letras_sin_unidad")
        self.assertEqual(F.emparejar("(en letra", "", despues=")"), "oferta.precio_letras")
        self.assertEqual(F.emparejar("en letra:", "", despues=""), "oferta.precio_letras")

    def test_un_modelo_completo_se_detecta_y_se_rellena(self):
        with tempfile.TemporaryDirectory() as d:
            ruta, destino = Path(d) / "m.docx", Path(d) / "o.docx"
            docx(ruta, p(r("ANEXO II. MODELO DE PROPOSICIÓN ECONÓMICA")) +
                 p(r("D./Dª "), r("__________"), r(", en representación de la empresa "), r("__________"), r(", se compromete a ejecutar el contrato por el precio de "), r("__________"),
                   r(" euros (IVA excluido), (en letra "), r("______________"), r(" euros)")) +
                 "<w:tbl><w:tblPr/><w:tblGrid/>" + fila(celda("IVA (21 %):"), celda()) + fila(celda("Importe total (IVA incluido):"), celda()) + "</w:tbl>")
            det = F.detectar(ruta, "docx")["campos"]
            self.assertEqual([c["clave"] for c in det], ["representante.nombre", "empresa.razon_social", "oferta.precio", "oferta.precio_letras_sin_unidad", "oferta.iva", "oferta.precio_con_iva"])
            valores = {"representante.nombre": "Ana Pérez", "empresa.razon_social": "101 S.L.", "oferta.precio": "125.000,00", "oferta.precio_letras_sin_unidad": "ciento veinticinco mil",
                       "oferta.iva": "26.250,00", "oferta.precio_con_iva": "151.250,00"}
            F.rellenar(ruta, "docx", destino, {c["id"]: valores[c["clave"]] for c in det})
            t = " ".join(texto_original_n(destino).split())
            self.assertIn("por el precio de 125.000,00 euros (iva excluido), (en letra ciento veinticinco mil euros)", t)
            self.assertIn("iva (21 %): 26.250,00", t)
            self.assertIn("importe total (iva incluido): 151.250,00", t)


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
