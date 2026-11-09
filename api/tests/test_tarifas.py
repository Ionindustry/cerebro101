"""Lectura flexible de tarifas (cerebro/tarifas.py). Los ficheros son SINTÉTICOS: imitan la estructura de las tarifas reales (un fabricante en Excel con varias hojas y tablas, un distribuidor en CSV),
sin nada de las tarifas de ningún proveedor."""
import io
import json
import unittest
from decimal import Decimal

import openpyxl

from cerebro import tarifas as T


def excel_fabricante() -> bytes:
    wb = openpyxl.Workbook()
    wb.active.title = "Naming Rule"
    wb.active["A1"] = "https://ejemplo.invalid/reglas"
    cctv = wb.create_sheet("CCTV")
    cctv.append(["Series", "Product name", "Main Model Name", "Order Model Name", "Production status", "Material Code", "MSRP Price", "EXW CHINA", "Picture", "Resolution", "Lens"])
    cctv.append(["Mini Series", "Cámara domo mini", "XX-C100", "XX-C100/2.8mm", "TBE: 2026Q4", "60.001", 247.5, 82.5, '=DISPIMG("ID_1")', "2MP\n1920*1080", "Fixed 2.8mm"])
    cctv.append(["Mini Series", "Cámara domo mini", "XX-C100", "XX-C100/4mm", "MP", "60.002", 247.5, 82.5, None, "2MP\n1920*1080", "Fixed 4mm"])
    cctv.append(["Mini Series", "Cámara bullet", "XX-C200", "XX-C200/2.8mm", "EOL", "60.003", 280.5, 93.5, None, "N/A", "N/A"])
    cctv.append(["Mini Series", "Sin precio todavía", "XX-C300", "XX-C300", "MP", "60.004", None, None, None, "", ""])
    ov = wb.create_sheet("Openvision Series")
    ov.append(["Series", "Product name", "Main Model Name", "Order Model Name", "Production status", "MSRP Price", "EXW CHINA", "Resolution"])
    ov.append(["Openvision Series", "Cámara motorizada", "XX-C500", "XX-C500/2.7-13.5mm", "MP", 825, 338, "5MP"])
    ov.append([])
    ov.append(["Series", "Product name", "Main Model Name", "Order Model Name", "Production status", "MSRP Price", "Standard Price", "Inputs"])      # segunda tabla con otra columna de coste
    ov.append(["Openvision Series", "Servidor", "SE01", "SE01", "EOL", 2062.5, 688, "Max. 16CH"])
    acc = wb.create_sheet("Accessories")
    acc.append(["Accessory Map: https://ejemplo.invalid/accesorios"])
    acc.append(["Accessories"])
    acc.append(["Image", "Order Model Name", "Description", "Price", "Material Code", "Production status"])      # cabecera en la fila 3
    acc.append([None, "A01", "Soporte de poste\n* Peso: 100g", 10, "60.999.1", "MP"])
    acc.append([None, "A02", "Caja de conexión", "15", "60.999.2", "MP"])
    nvr = wb.create_sheet("NVR")
    nvr.append(["NVR Series"])
    nvr.append(["Picture", "Model", "PoE Ports", "MSRP", "EXW", "Production status"])
    nvr.append(["", "HDMI", "VGA"])                                              # subcabecera: no es un producto
    nvr.append([None, "NV-1004", 4, 282, 94, "MP"])
    oculta = wb.create_sheet("Oculta")
    oculta.append(["Referencia", "Precio"])
    oculta.append(["ZZ", 1])
    oculta.sheet_state = "hidden"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def csv_distribuidor() -> bytes:
    cab = ["reference", "brand", "name", "price", "ean", "stock", "categories", "img1", "specs"]
    specs = json.dumps({"Información general": [{"Tipo": "Caja de alarma"}], "Material y dimensiones": [{"Material": "ABS"}, {"Peso": "120 g"}]}, ensure_ascii=False)
    filas = [
        ["ARB1606", "DAHUA", "Caja de alarma", "17,50\xa0€", "6939554916045", "27.0", "Accesorios / Videovigilancia, Accesorios / Videovigilancia / Conversores", "https://ejemplo.invalid/1.png", specs],
        ["TS5511-GH", "MILESIGHT", "Cámara de tráfico 5 Mpx", "3.145,00\xa0€", "", "0.0", "Videovigilancia / Cámaras IP", "", "{}"],
        ["XX-ROTO", "ACME", "Producto sin precio", "", "", "3.0", "Accesorios", "", ""],
        ["XX-RARO", "ACME", "Precio absurdo", "gratis", "", "1.0", "Accesorios", "", ""],
    ]
    import csv
    s = io.StringIO()
    w = csv.writer(s)
    w.writerow(cab)
    w.writerows(filas)
    return s.getvalue().encode("utf-8-sig")


class TestNumero(unittest.TestCase):
    def test_formatos_europeos_y_anglosajones(self):
        casos = {"17,50\xa0€": (Decimal("17.50"), "EUR"), "3.145,00 €": (Decimal("3145.00"), "EUR"), "1,234.50": (Decimal("1234.50"), ""), "$ 1,200": (Decimal("1200"), "USD"),
                 "247.5": (Decimal("247.5"), ""), 82.5: (Decimal("82.5"), ""), "1.234": (Decimal("1234"), ""), "12,5": (Decimal("12.5"), ""), "1.234.567": (Decimal("1234567"), "")}
        for entrada, esperado in casos.items():
            self.assertEqual(T.numero(entrada), esperado, entrada)

    def test_lo_que_no_es_un_numero_no_se_inventa(self):
        for malo in (None, "", "gratis", "N/A", "—", True, "1,2,3x"):
            self.assertEqual(T.numero(malo), (None, ""), repr(malo))


class TestExcelDelFabricante(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.t = T.leer(excel_fabricante(), "tarifa.xlsx", moneda="usd")
        cls.por_ref = {p.referencia: p for p in cls.t.productos}

    def test_lee_varias_hojas_y_varias_tablas_con_la_cabecera_donde_este(self):
        self.assertEqual(self.t.formato, "xlsx")
        self.assertEqual(set(self.por_ref), {"XX-C100/2.8mm", "XX-C100/4mm", "XX-C200/2.8mm", "XX-C500/2.7-13.5mm", "SE01", "A01", "A02", "NV-1004"})
        self.assertEqual(self.por_ref["XX-C500/2.7-13.5mm"].coste, Decimal("338"))
        self.assertEqual(self.por_ref["SE01"].coste, Decimal("688"))                  # la segunda tabla de la hoja usa «Standard Price»
        self.assertEqual(self.por_ref["A01"].coste, Decimal("10"))                    # cabecera en la fila 3, columna «Price»
        self.assertEqual(self.por_ref["A02"].coste, Decimal("15"))                    # «15» como texto
        self.assertEqual(self.por_ref["NV-1004"].pvp_recomendado, Decimal("282"))     # «Model» / «MSRP» / «EXW»

    def test_coste_y_precio_recomendado_son_cosas_distintas(self):
        p = self.por_ref["XX-C100/4mm"]
        self.assertEqual((p.coste, p.pvp_recomendado), (Decimal("82.5"), Decimal("247.5")))
        self.assertEqual(p.referencia_fabricante, "XX-C100")
        self.assertEqual(p.familia, "Mini Series")

    def test_el_estado_del_producto_se_entiende_y_se_avisa(self):
        self.assertEqual(self.por_ref["XX-C100/2.8mm"].estado, "proximamente")
        self.assertEqual(self.por_ref["XX-C100/2.8mm"].estado_original, "TBE: 2026Q4")
        self.assertEqual(self.por_ref["XX-C100/4mm"].estado, "disponible")
        self.assertEqual(self.por_ref["XX-C200/2.8mm"].estado, "fin_de_vida")
        self.assertTrue(any("no están disponibles todavía" in a for a in self.t.avisos))

    def test_hojas_que_no_son_productos_y_ocultas_se_omiten_con_su_motivo(self):
        hojas = {h["hoja"]: h for h in self.t.hojas}
        self.assertEqual(hojas["Naming Rule"]["estado"], "omitida")
        self.assertEqual(hojas["Oculta"]["motivo"], "hoja oculta")
        self.assertEqual(hojas["CCTV"]["productos"], 3)
        self.assertEqual(hojas["CCTV"]["filas_sin_precio"], 1)                        # la fila sin precio no se importa, y se cuenta
        self.assertNotIn("ZZ", self.por_ref)

    def test_las_columnas_sobrantes_son_caracteristicas_y_las_imagenes_no(self):
        esp = self.por_ref["XX-C100/4mm"].especificaciones
        self.assertEqual(esp["Resolution"], "2MP · 1920*1080")                       # las celdas de varias líneas se aplanan
        self.assertEqual(esp["Lens"], "Fixed 4mm")
        self.assertNotIn("Picture", esp)
        self.assertNotIn("Material Code", esp)                                         # el código interno del proveedor es un dato propio, no una característica
        self.assertEqual(self.por_ref["XX-C100/4mm"].codigo_proveedor, "60.002")
        self.assertEqual(self.por_ref["XX-C100/4mm"].linea, "CCTV")
        self.assertNotIn("Resolution", self.por_ref["XX-C200/2.8mm"].especificaciones)  # «N/A» no es una característica
        self.assertEqual(self.por_ref["A01"].descripcion, "Soporte de poste · * Peso: 100g")

    def test_la_moneda_del_proveedor_se_aplica_si_el_fichero_no_la_dice(self):
        self.assertTrue(all(p.moneda == "USD" for p in self.t.productos))
        sin = T.leer(excel_fabricante())
        self.assertTrue(any("no dice la moneda" in a for a in sin.avisos))


class TestCsvDelDistribuidor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.t = T.leer(csv_distribuidor(), "products.csv", moneda="EUR")
        cls.por_ref = {p.referencia: p for p in cls.t.productos}

    def test_precio_con_simbolo_stock_ean_y_marca(self):
        p = self.por_ref["ARB1606"]
        self.assertEqual((p.coste, p.moneda, p.stock, p.ean, p.marca), (Decimal("17.50"), "EUR", Decimal("27.0"), "6939554916045", "DAHUA"))
        self.assertEqual(self.por_ref["TS5511-GH"].coste, Decimal("3145.00"))
        self.assertEqual(self.por_ref["TS5511-GH"].stock, Decimal("0.0"))

    def test_categorias_en_jerarquia_dan_la_familia(self):
        p = self.por_ref["ARB1606"]
        self.assertEqual(p.familia, "Accesorios")
        self.assertEqual(len(p.categorias), 2)
        self.assertIn("Accesorios / Videovigilancia / Conversores", p.categorias)

    def test_las_caracteristicas_en_json_largo_no_se_cortan(self):
        largo = json.dumps({"Sección": [{f"Dato {i}": "x" * 40} for i in range(30)]}, ensure_ascii=False)
        import csv
        s = io.StringIO()
        csv.writer(s).writerows([["reference", "price", "specs"], ["L-1", "5,00", largo]])
        p = T.leer(s.getvalue().encode(), "x.csv", moneda="EUR").productos[0]
        self.assertGreater(len(largo), 500)
        self.assertEqual(len(p.especificaciones), 30)

    def test_las_caracteristicas_en_json_se_aplanan(self):
        esp = self.por_ref["ARB1606"].especificaciones
        self.assertEqual(esp["Material y dimensiones · Peso"], "120 g")
        self.assertEqual(esp["Información general · Tipo"], "Caja de alarma")
        self.assertNotIn("specs", esp)                                                 # el JSON en bruto no se queda como una característica

    def test_sin_precio_o_con_precio_no_numerico_no_se_importa(self):
        self.assertNotIn("XX-ROTO", self.por_ref)
        self.assertNotIn("XX-RARO", self.por_ref)
        self.assertEqual(self.t.hojas[0]["filas_sin_precio"], 2)

    def test_otro_separador_y_otra_codificacion(self):
        txt = "Referencia;Descripción;Precio\r\nA-1;Cámara ñoño;1.234,50\r\nA-2;Otra;10,00\r\n".encode("cp1252")
        t = T.leer(txt, "tarifa.csv")
        self.assertEqual({p.referencia: p.coste for p in t.productos}, {"A-1": Decimal("1234.50"), "A-2": Decimal("10.00")})
        self.assertEqual(t.productos[0].descripcion, "Cámara ñoño")


class TestRechazos(unittest.TestCase):
    def test_se_decide_por_el_contenido_no_por_la_extension(self):
        for malo, motivo in ((b"", "vacío"), (b"%PDF-1.7 algo", "PDF"), (b"<html><body>hola</body></html>", "no es un Excel"), (b"MZ\x90\x00", "no es un Excel"),
                             (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1xx", ".xls"), (b"PK\x03\x04" + b"\0" * 40, "dañado")):
            with self.assertRaisesRegex(T.ErrorTarifa, motivo):
                T.leer(malo, "tarifa.xlsx")

    def test_un_zip_que_no_es_un_excel_se_rechaza(self):
        import zipfile
        b = io.BytesIO()
        with zipfile.ZipFile(b, "w") as z:
            z.writestr("hola.txt", "x")
        with self.assertRaisesRegex(T.ErrorTarifa, "no es un Excel"):
            T.leer(b.getvalue(), "x.xlsx")

    def test_un_fichero_sin_tabla_de_productos_lo_dice(self):
        with self.assertRaisesRegex(T.ErrorTarifa, "ninguna tabla con referencia y precio"):
            T.leer(b"hola,mundo\n1,2\n", "x.csv")

    def test_monedas_mezcladas_y_precio_mayor_que_el_recomendado_avisan(self):
        t = T.leer("Referencia,Precio,PVP\nA,10 €,5 €\nB,$ 20,30\n".encode(), "x.csv", moneda="EUR")
        self.assertTrue(any("moneda distinta" in a for a in t.avisos))
        self.assertIn("el coste es mayor que el precio recomendado", " ".join(t.productos[0].avisos))

    def test_referencias_repetidas_avisan(self):
        t = T.leer("Referencia,Precio\nA,1\nA,2\nB,3\n".encode(), "x.csv", moneda="EUR")
        self.assertTrue(any("más de una vez" in a for a in t.avisos))


if __name__ == "__main__":
    unittest.main()
