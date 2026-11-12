"""El vigilante de autoarranque de Windows (scripts/windows/autoarranque.ps1): no hay PowerShell aquí, así que se comprueba lo que se puede sin ejecutarlo."""
import re
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
RUTA = RAIZ / "scripts" / "windows" / "autoarranque.ps1"
if not RUTA.exists():
    raise unittest.SkipTest("se ejecuta desde el repositorio, no desde la imagen")
T = RUTA.read_text(encoding="utf-8-sig")
ESQUEMA = (RAIZ / "db" / "esquema.sql").read_text(encoding="utf-8")


class TestScript(unittest.TestCase):
    def test_solo_ascii_y_parentesis_cuadran(self):
        self.assertEqual({c for c in T if ord(c) > 127}, set())
        for a, b in (("{", "}"), ("(", ")"), ("[", "]")):
            self.assertEqual(T.count(a), T.count(b), a)

    def test_reinicia_docker_desktop_si_los_puertos_no_responden_pero_no_con_trabajos_en_curso(self):
        self.assertIn("function Backend-Viejo", T)
        self.assertIn("function Trabajos-En-Curso", T)
        i = T.index("Trabajos-En-Curso\n          $hace1h") if "Trabajos-En-Curso\n          $hace1h" in T else T.index("$trabajos = Trabajos-En-Curso")
        resto = T[i:]
        self.assertLess(resto.index("-gt 0"), resto.index("Recuperar-Docker"))                 # primero comprueba el trabajo en curso, después reinicia
        self.assertIn("no reinicio Docker Desktop hasta que terminen", T)

    def test_con_tope_de_dos_reinicios_por_hora_y_avisa_si_no_basta(self):
        self.assertIn("$recientes.Count -ge 2", T)
        self.assertIn("REQUIERE ATENCION", T)

    def test_el_backend_viejo_acelera_el_reinicio_pero_no_lo_provoca_solo(self):
        """Un backend más viejo que wslrelay, sin que fallen los puertos, no reinicia nada: solo cuenta cuando ya fallan."""
        self.assertIn("($e.puertos -ge 3) -or ($viejo -and $e.puertos -ge 2)", T)
        self.assertIn('Get-Process -Name "com.docker.backend"', T)
        self.assertIn('Get-Process -Name "wslrelay"', T)
        self.assertIn("-gt 2)", T)                                                                # margen de 2 minutos entre los dos arranques

    def test_la_consulta_de_trabajos_usa_tablas_que_existen_y_va_entrecomillada(self):
        m = re.search(r'\$consulta = "([^"]+)"', T)
        self.assertIsNotNone(m)
        for tabla in re.findall(r"FROM (\w+)", m.group(1)):
            self.assertIn(f"CREATE TABLE IF NOT EXISTS {tabla} (", ESQUEMA, tabla)
        self.assertIn("'\"' + $consulta + '\"'", T)                                              # sin comillas, Start-Process parte la consulta en palabras
        self.assertIn("estado = 'en_curso'", m.group(1))

    def test_lo_que_lee_de_psql_encaja_con_su_salida(self):
        m = re.search(r"\[regex\]::Match\(\$texto, '([^']+)'\)", T)
        self.assertIsNotNone(m)
        p = m.group(1).replace("\\\\", "\\")
        for texto, valor in (("0\n", "0"), (" 2 \r\n", "2")):
            r = re.match(p, texto)
            self.assertIsNotNone(r, repr(texto))
            self.assertEqual(r.group(1), valor)
        for malo in ("", "ERROR: no existe\n", "0\n1\n"):
            self.assertIsNone(re.match(p, malo), repr(malo))

    def test_docker_con_tiempo_maximo_para_no_colgarse(self):
        self.assertIn("WaitForExit($Segundos * 1000)", T)

    def test_el_estado_trae_el_contador_de_puertos(self):
        self.assertIn("puertos = 0", T)


if __name__ == "__main__":
    unittest.main()
