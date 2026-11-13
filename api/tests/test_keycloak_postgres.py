"""Keycloak en modo producción con PostgreSQL: el añadido de compose y el script de migración (sin Docker: se comprueba su forma, no su ejecución)."""
import re
import subprocess
import unittest
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parents[2]
COMPOSE = RAIZ / "despliegue" / "docker-compose.keycloak-postgres.yml"
SCRIPT = RAIZ / "scripts" / "keycloak_a_postgres.sh"


class TestCompose(unittest.TestCase):
    def setUp(self):
        self.c = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
        self.kc = self.c["services"]["keycloak"]

    def test_keycloak_arranca_en_modo_produccion_no_en_desarrollo(self):
        self.assertEqual(self.kc["command"].split()[0], "start")
        self.assertNotIn("start-dev", self.kc["command"])

    def test_usa_postgres_con_contrasena_obligatoria(self):
        e = self.kc["environment"]
        self.assertEqual(e["KC_DB"], "postgres")
        self.assertIn("keycloak-db", e["KC_DB_URL"])
        self.assertIn(":?", self.c["services"]["keycloak-db"]["environment"]["POSTGRES_PASSWORD"])          # sin contraseña definida, Compose se niega a arrancar
        self.assertNotIn("cambia-esto", COMPOSE.read_text(encoding="utf-8"))

    def test_la_carpeta_de_importacion_y_la_version_son_configurables(self):
        self.assertTrue(any("KEYCLOAK_IMPORT_DIR" in v and v.endswith("/opt/keycloak/data/import:ro") for v in self.kc["volumes"]))
        self.assertIn("KEYCLOAK_IMAGEN", self.kc["image"])

    def test_no_publica_puertos_nuevos_ni_la_base_de_datos(self):
        self.assertNotIn("ports", self.kc)
        self.assertNotIn("ports", self.c["services"]["keycloak-db"])

    def test_la_base_tiene_su_volumen_y_espera_a_estar_sana(self):
        self.assertIn("keycloak-db", self.c["volumes"])
        self.assertEqual(self.kc["depends_on"]["keycloak-db"]["condition"], "service_healthy")


class TestScript(unittest.TestCase):
    def setUp(self):
        self.t = SCRIPT.read_text(encoding="utf-8")

    def test_la_sintaxis_es_valida(self):
        r = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_no_toca_los_datos_viejos_y_vuelve_atras_si_falla(self):
        self.assertIn("trap volver ERR", self.t)
        self.assertIn("docker cp", self.t)                                             # copia antes de nada
        self.assertNotIn("docker volume rm", self.t)
        self.assertNotIn("down -v", self.t)
        self.assertNotIn("rm -rf", self.t)
        self.assertIn("--deshacer", self.t)

    def test_exporta_los_usuarios_y_comprueba_antes_de_seguir(self):
        self.assertIn("--users realm_file", self.t)
        self.assertRegex(self.t, r"grep -c '\"username\"'")
        self.assertIn("no trae ningún usuario", self.t)

    def test_la_contrasena_la_genera_el_script_y_no_se_muestra(self):
        self.assertIn("/dev/urandom", self.t)
        gen = self.t[self.t.index("Creando la contraseña"):]
        self.assertNotRegex(gen.split("\n")[1], r"echo .*KEYCLOAK_DB_PASSWORD\)")           # la línea que la pone no la imprime
        self.assertNotRegex(self.t, r"echo[^\n]*\$\{?clave")                              # la del administrador tampoco

    def test_es_idempotente(self):
        self.assertIn("ya funciona en modo producción con PostgreSQL", self.t)


class TestFuncionesDelScript(unittest.TestCase):
    """Las funciones que tocan el .env se ejecutan de verdad en bash (sin Docker) contra un .env de prueba."""

    def correr(self, env_texto: str, orden: str) -> str:
        import tempfile
        t = SCRIPT.read_text(encoding="utf-8")
        ini, fin = t.index("valor_env()"), t.index("esperar()")
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / ".env").write_bytes(env_texto.encode())
            prog = f'cd "{d}"; ENV=.env; FICHERO="despliegue/docker-compose.keycloak-postgres.yml"\n{t[ini:fin]}\n{orden}'
            r = subprocess.run(["bash", "-c", prog], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            return r.stdout

    def test_un_env_con_saltos_de_windows_no_deja_barra_r_en_los_valores(self):
        self.assertEqual(self.correr("A=uno\r\nCOMPOSE_FILE=docker-compose.yml\r\n", 'valor_env COMPOSE_FILE | od -c | head -2'), self.correr("A=uno\nCOMPOSE_FILE=docker-compose.yml\n", 'valor_env COMPOSE_FILE | od -c | head -2'))

    def test_poner_env_cambia_o_anade_sin_tocar_el_resto(self):
        out = self.correr("A=1\nB=2\n", 'poner_env B 3; poner_env C 4; cat .env')
        self.assertEqual(out.split(), ["A=1", "B=3", "C=4"])

    def test_con_fichero_y_sin_fichero(self):
        f = "despliegue/docker-compose.keycloak-postgres.yml"
        self.assertEqual(self.correr(f"COMPOSE_FILE=docker-compose.yml:{f}\n", f'con_fichero && echo si; sin_fichero').split(), ["si", "docker-compose.yml"])
        self.assertEqual(self.correr("COMPOSE_FILE=docker-compose.yml\n", 'con_fichero && echo si || echo no').strip(), "no")
        self.assertEqual(self.correr("A=1\n", 'valor_env COMPOSE_FILE; echo fin').strip(), "fin")

    def test_la_copia_vieja_solo_la_lee_quien_ejecuta(self):
        self.assertIn('chmod -R go-rwx "$copia/h2"', SCRIPT.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
