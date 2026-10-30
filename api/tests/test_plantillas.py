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
    from cerebro.licitaciones import deuc as D, empresa as E, formularios as F, ofertas as O, plantillas as PL, pliegos, redaccion as R
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
        self.ficheros = []                      # los File adjuntos a la Company (DEUC base…)

    async def __call__(self, doctype, dep, filtros=None, campos=None, limite=20):
        self.llamadas.append((doctype, dep, tuple(campos or [])))
        if self.sin_personalizados and any(c in (campos or []) for c in ("registration_details", "dni", "poder")):
            raise httpx.HTTPStatusError("x", request=httpx.Request("GET", "http://x"), response=httpx.Response(417))
        if doctype == "File":
            return [f for f in self.ficheros if f["attached_to_name"] == filtros[1][2]]
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


class TestDeucBase(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(D, "base_local", mock.AsyncMock(return_value=None))       # sin nada subido desde Jarvis (eso se prueba con base de datos más abajo)
        p.start()
        self.addCleanup(p.stop)

    def fichero(self, nombre, modificado, empresa="101 Telecom S.L."):
        return {"attached_to_name": empresa, "name": nombre, "file_name": nombre, "file_url": f"/private/files/{nombre}", "modified": modificado}

    def con(self, ficheros, contenido=b"PK\x03\x04docx"):
        erp = ERPFalso()
        erp.ficheros = ficheros
        descargar = mock.AsyncMock(return_value=contenido)
        return erp, descargar, mock.patch.object(erpnext, "listar_sistema", erp), mock.patch.object(erpnext, "descargar_sistema", descargar)

    def test_elige_el_word_mas_reciente_con_deuc_en_el_nombre_y_lo_lee_con_la_clave_del_departamento(self):
        erp, descargar, a, b = self.con([self.fichero("DEUC 2024.docx", "2024-01-01"), self.fichero("DEUC 2026.docx", "2026-03-01"), self.fichero("Escrituras.docx", "2026-05-01"),
                                         self.fichero("DEUC.txt", "2026-06-01")])
        with a, b:
            nombre, datos, formato = ejecutar(E.deuc_base("101 Telecom S.L."))
        self.assertEqual((nombre, datos, formato), ("DEUC 2026.docx", b"PK\x03\x04docx", "docx"))
        descargar.assert_awaited_once_with("/private/files/DEUC 2026.docx", "licitaciones", E.MAX_DEUC)
        self.assertEqual(erp.llamadas[0][:2], ("File", "licitaciones"))

    def test_sin_deuc_no_hay_nada_y_cada_sociedad_tiene_el_suyo(self):
        _, descargar, a, b = self.con([self.fichero("Escrituras.docx", "2026-05-01"), self.fichero("DEUC Ion.docx", "2026-05-01", "Ion Industry S.A.")])
        with a, b:
            self.assertIsNone(ejecutar(E.deuc_base("101 Telecom S.L.")))
            self.assertEqual(ejecutar(E.deuc_base("Ion Industry S.A."))[0], "DEUC Ion.docx")
        descargar.assert_awaited_once()

    def test_un_fichero_que_no_es_un_word_no_se_admite(self):
        _, _, a, b = self.con([self.fichero("DEUC.docx", "2026-01-01")], contenido=b"<html>")
        with a, b, self.assertRaisesRegex(E.ErrorEmpresa, "no es un Word"):
            ejecutar(E.deuc_base("101 Telecom S.L."))
        _, _, a, b = self.con([self.fichero("DEUC.pdf", "2026-01-01")], contenido=b"PK\x03\x04")
        with a, b, self.assertRaisesRegex(E.ErrorEmpresa, "no es un PDF"):
            ejecutar(E.deuc_base("101 Telecom S.L."))

    def test_el_deuc_base_puede_ser_un_pdf_y_gana_el_mas_reciente_sea_cual_sea_el_formato(self):
        _, _, a, b = self.con([self.fichero("DEUC 2025.docx", "2025-01-01"), self.fichero("DEUC 2026.pdf", "2026-02-01")], contenido=b"%PDF-1.7 x")
        with a, b:
            nombre, datos, formato = ejecutar(E.deuc_base("101 Telecom S.L."))
        self.assertEqual((nombre, formato), ("DEUC 2026.pdf", "pdf"))

    def test_rutas_de_fichero_solo_dentro_de_files(self):
        for mala in ("/api/method/frappe.client.get", "/private/files/../../etc/passwd", "http://otro/x", "/files/a?x=1"):
            with self.assertRaises(PermissionError, msg=mala):
                ejecutar(erpnext.descargar_sistema(mala, "licitaciones"))
        with self.assertRaises(PermissionError):
            ejecutar(erpnext.descargar_sistema("/files/a.docx", "comercial"))          # solo quien tiene «File» en «sistema»


class TestFichaDeLaLicitacion(unittest.TestCase):
    """Las plantillas reciben la ficha COMPLETA del motor; pero si les llega la resumida que ven los agentes (comprador a secas) no deben romperse (fallo visto con una licitación real)."""
    def test_ficha_resumida_de_los_agentes_comprador_como_texto(self):
        d = {k: v["valor"] for k, v in PL.datos_licitacion({"titulo": "Obra", "expediente": "X/1", "comprador": "Ajuntament de Girona", "cpv": ["32323500"],
                                                           "plazo_presentacion": "2026-11-20T09:00:00+00:00", "importes": ["1000 EUR (sin iva; valor estimado)"]}).items()}
        self.assertEqual((d["licitacion.organo"], d["licitacion.objeto"], d["licitacion.cpv"], d["licitacion.plazo"]), ("Ajuntament de Girona", "Obra", "32323500", "20/11/2026"))
        self.assertNotIn("licitacion.importe", d)                                     # el importe de la ficha resumida es texto: no se interpreta

    def test_ficha_completa_y_formas_raras_no_rompen(self):
        d = {k: v["valor"] for k, v in PL.datos_licitacion({"comprador": {"nombre": "Ajuntament"}, "plazos": {"presentacion": "2026-11-20T09:00:00+00:00"}}).items()}
        self.assertEqual((d["licitacion.organo"], d["licitacion.plazo"]), ("Ajuntament", "20/11/2026"))
        for rara in (None, "texto", [], {"comprador": ["x"], "plazos": "mañana", "cpv": "32", "importes": "1"}, {"comprador": None, "importes": [None, 3, "x"]}):
            PL.datos_licitacion(rara)                                                    # no lanza

    def test_la_cadena_pide_la_ficha_completa_y_no_la_resumida(self):
        ficha = {"comprador": {"nombre": "Ajuntament"}}
        preparar = mock.AsyncMock(return_value={"documentos": []})
        with mock.patch.object(PL, "ficha_del_motor", mock.AsyncMock(return_value=ficha)), mock.patch.object(PL, "preparar", preparar):
            ejecutar(R._preparar_plantillas(ID, {"comprador": "resumida, a secas"}, "agente:administrativo"))
        preparar.assert_awaited_once_with(ID, ficha, "agente:administrativo")

    def test_el_motor_caido_no_impide_rellenar(self):
        from cerebro.herramientas import licitaciones as motor
        with mock.patch.object(motor, "_get", mock.AsyncMock(side_effect=motor.MotorNoDisponible("caído"))):
            self.assertEqual(ejecutar(PL.ficha_del_motor(ID)), {})
        with mock.patch.object(motor, "_get", mock.AsyncMock(return_value={"titulo": "T"})) as g:
            self.assertEqual(ejecutar(PL.ficha_del_motor(ID.upper())), {"titulo": "T"})
        g.assert_awaited_once_with(f"/tenders/{ID}")
        self.assertEqual(ejecutar(PL.ficha_del_motor("no-es-un-uuid")), {})


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

    def test_un_modelo_en_excel_deja_constancia_y_lo_demas_no(self):
        self.documento(1, "Anexo II - Modelo de oferta.xlsx", "xlsx", lambda r: r.write_bytes(b"PK xlsx"))
        self.documento(2, "Memoria descriptiva.xlsx", "xlsx", lambda r: r.write_bytes(b"PK xlsx memoria"))
        r = self.preparar(empresa="101 Telecom S.L.")
        self.assertEqual([(d["documento"], d["estado"]) for d in r["documentos"]], [(1, "error")])      # solo el que parece un modelo
        self.assertIn("xlsx", r["documentos"][0]["avisos"][0])
        self.assertIn("Word", r["documentos"][0]["avisos"][0])

    def test_un_modelo_en_odt_se_convierte_a_word_se_rellena_y_lo_dice(self):
        self.documento(1, "Anexo I - Declaración.odt", "odt", lambda r: r.write_bytes(b"PK odt"))
        convertidos = []

        def convertir(origen, destino, formato):
            convertidos.append(formato)
            destino.parent.mkdir(parents=True, exist_ok=True)
            docx(destino)
            return destino
        with mock.patch.object(PL.C, "a_docx", convertir):
            d = self.preparar(empresa="101 Telecom S.L.")["documentos"][0]
        self.assertEqual(convertidos, ["odt"])
        self.assertEqual((d["formato"], d["fichero"].endswith(".docx")), ("docx", True))
        self.assertTrue(d["rellenados"])
        self.assertTrue(any("convertido de odt a Word" in a for a in d["avisos"]))

    def test_si_la_conversion_falla_queda_como_error_con_su_motivo(self):
        self.documento(1, "Anexo I - Declaración.odt", "odt", lambda r: r.write_bytes(b"PK odt"))

        def convertir(origen, destino, formato):
            raise F.ErrorFormulario("El servicio de conversión a Word no responde")
        with mock.patch.object(PL.C, "a_docx", convertir):
            d = self.preparar(empresa="101 Telecom S.L.")["documentos"][0]
        self.assertEqual(d["estado"], "error")
        self.assertIn("no responde", d["avisos"][0])

    DEUC = ("<w:p><w:r><w:t>PARTE I: INFORMACIÓN SOBRE EL PROCEDIMIENTO DE CONTRATACIÓN</w:t></w:r></w:p>"
            '<w:p><w:r><w:t xml:space="preserve">Nombre oficial: </w:t></w:r><w:r><w:t>__________</w:t></w:r></w:p>'
            '<w:p><w:r><w:t xml:space="preserve">Título o breve descripción de la contratación: </w:t></w:r><w:r><w:t>__________</w:t></w:r></w:p>'
            '<w:p><w:r><w:t xml:space="preserve">Número de referencia del expediente asignado por el poder adjudicador (si procede): </w:t></w:r><w:r><w:t>__________</w:t></w:r></w:p>'
            "<w:p><w:r><w:t>PARTE II: INFORMACIÓN SOBRE EL OPERADOR ECONÓMICO</w:t></w:r></w:p>"
            '<w:p><w:r><w:t xml:space="preserve">Nombre: 101 Telecomunicaciones &amp; Seguridad, S.L.</w:t></w:r></w:p>')

    def poner_deuc(self, contenido=None, nombre="DEUC 101.docx"):
        r = erpnext.listar_sistema.ficheros = [{"attached_to_name": "101 Telecom S.L.", "name": nombre, "file_name": nombre, "file_url": f"/private/files/{nombre}", "modified": "2026-01-01"}]
        if contenido is None:
            ruta = self.dir / "deuc-base.docx"
            docx(ruta, self.DEUC)
            contenido = ruta.read_bytes()
        p = mock.patch.object(erpnext, "descargar_sistema", mock.AsyncMock(return_value=contenido))
        p.start()
        self.addCleanup(p.stop)
        return r

    def test_el_deuc_base_de_la_sociedad_se_copia_y_solo_se_rellenan_los_campos_del_concurso(self):
        self.poner_deuc()
        r = self.preparar(empresa="101 Telecom S.L.")
        d = next(x for x in r["documentos"] if x["documento"] == 0)
        self.assertEqual((d["miembro"], d["fichero"]), ("DEUC", "00 - DEUC (rellenado).docx"))
        dados = {x["clave"]: x["valor"] for x in d["rellenados"]}
        self.assertEqual(dados, {"licitacion.organo": "Ajuntament de Girona", "licitacion.objeto": "Videovigilancia urbana", "licitacion.expediente": "2026/045"})
        self.assertEqual(d["estado"], "lista_para_firma")
        self.assertEqual(d["pendientes"], [])

    def test_el_deuc_se_puede_rehacer_con_el_documento_cero_y_no_se_toca_el_resto(self):
        self.documento(1, "Anexo I - Declaración responsable.docx", "docx", docx)
        self.poner_deuc()
        self.preparar(empresa="101 Telecom S.L.")
        r = self.preparar(empresa="101 Telecom S.L.", n=0)
        self.assertEqual(sorted(d["documento"] for d in r["documentos"]), [0, 1])

    def test_sin_deuc_base_solo_se_avisa_si_el_pliego_pide_un_deuc(self):
        self.documento(1, "Anexo I - Declaración responsable.docx", "docx", docx)
        r = self.preparar(empresa="101 Telecom S.L.")
        self.assertEqual([d["documento"] for d in r["documentos"]], [1])             # no hay DEUC y el pliego no lo pide: nada
        self.documento(2, "Modelo DEUC.xlsx", "xlsx", lambda r: r.write_bytes(b"PK deuc"))
        r = self.preparar(empresa="101 Telecom S.L.")
        d = next(x for x in r["documentos"] if x["documento"] == 0)
        self.assertEqual(d["estado"], "error")
        self.assertIn("DEUC base", d["avisos"][0])

    def test_un_deuc_base_roto_queda_como_error_sin_tumbar_lo_demas(self):
        self.documento(1, "Anexo I - Declaración responsable.docx", "docx", docx)
        self.poner_deuc(contenido=b"esto no es un word")
        r = self.preparar(empresa="101 Telecom S.L.")
        self.assertEqual({d["documento"]: d["estado"] for d in r["documentos"]}[0], "error")
        self.assertIn(1, [d["documento"] for d in r["documentos"]])

    def test_el_deuc_base_en_pdf_con_formulario_se_rellena_y_un_pdf_plano_se_dice_claro(self):
        ruta = self.dir / "deuc-base.pdf"
        pdf_con_formulario(ruta, [("a", "Nombre oficial"), ("b", "Título o breve descripción de la contratación"), ("c", "Número de referencia del expediente asignado por el poder adjudicador")])
        self.poner_deuc(contenido=ruta.read_bytes(), nombre="DEUC 101.pdf")
        d = next(x for x in self.preparar(empresa="101 Telecom S.L.")["documentos"] if x["documento"] == 0)
        self.assertEqual((d["formato"], d["estado"], d["fichero"]), ("pdf", "lista_para_firma", "00 - DEUC (rellenado).pdf"))
        from pypdf import PdfReader
        _, datos, tipo = ejecutar(PL.fichero(ID, d["id"]))
        self.assertEqual(tipo, "application/pdf")
        (self.dir / "x.pdf").write_bytes(datos)
        self.assertEqual({k: v.get("/V") for k, v in PdfReader(str(self.dir / "x.pdf")).get_fields().items()},
                         {"a": "Ajuntament de Girona", "b": "Videovigilancia urbana", "c": "2026/045"})
        from pypdf import PdfWriter
        w = PdfWriter()
        w.add_blank_page(100, 100)
        with open(self.dir / "plano.pdf", "wb") as f:
            w.write(f)
        self.poner_deuc(contenido=(self.dir / "plano.pdf").read_bytes(), nombre="DEUC plano.pdf")
        d = next(x for x in self.preparar(empresa="101 Telecom S.L.")["documentos"] if x["documento"] == 0)
        self.assertEqual(d["estado"], "error")
        self.assertIn("sin campos de formulario", d["avisos"][0])

    def subido(self, formato="docx", estado="limpio", contenido=None, nombre="DEUC 101.docx"):
        """Un documento subido a Jarvis, ya analizado, en una carpeta de prueba."""
        limpio = self.dir / "subidas" / "limpio"
        limpio.mkdir(parents=True, exist_ok=True)
        ruta = limpio / f"abc.{formato}"
        if contenido is not None:
            ruta.write_bytes(contenido)
        elif formato == "docx":
            docx(ruta, self.DEUC)
        else:
            pdf_con_formulario(ruta, [("a", "Nombre oficial")])
        cm = mock.MagicMock()
        cm.__aenter__ = mock.AsyncMock(return_value=cm)
        cm.__aexit__ = mock.AsyncMock(return_value=False)
        ficha = {"id": "abc", "nombre": nombre, "formato": formato, "estado": estado, "bytes": ruta.stat().st_size, "paginas": 1, "aviso": None}
        for p in (mock.patch.object(D.S, "_id", lambda x: x), mock.patch.object(D.S, "_carpeta", lambda e: limpio), mock.patch.object(D.S, "_disponible", mock.AsyncMock(return_value=ficha)),
                  mock.patch.object(D.S, "_conectar", mock.AsyncMock(return_value=cm)), mock.patch.object(D, "DIR", self.dir / "deuc")):
            p.start()
            self.addCleanup(p.stop)
        return ruta

    def test_un_deuc_subido_desde_jarvis_se_guarda_se_usa_y_gana_al_del_erp(self):
        self.subido()
        self.assertIn("101 Telecom S.L.", ejecutar(D.vista("abc", "101 Telecom S.L.", departamento="licitaciones"))["campos"][0])
        r = ejecutar(D.guardar("abc", "101 Telecom S.L.", "agente:administrativo-licitaciones"))
        self.assertEqual((r["guardado"], r["sociedad"], r["formato"]), (True, "101 Telecom S.L.", "docx"))
        self.assertEqual(len(list((self.dir / "deuc").rglob("*.docx"))), 1)
        # hay además uno más reciente adjunto en el ERP: lo subido desde Jarvis tiene prioridad
        self.poner_deuc(nombre="DEUC del ERP.docx")
        d = next(x for x in self.preparar(empresa="101 Telecom S.L.")["documentos"] if x["documento"] == 0)
        self.assertEqual(d["estado"], "lista_para_firma")
        self.assertIn("DEUC 101.docx", d["nombre"])
        # una versión nueva sustituye a la anterior y la anterior se conserva
        self.subido(contenido=b"PK\x03\x04")                                                  # no es un Word válido: no se guarda
        with self.assertRaisesRegex(D.ErrorDeuc, "no es un Word"):
            ejecutar(D.guardar("abc", "101 Telecom S.L."))

    def test_lo_que_no_sirve_como_deuc_se_rechaza_antes_de_pedir_aprobacion(self):
        self.subido(estado="con_macros")
        with self.assertRaisesRegex(D.ErrorDeuc, "macros"):
            ejecutar(D.vista("abc", "101 Telecom S.L."))
        self.subido(formato="docx", estado="limpio")
        with self.assertRaisesRegex(D.ErrorDeuc, "sociedades|no existe"):
            ejecutar(D.vista("abc", "Inventada S.A."))
        with self.assertRaisesRegex(D.ErrorDeuc, "varias sociedades"):
            ejecutar(D.vista("abc", None))                                                   # hay dos sociedades y no se dice cuál
        from pypdf import PdfWriter
        plano = self.dir / "plano.pdf"
        w = PdfWriter()
        w.add_blank_page(100, 100)
        with open(plano, "wb") as f:
            w.write(f)
        self.subido(formato="pdf", contenido=plano.read_bytes())
        with self.assertRaisesRegex(D.ErrorDeuc, "sin campos|no tiene campos"):
            ejecutar(D.vista("abc", "101 Telecom S.L."))

    def test_un_pdf_con_formulario_subido_desde_jarvis_vale(self):
        self.subido(formato="pdf", nombre="DEUC 101.pdf")
        r = ejecutar(D.guardar("abc", "101 Telecom S.L."))
        self.assertEqual(r["formato"], "pdf")
        self.assertEqual(ejecutar(D.base_local("101 Telecom S.L."))[2], "pdf")

    def test_si_el_fichero_guardado_cambia_en_el_disco_no_se_usa(self):
        self.subido()
        ejecutar(D.guardar("abc", "101 Telecom S.L."))
        next((self.dir / "deuc").rglob("*.docx")).write_bytes(b"PK manipulado")
        with self.assertRaisesRegex(D.ErrorDeuc, "ha cambiado"):
            ejecutar(D.base_local("101 Telecom S.L."))

    def test_los_datos_de_la_licitacion_para_el_deuc(self):
        f = {"titulo": "Obra", "expediente": "X/1", "comprador": {"nombre": "Ajuntament"}, "cpv": ["32323500", "35120000"], "procedimiento": "abierto",
             "plazos": {"presentacion": "2026-11-20T09:00:00+00:00"}, "importes": [{"valor": "1234567.5", "moneda": "EUR", "significado": "valor_estimado"}]}
        d = {k: v["valor"] for k, v in PL.datos_licitacion(f).items()}
        self.assertEqual((d["licitacion.cpv"], d["licitacion.procedimiento"], d["licitacion.plazo"], d["licitacion.importe"]), ("32323500, 35120000", "abierto", "20/11/2026", "1.234.567,50 €"))

    def test_los_huecos_se_agrupan_por_anexo(self):
        self.documento(1, "Documentación administrativa.docx", "docx", lambda r: docx(r, "<w:p><w:r><w:t>ANEXO I. DECLARACIÓN</w:t></w:r></w:p>" + CUERPO_SIMPLE + "<w:p><w:r><w:t>ANEXO II. MODELO DE OFERTA</w:t></w:r></w:p>" + CUERPO_SIMPLE))
        d = self.preparar(empresa="101 Telecom S.L.")["documentos"][0]
        self.assertEqual({x["anexo"] for x in d["rellenados"]}, {"ANEXO I. DECLARACIÓN", "ANEXO II. MODELO DE OFERTA"})

    def test_el_modelo_de_proposicion_se_rellena_con_el_precio_que_fija_una_persona(self):
        def modelo(r):
            docx(r, "<w:p><w:r><w:t>ANEXO II. MODELO DE PROPOSICIÓN ECONÓMICA</w:t></w:r></w:p>"
                    '<w:p><w:r><w:t xml:space="preserve">Se compromete a ejecutar el contrato por el precio de </w:t></w:r><w:r><w:t>__________</w:t></w:r><w:r><w:t xml:space="preserve"> euros (IVA excluido), (en letra </w:t></w:r><w:r><w:t>____________</w:t></w:r><w:r><w:t xml:space="preserve"> euros)</w:t></w:r></w:p>'
                    '<w:tbl><w:tblPr/><w:tblGrid/><w:tr><w:tc><w:p><w:r><w:t>IVA (21 %):</w:t></w:r></w:p></w:tc><w:tc><w:p/></w:tc></w:tr>'
                    '<w:tr><w:tc><w:p><w:r><w:t>Importe total (IVA incluido):</w:t></w:r></w:p></w:tc><w:tc><w:p/></w:tc></w:tr></w:tbl>')
        self.documento(1, "Anexo II - Modelo de proposición.docx", "docx", modelo)
        self.assertEqual(ejecutar(PL.datos_oferta(ID)), {})                                    # sin precio fijado no hay nada que poner
        d = self.preparar(empresa="101 Telecom S.L.")["documentos"][0]
        motivos = " ".join(p["motivo"] for p in d["pendientes"] if p["bloquea"])
        self.assertIn("Fijar precio", motivos)                                                 # se dice dónde se resuelve
        self.assertEqual(d["estado"], "faltan_datos")
        ejecutar(O.fijar_precio(ID, 125000, 21, "albert"))                                       # lo fija una PERSONA
        d = self.preparar()["documentos"][0]
        valores = {x["clave"]: x for x in d["rellenados"]}
        self.assertEqual(valores["oferta.precio"]["valor"], "125.000,00")
        self.assertEqual(valores["oferta.precio_letras_sin_unidad"]["valor"], "ciento veinticinco mil")
        self.assertEqual((valores["oferta.iva"]["valor"], valores["oferta.precio_con_iva"]["valor"]), ("26.250,00", "151.250,00"))
        self.assertIn("precio fijado por albert", valores["oferta.precio"]["origen"])
        _, datos, _ = ejecutar(PL.fichero(ID, d["id"]))
        ruta = self.dir / "r.docx"
        ruta.write_bytes(datos)
        t = " ".join(F._texto_xml(__import__("zipfile").ZipFile(ruta).read("word/document.xml").decode()).split())
        self.assertIn("por el precio de 125.000,00 euros (iva excluido), (en letra ciento veinticinco mil euros)", t)
        self.assertIn("iva (21 %): 26.250,00", t)

    def test_con_centimos_y_euros_ya_escrito_la_letra_queda_para_una_persona(self):
        self.documento(1, "Modelo.docx", "docx", lambda r: docx(r, '<w:p><w:r><w:t xml:space="preserve">Precio (en letra </w:t></w:r><w:r><w:t>____________</w:t></w:r><w:r><w:t xml:space="preserve"> euros)</w:t></w:r></w:p>'))
        ejecutar(O.fijar_precio(ID, 125000.5, 21, "albert"))
        d = self.preparar(empresa="101 Telecom S.L.")["documentos"][0]
        pendiente = next(p for p in d["pendientes"] if p["bloquea"])
        self.assertIn("céntimos", pendiente["motivo"])
        self.assertEqual(d["estado"], "faltan_datos")

    def test_la_letra_de_un_millon_exacto_lleva_de(self):
        ejecutar(O.fijar_precio(ID, 2000000, 10, "albert"))
        v = ejecutar(PL.datos_oferta(ID))
        self.assertEqual(v["oferta.precio_letras"]["valor"], "dos millones de euros")
        self.assertNotIn("oferta.precio_letras_sin_unidad", v)
        self.assertEqual((v["oferta.iva_pct"]["valor"], v["oferta.iva"]["valor"], v["oferta.precio_con_iva"]["valor"]), ("10", "200.000,00", "2.200.000,00"))


def O_leer():
    return ejecutar(O.leer(ID, con_contenido=False))


class TestImportaciones(unittest.TestCase):
    """Cada módulo se tiene que poder importar el PRIMERO en un intérprete limpio: `herramientas` importa la herramienta «plantillas», que importa a `empresa`, que usa el ERP de `herramientas`.
    Las demás pruebas importan antes las herramientas y no ven un ciclo (así se coló en producción al probar `empresa` suelto)."""

    MODULOS = ("cerebro.licitaciones.empresa", "cerebro.licitaciones.plantillas", "cerebro.licitaciones.redaccion", "cerebro.licitaciones.formularios", "cerebro.licitaciones.importes",
               "cerebro.herramientas.plantillas", "cerebro.herramientas.erpnext", "cerebro.herramientas")

    def test_cada_modulo_se_importa_solo(self):
        import subprocess
        import sys
        raiz = str(Path(__file__).resolve().parents[1])
        for m in self.MODULOS:
            r = subprocess.run([sys.executable, "-I", "-c", f"import sys; sys.path.insert(0, {raiz!r}); import {m}"], capture_output=True, timeout=60)
            self.assertEqual(r.returncode, 0, f"{m}: {r.stderr.decode()[-400:]}")


class TestHerramienta(unittest.TestCase):
    def test_el_agente_solo_elige_claves_y_no_hay_operaciones_para_escribir_valores(self):
        with self.assertRaisesRegex(ValueError, "Claves no válidas"):
            ejecutar(herramienta.rellenar(ID, 1, {"t1": "Ana Pérez"}))
        with self.assertRaisesRegex(ValueError, "asignaciones"):
            ejecutar(herramienta.rellenar(ID, 1, {"t1": 5}))
        with self.assertRaisesRegex(ValueError, "documento"):
            ejecutar(herramienta.rellenar(ID, -1, {}))

    def test_esta_registrada_con_el_esquema_que_ve_el_modelo(self):
        from cerebro.herramientas import base, esquemas
        h = base._REGISTRO.get("plantillas")
        self.assertIsNotNone(h)
        self.assertEqual(set(h.operaciones), {"listar", "datos_disponibles", "rellenar", "guardar_deuc"})
        self.assertEqual(h.externas, {"guardar_deuc"})                       # guardar un DEUC necesita la aprobación de una persona
        self.assertIn("guardar_deuc", h.vistas)
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
