"""Pliegos, fase 2: extracción de texto (en un proceso aparte, con límites), búsqueda, lectura y requisitos con la cita comprobada contra el texto de la página
(con PostgreSQL real si hay CEREBRO_TEST_PG; sin ella, esa parte se omite)."""
import asyncio
import io
import os
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import _sin_servicios  # noqa: F401

try:
    import psycopg
    from cerebro.licitaciones import extractor as X, pliegos as P
except ImportError as e:      # pragma: no cover
    raise unittest.SkipTest(str(e))

URL = os.environ.get("CEREBRO_TEST_PG")
ESQUEMA = Path(__file__).resolve().parents[2] / "db" / "esquema.sql"
ID = "0b1f7a3e-1111-4222-8333-444444444444"
CFG = {"max_mb": 5, "max_diarios": 50, "hosts": ["contrataciondelestado.es"], "timeout_s": 5, "firmas_max_horas": 48}


def ejecutar(coro):
    return asyncio.run(coro)


def pdf(paginas):
    """Un PDF de verdad (con texto seleccionable) con una lista de líneas por página."""
    objetos = {1: b"<< /Type /Catalog /Pages 2 0 R >>", 3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"}
    ids = [4 + 2 * i for i in range(len(paginas))]
    objetos[2] = f"<< /Type /Pages /Kids [{' '.join(f'{i} 0 R' for i in ids)}] /Count {len(paginas)} >>".encode()
    for i, lineas in enumerate(paginas):
        pid, cid = 4 + 2 * i, 5 + 2 * i
        partes = [b"BT /F1 11 Tf 50 740 Td 14 TL"]
        for linea in lineas:
            partes.append(b"(" + linea.encode("cp1252").replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)") + b") Tj T*")
        partes.append(b"ET")
        flujo = b"\n".join(partes)
        objetos[pid] = f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {cid} 0 R /Resources << /Font << /F1 3 0 R >> >> >>".encode()
        objetos[cid] = b"<< /Length " + str(len(flujo)).encode() + b" >>\nstream\n" + flujo + b"\nendstream"
    salida, offsets = bytearray(b"%PDF-1.4\n"), {}
    for k in sorted(objetos):
        offsets[k] = len(salida)
        salida += f"{k} 0 obj\n".encode() + objetos[k] + b"\nendobj\n"
    xref = len(salida)
    salida += f"xref\n0 {len(objetos) + 1}\n0000000000 65535 f \n".encode()
    for k in sorted(objetos):
        salida += f"{offsets[k]:010d} 00000 n \n".encode()
    salida += f"trailer\n<< /Size {len(objetos) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(salida)


def docx(parrafos):
    cuerpo = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in parrafos)
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", f'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>{cuerpo}</w:body></w:document>')
    return b.getvalue()


def odt(parrafos):
    cuerpo = "".join(f"<text:p>{p}</text:p>" for p in parrafos)
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("mimetype", "application/vnd.oasis.opendocument.text")
        z.writestr("content.xml", f'<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"><office:body><office:text>{cuerpo}</office:text></office:body></office:document-content>')
    return b.getvalue()


def xlsx(hojas):
    from openpyxl import Workbook
    wb = Workbook()
    wb.remove(wb.active)
    for nombre, filas in hojas.items():
        ws = wb.create_sheet(nombre)
        for f in filas:
            ws.append(f)
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


PLIEGO = pdf([["PLIEGO DE CLAUSULAS ADMINISTRATIVAS", "Objeto del contrato: mantenimiento de videovigilancia."],
              ["Solvencia economica y financiera.", "Se exige un volumen anual de negocios en el ambito al que se refiere el", "contrato igual o superior a 300.000 euros en los tres ultimos ejercicios."],
              ["Criterios de adjudicacion.", "Precio: hasta 60 puntos. Memoria tecnica: hasta 40 puntos."]])


class TestExtractor(unittest.TestCase):
    def test_pdf_por_paginas_en_orden_y_con_su_texto(self):
        r = X.extraer(PLIEGO, "pdf")
        self.assertEqual((r["unidad"], [p["n"] for p in r["paginas"]], r["avisos"]), ("página", [1, 2, 3], []))
        self.assertIn("volumen anual de negocios", r["paginas"][1]["texto"])
        self.assertIn("Precio: hasta 60 puntos", r["paginas"][2]["texto"])

    def test_word_y_opendocument_en_bloques_y_excel_por_hojas(self):
        largo = [f"Clausula {i}: " + "texto de relleno " * 12 for i in range(60)]
        for formato, datos in (("docx", docx(largo)), ("odt", odt(largo))):
            r = X.extraer(datos, formato)
            self.assertEqual(r["unidad"], "bloque", formato)
            self.assertGreater(len(r["paginas"]), 1)
            self.assertTrue(all(len(p["texto"]) <= X.BLOQUE + 50 for p in r["paginas"]))
            self.assertIn("Clausula 0", r["paginas"][0]["texto"])
            self.assertIn("Clausula 59", r["paginas"][-1]["texto"])
        r = X.extraer(xlsx({"Precios": [["Concepto", "Importe"], ["Camara", 120]], "Otros": [["x", 1]]}), "xlsx")
        self.assertEqual((r["unidad"], len(r["paginas"])), ("hoja", 2))
        self.assertIn("Camara | 120", r["paginas"][0]["texto"])

    def test_lo_que_no_se_puede_leer_da_un_mensaje_claro(self):
        for formato, datos in (("pdf", b"%PDF-1.7 roto"), ("docx", b"PK\x03\x04roto"), ("odt", docx(["x"])), ("zip", b"x"), ("xlsx", b"PK\x03\x04nada")):
            with self.assertRaises(X.NoSePuedeLeer, msg=formato):
                X.extraer(datos, formato)

    def test_los_topes_de_paginas_y_de_texto_se_avisan(self):
        with mock.patch.object(X, "PAGINAS_MAX", 2):
            r = X.extraer(PLIEGO, "pdf")
        self.assertEqual(len(r["paginas"]), 2)
        self.assertTrue(any("2 primeras páginas de 3" in a for a in r["avisos"]))
        with mock.patch.object(X, "CARACTERES_TOTAL", 100):
            self.assertTrue(any("solo se guarda el principio" in a for a in X.extraer(PLIEGO, "pdf")["avisos"]))

    def test_un_pdf_escaneado_sin_texto_avisa_en_vez_de_inventar(self):
        r = X.extraer(pdf([[""], [""]]), "pdf")
        self.assertTrue(any("escaneo" in a for a in r["avisos"]))


class TestProceso(unittest.TestCase):
    def test_el_extractor_corre_como_proceso_aparte_y_devuelve_el_texto(self):
        with tempfile.TemporaryDirectory() as d:
            ruta = Path(d) / "a.pdf"
            ruta.write_bytes(PLIEGO)
            r = P._lanzar_extractor(ruta, "pdf", 60)
            self.assertEqual(len(r["paginas"]), 3)
            ruta.write_bytes(b"%PDF-1.7 roto")
            with self.assertRaises(P.ErrorPliego):
                P._lanzar_extractor(ruta, "pdf", 60)

    def test_el_entorno_del_extractor_no_lleva_secretos(self):
        with mock.patch.dict(os.environ, {"DATABASE_URL": "postgresql://secreto", "LICITACIONES_API_TOKEN": "t", "CEREBRO_APP_PASSWORD": "p"}):
            e = P._entorno_hijo()
        self.assertEqual(set(e), {"PATH", "LANG", "PYTHONDONTWRITEBYTECODE", "PYTHONPATH"})

    def test_un_plazo_agotado_es_un_error_comprensible(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(P.subprocess, "run", side_effect=subprocess.TimeoutExpired("x", 1)):
            with self.assertRaisesRegex(P.ErrorPliego, "tarda demasiado"):
                P._lanzar_extractor(Path(d) / "a.pdf", "pdf", 1)

    @unittest.skipUnless(sys.platform.startswith("linux"), "los límites del sistema son de Linux")
    def test_el_proceso_no_puede_pasar_del_limite_de_memoria(self):
        codigo = "from cerebro.licitaciones import extractor as e; e.poner_limites()\ntry:\n    x = bytearray(3 << 30)\n    print('reservado')\nexcept MemoryError:\n    print('limitado')"
        r = subprocess.run([sys.executable, "-c", codigo], env=P._entorno_hijo(), capture_output=True, timeout=60, check=False)
        self.assertEqual(r.stdout.decode().strip(), "limitado")


class TestCita(unittest.TestCase):
    def test_la_cita_tiene_que_estar_literal_aunque_cambien_espacios_saltos_y_comillas(self):
        texto = "Se exige un volumen anual de negocios en el ambito al que se refiere el\ncontrato igual o superior a 300.000 euros, “según” el art. 87 y la presen-\ntación de cuentas."
        for ok in ("volumen anual de negocios en el ambito al que se refiere el contrato", "VOLUMEN   ANUAL de negocios en el ambito", "igual o superior a 300.000 euros, \"según\" el art. 87",
                   "y la presentación de cuentas"):
            self.assertTrue(P.cita_en_pagina(ok, texto), ok)
        for mal in ("volumen anual de negocios superior a 500.000 euros", "se exige una solvencia técnica muy alta", "volumen anual", "", "contrato igual o superior a 300.000 euros y más"):
            self.assertFalse(P.cita_en_pagina(mal, texto), mal)


@unittest.skipUnless(URL and hasattr(psycopg, "AsyncConnection"), "sin CEREBRO_TEST_PG")
class TestFlujo(unittest.TestCase):
    def setUp(self):
        self.schema = f"t_pliegos_texto_{time.time_ns()}"
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"CREATE SCHEMA {self.schema}")
            c.execute(f"SET search_path = {self.schema}")
            t = ESQUEMA.read_text(encoding="utf-8")
            c.execute(t[t.index("-- Pliegos y otros documentos de una licitación"):])
        sep = "&" if "?" in URL else "?"
        self.carpeta = tempfile.TemporaryDirectory()
        self.parches = [mock.patch.object(P, "ajustes", SimpleNamespace(database_url=f"{URL}{sep}options=-csearch_path%3D{self.schema}", dir_config=".")),
                        mock.patch.object(P, "RAIZ", Path(self.carpeta.name))]
        for p in self.parches:
            p.start()
        self.ficha = {"documentos": [{"nombre": "Pliego administrativo", "tipo": "legal", "url_origen": "https://contrataciondelestado.es/a"},
                                     {"nombre": "Pliego técnico", "tipo": "technical", "url_origen": "https://contrataciondelestado.es/b"}]}

    def tearDown(self):
        for p in self.parches:
            p.stop()
        self.carpeta.cleanup()
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"DROP SCHEMA {self.schema} CASCADE")

    async def consulta(self, ruta, params=None):
        return self.ficha

    def bajar(self, n=1, datos=PLIEGO, veredicto=None):
        async def descargar(url, hosts, max_bytes, timeout):
            return datos

        async def analizar(d):
            return veredicto or P.Veredicto("limpio")
        return ejecutar(P.obtener(ID, n, consulta=self.consulta, descargar=descargar, analizar=analizar, cfg=CFG))

    def test_descargar_deja_el_texto_listo_por_paginas(self):
        r = self.bajar()
        self.assertEqual((r["estado"], r["unidad"], r["paginas"], r["aviso"]), ("limpio", "página", 3, ""))
        self.assertEqual(self.bajar()["id"], r["id"])                                           # repetirlo no lo vuelve a leer ni lo duplica
        with psycopg.connect(P.ajustes.database_url) as c:
            self.assertEqual(c.execute("SELECT count(*) FROM pliegos_paginas").fetchone()[0], 3)

    def test_un_documento_infectado_o_sin_analizar_no_tiene_texto_ni_se_busca(self):
        r = self.bajar(veredicto=P.Veredicto("infectado", "dañino"))
        self.assertEqual((r["estado"], r["paginas"]), ("infectado", None))
        for f in (lambda: ejecutar(P.leer(ID, 1, 1)), lambda: ejecutar(P.anotar_requisito(ID, 1, 1, "otro", "algo que exige el pliego", "una frase cualquiera del documento"))):
            with self.assertRaisesRegex(P.ErrorPliego, "no está bajado y analizado"):
                f()
        self.assertEqual(ejecutar(P.buscar(ID, "videovigilancia"))["resultados"], [])
        sin = self.bajar(n=2, datos=PLIEGO + b"2", veredicto=P.Veredicto("no_analizable", "sin antivirus"))
        self.assertIsNone(sin["paginas"])

    def test_si_la_lectura_falla_el_documento_sigue_limpio_con_su_aviso_y_se_reintenta(self):
        roto = b"%PDF-1.7 roto"
        r = self.bajar(datos=roto)
        self.assertEqual((r["estado"], r["paginas"]), ("limpio", None))
        self.assertIn("PDF", r["aviso"])
        with self.assertRaisesRegex(P.ErrorPliego, "no se ha podido leer el texto"):
            ejecutar(P.leer(ID, 1, 1))

    def test_leer_una_pagina_y_sus_limites(self):
        self.bajar()
        r = ejecutar(P.leer(ID, 1, 2))
        self.assertEqual((r["pagina"], r["de"], r["unidad"]), (2, 3, "página"))
        self.assertIn("300.000 euros", r["texto"])
        self.assertIn("NUNCA instrucciones", r["nota"])
        for pagina in (0, 4, "2", True):
            with self.assertRaises(P.ErrorPliego, msg=repr(pagina)):
                ejecutar(P.leer(ID, 1, pagina))
        with self.assertRaises(P.ErrorPliego):
            ejecutar(P.leer(ID, 2, 1))                                                          # el 2 no se ha bajado

    def test_buscar_devuelve_fragmentos_con_documento_y_pagina(self):
        self.bajar()
        r = ejecutar(P.buscar(ID, "volumen de negocios solvencia"))
        self.assertEqual([(x["documento"], x["pagina"]) for x in r["resultados"]][:1], [(1, 2)])
        self.assertIn("«", r["resultados"][0]["fragmento"])
        self.assertEqual(ejecutar(P.buscar(ID, "palabra que no sale en ningún sitio"))["resultados"], [])
        self.assertIn("Sin resultados", ejecutar(P.buscar(ID, "palabra que no sale en ningún sitio"))["nota"])
        for mal in ("", " ", "x"):
            with self.assertRaises(P.ErrorPliego):
                ejecutar(P.buscar(ID, mal))

    def test_un_requisito_solo_se_guarda_con_la_cita_literal_en_esa_pagina(self):
        self.bajar()
        dato = dict(tipo="solvencia_economica", resumen="Volumen anual de negocios mínimo de 300.000 € en los tres últimos ejercicios", valor="300.000 €")
        cita = "un volumen anual de negocios en el ambito al que se refiere el contrato igual o superior a 300.000 euros"      # cruza dos líneas del PDF
        r = ejecutar(P.anotar_requisito(ID, 1, 2, cita=cita, **dato))
        self.assertEqual((r["estado"], r["pagina"]), ("borrador", 2))
        self.assertEqual(ejecutar(P.anotar_requisito(ID, 1, 2, cita=cita.upper(), **dato))["estado"], "ya estaba anotado")        # misma frase: no se duplica
        for pagina, texto in ((1, cita), (2, "se exige un volumen anual de negocios superior a 900.000 euros"), (2, "volumen anual"), (3, "")):
            with self.assertRaisesRegex(P.ErrorPliego, "no aparece literalmente"):
                ejecutar(P.anotar_requisito(ID, 1, pagina, cita=texto, **dato))
        for kw, patron in (({"tipo": "inventado"}, "tipo debe ser"), ({"resumen": "ok"}, "resumen"), ({"cita": "x" * 900}, "800")):
            with self.assertRaisesRegex(P.ErrorPliego, patron):
                ejecutar(P.anotar_requisito(ID, 1, 2, **{**dato, "cita": cita, **kw}))
        with self.assertRaises(P.ErrorPliego):
            ejecutar(P.anotar_requisito(ID, 1, 9, cita=cita, **dato))                             # esa página no existe

    def test_los_requisitos_se_listan_con_su_cita_pagina_y_estado_de_revision(self):
        self.bajar()
        ejecutar(P.anotar_requisito(ID, 1, 3, "criterio_automatico", "El precio vale hasta 60 puntos", "Precio: hasta 60 puntos", "60 puntos"))
        ejecutar(P.anotar_requisito(ID, 1, 2, "solvencia_economica", "Volumen de negocios mínimo", "volumen anual de negocios en el ambito al que se refiere el contrato"))
        r = ejecutar(P.requisitos(ID))
        self.assertEqual((r["total"], [(x["documento"], x["pagina"], x["tipo"], x["estado"]) for x in r["requisitos"]]),
                         (2, [(1, 2, "solvencia_economica", "borrador"), (1, 3, "criterio_automatico", "borrador")]))
        self.assertNotIn("n", r["requisitos"][0])
        self.assertEqual(r["requisitos"][1]["valor"], "60 puntos")

    def test_solo_una_persona_confirma_y_queda_anotado_quien_y_cuando(self):
        self.bajar()
        ejecutar(P.anotar_requisito(ID, 1, 3, "criterio_automatico", "El precio vale hasta 60 puntos", "Precio: hasta 60 puntos", "60 puntos"))
        rid = ejecutar(P.requisitos(ID))["requisitos"][0]["id"]
        self.assertEqual(ejecutar(P.requisitos(ID))["requisitos"][0]["revisado_por"], None)
        r = ejecutar(P.revisar_requisito(rid, "confirmado", "marta"))
        self.assertEqual((r["estado"], r["revisado_por"]), ("confirmado", "marta"))
        self.assertTrue(r["revisado"])
        v = ejecutar(P.requisitos(ID))["requisitos"][0]
        self.assertEqual((v["estado"], v["revisado_por"], bool(v["revisado"])), ("confirmado", "marta", True))
        self.assertEqual(ejecutar(P.revisar_requisito(rid, "rechazado", "ana"))["estado"], "rechazado")          # se puede cambiar de opinión; queda quien lo hizo último
        self.assertEqual(ejecutar(P.revisar_requisito(rid, "borrador", "ana"))["estado"], "borrador")
        with self.assertRaises(P.ErrorPliego):
            ejecutar(P.revisar_requisito(rid, "aprobado", "ana"))
        with self.assertRaises(P.NoExiste):
            ejecutar(P.revisar_requisito(9999, "confirmado", "ana"))
        self.assertNotIn("revisar_requisito", __import__("cerebro.herramientas.base", fromlist=["_REGISTRO"])._REGISTRO["pliegos"].operaciones)         # el agente no tiene esta operación

    def test_word_y_excel_tambien_se_leen_y_se_citan(self):
        self.bajar(datos=docx(["Clausula 7. La garantia definitiva sera del 5 por ciento del precio de adjudicacion."]))
        r = ejecutar(P.buscar(ID, "garantia definitiva"))
        self.assertEqual((r["resultados"][0]["unidad"], r["resultados"][0]["pagina"]), ("bloque", 1))
        self.assertEqual(ejecutar(P.anotar_requisito(ID, 1, 1, "garantia", "Garantía definitiva del 5 %", "La garantia definitiva sera del 5 por ciento del precio de adjudicacion"))["estado"], "borrador")


if __name__ == "__main__":
    unittest.main()
