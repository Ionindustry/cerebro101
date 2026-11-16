"""La copia de seguridad automática (scripts/copia_automatica.sh): comprueba lo que copia, rota las antiguas, deja el estado y avisa a soporte@ si falla. El script de copia real y el aviso se sustituyen."""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import _sin_servicios  # noqa: F401

RAIZ = Path(__file__).resolve().parents[2]
SCRIPT = RAIZ / "scripts" / "copia_automatica.sh"

COPIA_BUENA = """#!/usr/bin/env bash
mkdir -p "$1"; cd "$1"
echo "-- dump" | gzip > cerebro.sql.gz; echo "-- dump" | gzip > langfuse.sql.gz
sha256sum *.gz > SHA256SUMS
"""
COPIA_SIN_CEREBRO = COPIA_BUENA.replace("cerebro.sql.gz; ", "otra.sql.gz; ")
COPIA_ROTA = COPIA_BUENA + 'echo "no es un gzip" > cerebro.sql.gz\n'
COPIA_QUE_FALLA = "#!/usr/bin/env bash\necho 'pg_dump: error de conexion' >&2\nexit 3\n"


@unittest.skipUnless(os.name == "posix", "script de bash")
class TestCopiaAutomatica(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.avisos = self.dir / "avisos.txt"
        self.aviso_cmd = self.dir / "avisar.sh"
        self.aviso_cmd.write_text(f'#!/usr/bin/env bash\necho "$1 | $2" >> "{self.avisos}"\n')
        self.aviso_cmd.chmod(0o755)

    def tearDown(self):
        self.tmp.cleanup()

    def ejecutar(self, copia: str, conservar: int = 7, extra: str = "", previas: int = 0, config: str = "", conservar_extra: int = 0, previas_extra: int = 0, entorno: dict | None = None):
        cmd = self.dir / "copia.sh"
        cmd.write_text(copia)
        cmd.chmod(0o755)
        base = self.dir / "auto"
        for i in range(previas):
            (base / f"2026-10-{10 + i:02d}_0300").mkdir(parents=True)
            (base / f"2026-10-{10 + i:02d}_0300" / "x").write_text("x")
        (base / "otra-cosa").mkdir(parents=True, exist_ok=True)          # nada que no sea una copia se borra
        reg = self.dir / "registrar.sh"
        reg.write_text(f'#!/usr/bin/env bash\necho "$@" >> "{self.dir / "registro.txt"}"\n')
        reg.chmod(0o755)
        cfg = self.dir / "config.sh"
        cfg.write_text(f"#!/usr/bin/env bash\ncat <<'FIN'\n{config}FIN\n")                # lo que diría «python -m cerebro.copias config»: lo fijado en Jarvis
        cfg.chmod(0o755)
        for i in range(previas_extra):
            (Path(extra) / f"2026-09-{10 + i:02d}_0300").mkdir(parents=True, exist_ok=True)
            (Path(extra) / f"2026-09-{10 + i:02d}_0300" / "x").write_text("x")
        env = {**os.environ, "COPIA_CONFIG": str(cfg), "COPIA_CONSERVAR_EXTRA": str(conservar_extra), "COPIA_REGISTRAR": str(reg), "COPIA_BASE": str(base), "COPIA_COMANDO": str(cmd), "COPIA_AVISAR": str(self.aviso_cmd), "COPIA_CONSERVAR": str(conservar), "COPIA_EXTRA": extra, **(entorno or {})}
        r = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=60)
        estado = json.loads((self.dir / "estado.json").read_text())
        return r, estado, base

    def test_copia_buena_deja_estado_ok_y_no_avisa(self):
        r, estado, base = self.ejecutar(COPIA_BUENA)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(estado["ok"])
        self.assertGreater(estado["bytes"], 0)
        self.assertFalse(self.avisos.exists())
        anotado = (self.dir / "registro.txt").read_text()
        self.assertIn("true", anotado)                                                     # lo anota para la tarjeta de Jarvis
        self.assertRegex(anotado, r"copia correcta \d+")

    def test_rota_las_antiguas_y_solo_las_que_son_copias(self):
        r, estado, base = self.ejecutar(COPIA_BUENA, conservar=3, previas=5)
        self.assertEqual(r.returncode, 0, r.stderr)
        carpetas = sorted(p.name for p in base.iterdir())
        self.assertIn("otra-cosa", carpetas)
        copias = [c for c in carpetas if c != "otra-cosa"]
        self.assertEqual(len(copias), 3)
        self.assertEqual(copias[:2], ["2026-10-13_0300", "2026-10-14_0300"])          # se quedan las más nuevas
        self.assertNotIn("2026-10-10_0300", copias)

    def test_lo_fijado_en_jarvis_manda_sobre_el_entorno(self):
        r, estado, base = self.ejecutar(COPIA_BUENA, conservar=7, previas=5, config="conservar=2\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len([c for c in base.iterdir() if c.name != "otra-cosa"]), 2)

    def test_un_ajuste_con_mala_forma_se_ignora(self):
        r, _estado, base = self.ejecutar(COPIA_BUENA, conservar=4, previas=5, config="conservar=0\nconservar=abc\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len([c for c in base.iterdir() if c.name != "otra-cosa"]), 4)         # se queda el del entorno

    def test_una_ruta_extra_rara_de_jarvis_no_se_usa(self):
        extra = self.dir / "otro-disco"
        r, _e, _b = self.ejecutar(COPIA_BUENA, extra=str(extra), config="extra=/etc/cron.d\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(any(extra.iterdir()))                                                  # sigue copiando donde decía el entorno, no en /etc

    def test_extra_vacio_en_jarvis_desactiva_la_segunda_copia(self):
        extra = self.dir / "otro-disco"
        r, _e, _b = self.ejecutar(COPIA_BUENA, extra=str(extra), config="extra=\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(extra.exists())

    def test_la_segunda_ubicacion_conserva_solo_las_ultimas_si_se_pide(self):
        extra = self.dir / "otro-disco"
        r, _e, _b = self.ejecutar(COPIA_BUENA, extra=str(extra), previas_extra=4, conservar_extra=2)
        self.assertEqual(r.returncode, 0, r.stderr)
        nombres = sorted(p.name for p in extra.iterdir())
        self.assertEqual(len(nombres), 2)
        self.assertNotIn("2026-09-10_0300", nombres)
        r, _e, _b = self.ejecutar(COPIA_BUENA, extra=str(extra), previas_extra=0, conservar_extra=0)       # 0 = no se borra nada
        self.assertGreaterEqual(len(list(extra.iterdir())), 2)

    def test_si_el_script_de_copia_falla_avisa_y_sale_con_error(self):
        r, estado, _ = self.ejecutar(COPIA_QUE_FALLA)
        self.assertEqual(r.returncode, 1)
        self.assertFalse(estado["ok"])
        self.assertIn("error", estado["mensaje"])
        self.assertIn("Copia de seguridad fallida", self.avisos.read_text())
        self.assertTrue((self.dir / "registro.txt").read_text().startswith("false"))       # el fallo también se anota

    def test_una_copia_dañada_o_incompleta_se_detecta(self):
        for copia, texto in ((COPIA_ROTA, "dañado"), (COPIA_SIN_CEREBRO, "falta cerebro.sql.gz")):
            self.avisos.unlink(missing_ok=True)
            r, estado, _ = self.ejecutar(copia)
            self.assertEqual(r.returncode, 1, texto)
            self.assertIn(texto, estado["mensaje"])
            self.assertTrue(self.avisos.exists())

    def test_segunda_copia_en_otra_carpeta_y_aviso_si_no_se_puede(self):
        extra = self.dir / "otro_disco"
        r, _, base = self.ejecutar(COPIA_BUENA, extra=str(extra))
        self.assertEqual(r.returncode, 0, r.stderr)
        copiada = list(extra.iterdir())
        self.assertEqual(len(copiada), 1)
        self.assertTrue((copiada[0] / "cerebro.sql.gz").is_file())
        (self.dir / "bloqueado").write_text("no es una carpeta")
        r, estado, _ = self.ejecutar(COPIA_BUENA, extra=str(self.dir / "bloqueado" / "dentro"))
        self.assertEqual(r.returncode, 1)
        self.assertIn("segunda copia", estado["mensaje"])


class TestAvisarSoporte(unittest.TestCase):
    def test_envia_a_los_destinatarios_configurados_con_asunto_recortado(self):
        from cerebro import avisar_soporte as A
        enviados = []
        cfg = {"vigilante": {"destinatarios": ["soporte@101.cat"]}}
        import unittest.mock as mock
        with mock.patch.object(A.vigilante, "_enviar_a", lambda d, a, c, e: (enviados.append((d, a, c)), (len(d), 0))[1]):
            ok, mal = A.avisar("  Copia   fallida \n", "Cuerpo", cfg=cfg)
        self.assertEqual((ok, mal), (1, 0))
        self.assertEqual(enviados[0][0], ["soporte@101.cat"])
        self.assertEqual(enviados[0][1], "Copia fallida")
        self.assertIn("Mensaje automático", enviados[0][2])
        self.assertEqual(A.avisar("x", "y", cfg={"vigilante": {"destinatarios": []}}), (0, 0))
        self.assertEqual(A.main([]), 2)


if __name__ == "__main__":
    unittest.main()

RESTIC_FALSO = """#!/usr/bin/env bash
echo "$@" >> "{registro}"
case "$1" in
  cat) [ -f "{marca}" ] || exit 1 ;;
  init) touch "{marca}" ;;
  backup) {backup} ;;
esac
exit 0
"""


@unittest.skipUnless(os.name == "posix", "script de bash")
class TestCopiaIncremental(TestCopiaAutomatica):
    def restic(self, backup: str = "true", clave: bool = True, repo: str | None = None, sin_validar: bool = True):
        reg = self.dir / "restic.txt"
        falso = self.dir / "restic.sh"
        falso.write_text(RESTIC_FALSO.format(registro=reg, marca=self.dir / "repo_creado", backup=backup))
        falso.chmod(0o755)
        k = self.dir / "clave.txt"
        if clave:
            k.write_text("contrasena-de-prueba\n")
        # la ruta del repositorio de verdad solo admite /mnt/x, /media, /srv y /home/usuario: en las pruebas se salta esa comprobación (COPIA_RESTIC_SIN_VALIDAR) y se usa una carpeta temporal
        env = {"COPIA_RESTIC": str(falso), "COPIA_RESTIC_REPO": repo or str(self.dir / "restic"), "COPIA_RESTIC_CLAVE": str(k)}
        if sin_validar:
            env["COPIA_RESTIC_SIN_VALIDAR"] = "1"
        return env

    def test_sin_configurar_no_se_llama_a_restic(self):
        r, estado, _ = self.ejecutar(COPIA_BUENA)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse((self.dir / "restic.txt").exists())

    def test_incremental_crea_el_repositorio_copia_y_limpia(self):
        env = self.restic()
        r, estado, _ = self.ejecutar(COPIA_BUENA, entorno=env)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertTrue(estado["ok"])
        ordenes = (self.dir / "restic.txt").read_text().splitlines()
        self.assertEqual([o.split()[0] for o in ordenes], ["cat", "init", "backup", "forget"])
        self.assertIn("--keep-daily 7 --keep-weekly 8 --keep-monthly 12 --prune", ordenes[-1])
        self.assertIn("--tag cerebro", ordenes[2])

    def test_si_el_repositorio_ya_existe_no_lo_vuelve_a_crear(self):
        env = self.restic()
        (self.dir / "repo_creado").write_text("")
        r, _, _ = self.ejecutar(COPIA_BUENA, entorno=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([o.split()[0] for o in (self.dir / "restic.txt").read_text().splitlines()], ["cat", "backup", "forget"])

    def test_si_restic_falla_la_copia_falla_y_avisa(self):
        env = self.restic(backup="echo disco lleno >&2; exit 1")
        r, estado, _ = self.ejecutar(COPIA_BUENA, entorno=env)
        self.assertEqual(r.returncode, 1)
        self.assertFalse(estado["ok"])
        self.assertIn("restic no ha podido", estado["mensaje"])
        self.assertTrue(self.avisos.exists())

    def test_sin_fichero_de_contrasena_no_se_hace_y_se_dice(self):
        env = self.restic(clave=False)
        r, estado, _ = self.ejecutar(COPIA_BUENA, entorno=env)
        self.assertEqual(r.returncode, 1)
        self.assertIn("contraseña del repositorio", estado["mensaje"])

    def test_el_repositorio_tiene_que_ser_una_carpeta_local_razonable(self):
        for malo in ("sftp:usuario@host:/copias", "/etc/restic", "/mnt/d/../etc"):
            env = self.restic(repo=malo, sin_validar=False)
            r, estado, _ = self.ejecutar(COPIA_BUENA, entorno=env)
            self.assertEqual(r.returncode, 1, malo)
            self.assertIn("carpeta local", estado["mensaje"], malo)


# la clase hija repite los tests de la madre; se quitan para no ejecutarlos dos veces
for _n in [n for n in dir(TestCopiaIncremental) if n.startswith("test_") and n not in TestCopiaIncremental.__dict__]:
    setattr(TestCopiaIncremental, _n, None)

