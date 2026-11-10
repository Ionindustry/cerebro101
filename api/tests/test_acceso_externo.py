"""Acceso externo (HTTPS) para una instalación local: validación, edición del .env sin tocar lo demás, el proxy y el flujo de activar/desactivar con un docker de pega."""
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parents[2]
if not (RAIZ / "despliegue" / "acceso_externo.py").exists():
    raise unittest.SkipTest("se ejecuta desde el repositorio, no desde la imagen")


def cargar(ruta: Path):
    spec = importlib.util.spec_from_file_location("acceso_externo_t", ruta)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


AE = cargar(RAIZ / "despliegue" / "acceso_externo.py")


class TestPuras(unittest.TestCase):
    def test_validar(self):
        self.assertEqual(AE.validar(" Brain.101.cat ", "auth.101.cat", "a@b.es"), ("brain.101.cat", "auth.101.cat", "a@b.es"))
        for malo in (("localhost", "auth.101.cat", "a@b.es"), ("brain.101.cat", "brain.101.cat", "a@b.es"), ("brain.101.cat", "auth.101.cat", "sin-arroba"),
                     ("https://brain.101.cat", "auth.101.cat", "a@b.es"), ("brain .101.cat", "auth.101.cat", "a@b.es")):
            with self.assertRaises(AE.ErrorAcceso, msg=str(malo)):
                AE.validar(*malo)

    def test_valores_conservan_el_compose_que_ya_hubiera(self):
        v = AE.valores_nuevos("brain.101.cat", "auth.101.cat", "a@b.es", "docker-compose.yml:docker-compose.sin-gpu.yml")
        self.assertEqual(v["COMPOSE_FILE"], "docker-compose.yml:docker-compose.sin-gpu.yml:despliegue/docker-compose.externo.yml")
        self.assertEqual((v["PANEL_URL"], v["KEYCLOAK_URL_PUBLICA"], v["TLS_MODO"]), ("https://brain.101.cat", "https://auth.101.cat", "letsencrypt"))
        self.assertEqual(AE.valores_nuevos("a.b.cat", "c.b.cat", "a@b.es", "")["COMPOSE_FILE"], "docker-compose.yml:despliegue/docker-compose.externo.yml")
        again = AE.valores_nuevos("a.b.cat", "c.b.cat", "a@b.es", v["COMPOSE_FILE"])["COMPOSE_FILE"]
        self.assertEqual(again.count("externo"), 1)                                          # no se añade dos veces

    def test_sin_puerto_80_el_proxy_solo_lo_publica_en_local(self):
        v = AE.valores_nuevos("a.b.cat", "c.b.cat", "a@b.es", "", sin_puerto_80=True)
        self.assertEqual(v["PROXY_HTTP_BIND"], "127.0.0.1:8088")
        self.assertNotIn("PROXY_HTTP_BIND", AE.valores_nuevos("a.b.cat", "c.b.cat", "a@b.es", ""))

    def test_poner_solo_toca_esas_claves(self):
        t = "A=1  # comentario\nPANEL_URL=http://localhost:3000\nB=2\n"
        r = AE.poner(t, {"PANEL_URL": "https://x.cat", "NUEVA": "z", "A": None})
        self.assertEqual(AE.leer_env(r), {"PANEL_URL": "https://x.cat", "B": "2", "NUEVA": "z"})


class TestFicheros(unittest.TestCase):
    def test_el_proxy_solo_publica_80_y_443_y_nada_mas_se_expone(self):
        c = yaml.safe_load((RAIZ / "despliegue" / "docker-compose.externo.yml").read_text(encoding="utf-8"))
        self.assertEqual(set(c["services"]), {"keycloak", "proxy"})
        self.assertEqual(set(c["services"]["proxy"]["ports"]), {"${PROXY_HTTP_BIND:-80}:80", "443:443", "443:443/udp"})
        self.assertNotIn("ports", c["services"]["keycloak"])                                  # Keycloak sigue solo en 127.0.0.1 (lo dice el compose base)
        self.assertIn("./despliegue/Caddyfile.externo:/etc/caddy/Caddyfile:ro", c["services"]["proxy"]["volumes"])

    def test_el_caddyfile_sirve_solo_el_panel_y_el_login_y_restringe_la_administracion(self):
        t = (RAIZ / "despliegue" / "Caddyfile.externo").read_text(encoding="utf-8")
        self.assertIn("{$DOM_PANEL}", t)
        self.assertIn("{$DOM_AUTH}", t)
        for no in ("DOM_ERP", "DOM_TRAZAS", "langfuse", "erpnext", "api:8000"):
            self.assertNotIn(no, t)
        self.assertIn("/realms/master", t)
        self.assertIn("not remote_ip {$IPS_ADMIN}", t)
        self.assertIn("reverse_proxy panel:3000", t)


DOCKER_FALSO = '''#!/usr/bin/env bash
cd "$FALSO" 2>/dev/null || true
echo "$*" >> llamadas.log
case "$1 $2" in
  "compose ps") [ -f sin_contenedor ] || echo "kc123"; exit 0 ;;
  "compose up") [ -f falla_up ] && exit 1; exit 0 ;;
esac
case "$1" in
  inspect) [ -f sin_volumen ] || echo "/opt/keycloak/data/h2"; exit 0 ;;
esac
exit 0
'''
KC_FALSO = 'import sys\nopen("kc.log","a").write(" ".join(sys.argv[1:]) + "\\n")\n'


class Entorno:
    def __init__(self, **banderas):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.repo = t / "repo"
        (self.repo / "despliegue").mkdir(parents=True)
        shutil.copy(RAIZ / "despliegue" / "acceso_externo.py", self.repo / "despliegue" / "acceso_externo.py")
        (self.repo / "despliegue" / "configurar_keycloak.py").write_text(f'import os\nopen(r"{t}/kc.log","a").write(os.environ.get("X","ejecutado")+"\\n")\n')
        (self.repo / ".env").write_text("A=1\nPANEL_URL=http://localhost:3000\nKEYCLOAK_URL_PUBLICA=http://localhost:8080\nKEYCLOAK_ADMIN_PASSWORD=vieja\n")
        self.falso = t / "falso"
        self.falso.mkdir()
        bin_ = t / "bin"
        bin_.mkdir()
        f = bin_ / "docker"
        f.write_text(DOCKER_FALSO)
        f.chmod(f.stat().st_mode | stat.S_IEXEC)
        self.env = {**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}", "FALSO": str(self.falso)}
        for b, v in banderas.items():
            if v:
                (self.falso / b).write_text("")
        self.kc = t / "kc.log"

    def correr(self, *args):
        return subprocess.run([sys.executable, "despliegue/acceso_externo.py", *args], cwd=self.repo, env=self.env, capture_output=True, text=True, timeout=60)

    def env_repo(self):
        return AE.leer_env((self.repo / ".env").read_text())

    def llamadas(self):
        f = self.falso / "llamadas.log"
        return f.read_text() if f.exists() else ""

    def limpiar(self):
        self.tmp.cleanup()


ARGS = ("activar", "--panel", "localhost.invalid.example", "--auth", "auth.example.com", "--correo", "a@b.es", "--sin-dns")


class TestFlujo(unittest.TestCase):
    def test_simular_no_toca_nada(self):
        e = Entorno()
        try:
            r = e.correr(*ARGS[:-1], "--simular")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("PANEL_URL=https://", r.stdout)
            self.assertEqual(e.env_repo()["PANEL_URL"], "http://localhost:3000")
            self.assertFalse((e.repo / ".acceso-externo.json").exists())
            self.assertNotIn("up", e.llamadas())
        finally:
            e.limpiar()

    def test_no_activa_si_keycloak_no_conserva_sus_datos(self):
        e = Entorno(sin_volumen=True)
        try:
            r = e.correr(*ARGS)
            self.assertEqual(r.returncode, 1)
            self.assertIn("keycloak_conservar.sh", r.stderr)
            self.assertEqual(e.env_repo()["PANEL_URL"], "http://localhost:3000")             # no se ha tocado nada
        finally:
            e.limpiar()

    def test_no_activa_si_los_nombres_no_resuelven_en_dns(self):
        e = Entorno()
        try:
            r = e.correr("activar", "--panel", "no-existe-ninguno.invalid", "--auth", "auth.no-existe.invalid", "--correo", "a@b.es")
            self.assertEqual(r.returncode, 1)
            self.assertIn("DNS", r.stderr)
            self.assertFalse((e.repo / ".acceso-externo.json").exists())
        finally:
            e.limpiar()

    def test_activar_fija_el_env_recrea_los_servicios_y_ajusta_keycloak(self):
        e = Entorno()
        try:
            r = e.correr(*ARGS)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            v = e.env_repo()
            self.assertEqual((v["PANEL_URL"], v["KEYCLOAK_URL_PUBLICA"], v["DOM_PANEL"], v["TLS_MODO"]), ("https://localhost.invalid.example", "https://auth.example.com", "localhost.invalid.example", "letsencrypt"))
            self.assertIn("externo.yml", v["COMPOSE_FILE"])
            self.assertEqual(stat.S_IMODE((e.repo / ".env").stat().st_mode), 0o600)
            antes = json.loads((e.repo / ".acceso-externo.json").read_text())
            self.assertEqual((antes["PANEL_URL"], antes["COMPOSE_FILE"]), ("http://localhost:3000", None))
            self.assertIn("up -d --no-build keycloak panel api worker beat proxy", e.llamadas())
            self.assertTrue(e.kc.exists())                                                     # se ejecutó configurar_keycloak
            self.assertIn("Cortafuegos de Windows", r.stdout)
            self.assertEqual(e.correr(*ARGS).returncode, 1)                                    # y no se activa dos veces
        finally:
            e.limpiar()

    def test_desactivar_devuelve_solo_lo_que_cambio_y_respeta_el_resto(self):
        e = Entorno()
        try:
            self.assertEqual(e.correr(*ARGS).returncode, 0)
            t = (e.repo / ".env").read_text().replace("KEYCLOAK_ADMIN_PASSWORD=vieja", "KEYCLOAK_ADMIN_PASSWORD=ROTADA")        # entre medias se rotó la clave
            (e.repo / ".env").write_text(t)
            r = e.correr("desactivar")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            v = e.env_repo()
            self.assertEqual((v["PANEL_URL"], v["KEYCLOAK_URL_PUBLICA"], v["KEYCLOAK_ADMIN_PASSWORD"], v["A"]), ("http://localhost:3000", "http://localhost:8080", "ROTADA", "1"))
            for k in ("COMPOSE_FILE", "DOM_PANEL", "CORREO_ADMIN"):
                self.assertNotIn(k, v)
            self.assertFalse((e.repo / ".acceso-externo.json").exists())
            self.assertIn("rm -sf proxy", e.llamadas())
        finally:
            e.limpiar()

    def test_si_falla_al_recrear_dice_como_volver_atras(self):
        e = Entorno(falla_up=True)
        try:
            r = e.correr(*ARGS)
            self.assertEqual(r.returncode, 1)
            self.assertIn("desactivar", r.stderr)
            self.assertTrue((e.repo / ".acceso-externo.json").exists())                        # y se puede volver atrás
        finally:
            e.limpiar()


if __name__ == "__main__":
    unittest.main()
