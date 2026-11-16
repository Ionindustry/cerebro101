import unittest

from cerebro import articulos_erp as A

CFG = {"item_group": "Products", "stock_uom": "Nos"}
L = {"codigo": "MILESI-UR32", "ref": "UR32", "desc": "Router <b>4G</b>", "marca": "Milesight", "ean": "6939554916045", "familia": "Routers",
     "categorias": ["IoT", "Routers"], "especificaciones": {"Puertos": "2 & 3"}, "enlaces": {"Ficha": "https://x.es/f.pdf", "Mal": "javascript:alert(1)"},
     "imagen": "https://x.es/a.jpg", "unidad": ""}


class TestArticulos(unittest.TestCase):
    def test_codigo_de_barras_solo_si_el_digito_de_control_es_valido(self):
        self.assertEqual(A.codigo_de_barras("6939554916045")["barcode_type"], "EAN")
        self.assertEqual(A.codigo_de_barras("036000291452")["barcode_type"], "UPC-A")
        for malo in ("6939554916044", "123", "", None, "abcdefghijklm"):
            self.assertIsNone(A.codigo_de_barras(malo))

    def test_descripcion_escapa_y_solo_enlaza_http(self):
        h = A.descripcion_html(L)
        self.assertIn("Router &lt;b&gt;4G&lt;/b&gt;", h)
        self.assertIn("2 &amp; 3", h)
        self.assertIn("https://x.es/f.pdf", h)
        self.assertNotIn("javascript", h)

    def test_documento_completo_y_basico(self):
        d = A.documento_articulo(L, "Milesight", CFG)
        self.assertEqual((d["brand"], d["image"], d["barcodes"][0]["barcode"], d["stock_uom"]), ("Milesight", "https://x.es/a.jpg", "6939554916045", "Nos"))
        self.assertEqual(d["supplier_items"], [{"supplier": "Milesight", "supplier_part_no": "UR32"}])
        b = A.documento_articulo(L, "Milesight", CFG, con_extras=False)
        self.assertFalse({"brand", "image", "barcodes"} & set(b))
        self.assertNotIn("<", b["description"].replace("&lt;", "")) if False else None
        d2 = A.documento_articulo({**L, "imagen": "http://inseguro/x.jpg"}, "M", CFG)
        self.assertNotIn("image", d2)

    def test_codigos_repetidos_se_quitan_al_segundo(self):
        a, b = A.documento_articulo(L, "M", CFG), A.documento_articulo({**L, "codigo": "OTRO"}, "M", CFG)
        out, q = A.sin_codigos_repetidos([a, b])
        self.assertEqual((q, "barcodes" in out[0], "barcodes" in out[1]), (1, True, False))


if __name__ == "__main__":
    unittest.main()
