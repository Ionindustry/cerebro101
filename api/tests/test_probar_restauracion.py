"""scripts/probar_restauracion.sh: restaura la copia en una base TEMPORAL, cuenta tablas y filas, detecta copias rotas y no deja nada atrás. Con PostgreSQL de prueba (CEREBRO_TEST_PG); el servidor de verdad se sustituye."""
import gzip
import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import _sin_servicios  # noqa: F401

try:
    import psycopg
except ImportError as e:      # pragma: no cover
    raise unittest.SkipTest(str(e))

URL = os.environ.get("CEREBRO_TEST_PG")
RAIZ = Path(__file__).resolve().parents[2]
SCRIPT = RAIZ / "scripts" / "probar_restauracion.sh"
PSQL = "env PGPASSWORD=postgres psql -h localhost -U postgres"


def volcado(tablas: int, filas: int = 3) -> bytes:
    sql = "".join(f"CREATE TABLE t{i} (id int, v text);\nINSERT INTO t{i} SELECT g, 'x' FROM generate_series(1, {filas}) g;\n" for i in range(tablas))
    return gzip.compress(sql.encode())


def erp(completo=True, tablas=60) -> bytes:
    sql = "".join(f"CREATE TABLE `t{i}` (id int);\n" for i in range(tablas)) + "INSERT INTO `t0` VALUES (1);\n" + ("-- Dump completed on 2026-11-04\n" if completo else "")
    return gzip.compress(sql.encode())


@unittest.skipUnless(URL and hasattr(psycopg, "AsyncConnection"), "sin CEREBRO_TEST_PG")
class TestRestauracion(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.copias = Path(self.tmp.name) / "copias"
        self.dir = self.copias / "auto" / "2026-11-04_1400"
        self.dir.mkdir(parents=True)
        self.registro = Path(self.tmp.name) / "registro.txt"
        reg = Path(self.tmp.name) / "registrar.sh"
        reg.write_text(f'#!/usr/bin/env bash\necho "$@" >> "{self.registro}"\n')
        reg.chmod(0o755)
        self.env = {**os.environ, "RESTAURAR_PG_CEREBRO": PSQL, "RESTAURAR_PG_LANGFUSE": PSQL, "RESTAURAR_PG_LIC": PSQL, "RESTAURAR_REGISTRAR": str(reg)}

    def tearDown(self):
        self.tmp.cleanup()

    def copia(self, ficheros: dict, sumas=True):
        for n, d in ficheros.items():
            (self.dir / n).write_bytes(d)
        if sumas:
            (self.dir / "SHA256SUMS").write_text("".join(f"{hashlib.sha256(d).hexdigest()}  {n}\n" for n, d in ficheros.items()))

    def probar(self):
        r = subprocess.run(["bash", str(SCRIPT), str(self.dir)], env=self.env, capture_output=True, text=True, timeout=120)
        with psycopg.connect(URL.rsplit("/", 1)[0] + "/postgres", autocommit=True) as c:
            sobrantes = [x[0] for x in c.execute("SELECT datname FROM pg_database WHERE datname LIKE 'restauracion_prueba_%'").fetchall()]
        return r, sobrantes

    def test_copia_buena_se_restaura_cuenta_y_no_deja_base_temporal(self):
        self.copia({"cerebro.sql.gz": volcado(6, 4), "langfuse.sql.gz": volcado(2), "erpnext.sql.gz": erp()})
        r, sobrantes = self.probar()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("cerebro.sql.gz: restaurado; 6 tablas y 24 filas", r.stdout)
        self.assertIn("erpnext.sql.gz: 60 tablas", r.stdout)
        self.assertEqual(sobrantes, [])
        estado = json.loads((self.copias / "restauracion.json").read_text())
        self.assertTrue(estado["ok"])
        self.assertIn("true", self.registro.read_text())

    def test_sumas_distintas_o_ficheros_dañados_fallan(self):
        self.copia({"cerebro.sql.gz": volcado(6)})
        (self.dir / "cerebro.sql.gz").write_bytes(b"no es un gzip")
        r, sobrantes = self.probar()
        self.assertEqual(r.returncode, 1)
        self.assertIn("SHA256SUMS no coincide", r.stdout)
        self.assertIn("dañado", r.stdout)
        self.assertFalse(json.loads((self.copias / "restauracion.json").read_text())["ok"])
        self.assertIn("false", self.registro.read_text())

    def test_un_volcado_que_no_se_restaura_o_con_pocas_tablas_falla_y_se_limpia(self):
        malo = gzip.compress(b"CREATE TABLE a (id int);\nINSERT INTO no_existe VALUES (1);\n")
        self.copia({"cerebro.sql.gz": malo})
        r, sobrantes = self.probar()
        self.assertEqual(r.returncode, 1)
        self.assertIn("NO se restaura", r.stdout)
        self.assertEqual(sobrantes, [])
        self.copia({"cerebro.sql.gz": volcado(2)})                      # se restaura, pero un Cerebro con 2 tablas no es una copia buena
        r, sobrantes = self.probar()
        self.assertEqual(r.returncode, 1)
        self.assertIn("solo 2 tablas", r.stdout)
        self.assertEqual(sobrantes, [])

    def test_el_volcado_del_erp_incompleto_se_detecta_y_nunca_se_restaura(self):
        self.copia({"cerebro.sql.gz": volcado(6), "erpnext.sql.gz": erp(completo=False)})
        r, _ = self.probar()
        self.assertEqual(r.returncode, 1)
        self.assertIn("no está completo", r.stdout)

    def test_sin_copia_que_probar_avisa(self):
        r = subprocess.run(["bash", str(SCRIPT), str(self.copias / "no_existe")], env=self.env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
