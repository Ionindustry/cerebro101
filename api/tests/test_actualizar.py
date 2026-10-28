"""scripts/actualizar.sh: descargar las imágenes de GitHub o construirlas, con reintentos, sin tocar Docker de verdad (docker es un doble)."""
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
SCRIPT = RAIZ / "scripts" / "actualizar.sh"
if not SCRIPT.exists():             # dentro de la imagen de la API no está la carpeta scripts del repositorio
    raise unittest.SkipTest("se ejecuta desde el repositorio, no desde la imagen")

DOCKER_FALSO = """#!/bin/sh
echo "$*" >> "$REGISTRO"
case " $* " in
  *" pull "*)
    n=$(cat "$FALLOS" 2>/dev/null || echo 0)
    if [ "$n" -gt 0 ]; then echo $((n - 1)) > "$FALLOS"; echo "fallo de descarga simulado" >&2; exit 1; fi ;;
esac
exit 0
"""


class TestActualizar(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        (self.tmp / "scripts").mkdir()
        shutil.copy(SCRIPT, self.tmp / "scripts" / "actualizar.sh")
        (self.tmp / "bin").mkdir()
        d = self.tmp / "bin" / "docker"
        d.write_text(DOCKER_FALSO)
        d.chmod(d.stat().st_mode | stat.S_IEXEC)
        self.registro, self.fallos = self.tmp / "registro.txt", self.tmp / "fallos.txt"

    def correr(self, env_texto=None, fallos=0, args=("--sin-git",)):
        if env_texto is not None:
            (self.tmp / ".env").write_text(env_texto)
        self.fallos.write_text(str(fallos))
        entorno = {**os.environ, "PATH": f"{self.tmp / 'bin'}:{os.environ['PATH']}", "REGISTRO": str(self.registro), "FALLOS": str(self.fallos),
                   "ESPERA_REINTENTO": "0"}
        r = subprocess.run(["bash", str(self.tmp / "scripts" / "actualizar.sh"), *args], capture_output=True, text=True, env=entorno, cwd=self.tmp)
        lineas = self.registro.read_text().splitlines() if self.registro.exists() else []
        return r, lineas

    def test_sin_imagenes_en_el_env_construye_aqui_como_siempre(self):
        r, l = self.correr("CEREBRO_MODO=produccion\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse([x for x in l if " pull " in f" {x} "])
        construidos = [x for x in l if "up -d --build" in x]
        self.assertEqual(len(construidos), 3)
        self.assertIn("api ingestor proyector", construidos[0])                       # primero el motor
        self.assertIn("migraciones api worker beat licitaciones-eventos", construidos[1])
        self.assertIn("--profile licitaciones", construidos[1])
        self.assertTrue(construidos[2].endswith("up -d --build panel"))

    def test_con_las_tres_imagenes_descarga_y_no_construye(self):
        r, l = self.correr('LIC_IMAGEN=ghcr.io/x/cerebro101-licitaciones:main\nCEREBRO_IMAGEN_API="ghcr.io/x/cerebro101-api:main"   # de GitHub\n'
                           "CEREBRO_IMAGEN_PANEL=ghcr.io/x/cerebro101-panel:main\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([x for x in l if "--build" in x], [])                         # este PC no construye nada
        descargas = [x for x in l if x.endswith(" pull api") or x.endswith(" pull migraciones") or x.endswith(" pull panel")]
        self.assertEqual(len(descargas), 3, l)
        self.assertEqual(len([x for x in l if "up -d --no-build" in x]), 3)
        self.assertIn("ghcr.io/x/cerebro101-api:main", r.stdout)                       # sin comillas ni el comentario del final
        self.assertNotIn("# de GitHub", r.stdout)

    def test_mezcla_descarga_lo_que_tiene_imagen_y_construye_el_resto(self):
        r, l = self.correr("LIC_IMAGEN=ghcr.io/x/cerebro101-licitaciones:main\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len([x for x in l if " pull " in f" {x} "]), 1)
        self.assertEqual(len([x for x in l if "up -d --build" in x]), 2)               # el Cerebro y el panel, aquí

    def test_la_descarga_se_reintenta_y_si_no_hay_manera_no_arranca_nada(self):
        env = "LIC_IMAGEN=ghcr.io/x/cerebro101-licitaciones:main\n"
        r, l = self.correr(env, fallos=2)
        self.assertEqual(r.returncode, 0, r.stderr)                                    # a la tercera sale bien
        self.assertEqual(len([x for x in l if " pull " in f" {x} "]), 3)
        r, l = self.correr(env, fallos=9)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("docker login ghcr.io", r.stderr)
        self.assertEqual([x for x in l[-5:] if " up " in f" {x} "], [])                # tras el fallo no se levanta nada con una imagen vieja

    def test_avisa_si_no_hay_copia_reciente_y_rechaza_argumentos_desconocidos(self):
        (self.tmp / "copias").mkdir()
        r, _ = self.correr("")
        self.assertIn("ninguna copia de seguridad", r.stdout)
        (self.tmp / "copias" / "2026-10-28_1200").mkdir()
        r, _ = self.correr("")
        self.assertNotIn("ninguna copia de seguridad", r.stdout)
        r, _ = self.correr("", args=("--rapido",))
        self.assertEqual(r.returncode, 2)

    def test_sin_env_tampoco_rompe(self):
        r, l = self.correr(None)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len([x for x in l if "up -d --build" in x]), 3)


if __name__ == "__main__":
    unittest.main()
