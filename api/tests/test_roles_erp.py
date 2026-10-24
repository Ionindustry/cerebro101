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
