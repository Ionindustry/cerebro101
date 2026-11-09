"""scripts/erpnext_roles_cerebro.py: los permisos de cada rol salen de la política y nunca incluyen validar, cancelar ni borrar."""
import sys
import unittest
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "scripts"))
import erpnext_roles_cerebro as roles  # noqa: E402

POL = yaml.safe_load((RAIZ / "config" / "erp_acceso.yaml").read_text(encoding="utf-8"))
PELIGROSOS = {"delete", "submit", "cancel", "amend", "import", "export", "share"}


class TestPermisosDeLosRoles(unittest.TestCase):
    def test_nombre_del_rol(self):
        self.assertEqual(roles.nombre_rol("comercial"), "Cerebro Comercial")

    def test_leer_da_solo_lectura_y_borrador_da_leer_crear_y_modificar(self):
        p = roles.permisos_deseados(POL, "comercial")
        self.assertEqual(p["Customer"], {"read": 1})                       # solo se consulta
        self.assertEqual(p["Lead"], {"read": 1, "write": 1, "create": 1})  # se puede crear en borrador
        self.assertEqual(p["CRM Lead"], {"read": 1, "write": 1, "create": 1})

    def test_maestros_dan_leer_crear_y_modificar_en_el_erp(self):
        pol = {"departamentos": {"x": {"leer": ["Supplier", "Item"], "borrador": [], "maestros": ["Supplier"]}}}
        d = roles.permisos_deseados(pol, "x")
        self.assertEqual(d["Supplier"], {"read": 1, "write": 1, "create": 1})
        self.assertEqual(d["Item"], {"read": 1})

    def test_las_referencias_son_solo_seleccion_y_no_pisan_lo_que_ya_se_lee(self):
        p = roles.permisos_deseados(POL, "comercial")
        self.assertEqual(p["Account"], {"select": 1})
        pol = {"referencias": ["Customer", "Account"], "departamentos": {"x": {"leer": ["Customer"], "borrador": []}}}
        d = roles.permisos_deseados(pol, "x")
        self.assertEqual(d["Customer"], {"read": 1})                       # ya lo lee: no se degrada a «selección»
        self.assertEqual(d["Account"], {"select": 1})

    def test_ningun_departamento_puede_validar_cancelar_ni_borrar(self):
        for dep in POL["departamentos"]:
            for doc, perms in roles.permisos_deseados(POL, dep).items():
                self.assertFalse(PELIGROSOS & {k for k, v in perms.items() if v}, f"{dep}/{doc}: {perms}")

    def test_lo_delicado_no_llega_por_las_referencias(self):
        for doc in POL.get("referencias", []):
            self.assertNotIn(doc, ("User", "Role", "Bank Account", "Employee", "Salary Slip", "Customer", "Supplier"), doc)

    def test_un_departamento_inexistente_no_tiene_permisos(self):
        d = roles.permisos_deseados(POL, "inventado")
        self.assertTrue(all(set(v) == {"select"} for v in d.values()))     # solo las referencias, nada más


if __name__ == "__main__":
    unittest.main()


class FalsoERP:
    """Un ERP de mentira para `aplicar_departamento`: guarda los permisos del rol y registra lo que se le pide."""
    def __init__(self, filas):
        self.filas, self.llamadas = filas, []

    def llamar(self, metodo, ruta, datos=None):
        self.llamadas.append((metodo, ruta, datos))
        if ruta.startswith("/api/resource/Role/"):
            return 200, {"data": {}}
        if ruta.startswith("/api/resource/Custom DocPerm"):
            return 200, {"data": self.filas}
        if ruta.endswith("permission_manager.add"):
            return 417, {"error": "ya existe"}                      # la fila existe (solo con «select»): «add» no sirve
        if ruta.startswith("/api/resource/User/"):
            return 200, {"data": {"roles": [{"role": "Cerebro Licitaciones"}]}}
        return 200, {}


class TestAplicarSobreFilaExistente(unittest.TestCase):
    def test_una_fila_solo_con_select_se_ajusta_a_lectura(self):
        import tempfile
        fila = {"parent": "Company", "permlevel": 0, **{t: 0 for t in roles.TIPOS}, "select": 1}
        erp = FalsoERP([fila])
        with tempfile.TemporaryDirectory() as t:
            env = Path(t) / ".env"
            env.write_text("ERPNEXT_TOKEN_LICITACIONES=a:b\n", encoding="utf-8")
            from unittest import mock
            with mock.patch.object(roles, "probar", return_value="lee"), mock.patch.object(roles, "puede_leer", return_value=True), mock.patch.object(roles.time, "sleep"):
                roles.aplicar_departamento(erp, POL, "licitaciones", "101.cat", env, False, False, "http://x")
        ajustes = [(d["ptype"], d["value"]) for m, r, d in erp.llamadas if r.endswith("permission_manager.update") and d["doctype"] == "Company"]
        self.assertIn(("read", 1), ajustes)                       # ahora SÍ lee la Company
        self.assertIn(("select", 0), ajustes)                     # y deja de ser solo «select»

    def test_el_filtro_de_permisos_no_va_codificado_dos_veces(self):
        import tempfile
        erp = FalsoERP([])
        with tempfile.TemporaryDirectory() as t:
            env = Path(t) / ".env"
            env.write_text("ERPNEXT_TOKEN_LICITACIONES=a:b\n", encoding="utf-8")
            from unittest import mock
            with mock.patch.object(roles, "probar", return_value="lee"), mock.patch.object(roles, "puede_leer", return_value=True), mock.patch.object(roles.time, "sleep"):
                roles.aplicar_departamento(erp, POL, "licitaciones", "101.cat", env, True, False, "http://x")
        pedido = next(r for m, r, d in erp.llamadas if r.startswith("/api/resource/Custom DocPerm"))
        self.assertNotIn("%", pedido)
        self.assertIn('"role"', pedido)
