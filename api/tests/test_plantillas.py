"""Documentación administrativa de una oferta: datos de la sociedad desde el ERP (varias sociedades), plantillas del concurso rellenadas en copias y pasos de la cadena de agentes
(con CEREBRO_TEST_PG para la parte de base de datos)."""
import asyncio
import hashlib
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import _sin_servicios  # noqa: F401

try:
    import httpx
    import psycopg
    from cerebro.herramientas import erpnext, plantillas as herramienta
    from cerebro.licitaciones import empresa as E, formularios as F, ofertas as O, plantillas as PL, pliegos, redaccion as R
    from test_formularios import DATOS, docx, pdf_con_formulario
except ImportError as e:      # pragma: no cover
    raise unittest.SkipTest(str(e))

URL = os.environ.get("CEREBRO_TEST_PG")
ESQUEMA = Path(__file__).resolve().parents[2] / "db" / "esquema.sql"
ID = "0b1f7a3e-1111-4222-8333-444444444444"
FICHA = {"titulo": "Videovigilancia urbana", "expediente": "2026/045", "comprador": {"nombre": "Ajuntament de Girona"}, "criterios": []}


def ejecutar(c):
    return asyncio.run(c)


CUERPO_SIMPLE = ('<w:p><w:r><w:t xml:space="preserve">Razón social: </w:t></w:r><w:r><w:t>__________</w:t></w:r></w:p>'
                 '<w:p><w:r><w:t xml:space="preserve">con NIF </w:t></w:r><w:r><w:t>_________</w:t></w:r></w:p>')


def docx_sin_huecos(carpeta):
    ruta = carpeta / "sin_huecos.docx"
    docx(ruta, "<w:p><w:r><w:t>Solo texto, sin huecos.</w:t></w:r></w:p>")
    return ruta.read_bytes()


EMPRESAS = [{"name": "101 Telecom S.L.", "company_name": "101 Telecomunicaciones & Seguridad, S.L.", "tax_id": "B12345678", "phone_no": "972 000 000", "email": "licitaciones@101.cat",
             "country": "Spain", "registration_details": "Registro Mercantil de Girona, tomo 1, folio 2"},
            {"name": "Ion Industry S.A.", "company_name": "Ion Industry, S.A.", "tax_id": "A87654321", "phone_no": "", "email": "", "country": "Spain"}]
DIRECCIONES = {"101 Telecom S.L.": [{"name": "D1", "address_line1": "Calle Major 1", "address_line2": "", "city": "Girona", "state": "Girona", "pincode": "17001", "country": "Spain",
                                     "is_primary_address": 1, "is_your_company_address": 1, "phone": "", "email_id": ""}],
               "Ion Industry S.A.": []}
CONTACTOS = {"101 Telecom S.L.": [{"name": "C1", "first_name": "Marta", "last_name": "Soler", "designation": "Comercial", "dni": "11111111H"},
                                  {"name": "C2", "first_name": "Ana", "last_name": "Pérez Soler", "designation": "Administradora única", "dni": "12345678Z", "poder": "Escritura 123, notario X"}],
             "Ion Industry S.A.": []}


class ERPFalso:
    def __init__(self, sin_personalizados=False):
        self.sin_personalizados = sin_personalizados
        self.llamadas = []

    async def __call__(self, doctype, dep, filtros=None, campos=None, limite=20):
        self.llamadas.append((doctype, dep, tuple(campos or [])))
        if self.sin_personalizados and any(c in (campos or []) for c in ("registration_details", "dni", "poder")):
            raise httpx.HTTPStatusError("x", request=httpx.Request("GET", "http://x"), response=httpx.Response(417))
        if doctype == "Company":
            return [c for c in EMPRESAS if not filtros or c["name"] == filtros[0][2]]
        nombre = next(f[3] for f in filtros if f[1] == "link_name")
        return (DIRECCIONES if doctype == "Address" else CONTACTOS)[nombre]


class TestEmpresa(unittest.TestCase):
    def test_con_varias_sociedades_hay_que_elegir_y_cada_una_tiene_sus_datos(self):
        with mock.patch.object(erpnext, "listar_sistema", ERPFalso()):
            with self.assertRaises(E.VariasEmpresas) as c:
                ejecutar(E.elegir(None))
            self.assertEqual([x["nif"] for x in c.exception.empresas], ["B12345678", "A87654321"])
            with self.assertRaises(E.ErrorEmpresa):
                ejecutar(E.elegir("No existe"))
            d = ejecutar(E.datos("101 Telecom S.L."))
            v = {k: x["valor"] for k, x in d["valores"].items()}
            self.assertEqual(v["empresa.razon_social"], "101 Telecomunicaciones & Seguridad, S.L.")
            self.assertEqual(v["empresa.nif"], "B12345678")
            self.assertEqual((v["empresa.domicilio"], v["empresa.cp"], v["empresa.localidad"], v["empresa.provincia"]), ("Calle Major 1", "17001", "Girona", "Girona"))
            self.assertEqual((v["representante.nombre"], v["representante.cargo"], v["representante.dni"]), ("Ana Pérez Soler", "Administradora única", "12345678Z"))
            self.assertEqual(d["valores"]["empresa.nif"]["origen"], "ERP · Company 101 Telecom S.L. · tax_id")
            self.assertEqual(d["faltan"], {})
            otra = ejecutar(E.datos("Ion Industry S.A."))
            self.assertEqual(otra["valores"]["empresa.nif"]["valor"], "A87654321")
            self.assertIn("representante.nombre", otra["faltan"])            # esa sociedad no tiene representante en el ERP: se dice dónde completarlo
            self.assertIn("empresa.domicilio", otra["faltan"])
            self.assertNotIn("empresa.telefono", otra["valores"])

    def test_una_sola_sociedad_se_usa_sin_preguntar(self):
        with mock.patch.object(erpnext, "listar_sistema", mock.AsyncMock(return_value=[EMPRESAS[0]])):
            self.assertEqual(ejecutar(E.elegir(None)), "101 Telecom S.L.")

    def test_los_campos_personalizados_que_no_existen_en_el_erp_no_rompen_nada(self):
        with mock.patch.object(erpnext, "listar_sistema", ERPFalso(sin_personalizados=True)):
            d = ejecutar(E.datos("101 Telecom S.L."))
        self.assertIn("empresa.nif", d["valores"])
        for k in ("empresa.registro", "representante.dni", "representante.poder"):
            self.assertIn(k, d["faltan"])

    def test_solo_se_piden_los_campos_de_una_lista_cerrada_y_con_la_clave_del_departamento(self):
        erp = ERPFalso()
        with mock.patch.object(erpnext, "listar_sistema", erp):
            ejecutar(E.datos("101 Telecom S.L."))
        self.assertEqual({d for _, d, _ in erp.llamadas}, {"licitaciones"})
        for _, _, campos in erp.llamadas:
            self.assertNotIn("default_bank_account", campos)

    def test_el_erp_caido_o_sin_permiso_es_un_error_comprensible(self):
        with mock.patch.object(erpnext, "listar_sistema", mock.AsyncMock(side_effect=httpx.ConnectError("x"))), self.assertRaisesRegex(E.ErrorEmpresa, "ERP"):
            ejecutar(E.empresas())
        with mock.patch.object(erpnext, "listar_sistema", mock.AsyncMock(side_effect=PermissionError("no permitido"))), self.assertRaisesRegex(E.ErrorEmpresa, "no permitido"):
            ejecutar(E.empresas())


class TestClasificar(unittest.TestCase):
    CAMPOS = [{"id": "t1", "tipo": "texto", "etiqueta": "con NIF", "clave": "empresa.nif", "opcional": False, "fijo": False},
              {"id": "t2", "tipo": "texto", "etiqueta": "domicilio en", "clave": "empresa.domicilio", "opcional": False, "fijo": False},
              {"id": "t3", "tipo": "texto", "etiqueta": "Observaciones", "clave": None, "opcional": False, "fijo": False},
              {"id": "t4", "tipo": "texto", "etiqueta": "Fax", "clave": None, "opcional": True, "fijo": False},
              {"id": "t5", "tipo": "texto", "etiqueta": "a", "clave": F.SIN_DATO, "opcional": False, "fijo": False},
              {"id": "c6", "tipo": "casilla", "etiqueta": "Microempresa", "clave": None, "opcional": False, "fijo": True}]
    FUENTE = {"empresa.nif": {"valor": "B1", "origen": "ERP · Company X · tax_id"}, "empresa.cp": {"valor": "17001", "origen": "ERP"}}

    def test_reparte_rellenado_pendiente_y_lo_que_no_bloquea(self):
        valores, rellenados, pendientes = PL.clasificar(self.CAMPOS, {}, self.FUENTE)
        self.assertEqual(valores, {"t1": "B1"})
        self.assertEqual(rellenados[0]["origen"], "ERP · Company X · tax_id")
        por = {p["id"]: p for p in pendientes}
        self.assertEqual(set(por), {"t2", "t3", "t5", "c6"})                 # el opcional sin dato no aparece
        self.assertIn("Falta el dato en", por["t2"]["motivo"])
        self.assertIn("Dirección enlazada a la empresa", por["t2"]["motivo"])
        self.assertTrue(por["t2"]["bloquea"] and por["t3"]["bloquea"] and por["c6"]["bloquea"])
        self.assertFalse(por["t5"]["bloquea"])                                # la fecha se completa al firmar
        self.assertEqual(PL.estado_de(self.CAMPOS, valores, pendientes), "faltan_datos")

    def test_un_agente_solo_elige_la_clave_el_valor_sale_siempre_de_la_fuente(self):
        valores, _, pendientes = PL.clasificar(self.CAMPOS, {"t3": "empresa.cp", "t2": "inventado.cosa"}, self.FUENTE)
        self.assertEqual(valores["t3"], "17001")
        self.assertNotIn("t2", valores)                                      # una clave que no existe se ignora
        self.assertIn("t2", {p["id"] for p in pendientes})

    def test_listo_para_firmar_solo_sin_pendientes_que_bloqueen(self):
        c = [x for x in self.CAMPOS if x["id"] in ("t1", "t5")]
        valores, _, pendientes = PL.clasificar(c, {}, self.FUENTE)
        self.assertEqual(PL.estado_de(c, valores, pendientes), "lista_para_firma")
        self.assertEqual(PL.estado_de([], {}, []), "sin_huecos")
        self.assertEqual(PL.estado_de(c, {}, pendientes), "faltan_datos")

    def test_nombre_de_salida_seguro(self):
        n = PL._nombre_salida(3, "../../Anexo I: Modelo/declaración.docx", "docx")
        self.assertTrue(n.startswith("03 - ") and n.endswith("(rellenado).docx"))
        self.assertNotIn("/", n)
        self.assertNotIn("..", n.replace("(rellenado)", ""))


@unittest.skipUnless(URL, "sin CEREBRO_TEST_PG")
class TestBaseDeDatos(unittest.TestCase):
    def setUp(self):
        self.schema = f"t_plantillas_{time.time_ns()}"
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"CREATE SCHEMA {self.schema}")
            c.execute(f"SET search_path = {self.schema}")
            t = ESQUEMA.read_text(encoding="utf-8")
            c.execute(t[t.index("-- Pliegos y otros documentos de una licitación"):])
        sep = "&" if "?" in URL else "?"
        ajustes = SimpleNamespace(database_url=f"{URL}{sep}options=-csearch_path%3D{self.schema}")
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.p = [mock.patch.object(O, "ajustes", ajustes), mock.patch.object(pliegos, "ajustes", ajustes), mock.patch.object(pliegos, "RAIZ", self.dir / "pliegos"),
                  mock.patch.object(PL, "RAIZ", self.dir / "ofertas"), mock.patch.object(erpnext, "listar_sistema", ERPFalso())]
        for p in self.p:
            p.start()
        ejecutar(O.plan(ID, {}, "albert"))

    def tearDown(self):
        for p in self.p:
            p.stop()
        self.tmp.cleanup()
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"DROP SCHEMA {self.schema} CASCADE")

    def documento(self, n, nombre, formato, crear, estado="limpio"):
        carpeta = self.dir / "pliegos" / ID / "limpio"
        carpeta.mkdir(parents=True, exist_ok=True)
        tmp = carpeta / "tmp"
        crear(tmp)
        datos = tmp.read_bytes()
        sha = hashlib.sha256(datos).hexdigest()
        tmp.replace(carpeta / f"{sha}.{formato}")
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"SET search_path = {self.schema}")
            return c.execute("INSERT INTO pliegos_documentos (motor_id, n, nombre, formato, bytes, sha256, estado) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                             [ID, n, nombre, formato, len(datos), sha, estado]).fetchone()[0], carpeta / f"{sha}.{formato}", datos

    def preparar(self, **kw):
        return ejecutar(PL.preparar(ID, FICHA, "albert", **kw))

    def test_rellena_la_plantilla_con_los_datos_de_la_sociedad_elegida_y_deja_el_original(self):
        _, original, antes = self.documento(1, "Anexo I - Declaración responsable.docx", "docx", docx)
        self.documento(2, "Pliego administrativo.docx", "docx", lambda r: docx(r, "<w:p><w:r><w:t>Solo texto, sin huecos.</w:t></w:r></w:p>"))
        with self.assertRaises(E.VariasEmpresas):
            self.preparar()                                                  # hay dos sociedades en el ERP y no se ha elegido
        r = self.preparar(empresa="101 Telecom S.L.")
        self.assertEqual(original.read_bytes(), antes)
        self.assertEqual(r["empresa"], "101 Telecom S.L.")
        self.assertEqual([d["documento"] for d in r["documentos"]], [1])     # el pliego sin huecos no es una plantilla
        d = r["documentos"][0]
        self.assertEqual(d["fichero"], "01 - Anexo I - Declaración responsable (rellenado).docx")
        self.assertEqual(d["estado"], "faltan_datos")                        # las casillas (tamaño de empresa) las marca una persona, y el campo raro no se sabe
        self.assertTrue(any(p["tipo"] == "casilla" for p in d["pendientes"]))
        self.assertTrue(any(x["clave"] == "representante.dni" and x["valor"] == "12345678Z" for x in d["rellenados"]))
        self.assertEqual(O_leer()["empresa"], "101 Telecom S.L.")            # la sociedad queda guardada en la oferta
        nombre, datos, tipo = ejecutar(PL.fichero(ID, d["id"]))
        self.assertEqual(tipo, PL.MIME["docx"])
        self.assertNotEqual(datos, antes)
        # sin volver a elegir, la siguiente vez usa la sociedad guardada
        self.assertEqual(self.preparar()["empresa"], "101 Telecom S.L.")

    def test_otra_sociedad_otro_documento_con_sus_datos_y_sus_faltas(self):
        self.documento(1, "Anexo.docx", "docx", docx)
        r = self.preparar(empresa="Ion Industry S.A.")
        d = r["documentos"][0]
        self.assertEqual(d["empresa"], "Ion Industry S.A.")
        faltan = " ".join(p["motivo"] for p in d["pendientes"])
        self.assertIn("Contacto enlazado a la empresa", faltan)             # esa sociedad no tiene representante en el ERP: se dice dónde completarlo
        self.assertTrue(any(x["clave"] == "empresa.nif" and x["valor"] == "A87654321" for x in d["rellenados"]))
        self.assertEqual(d["estado"], "faltan_datos")

    def test_un_agente_elige_el_dato_de_un_hueco_dudoso_y_se_recuerda(self):
        did, _, _ = self.documento(1, "Anexo.docx", "docx", docx)
        r = self.preparar(empresa="101 Telecom S.L.")
        dudoso = next(p for p in r["documentos"][0]["pendientes"] if p["tipo"] == "celda" and p["etiqueta"] == "dato raro")
        r = self.preparar(n=1, asignaciones={dudoso["id"]: "empresa.localidad"})
        self.assertTrue(any(x["id"] == dudoso["id"] and x["valor"] == "Girona" for x in r["documentos"][0]["rellenados"]))
        r = self.preparar(n=1)                                               # repetir no pierde lo que eligió el agente
        self.assertTrue(any(x["id"] == dudoso["id"] for x in r["documentos"][0]["rellenados"]))
        self.assertEqual(len(r["documentos"]), 1)

    def test_pdf_con_formulario_y_pdf_plano(self):
        self.documento(1, "Modelo.pdf", "pdf", lambda r: pdf_con_formulario(r, [("a", "Razón social"), ("b", "NIF/CIF"), ("c", "Nombre y apellidos del representante")]))
        def plano(ruta):
            from pypdf import PdfWriter
            w = PdfWriter()
            w.add_blank_page(100, 100)
            with open(ruta, "wb") as f:
                w.write(f)
        self.documento(2, "Pliego.pdf", "pdf", plano)
        r = self.preparar(empresa="101 Telecom S.L.")
        self.assertEqual([(d["documento"], d["estado"]) for d in r["documentos"]], [(1, "lista_para_firma")])
        from pypdf import PdfReader
        nombre, datos, tipo = ejecutar(PL.fichero(ID, r["documentos"][0]["id"]))
        ruta = self.dir / "x.pdf"
        ruta.write_bytes(datos)
        self.assertEqual({k: v.get("/V") for k, v in PdfReader(str(ruta)).get_fields().items()},
                         {"a": "101 Telecomunicaciones & Seguridad, S.L.", "b": "B12345678", "c": "Ana Pérez Soler"})
        # pedido por su número, un PDF plano queda con su aviso y no se rellena
        r = self.preparar(n=2)
        plano_ = next(d for d in r["documentos"] if d["documento"] == 2)
        self.assertEqual(plano_["estado"], "sin_huecos")
        self.assertIsNone(plano_["fichero"])

    def test_el_fichero_manipulado_o_ausente_no_se_entrega(self):
        self.documento(1, "Anexo.docx", "docx", docx)
        d = self.preparar(empresa="101 Telecom S.L.")["documentos"][0]
        ruta = self.dir / "ofertas" / ID / d["fichero"]
        ruta.write_bytes(b"cambiado")
        with self.assertRaises(PL.ErrorPlantilla):
            ejecutar(PL.fichero(ID, d["id"]))
        ruta.unlink()
        with self.assertRaises(O.NoExiste):
            ejecutar(PL.fichero(ID, d["id"]))
        with self.assertRaises(O.NoExiste):
            ejecutar(PL.fichero(ID, 99999))

    def test_sin_oferta_preparada_o_documento_que_no_sirve(self):
        with self.assertRaises(O.NoExiste):
            ejecutar(PL.preparar("1c2f7a3e-1111-4222-8333-444444444444", FICHA, "albert", "101 Telecom S.L."))
        with self.assertRaises(PL.ErrorPlantilla):
            self.preparar(empresa="101 Telecom S.L.", n=7)

    def test_un_documento_roto_queda_como_error_sin_tumbar_a_los_demas(self):
        self.documento(1, "Roto.docx", "docx", lambda r: r.write_bytes(b"no es un zip"))
        self.documento(2, "Anexo.docx", "docx", docx)
        r = self.preparar(empresa="101 Telecom S.L.")
        self.assertEqual([d["documento"] for d in r["documentos"]], [2])     # el roto no se presenta como plantilla
        r = self.preparar(n=1)
        self.assertEqual(next(d for d in r["documentos"] if d["documento"] == 1)["estado"], "error")

    def zip_con(self, miembros):
        def crear(ruta):
            import zipfile
            with zipfile.ZipFile(ruta, "w", zipfile.ZIP_DEFLATED) as z:
                for nombre, datos in miembros:
                    z.writestr(nombre, datos)
        return crear

    def test_un_zip_de_documentacion_se_abre_y_se_rellena_cada_anexo_y_se_avisa_del_resto(self):
        d1, d2 = self.dir / "a.docx", self.dir / "b.pdf"
        docx(d1)
        pdf_con_formulario(d2, [("a", "Razón social"), ("b", "NIF/CIF")])
        self.documento(1, "Documentación administrativa.zip", "zip", self.zip_con([("Sobre 1/Anexo I - Declaración.docx", d1.read_bytes()), ("Sobre 1/Anexo II - Modelo.pdf", d2.read_bytes()),
                                                                                     ("Sobre 1/Anexo III.doc", b"binario antiguo"), ("Sobre 1/Pliego.docx", docx_sin_huecos(self.dir))]))
        r = self.preparar(empresa="101 Telecom S.L.")
        por = {d["miembro"]: d for d in r["documentos"]}
        self.assertEqual(set(por), {"Sobre 1/Anexo I - Declaración.docx", "Sobre 1/Anexo II - Modelo.pdf", None})      # el Pliego sin huecos no es un modelo; el .doc deja constancia
        w, pdf, resumen = por["Sobre 1/Anexo I - Declaración.docx"], por["Sobre 1/Anexo II - Modelo.pdf"], por[None]
        self.assertEqual((w["estado"], pdf["estado"]), ("faltan_datos", "lista_para_firma"))
        self.assertNotEqual(w["fichero"], pdf["fichero"])                         # cada anexo, su propio fichero rellenado
        self.assertTrue(w["fichero"].startswith("01.01 - Anexo I - Declaración") and pdf["fichero"].startswith("01.02 - Anexo II - Modelo"))
        self.assertEqual(w["nombre"], "Documentación administrativa.zip › Sobre 1/Anexo I - Declaración.docx")
        self.assertEqual(resumen["estado"], "faltan_datos")
        self.assertIn("Anexo III.doc", resumen["avisos"][0])
        self.assertTrue(resumen["pendientes"][0]["bloquea"])
        for d in (w, pdf):
            ejecutar(PL.fichero(ID, d["id"]))                                    # se pueden descargar
        # repetir no duplica las filas
        self.assertEqual(len(self.preparar()["documentos"]), 3)

    def test_un_hueco_dudoso_de_un_anexo_dentro_de_un_zip_se_elige_con_su_miembro(self):
        d1 = self.dir / "a.docx"
        docx(d1)
        self.documento(1, "Paquete.zip", "zip", self.zip_con([("Anexo I.docx", d1.read_bytes()), ("Anexo II.docx", d1.read_bytes())]))
        r = self.preparar(empresa="101 Telecom S.L.")
        dudoso = next(p for p in r["documentos"][0]["pendientes"] if p["etiqueta"] == "dato raro")
        with self.assertRaisesRegex(PL.ErrorPlantilla, "miembro"):
            self.preparar(n=1, asignaciones={dudoso["id"]: "empresa.localidad"})        # los ids se repiten en cada anexo: hay que decir de cuál
        with self.assertRaisesRegex(PL.ErrorPlantilla, "no tiene el fichero"):
            self.preparar(n=1, asignaciones={dudoso["id"]: "empresa.localidad"}, miembro="Otro.docx")
        r = self.preparar(n=1, asignaciones={dudoso["id"]: "empresa.localidad"}, miembro="Anexo II.docx")
        por = {d["miembro"]: d for d in r["documentos"]}
        self.assertTrue(any(x["valor"] == "Girona" for x in por["Anexo II.docx"]["rellenados"] if x["etiqueta"] == "dato raro"))
        self.assertFalse(any(x["etiqueta"] == "dato raro" for x in por["Anexo I.docx"]["rellenados"]))        # el otro anexo no se toca

    def test_un_modelo_en_odt_o_excel_deja_constancia_y_lo_demas_no(self):
        self.documento(1, "Anexo II - Modelo de proposición.odt", "odt", lambda r: r.write_bytes(b"PK odt"))
        self.documento(2, "Memoria descriptiva.xlsx", "xlsx", lambda r: r.write_bytes(b"PK xlsx"))
        r = self.preparar(empresa="101 Telecom S.L.")
        self.assertEqual([(d["documento"], d["estado"]) for d in r["documentos"]], [(1, "error")])      # solo el que parece un modelo
        self.assertIn("odt", r["documentos"][0]["avisos"][0])
        self.assertIn("Word", r["documentos"][0]["avisos"][0])

    def test_los_huecos_se_agrupan_por_anexo(self):
        self.documento(1, "Documentación administrativa.docx", "docx", lambda r: docx(r, "<w:p><w:r><w:t>ANEXO I. DECLARACIÓN</w:t></w:r></w:p>" + CUERPO_SIMPLE + "<w:p><w:r><w:t>ANEXO II. MODELO DE OFERTA</w:t></w:r></w:p>" + CUERPO_SIMPLE))
        d = self.preparar(empresa="101 Telecom S.L.")["documentos"][0]
        self.assertEqual({x["anexo"] for x in d["rellenados"]}, {"ANEXO I. DECLARACIÓN", "ANEXO II. MODELO DE OFERTA"})


def O_leer():
    return ejecutar(O.leer(ID, con_contenido=False))


class TestHerramienta(unittest.TestCase):
    def test_el_agente_solo_elige_claves_y_no_hay_operaciones_para_escribir_valores(self):
        with self.assertRaisesRegex(ValueError, "Claves no válidas"):
            ejecutar(herramienta.rellenar(ID, 1, {"t1": "Ana Pérez"}))
        with self.assertRaisesRegex(ValueError, "asignaciones"):
            ejecutar(herramienta.rellenar(ID, 1, {"t1": 5}))
        with self.assertRaisesRegex(ValueError, "documento"):
            ejecutar(herramienta.rellenar(ID, 0, {}))

    def test_esta_registrada_con_el_esquema_que_ve_el_modelo(self):
        from cerebro.herramientas import base, esquemas
        h = base._REGISTRO.get("plantillas")
        self.assertIsNotNone(h)
        self.assertEqual(set(h.operaciones), {"listar", "datos_disponibles", "rellenar"})
        parametros, _ = esquemas.parametros(h.operaciones["rellenar"])
        self.assertNotIn("agente", [p.nombre for p in parametros])


class TestAccesoSistema(unittest.TestCase):
    def test_los_datos_de_la_empresa_son_solo_del_sistema_no_de_los_agentes(self):
        erpnext.comprobar_acceso("licitaciones", "Company", "sistema")
        erpnext.comprobar_acceso("licitaciones", "Address", "sistema")
        for doc in ("Company", "Address"):
            with self.assertRaises(PermissionError):
                erpnext.comprobar_acceso("licitaciones", doc, "leer")            # la herramienta «erpnext» de los agentes no los ve
        with self.assertRaises(PermissionError):
            erpnext.comprobar_acceso("comercial", "Company", "sistema")
        with self.assertRaises(PermissionError):
            erpnext.comprobar_acceso("licitaciones", "Company", "borrador")


if __name__ == "__main__":
    unittest.main()
