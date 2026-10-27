"""El detector de secretos de scripts/comprobar_secretos.py: encuentra lo peligroso y no se queja de los marcadores."""
import importlib.util
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("comprobar_secretos", RAIZ / "scripts" / "comprobar_secretos.py")
S = importlib.util.module_from_spec(spec)
spec.loader.exec_module(S)


def encontrados(texto):
    return list(S.hallazgos(texto, "x.txt"))


class TestDetector(unittest.TestCase):
    def test_encuentra_secretos_reales(self):
        for texto in ("-----BEGIN RSA PRIVATE KEY-----",
                      "token = ghp_" + "a" * 36,
                      "AWS = AKIA" + "A1B2C3D4E5F6G7H8",
                      "JEV_API_KEY=" + "q9Zr4kLm2PxV7tBw8NcYdE3h",
                      "DATABASE_URL=postgresql://cerebro:Zx8mQ2vL9pTr4Ws@db:5432/x",
                      "OTRA_CLAVE: 'Tg7vN2xQp9LmZ4rWk8Bd'"):
            with self.subTest(texto[:20]):
                self.assertTrue(encontrados(texto), texto)

    def test_no_se_queja_de_marcadores_ni_de_valores_de_prueba(self):
        for texto in ("JEV_API_KEY=", "JEV_API_KEY=                       # clave de console", "LANGFUSE_SECRET_KEY=sk-lf-cambia-esto",
                      "DATABASE_URL=postgresql://cerebro:cerebro@postgres:5432/cerebro", "x = os.environ['API_KEY']",
                      "PASSWORD: ${POSTGRES_PASSWORD}", 'CEREBRO_APP_PASSWORD: "${CEREBRO_APP_PASSWORD}"',
                      "DATABASE_URL=postgresql://cerebro_app:${CEREBRO_APP_PASSWORD}@postgres:5432/cerebro",
                      "PG=postgres://postgres:prueba@localhost:5432/lic_test", "PG=postgres://usuario:clave@host/base",
                      "PG=postgres://postgres:changeme@db/x",
                      'const token = "token-de-pruebas-con-al-menos-32-caracteres"',
                      'EnvNATSClave = "LIC_NATS_PASSWORD"', 'EnvPG = "LIC_PG_URL"', "TOKEN_VAR = 'LIC_API_TOKEN_SECRET'"):
            with self.subTest(texto[:30]):
                self.assertEqual(encontrados(texto), [], texto)

    def test_una_contrasena_real_en_una_direccion_sigue_saltando(self):
        self.assertEqual(len(encontrados("PG=postgres://postgres:Zx8mQ2vL9pTr4Ws@localhost/x")), 1)

    def test_una_clave_real_con_guiones_bajos_sigue_saltando(self):
        # solo se ignoran los NOMBRES de variable (mayúsculas y guiones bajos); una clave mezclada salta aunque lleve guiones bajos
        self.assertTrue(encontrados("API_KEY = 'q9Zr4kLm_2PxV7tBw8NcYdE3h'"))

    def test_no_imprime_el_secreto_entero(self):
        h = encontrados("JEV_API_KEY=" + "q9Zr4kLm2PxV7tBw8NcYdE3h")[0]
        self.assertNotIn("q9Zr4kLm2PxV7tBw8NcYdE3h", h)


if __name__ == "__main__":
    unittest.main()
