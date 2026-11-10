"""Keycloak conserva sus usuarios: volumen en el compose y los scripts que lo estrenan sin perder datos y rotan la contraseña de administrador (con un «docker» de pega que apunta lo que le piden)."""
import os
import re
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parents[2]
if not (RAIZ / "scripts" / "keycloak_conservar.sh").exists():
    raise unittest.SkipTest("se ejecuta desde el repositorio, no desde la imagen")
BASH = shutil.which("bash")

# Un «docker» de pega: guarda cada llamada en llamadas.log y responde lo justo. Estado en ficheros dentro de su carpeta.
DOCKER_FALSO = r'''#!/usr/bin/env bash
ORIG="$PWD"
cd "$FALSO"
echo "$*" >> llamadas.log
case "$1 $2" in
  "compose ps")
    [ -f existe ] && echo "viejo123" ; [ -f nuevo ] && echo "nuevo456"; exit 0 ;;
  "compose stop"|"compose start") exit 0 ;;
  "compose up")
    case "$*" in *--no-start*) touch nuevo; rm -f existe;; esac; exit 0 ;;
  "compose exec")
    echo "kcadm: $*" >> kcadm.log
    # con «clave_distinta»: la contraseña del .env/contenedor no sirve y solo vale la que se escriba («correcta»)
    if [ -f clave_distinta ] && [ "${ACTUAL:-}" != "correcta" ]; then echo "Invalid user credentials [invalid_grant]" >&2; exit 1; fi
    exit 0 ;;
esac
case "$1" in
  inspect) [ -f con_volumen ] && echo "/opt/keycloak/data/h2" ; echo "/opt/keycloak/data/import"; exit 0 ;;
  cp)
    # docker cp viejo:/ruta/. destino   |   docker cp -a origen/. nuevo:/ruta/
    if [ "$2" = "-a" ]; then echo "copiado-a-nuevo $3 $4" >> cp.log; exit 0; fi
    [ -f falla_cp ] && exit 1
    cd "$ORIG"; mkdir -p "$3"; [ -f "$FALSO/vacio" ] || echo datos > "$3/keycloakdb.mv.db"; exit 0 ;;
esac
exit 0
'''
CURL_FALSO = '#!/usr/bin/env bash\nexit 0\n'


class Entorno:
    def __init__(self, **banderas):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.falso = t / "falso"
        self.falso.mkdir()
        self.repo = t / "repo"
        (self.repo / "scripts").mkdir(parents=True)
        for n in ("keycloak_conservar.sh", "keycloak_clave_admin.sh"):
            shutil.copy(RAIZ / "scripts" / n, self.repo / "scripts" / n)
        (self.repo / ".env").write_text("A=1\nKEYCLOAK_ADMIN_PASSWORD=vieja\nB=2\n")
        bin_ = t / "bin"
        bin_.mkdir()
        for nombre, texto in (("docker", DOCKER_FALSO), ("curl", CURL_FALSO)):
            f = bin_ / nombre
            f.write_text(texto)
            f.chmod(f.stat().st_mode | stat.S_IEXEC)
        self.env = {**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}", "FALSO": str(self.falso)}
        for b, v in banderas.items():
            if v:
                (self.falso / b).write_text("")

    def correr(self, script: str):
        return subprocess.run([BASH, f"scripts/{script}"], cwd=self.repo, env=self.env, capture_output=True, text=True, timeout=60)

    def llamadas(self) -> str:
        f = self.falso / "llamadas.log"
        return f.read_text() if f.exists() else ""

    def limpiar(self):
        self.tmp.cleanup()


class TestCompose(unittest.TestCase):
    def test_keycloak_tiene_un_volumen_para_sus_datos(self):
        c = yaml.safe_load((RAIZ / "docker-compose.yml").read_text(encoding="utf-8"))
        self.assertIn("keycloak-datos:/opt/keycloak/data/h2", c["services"]["keycloak"]["volumes"])
        self.assertIn("keycloak-datos", c["volumes"])

    def test_los_arranques_pasan_antes_por_el_script(self):
        for n in ("iniciar.sh", "arrancar.sh"):
            t = (RAIZ / "scripts" / n).read_text(encoding="utf-8")
            self.assertIn("keycloak_conservar.sh", t, n)
            self.assertLess(t.index("keycloak_conservar.sh"), t.index("up -d --build" if n == "iniciar.sh" else 'up -d --no-build "${SERVICIOS'), n)


@unittest.skipUnless(BASH, "sin bash")
class TestConservar(unittest.TestCase):
    def test_migra_sin_perder_nada_y_en_este_orden(self):
        e = Entorno(existe=True)
        try:
            r = e.correr("keycloak_conservar.sh")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            llamadas = e.llamadas().splitlines()
            orden = [next(i for i, l in enumerate(llamadas) if k in l) for k in ("compose stop keycloak", "cp viejo123:/opt/keycloak/data/h2/.", "--no-start keycloak", "compose up -d keycloak")]
            self.assertEqual(orden, sorted(orden))                                            # parar → copia → crear con volumen → arrancar
            self.assertTrue((e.falso / "cp.log").exists())                                    # se vuelcan los datos en el contenedor nuevo (con -a: conserva el propietario)
            copias = list((e.repo / "copias").glob("keycloak-*/h2/keycloakdb.mv.db"))
            self.assertEqual(len(copias), 1)                                                  # y queda una copia de seguridad en el disco
            self.assertIn("Listo", r.stdout)
        finally:
            e.limpiar()

    def test_si_ya_tiene_el_volumen_no_toca_nada(self):
        e = Entorno(existe=True, con_volumen=True)
        try:
            r = e.correr("keycloak_conservar.sh")
            self.assertEqual(r.returncode, 0)
            self.assertNotIn("compose stop", e.llamadas())
            self.assertIn("ya conserva", r.stdout)
        finally:
            e.limpiar()

    def test_sin_contenedor_no_hay_nada_que_conservar(self):
        e = Entorno()
        try:
            r = e.correr("keycloak_conservar.sh")
            self.assertEqual(r.returncode, 0)
            self.assertNotIn("compose stop", e.llamadas())
        finally:
            e.limpiar()

    def test_si_la_copia_falla_vuelve_a_arrancar_keycloak_y_no_lo_recrea(self):
        for bandera in ("falla_cp", "vacio"):
            e = Entorno(existe=True, **{bandera: True})
            try:
                r = e.correr("keycloak_conservar.sh")
                self.assertEqual(r.returncode, 1, bandera)
                llamadas = e.llamadas()
                self.assertIn("compose start keycloak", llamadas, bandera)                   # lo deja funcionando como estaba
                self.assertNotIn("--no-start", llamadas, bandera)                             # y no se ha recreado: no se pierde nada
                self.assertIn("No se ha podido completar", r.stderr)
            finally:
                e.limpiar()


@unittest.skipUnless(BASH, "sin bash")
class TestClaveAdmin(unittest.TestCase):
    def test_rota_la_clave_la_guarda_en_env_con_permisos_600_y_no_pasa_por_la_linea_de_comandos(self):
        e = Entorno(existe=True, con_volumen=True)
        try:
            r = e.correr("keycloak_clave_admin.sh")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            env = (e.repo / ".env").read_text()
            nueva = re.search(r"^KEYCLOAK_ADMIN_PASSWORD=(.+)$", env, re.M).group(1)
            self.assertNotEqual(nueva, "vieja")
            self.assertGreaterEqual(len(nueva), 24)
            self.assertIn("A=1", env)
            self.assertIn("B=2", env)                                                         # el resto del .env queda igual
            self.assertEqual(stat.S_IMODE((e.repo / ".env").stat().st_mode), 0o600)
            self.assertIn(nueva, r.stdout)                                                    # se enseña una vez en pantalla
            llamadas = (e.falso / "llamadas.log").read_text()
            self.assertNotIn(nueva, llamadas)                                                 # no va como argumento de ningún comando (se vería en `ps`)
            self.assertIn("-e NUEVA -e ACTUAL keycloak", llamadas)                              # van por el entorno
        finally:
            e.limpiar()

    def correr_con(self, e, entrada):
        return subprocess.run([BASH, "scripts/keycloak_clave_admin.sh"], cwd=e.repo, env=e.env, input=entrada, capture_output=True, text=True, timeout=60)

    def test_si_la_clave_del_env_no_sirve_pide_la_actual_sin_mostrarla_y_reintenta(self):
        e = Entorno(existe=True, con_volumen=True, clave_distinta=True)
        try:
            r = self.correr_con(e, "correcta\n")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("No ha servido la contraseña del .env", r.stderr)
            nueva = re.search(r"^KEYCLOAK_ADMIN_PASSWORD=(.+)$", (e.repo / ".env").read_text(), re.M).group(1)
            self.assertNotEqual(nueva, "vieja")
            llamadas = (e.falso / "llamadas.log").read_text()
            self.assertNotIn("correcta", llamadas)                                            # la actual tampoco va como argumento
            self.assertNotIn("correcta", r.stdout + r.stderr)                                 # ni se escribe por pantalla
            self.assertIn("-e NUEVA -e ACTUAL keycloak", llamadas)
        finally:
            e.limpiar()

    def test_si_tampoco_sirve_la_que_se_escribe_o_no_se_escribe_nada_no_cambia_el_env(self):
        for entrada in ("mala\n", ""):
            e = Entorno(existe=True, con_volumen=True, clave_distinta=True)
            try:
                r = self.correr_con(e, entrada)
                self.assertEqual(r.returncode, 1, entrada)
                self.assertIn("KEYCLOAK_ADMIN_PASSWORD=vieja", (e.repo / ".env").read_text())     # el .env no se toca
            finally:
                e.limpiar()

    def test_si_keycloak_no_conserva_sus_datos_se_niega(self):
        e = Entorno(existe=True)
        try:
            r = e.correr("keycloak_clave_admin.sh")
            self.assertEqual(r.returncode, 1)
            self.assertIn("keycloak_conservar.sh", r.stderr)
            self.assertIn("KEYCLOAK_ADMIN_PASSWORD=vieja", (e.repo / ".env").read_text())
        finally:
            e.limpiar()


if __name__ == "__main__":
    unittest.main()
