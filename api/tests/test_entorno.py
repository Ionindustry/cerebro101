"""El entorno de cada contenedor es una lista cerrada y no se separa del código (mínimo privilegio también en las variables)."""
import re
import unittest
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parents[2]
if not (RAIZ / "docker-compose.yml").exists():      # dentro de la imagen de la API no están los ficheros del despliegue
    raise unittest.SkipTest("se ejecuta desde el repositorio, no desde la imagen")
COMPOSE = yaml.safe_load((RAIZ / "docker-compose.yml").read_text(encoding="utf-8"))
EJEMPLO = (RAIZ / ".env.example").read_text(encoding="utf-8")

# Secretos que la API, el worker y beat no deben ver nunca
PROHIBIDAS = ("POSTGRES_PASSWORD", "DATABASE_URL_ADMIN", "KEYCLOAK_ADMIN_PASSWORD", "KEYCLOAK_DB_PASSWORD",
              "ERPNEXT_ADMIN_PASSWORD", "ERPNEXT_DB_ROOT_PASSWORD", "LANGFUSE_ENCRYPTION_KEY", "LANGFUSE_SALT",
              "LANGFUSE_NEXTAUTH_SECRET", "LANGFUSE_DB_PASSWORD", "LANGFUSE_CLICKHOUSE_PASSWORD", "LANGFUSE_MINIO_PASSWORD",
              "LANGFUSE_REDIS_PASSWORD", "LANGFUSE_INIT_USER_PASSWORD", "TLS_MODO")
# Las lee el código pero no son del entorno de la API (migraciones, rutas, pruebas)
AJENAS = {"DATABASE_URL_ADMIN", "CEREBRO_APP_PASSWORD", "CEREBRO_DB_DIR", "CEREBRO_CONFIG", "CEREBRO_DATOS"}
# Variables que se crean con f-string: prefijo -> se exige al menos una en la lista
DINAMICAS = ("ERPNEXT_TOKEN_", "CORREO_", "CALENDARIO_")


def _env(servicio: str) -> dict:
    return COMPOSE["services"][servicio].get("environment") or {}


def _leidas_por_el_codigo() -> set[str]:
    nombres = set()
    for f in (RAIZ / "api" / "cerebro").rglob("*.py"):
        t = f.read_text(encoding="utf-8")
        nombres |= set(re.findall(r"(?:environ\.get\(|environ\[|getenv\(|_env\(|_num\()\s*[\"']([A-Z][A-Z_0-9]+)[\"']", t))
        nombres |= set(re.findall(r"os\.environ\.get\(\s*[\"']([A-Z][A-Z_0-9]+)", t))
        nombres |= set(re.findall(r"for v in \(([^)]*)\)", t) and re.findall(r"[\"']([A-Z][A-Z_0-9]{3,})[\"']", t))
    return {n for n in nombres if n.isupper() and "_" in n or n in {"TZ"}}


class TestEntorno(unittest.TestCase):
    def test_ningun_servicio_recibe_el_env_completo_salvo_los_que_lo_declaran(self):
        con_env_file = [n for n, s in COMPOSE["services"].items() if "env_file" in s]
        self.assertEqual(con_env_file, [], f"estos servicios reciben todo el .env: {con_env_file}")
        self.assertNotIn("env_file", COMPOSE["x-api"])

    def test_la_api_no_recibe_secretos_ajenos(self):
        for servicio in ("api", "worker", "beat"):
            env = _env(servicio)
            for v in PROHIBIDAS:
                self.assertNotIn(v, env, f"{servicio} no debe recibir {v}")
            # ni siquiera referenciada dentro de otro valor
            texto = yaml.dump(env)
            for v in PROHIBIDAS:
                self.assertNotIn("${" + v, texto, f"{servicio} usa {v} dentro de otro valor")

    def test_beat_solo_recibe_lo_imprescindible(self):
        self.assertLessEqual(set(_env("beat")), {"TZ", "REDIS_URL"})

    def test_la_api_usa_el_rol_de_minimo_privilegio(self):
        self.assertIn("cerebro_app:${CEREBRO_APP_PASSWORD}", _env("api")["DATABASE_URL"])

    def test_todo_lo_que_lee_el_codigo_llega_a_la_api(self):
        falta = sorted(n for n in _leidas_por_el_codigo() - AJENAS - set(_env("api")) if not n.startswith("__"))
        self.assertEqual(falta, [], f"el código lee estas variables y la API no las recibe: {falta}")

    def test_las_variables_dinamicas_tienen_alguna_entrada(self):
        for prefijo in DINAMICAS:
            self.assertTrue(any(k.startswith(prefijo) for k in _env("api")), f"ninguna variable {prefijo}* en la API")

    def test_la_api_no_recibe_nada_que_no_este_en_el_ejemplo(self):
        ejemplo = set(re.findall(r"^#?([A-Z][A-Z_0-9]+)=", EJEMPLO, re.M))
        sobran = sorted(set(_env("api")) - ejemplo - {"DATABASE_URL"})
        self.assertEqual(sobran, [], f"variables de la API que no están documentadas en .env.example: {sobran}")

    def test_cada_variable_de_la_api_con_valor_por_defecto_en_el_codigo_no_llega_vacia(self):
        # `os.environ.get("X", defecto)` devuelve "" si X llega vacía: estas deben llevar un valor por defecto en el compose
        for v in ("CEREBRO_MODO", "PERFIL_HARDWARE", "OLLAMA_URL", "REDIS_URL", "KEYCLOAK_URL", "KEYCLOAK_REALM", "KEYCLOAK_CLIENTE",
                  "XAI_MODELO", "JEFF_URL", "AGENT_REACH_URL", "USAR_JEV_NUBE", "ANONIMIZACION_NER"):
            self.assertRegex(_env("api")[v], r"\$\{%s:-.+\}" % v, f"{v} llegaría vacía si no está en .env")


if __name__ == "__main__":
    unittest.main()
