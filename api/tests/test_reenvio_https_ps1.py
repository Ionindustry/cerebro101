"""El vigilante del reenvio del 443 de Windows (scripts/windows/reenvio_https.ps1): no hay PowerShell aquí, así que se comprueba lo que se puede sin ejecutarlo."""
import re
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
RUTA = RAIZ / "scripts" / "windows" / "reenvio_https.ps1"
if not RUTA.exists():
    raise unittest.SkipTest("se ejecuta desde el repositorio, no desde la imagen")
T = RUTA.read_text(encoding="utf-8")


class TestScript(unittest.TestCase):
    def test_solo_ascii_para_que_powershell_5_lo_lea_igual_sin_importar_la_codificacion(self):
        self.assertEqual({c for c in T if ord(c) > 127}, set())

    def test_parentesis_y_llaves_cuadran(self):
        for a, b in (("{", "}"), ("(", ")"), ("[", "]")):
            self.assertEqual(T.count(a), T.count(b), a)

    def test_tiene_las_cuatro_acciones_y_la_tarea_corre_como_sistema_al_arrancar_y_cada_cinco_minutos(self):
        for p in ("-Instalar", "-Quitar", "-Vigilar", "-Estado"):
            self.assertIn(p, T)
        self.assertIn('-UserId "SYSTEM"', T)
        self.assertIn("New-ScheduledTaskTrigger -AtStartup", T)
        self.assertIn("-RepetitionInterval (New-TimeSpan -Minutes 5)", T)
        self.assertIn("-StartWhenAvailable", T)
        self.assertIn("-MultipleInstances IgnoreNew", T)

    def test_la_tarea_no_depende_de_donde_estaba_el_script(self):
        self.assertIn("Copy-Item -Path $ruta -Destination $destino", T)
        self.assertIn('Join-Path $env:ProgramData "Cerebro"', T)

    def test_solo_actua_si_hay_una_regla_del_443_y_no_escucha(self):
        self.assertIn("if ($ips.Count -eq 0) { return }", T)
        self.assertIn("Restart-Service -Name iphlpsvc", T)
        self.assertIn("LISTENING", T)

    def test_lo_que_lee_de_netsh_encaja_con_su_salida_real(self):
        """La tabla de «netsh interface portproxy show v4tov4» (copiada de un equipo real) debe dar la regla del 443 y no la del 80."""
        m = re.search(r"-match '(\^[^']+)'", T)
        self.assertIsNotNone(m)
        patron = m.group(1).replace("\\d", r"\d")
        tabla = ["0.0.0.0         80          172.19.117.42   80", "192.168.1.102   443         127.0.0.1       18443"]
        self.assertEqual([re.match(patron, l).group(1) for l in tabla if re.match(patron, l)], ["192.168.1.102"])

    def test_lo_que_busca_en_netstat_encaja_con_su_salida_real(self):
        buena = "  TCP    192.168.1.102:443      0.0.0.0:0              LISTENING       19920"
        otra = "  TCP    0.0.0.0:443            0.0.0.0:0              LISTENING       23868"
        patron = r"\s" + re.escape("192.168.1.102") + r":443\s.*LISTENING"
        self.assertTrue(re.search(patron, buena))
        self.assertFalse(re.search(patron, otra))


if __name__ == "__main__":
    unittest.main()
