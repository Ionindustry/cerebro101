"""Guarda el mínimo privilegio: si alguien afloja db/roles.sql o los disparadores, estas pruebas lo avisan."""
import re
import unittest
from pathlib import Path

DB = Path(__file__).resolve().parents[2] / "db"


class TestRoles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.roles = (DB / "roles.sql").read_text(encoding="utf-8")
        cls.esquema = (DB / "esquema.sql").read_text(encoding="utf-8")

    def test_el_rol_de_la_aplicacion_no_es_superusuario_ni_crea_nada(self):
        m = re.search(r"CREATE ROLE cerebro_app ([^;]+);", self.roles)
        self.assertIsNotNone(m)
        for opcion in ("NOSUPERUSER", "NOCREATEDB", "NOCREATEROLE", "NOREPLICATION"):
            self.assertIn(opcion, m.group(1))
        self.assertNotIn("GRANT CREATE", self.roles)
        self.assertNotRegex(self.roles, r"(?i)GRANT\s+ALL\b[^;]*TO cerebro_app")

    def test_registro_de_acciones_solo_se_anexa(self):
        self.assertRegex(self.roles, r"REVOKE UPDATE, DELETE ON registro_acciones FROM cerebro_app")
        self.assertIn("registro_acciones_solo_anexar", self.esquema)
        self.assertIn("BEFORE TRUNCATE ON registro_acciones", self.esquema)

    def test_las_aprobaciones_no_se_borran(self):
        self.assertRegex(self.roles, r"REVOKE DELETE ON aprobaciones FROM cerebro_app")
        self.assertIn("aprobaciones_historial", self.esquema)

    def test_los_permisos_se_conceden_despues_de_quitar_todo(self):
        # el orden importa: primero REVOKE ALL, luego GRANT, y por último los REVOKE de evidencias
        i_revoke = self.roles.index("REVOKE ALL ON ALL TABLES")
        i_grant = self.roles.index("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES")
        i_evid = self.roles.index("REVOKE UPDATE, DELETE ON registro_acciones")
        self.assertLess(i_revoke, i_grant)
        self.assertLess(i_grant, i_evid)


if __name__ == "__main__":
    unittest.main()
