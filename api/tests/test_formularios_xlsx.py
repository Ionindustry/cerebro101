"""Plantillas en Excel (.xlsx): detectar «etiqueta | celda vacía», rellenar sin sobrescribir nada y rechazar lo que no es de fiar."""
import tempfile
import unittest
import zipfile
from pathlib import Path

import _sin_servicios  # noqa: F401

try:
    import openpyxl
except ImportError as e:      # pragma: no cover
    raise unittest.SkipTest(str(e))

from cerebro.licitaciones import formularios as F


def libro(ruta: Path, relleno) -> Path:
    wb = openpyxl.Workbook()
    relleno(wb)
    wb.save(ruta)
    return ruta


def datos_empresa(wb):
    ws = wb.active
    ws.title = "Datos del licitador"
    ws["A1"], ws["A2"], ws["A3"], ws["A4"], ws["A5"] = "Razón social", "NIF/CIF:", "Domicilio", "Otros (opcional):", "Observaciones:"
    ws["B3"] = "Calle Mayor 1"                # ya relleno: no se toca
    ws["A7"], ws["B7"], ws["C7"] = "Importe sin IVA", None, None
    ws["A9"] = "Texto libre que no es una etiqueta"
    ws["B1"] = None


class TestXlsx(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_detecta_etiquetas_reconocidas_con_su_celda_vacia_y_no_toca_lo_ya_escrito(self):
        r = F.detectar(libro(self.dir / "a.xlsx", datos_empresa), "xlsx")
        por_etiqueta = {c["etiqueta"]: c for c in r["campos"]}
        self.assertEqual(por_etiqueta["Razón social"]["clave"], "empresa.razon_social")
        self.assertEqual(por_etiqueta["NIF/CIF"]["clave"], "empresa.nif")
        self.assertEqual(por_etiqueta["Importe sin IVA"]["clave"], "oferta.precio")
        self.assertIsNone(por_etiqueta["Observaciones"]["clave"])                  # acaba en «:» pero no se reconoce: queda pendiente para una persona
        self.assertNotIn("Domicilio", por_etiqueta)                                # su celda ya tiene un dato
        self.assertNotIn("Texto libre que no es una etiqueta", por_etiqueta)
        self.assertTrue(por_etiqueta["Otros (opcional)"]["opcional"])
        self.assertTrue(all(c["id"].startswith("h1!") and c["tipo"] == "celda" for c in r["campos"]))
        self.assertTrue(any("vuelve a guardar" in a for a in r["avisos"]))

    def test_rellena_una_copia_sin_sobrescribir_y_el_original_queda_igual(self):
        origen = libro(self.dir / "a.xlsx", datos_empresa)
        antes = origen.read_bytes()
        campos = {c["etiqueta"]: c["id"] for c in F.detectar(origen, "xlsx")["campos"]}
        destino = self.dir / "salida.xlsx"
        res = F.rellenar(origen, "xlsx", destino, {campos["Razón social"]: "101 Servicios S.L.", campos["NIF/CIF"]: "B12345678", "h1!Z99": "nada", "h1!B3": "intento de pisar"})
        self.assertEqual(sorted(res["rellenados"]), sorted([campos["Razón social"], campos["NIF/CIF"]]))
        self.assertIn("h1!B3", res["omitidos"])
        self.assertIn("h1!Z99", res["omitidos"])
        self.assertEqual(origen.read_bytes(), antes)
        ws = openpyxl.load_workbook(destino).active
        self.assertEqual((ws["B1"].value, ws["B2"].value, ws["B3"].value), ("101 Servicios S.L.", "B12345678", "Calle Mayor 1"))

    def test_un_dato_que_parece_formula_se_escribe_como_texto(self):
        origen = libro(self.dir / "f.xlsx", datos_empresa)
        campos = {c["etiqueta"]: c["id"] for c in F.detectar(origen, "xlsx")["campos"]}
        destino = self.dir / "f_out.xlsx"
        F.rellenar(origen, "xlsx", destino, {campos["Razón social"]: "=HYPERLINK(\"http://malo\",\"x\")", campos["NIF/CIF"]: "+1+1"})
        with zipfile.ZipFile(destino) as z:
            hoja = z.read("xl/worksheets/sheet1.xml").decode()
        self.assertNotIn("<f>", hoja)                                                  # ninguna fórmula en el libro
        ws = openpyxl.load_workbook(destino).active
        self.assertEqual((ws["B1"].data_type, ws["B1"].value), ("s", '=HYPERLINK("http://malo","x")'))

    def test_fila_de_cabeceras_rellena_la_celda_de_debajo_y_las_combinadas_su_esquina(self):
        def cabeceras(wb):
            ws = wb.active
            ws["A1"], ws["B1"], ws["C1"] = "Razón social", "NIF", "Teléfono"
            ws.merge_cells("A5:B5")
            ws["A5"] = "Correo electrónico"
            ws.merge_cells("C5:E5")
        r = F.detectar(libro(self.dir / "b.xlsx", cabeceras), "xlsx")
        ids = {c["etiqueta"]: c["id"] for c in r["campos"]}
        self.assertEqual(ids["Razón social"], "h1!A2")
        self.assertEqual(ids["NIF"], "h1!B2")
        self.assertEqual(ids["Correo electrónico"], "h1!C5")                       # la etiqueta combinada ocupa A5:B5; el hueco es la esquina de C5:E5

    def test_sin_huecos_lo_dice_y_un_libro_con_macros_o_roto_se_rechaza(self):
        vacio = libro(self.dir / "c.xlsx", lambda wb: wb.active.__setitem__("A1", "Solo texto"))
        self.assertEqual(F.detectar(vacio, "xlsx")["campos"], [])
        roto = self.dir / "roto.xlsx"
        roto.write_bytes(b"PK\x03\x04no es un zip de verdad")
        with self.assertRaises(F.ErrorFormulario):
            F.detectar(roto, "xlsx")
        macros = self.dir / "macros.xlsx"
        with zipfile.ZipFile(macros, "w") as z:
            z.writestr("[Content_Types].xml", "<Types/>")
            z.writestr("xl/vbaProject.bin", b"x")
        with self.assertRaises(F.ErrorFormulario) as e:
            F.detectar(macros, "xlsx")
        self.assertIn("macros", str(e.exception))

    def test_un_xlsx_dentro_de_un_zip_ya_se_extrae(self):
        zp = self.dir / "paquete.zip"
        origen = libro(self.dir / "m.xlsx", datos_empresa)
        with zipfile.ZipFile(zp, "w") as z:
            z.write(origen, "Anexo II.xlsx")
            z.writestr("hoja.xls", b"\xd0\xcf\x11\xe0 viejo")
        res = F.extraer_zip(zp, self.dir / "x")
        self.assertEqual([(m["miembro"], m["formato"]) for m in res["miembros"]], [("Anexo II.xlsx", "xlsx")])
        self.assertTrue(any("hoja.xls" in a for a in res["avisos"]))

    def test_por_el_proceso_aislado(self):
        origen = libro(self.dir / "a.xlsx", datos_empresa)
        det = F.ejecutar_aislado({"accion": "detectar", "ruta": str(origen), "formato": "xlsx"})
        self.assertGreaterEqual(len(det["campos"]), 3)
        destino = self.dir / "out.xlsx"
        F.ejecutar_aislado({"accion": "rellenar", "ruta": str(origen), "formato": "xlsx", "destino": str(destino), "valores": {det["campos"][0]["id"]: "X S.L."}})
        self.assertTrue(destino.is_file())


if __name__ == "__main__":
    unittest.main()
