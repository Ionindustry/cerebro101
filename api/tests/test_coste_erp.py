"""Coste desde un presupuesto del ERP: líneas con y sin coste, artículos, moneda y errores (ERP simulado)."""
import asyncio
import unittest
from unittest import mock

import _sin_servicios  # noqa: F401

try:
    import httpx
    from cerebro.licitaciones import coste_erp as C
except ImportError as e:      # pragma: no cover
    raise unittest.SkipTest(str(e))


def ejecutar(c):
    return asyncio.run(c)


def erp(docs, fallos=None):
    async def leer(doctype, nombre, departamento):
        assert departamento == "licitaciones"
        if (fallos or {}).get((doctype, nombre)):
            raise fallos[(doctype, nombre)]
        return docs[(doctype, nombre)]
    return mock.patch.object(C.erpnext, "leer", leer)


def error_http(codigo):
    return httpx.HTTPStatusError("x", request=httpx.Request("GET", "http://erp"), response=httpx.Response(codigo))


class TestCoste(unittest.TestCase):
    def test_suma_coste_de_la_linea_del_articulo_y_ultima_compra(self):
        q = {"currency": "EUR", "docstatus": 0, "net_total": 90000, "items": [
            {"item_code": "A", "qty": 2, "valuation_rate": 100},
            {"item_code": "B", "qty": 3},
            {"item_code": "C", "qty": 1}]}
        docs = {("Quotation", "QTN-1"): q, ("Item", "B"): {"valuation_rate": 0, "last_purchase_rate": 50}, ("Item", "C"): {"valuation_rate": 20}}
        with erp(docs):
            r = ejecutar(C.coste_de_presupuesto("QTN-1"))
        self.assertEqual(r["coste"], 200 + 150 + 20)
        self.assertTrue(r["completo"])
        self.assertEqual({x["articulo"]: x["origen"] for x in r["lineas"]}, {"A": "coste de la línea", "B": "último precio de compra", "C": "coste del artículo"})
        self.assertEqual(r["precio_neto"], 90000)

    def test_las_lineas_sin_coste_no_se_inventan(self):
        q = {"currency": "EUR", "items": [{"item_code": "A", "qty": 2, "valuation_rate": 100}, {"item_code": "X", "qty": 4}]}
        with erp({("Quotation", "Q"): q, ("Item", "X"): {}}):
            r = ejecutar(C.coste_de_presupuesto("Q"))
        self.assertEqual(r["coste"], 200)
        self.assertFalse(r["completo"])
        self.assertEqual(r["sin_coste"], [{"articulo": "X", "cantidad": 4.0}])

    def test_sin_acceso_al_articulo_la_linea_queda_sin_coste(self):
        q = {"currency": "EUR", "items": [{"item_code": "A", "qty": 1, "valuation_rate": 10}, {"item_code": "B", "qty": 1}]}
        with erp({("Quotation", "Q"): q}, {("Item", "B"): PermissionError("no")}):
            r = ejecutar(C.coste_de_presupuesto("Q"))
        self.assertFalse(r["completo"])

    def test_errores_claros(self):
        q = lambda **kw: {("Quotation", "Q"): {"currency": "EUR", "items": [{"item_code": "A", "qty": 1, "valuation_rate": 5}], **kw}}
        casos = [(q(currency="USD"), None, "USD"), (q(docstatus=2), None, "cancelado"), (q(items=[]), None, "sin líneas|no tiene líneas"),
                 (q(items=[{"item_code": "A", "qty": 1}]), {("Item", "A"): PermissionError("x")}, "Ninguna línea"),
                 ({}, {("Quotation", "Q"): error_http(404)}, "No existe"), ({}, {("Quotation", "Q"): error_http(500)}, "error"),
                 ({}, {("Quotation", "Q"): httpx.ConnectError("x")}, "no responde"), ({}, {("Quotation", "Q"): PermissionError("Sin permiso para Quotation")}, "Sin permiso")]
        for docs, fallos, texto in casos:
            with erp(docs, fallos):
                with self.assertRaisesRegex(C.ErrorCoste, texto):
                    ejecutar(C.coste_de_presupuesto("Q"))
        with self.assertRaises(C.ErrorCoste):
            ejecutar(C.coste_de_presupuesto("  "))


if __name__ == "__main__":
    unittest.main()
