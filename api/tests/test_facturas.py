"""Lectura de facturas de proveedor: las cifras tienen que cuadrar y estar en el documento antes de tocar el ERP."""
import asyncio
import os
import unittest
from decimal import Decimal as Dc
from types import SimpleNamespace
from unittest import mock

import _sin_servicios  # noqa: F401

from cerebro.herramientas import facturas as F

TEXTO = """Instal·lacions Roca SL   NIF B12345674
Factura nº 2026-0142   Fecha 01/10/2026
Instalación cámara IP    2    100,00    200,00
Base imponible 200,00   IVA 21% 42,00
TOTAL 242,00 EUR"""
LINEAS = [{"descripcion": "Instalación cámara IP", "cantidad": 2, "precio": 100}]


class TestNumeros(unittest.TestCase):
    def test_formatos_de_importe(self):
        for entrada, esperado in [("1.210,00", "1210.00"), ("1,210.00", "1210.00"), ("1210", "1210"), ("242,00 €", "242.00"), ("12,5", "12.5"),
                                  ("1.234.567,89", "1234567.89"), (100, "100"), (3.5, "3.5")]:
            self.assertEqual(F.a_decimal(entrada), Dc(esperado), entrada)

    def test_importes_ambiguos_o_basura_se_rechazan(self):
        for malo in ("1.210", "1,210", "mil", "12 euros y pico", None, True):
            with self.subTest(malo), self.assertRaises(F.DatosFactura):
                F.a_decimal(malo)

    def test_fechas(self):
        for f in ("01/10/2026", "2026-10-01", "1-10-2026", "01.10.2026"):
            self.assertEqual(F.a_fecha(f), "2026-10-01")
        for mala in ("31/02/2026", "ayer", "01/10/1999", "01/10/2099"):
            with self.subTest(mala), self.assertRaises(F.DatosFactura):
                F.a_fecha(mala)

    def test_importe_en_el_documento(self):
        self.assertTrue(F.aparece_importe("TOTAL 1.210,00 EUR", Dc("1210")))
        self.assertTrue(F.aparece_importe("Total: 1210.00", Dc("1210")))
        self.assertTrue(F.aparece_importe("Total 1 210,00", Dc("1210")))
        self.assertFalse(F.aparece_importe("Total 11.210,00", Dc("1210")))         # no vale como subcadena de otro importe
        self.assertFalse(F.aparece_importe("Total 1210,005", Dc("1210")))
        self.assertFalse(F.aparece_importe("Total 242,00", Dc("1210")))


class TestComprobar(unittest.TestCase):
    def comprobar(self, **k):
        a = dict(texto=TEXTO, proveedor="Instal·lacions Roca SL", nif="B12345674", numero="2026-0142", total=Dc("242"),
                 lineas=F.validar_lineas(LINEAS), iva=None, tipos_iva=[0, 4, 10, 21], tolerancia=Dc("0.02"))
        a.update(k)
        return F.comprobar(**a)

    def test_factura_correcta(self):
        tipo, base, adv = self.comprobar()
        self.assertEqual((tipo, base), (21, Dc("200.00")))
        self.assertEqual(adv, [])

    def test_no_cuadra_el_total(self):
        with self.assertRaises(F.DatosFactura) as e:
            self.comprobar(total=Dc("250"))
        self.assertIn("No cuadra", str(e.exception))

    def test_iva_no_admitido_o_que_no_corresponde(self):
        with self.assertRaises(F.DatosFactura):
            self.comprobar(iva=19)
        with self.assertRaises(F.DatosFactura):
            self.comprobar(iva=10)                                                  # con 10 % no saldrían 242

    def test_cifra_mal_leida_por_el_ocr_no_pasa(self):
        # El modelo/OCR dice 1.210 en vez de 242: aunque las líneas cuadrasen con ese total, no está en el documento
        lineas = F.validar_lineas([{"descripcion": "x", "cantidad": 1, "precio": 1000}])
        with self.assertRaises(F.DatosFactura) as e:
            self.comprobar(lineas=lineas, total=Dc("1210"))
        self.assertIn("no aparece en el documento", str(e.exception))

    def test_numero_de_factura_que_no_esta(self):
        with self.assertRaises(F.DatosFactura) as e:
            self.comprobar(numero="2026-0999")
        self.assertIn("2026-0999", str(e.exception))

    def test_documento_sin_texto(self):
        with self.assertRaises(F.DatosFactura):
            self.comprobar(texto="  ")

    def test_advertencias_no_bloquean(self):
        _, _, adv = self.comprobar(nif="B99999999", proveedor="Otra Empresa")
        self.assertTrue(any("NIF" in a for a in adv))
        self.assertTrue(any("proveedor" in a for a in adv))

    def test_varias_lineas_y_redondeo(self):
        lineas = F.validar_lineas([{"descripcion": "a", "cantidad": 3, "precio": "33,33"}, {"descripcion": "b", "cantidad": 1, "precio": "0,01"}])
        tipo, base, _ = F.comprobar("Factura 1 total 121,00 99,99 0,01 33,33", "x", None, "1", Dc("121"), lineas, 21, [21], Dc("0.02"))
        self.assertEqual(base, Dc("100.00"))

    def test_lineas_invalidas(self):
        for mal in ([], None, [{"descripcion": "", "cantidad": 1, "precio": 1}], [{"descripcion": "a", "cantidad": 0, "precio": 1}],
                    [{"descripcion": "a", "cantidad": 1, "precio": -5}], [{"descripcion": "a", "cantidad": "x", "precio": 1}], ["no es un dict"],
                    [{"descripcion": "a", "cantidad": 1, "precio": 1}] * 61):
            with self.subTest(str(mal)[:40]), self.assertRaises(F.DatosFactura):
                F.validar_lineas(mal)


PROVEEDORES = [{"name": "Instal·lacions Roca SL", "supplier_name": "Instal·lacions Roca SL", "tax_id": "B12345674"},
               {"name": "Vila Electricitat SA", "supplier_name": "Vila Electricitat SA", "tax_id": None}]


class TestProveedores(unittest.TestCase):
    def test_por_nif_y_por_nombre(self):
        self.assertEqual(F.buscar_proveedor(PROVEEDORES, "otro nombre", "B-12345674")["name"], "Instal·lacions Roca SL")
        self.assertEqual(F.buscar_proveedor(PROVEEDORES, "INSTAL·LACIONS ROCA, S.L.", None)["name"], "Instal·lacions Roca SL")
        self.assertEqual(F.buscar_proveedor(PROVEEDORES, "Vila Electricitat", None)["name"], "Vila Electricitat SA")

    def test_proveedor_inexistente_sugiere_parecidos(self):
        with self.assertRaises(F.DatosFactura) as e:
            F.buscar_proveedor(PROVEEDORES, "Vila Electricidad", None)
        self.assertIn("Vila Electricitat SA", str(e.exception))
        self.assertIn("alta de proveedores la hace una persona", str(e.exception))
        with self.assertRaises(F.DatosFactura):
            F.buscar_proveedor(PROVEEDORES, "Empresa Fantasma", "A00000000")


try:
    import httpx
    HAY_HTTPX = hasattr(httpx, "MockTransport")
except ImportError:
    HAY_HTTPX = False


@unittest.skipUnless(HAY_HTTPX, "requiere httpx")
class TestCrearFacturaEnElErp(unittest.TestCase):
    def setUp(self):
        from cerebro.herramientas import buzones as B, correo, documentos as D, erpnext
        self.E, self.B, self.correo, self.D = erpnext, B, correo, D
        erpnext._politica.cache_clear()
        erpnext._config_facturas.cache_clear()
        self.antes = dict(os.environ)
        os.environ["ERPNEXT_TOKEN_FINANZAS"] = "k:s"
        self.peticiones = []
        self.existentes = []

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.antes)

    def lanzar(self, texto=TEXTO, dep="finanzas", **k):
        peticiones, existentes = self.peticiones, self.existentes

        def manejar(req):
            peticiones.append(req)
            ruta = req.url.raw_path.decode()
            if ruta.startswith("/api/resource/Supplier"):
                return httpx.Response(200, json={"data": PROVEEDORES})
            if ruta.startswith("/api/resource/Purchase%20Invoice") and req.method == "GET":
                return httpx.Response(200, json={"data": existentes})
            if ruta.startswith("/api/resource/Purchase%20Invoice") and req.method == "POST":
                return httpx.Response(200, json={"data": {"name": "ACC-PINV-1", "grand_total": 242.0}})
            if ruta.startswith("/api/method/upload_file"):
                return httpx.Response(200, json={"message": {"file_name": "f.pdf", "file_url": "/private/files/f.pdf"}})
            if ruta.startswith("/api/method/frappe.auth.get_logged_user"):
                return httpx.Response(200, json={"message": "cerebro.finanzas@x"})
            return httpx.Response(404, json={})
        real = httpx.AsyncClient
        pr = mock.patch.object(self.E.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(manejar), **kw))
        aj = mock.patch.object(self.E, "ajustes", SimpleNamespace(erpnext_url="http://erp", dir_config=self.E.ajustes.dir_config))
        bz = mock.patch.object(self.B, "resolver", lambda d, b: ("facturacion", {}))
        ad = mock.patch.object(self.correo, "obtener_adjunto", lambda *a: ("factura.pdf", "application/pdf", b"%PDF-1.4 falso"))
        ex = mock.patch.object(self.D, "extraer_texto", lambda n, d: (texto, {}))
        args = dict(departamento=dep, message_id="<m@x>", adjunto=1, proveedor="Instal·lacions Roca SL", numero="2026-0142", fecha="01/10/2026",
                    lineas=LINEAS, total="242,00", nif="B12345674")
        args.update(k)
        with pr, aj, bz, ad, ex:
            return asyncio.run(self.E.crear_factura_compra(**args))

    def test_crea_borrador_con_iva_cuenta_y_original(self):
        r = self.lanzar()
        self.assertEqual((r["factura"], r["proveedor"], r["base"], r["iva"]), ("ACC-PINV-1", "Instal·lacions Roca SL", "200.00", "21%"))
        self.assertEqual(r["advertencias"], [])
        post = next(p for p in self.peticiones if p.method == "POST" and b"Purchase" in p.url.raw_path)
        import json
        doc = json.loads(post.content)
        self.assertEqual(doc["docstatus"], 0)
        self.assertEqual(doc["bill_date"], "2026-10-01")
        self.assertEqual(doc["taxes"][0]["rate"], 21)
        self.assertTrue(doc["items"][0]["expense_account"])
        self.assertEqual(r["original"], "/private/files/f.pdf")

    def test_si_no_cuadra_no_se_crea_nada(self):
        with self.assertRaises(ValueError):
            self.lanzar(total="250,00")
        self.assertFalse(any(p.method == "POST" for p in self.peticiones))

    def test_total_que_no_esta_en_el_documento_no_se_crea(self):
        with self.assertRaises(ValueError) as e:
            self.lanzar(texto="Factura 2026-0142 total 999,00")
        self.assertIn("no aparece", str(e.exception))
        self.assertFalse(any(p.method == "POST" for p in self.peticiones))

    def test_proveedor_que_no_existe_no_se_da_de_alta(self):
        with self.assertRaises(ValueError) as e:
            self.lanzar(proveedor="Empresa Fantasma", nif="A00000000", texto=TEXTO + " Empresa Fantasma")
        self.assertIn("no existe", str(e.exception))
        self.assertFalse(any(p.method == "POST" for p in self.peticiones))

    def test_duplicada(self):
        self.existentes.append({"name": "ACC-PINV-0", "docstatus": 1})
        with self.assertRaises(ValueError) as e:
            self.lanzar()
        self.assertIn("no se duplica", str(e.exception))

    def test_solo_los_departamentos_con_politica(self):
        for dep in ("comercial", "marketing", "inventado"):
            with self.subTest(dep), self.assertRaises(PermissionError):
                self.lanzar(dep=dep)
        self.assertEqual(self.peticiones, [])


if __name__ == "__main__":
    unittest.main()
