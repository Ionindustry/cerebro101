"""Despliegue en producción: generación del .env, configuración de Keycloak y coherencia del proxy y los compose."""
import re
import sys
import unittest
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parents[2]
if not (RAIZ / "despliegue").exists():             # dentro de la imagen de la API no están los ficheros del despliegue
    raise unittest.SkipTest("se ejecuta desde el repositorio, no desde la imagen")
sys.path[:0] = [str(RAIZ / "despliegue"), str(RAIZ / "scripts")]

import configurar_keycloak as kc  # noqa: E402
import erpnext_asistente as asistente  # noqa: E402
import preparar_env as pe  # noqa: E402

EJEMPLO = (RAIZ / ".env.example").read_text(encoding="utf-8")


class TestPrepararEnv(unittest.TestCase):
    def preparar(self, actual="", dominio="101.cat"):
        forzar = pe.direcciones(dominio, "it@101.cat", "letsencrypt") if dominio else {}
        return pe.completar(EJEMPLO, actual, forzar)

    def valores(self, texto):
        return {m.group(1): pe.limpiar(m.group(2)) for l in texto.splitlines() if (m := pe.LINEA.match(l))}

    def test_no_queda_ningun_secreto_de_ejemplo(self):
        v = self.valores(self.preparar()[0])
        for clave, valor in v.items():
            if clave.endswith(pe.SUFIJOS_SECRETOS) or clave in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_ENCRYPTION_KEY"):
                self.assertNotIn(valor, pe.PLACEHOLDERS, clave)
        self.assertEqual(len(v["LANGFUSE_ENCRYPTION_KEY"]), 64)
        self.assertRegex(v["LANGFUSE_ENCRYPTION_KEY"], r"^[0-9a-f]{64}$")

    def test_contrasenas_distintas_entre_si(self):
        v = self.valores(self.preparar()[0])
        contras = [valor for k, valor in v.items() if k.endswith("_PASSWORD")]
        self.assertGreater(len(contras), 6)
        self.assertEqual(len(contras), len(set(contras)))                      # ninguna repetida
        self.assertNotEqual(v["POSTGRES_PASSWORD"], v["CEREBRO_APP_PASSWORD"])  # propietario y aplicación, distintas

    def test_direcciones_y_modo_produccion(self):
        v = self.valores(self.preparar()[0])
        self.assertEqual((v["PANEL_URL"], v["KEYCLOAK_URL_PUBLICA"], v["LANGFUSE_URL_PUBLICA"]),
                         ("https://cerebro.101.cat", "https://auth.101.cat", "https://trazas.101.cat"))
        self.assertEqual((v["CEREBRO_MODO"], v["PANEL_USUARIO_DESARROLLO"], v["ERPNEXT_SITE"]), ("produccion", "", "erp.101.cat"))

    def test_no_pisa_valores_ya_rellenados_y_es_idempotente(self):
        primero, _ = self.preparar()
        segundo, cambios = pe.completar(EJEMPLO, primero, pe.direcciones("101.cat", "it@101.cat", "letsencrypt"))
        self.assertEqual(primero, segundo)
        self.assertEqual(cambios, {})

    def test_respeta_claves_externas_y_valores_propios(self):
        actual = "JEV_API_KEY=apikey_mia\nPOSTGRES_PASSWORD=la-mia\nXAI_API_KEY=\n"
        texto, cambios = self.preparar(actual)
        v = self.valores(texto)
        self.assertEqual((v["JEV_API_KEY"], v["POSTGRES_PASSWORD"], v["XAI_API_KEY"]), ("apikey_mia", "la-mia", ""))
        self.assertNotIn("POSTGRES_PASSWORD", cambios)

    def test_sin_dominio_solo_completa(self):
        texto, cambios = pe.completar(EJEMPLO, "", {})
        self.assertNotIn("PANEL_URL", {k for k, c in cambios.items() if c == "fijada"})

    def test_las_lineas_del_ejemplo_con_comentario_se_limpian(self):
        v = self.valores(self.preparar()[0])
        self.assertEqual(v["IPS_ADMIN"], "private_ranges")
        self.assertNotIn("#", v["TLS_MODO"])


class TestKeycloak(unittest.TestCase):
    def test_cliente_solo_acepta_el_panel_y_sin_contrasena_directa(self):
        actual = {"id": "x", "clientId": "cerebro-panel", "redirectUris": ["http://localhost:3000/*", "http://malo/*"],
                  "directAccessGrantsEnabled": True, "attributes": {"otro": "1"}}
        p = kc.payload_cliente(actual, "https://cerebro.101.cat/")
        self.assertEqual(p["redirectUris"], ["https://cerebro.101.cat/*"])
        self.assertEqual(p["webOrigins"], ["https://cerebro.101.cat"])
        self.assertFalse(p["directAccessGrantsEnabled"])
        self.assertTrue(p["publicClient"])
        self.assertEqual(p["attributes"], {"otro": "1", "post.logout.redirect.uris": "https://cerebro.101.cat/*"})
        self.assertEqual(p["id"], "x")

    def test_realm_endurecido(self):
        self.assertTrue(kc.AJUSTES_REALM["bruteForceProtected"])
        self.assertIn("length(12)", kc.AJUSTES_REALM["passwordPolicy"])
        self.assertFalse(kc.AJUSTES_REALM["registrationAllowed"])


class TestAsistenteErp(unittest.TestCase):
    def test_argumentos(self):
        a = asistente.construir_args("101.cat", "ab1")["args"]
        self.assertEqual((a["company_abbr"], a["currency"], a["country"], a["fy_start_date"]), ("AB1", "EUR", "Spain", "2026-01-01"))

    def test_validaciones(self):
        for mal in ("", "A", "ABCDEF", "a b"):
            with self.assertRaises(ValueError):
                asistente.construir_args("Empresa", mal)
        with self.assertRaises(ValueError):
            asistente.construir_args("  ", "AB")


class TestCoherenciaProxy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.caddy = (RAIZ / "despliegue" / "Caddyfile").read_text(encoding="utf-8")
        cls.prod = yaml.safe_load((RAIZ / "despliegue" / "docker-compose.produccion.yml").read_text(encoding="utf-8"))
        cls.base = yaml.safe_load((RAIZ / "docker-compose.yml").read_text(encoding="utf-8"))
        cls.erp = yaml.safe_load((RAIZ / "erpnext" / "docker-compose.yml").read_text(encoding="utf-8"))

    def test_todas_las_variables_del_caddyfile_llegan_al_proxy(self):
        usadas = set(re.findall(r"\{\$([A-Z_]+)\}", self.caddy))
        definidas = set(self.prod["services"]["proxy"]["environment"])
        self.assertEqual(usadas - definidas, set())

    def test_modos_tls_definidos(self):
        for modo in ("letsencrypt", "interno"):
            self.assertIn(f"(tls_{modo})", self.caddy)

    def test_las_variables_de_produccion_estan_en_el_ejemplo(self):
        claves = {m.group(1) for l in EJEMPLO.splitlines() if (m := pe.LINEA.match(l))}
        pedidas = set(re.findall(r"\$\{([A-Z_]+)[:?-]", (RAIZ / "despliegue" / "docker-compose.produccion.yml").read_text(encoding="utf-8")))
        self.assertEqual(pedidas - claves, set())

    def test_solo_el_proxy_se_publica_hacia_fuera(self):
        """Docker ignora el cortafuegos para los puertos publicados: todo menos Caddy debe quedar en 127.0.0.1."""
        for nombre, comp in (("principal", self.base), ("erpnext", self.erp)):
            for servicio, datos in comp["services"].items():
                for puerto in datos.get("ports", []):
                    self.assertTrue(str(puerto).startswith("127.0.0.1:"), f"{nombre}/{servicio} publica {puerto} hacia fuera")
        publicos = [str(p) for p in self.prod["services"]["proxy"]["ports"]]
        self.assertEqual(sorted(publicos), ["443:443", "443:443/udp", "80:80"])
        for servicio, datos in self.prod["services"].items():
            if servicio != "proxy":
                self.assertFalse(datos.get("ports"), f"{servicio} no debe publicar puertos en producción")

    def test_keycloak_en_produccion_y_detras_del_proxy(self):
        k = self.prod["services"]["keycloak"]
        self.assertTrue(k["command"].startswith("start "))
        self.assertNotIn("start-dev", k["command"])
        self.assertEqual(k["environment"]["KC_PROXY_HEADERS"], "xforwarded")
        self.assertEqual(k["environment"]["KC_DB"], "postgres")

    def test_la_administracion_de_keycloak_esta_restringida(self):
        self.assertRegex(self.caddy, r"@administracion path /admin")
        self.assertRegex(self.caddy, r"not remote_ip \{\$IPS_ADMIN\}")


if __name__ == "__main__":
    unittest.main()
