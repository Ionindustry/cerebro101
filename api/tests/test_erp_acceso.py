"""Cada departamento solo toca en el ERP y el CRM lo que dice config/erp_acceso.yaml, y nadie sale de /api/resource/."""
import asyncio
import glob
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import _sin_servicios  # noqa: F401
import yaml

try:
    import httpx
    HAY_HTTPX = hasattr(httpx, "MockTransport")
except ImportError:
    HAY_HTTPX = False

from cerebro.herramientas import erpnext as erp

RAIZ = Path(__file__).resolve().parents[2]
POL = yaml.safe_load((RAIZ / "config" / "erp_acceso.yaml").read_text(encoding="utf-8"))
DEPS = POL["departamentos"]


def agentes_con_erp() -> dict[str, list[str]]:
    por = {}
    for f in glob.glob(str(RAIZ / "config" / "agentes" / "*.yaml")):
        d = yaml.safe_load(open(f, encoding="utf-8"))
        for a in (d if isinstance(d, list) else d.get("agentes", [])):
            if "erpnext" in a.get("herramientas", []):
                por.setdefault(a["departamento"], []).append(a["id"])
    return por


class TestPoliticaDeAcceso(unittest.TestCase):
    def setUp(self):
        erp._politica.cache_clear()

    def test_todo_departamento_con_agentes_que_usan_el_erp_tiene_politica(self):
        sin = sorted(set(agentes_con_erp()) - set(DEPS))
        self.assertEqual(sin, [], f"sin política (se les bloquearía todo el ERP): {sin}")

    def test_borrador_es_un_subconjunto_de_leer(self):
        for dep, v in DEPS.items():
            self.assertLessEqual(set(v.get("borrador", [])), set(v.get("leer", [])), dep)

    def test_documentos_muy_delicados_no_estan_al_alcance_de_nadie_por_descuido(self):
        for dep, v in DEPS.items():
            for d in ("User", "Role", "Company"):
                self.assertNotIn(d, v.get("leer", []), f"{dep} puede leer {d}")
        con_banco = sorted(d for d, v in DEPS.items() if "Bank Account" in v.get("leer", []))
        self.assertEqual(con_banco, ["finanzas"], "Bank Account (IBAN de la empresa) solo para finanzas")
        con_nominas = sorted(d for d, v in DEPS.items() if "Salary Slip" in v.get("leer", []))
        self.assertEqual(con_nominas, ["personas"], "las nóminas solo para personas")

    def test_los_documentos_de_un_area_no_estan_en_otra_que_no_los_necesita(self):
        self.assertNotIn("Customer", DEPS["marketing"]["leer"])        # datos personales de clientes
        self.assertNotIn("Employee", DEPS["comercial"]["leer"])
        self.assertNotIn("CRM Deal", DEPS["finanzas"]["leer"])
        self.assertNotIn("Sales Invoice", DEPS["comercial"]["leer"])

    def test_permitido_y_denegado(self):
        erp.comprobar_acceso("comercial", "Customer", "leer")
        erp.comprobar_acceso("comercial", "CRM Lead", "borrador")
        for dep, doc, acc in [("comercial", "Bank Account", "leer"), ("comercial", "Sales Invoice", "borrador"),
                              ("marketing", "Customer", "leer"), ("finanzas", "CRM Deal", "leer"),
                              ("comercial", "Customer", "borrador"), ("inventado", "Customer", "leer")]:
            with self.subTest(dep=dep, doc=doc, acc=acc), self.assertRaises(PermissionError):
                erp.comprobar_acceso(dep, doc, acc)

    def test_el_error_dice_que_falta_y_como_arreglarlo(self):
        with self.assertRaises(PermissionError) as e:
            erp.comprobar_acceso("comercial", "Bank Account", "leer")
        t = str(e.exception)
        self.assertIn("comercial", t)
        self.assertIn("Bank Account", t)
        self.assertIn("config/erp_acceso.yaml", t)

    def test_no_se_puede_salir_de_api_resource(self):
        for doctype in ("Customer/../User", "../method/frappe.auth.get_logged_user", "Customer?x=1", "Customer#", "", "C", None, "A" * 90):
            with self.subTest(doctype=doctype), self.assertRaises(PermissionError):
                erp.comprobar_acceso("comercial", doctype, "leer")
        for nombre in ("../../User/Administrator", "a/b", "x?y=1", "x#y", "%2e%2e", "", "a\nb"):
            with self.subTest(nombre=nombre), self.assertRaises(PermissionError):
                erp.comprobar_acceso("comercial", "Customer", "leer", nombre)
        erp.comprobar_acceso("comercial", "Customer", "leer", "Comunitat Vilanova SL")       # un nombre normal sí

    def test_el_modo_avisar_no_bloquea_pero_deja_constancia(self):
        pol = {"modo": "avisar", "departamentos": {"comercial": {"leer": ["Customer"]}}}
        with mock.patch.object(erp, "_politica", return_value=pol), self.assertLogs("cerebro.erpnext", "WARNING"):
            erp.comprobar_acceso("comercial", "Bank Account", "leer")

    def test_sin_fichero_de_politica_no_se_abre_nada(self):
        erp._politica.cache_clear()
        self.assertEqual(erp._politica("/no/existe"), {"modo": "bloquear", "departamentos": {}})


@unittest.skipUnless(HAY_HTTPX, "requiere httpx real (se ejecuta en el contenedor)")
class TestLlamadasAlErp(unittest.TestCase):
    """Con la política delante, lo que no está permitido ni llega a salir hacia el ERP."""

    def setUp(self):
        erp._politica.cache_clear()
        self.peticiones = []

        def responder(request):
            self.peticiones.append(request)
            return httpx.Response(200, json={"data": [{"name": "X"}]})
        self.transporte = httpx.MockTransport(responder)
        real = httpx.AsyncClient
        self.parches = [mock.patch.dict(os.environ, {"ERPNEXT_TOKEN_COMERCIAL": "k:s"}),
                        mock.patch.object(erp.httpx, "AsyncClient", lambda **kw: real(transport=self.transporte, **kw)),
                        mock.patch.object(erp, "ajustes", SimpleNamespace(erpnext_url="http://erp", dir_config=erp.ajustes.dir_config))]
        for p in self.parches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self.parches])

    def correr(self, c):
        return asyncio.run(c)

    def test_lo_denegado_no_sale_hacia_el_erp(self):
        with self.assertRaises(PermissionError):
            self.correr(erp.listar("Bank Account", "comercial"))
        with self.assertRaises(PermissionError):
            self.correr(erp.crear_borrador("Sales Invoice", {"customer": "X"}, "comercial"))
        self.assertEqual(self.peticiones, [])

    def test_lo_permitido_sale_con_la_ruta_codificada(self):
        self.correr(erp.leer("Customer", "Comunitat Vilanova SL", "comercial"))
        self.assertEqual(self.peticiones[0].url.raw_path, b"/api/resource/Customer/Comunitat%20Vilanova%20SL")
        self.assertEqual(self.peticiones[0].headers["authorization"], "token k:s")
        self.correr(erp.listar("CRM Deal", "comercial"))
        self.assertEqual(self.peticiones[1].url.raw_path.split(b"?")[0], b"/api/resource/CRM%20Deal")


if __name__ == "__main__":
    unittest.main()
