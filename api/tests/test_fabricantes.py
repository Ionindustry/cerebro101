"""Directorio de fabricantes y autorización de dominios de fichas: qué es comprobado, qué no, y que el script nunca autorice a ciegas."""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _sin_servicios  # noqa: F401

try:
    from cerebro.licitaciones import fabricantes as F
except ImportError as e:      # pragma: no cover
    raise unittest.SkipTest(str(e))

RAIZ = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("fichas_autorizar", RAIZ / "scripts" / "fichas_autorizar.py")
S = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(S)

FILAS = ({"fabricante": "2N", "marcas": "", "especialidad": "Videoporteros", "dominios": ["2n.com"], "comprobado": True, "estado": "x", "acceso": "PUBLICO_INDICE", "login_area_documental": "NO_CONFIRMADO"},
         {"fabricante": "Axis", "marcas": "", "especialidad": "Cámaras", "dominios": ["axis.com"], "comprobado": True, "estado": "x", "acceso": "MIXTO_SEGUN_DOCUMENTO", "login_area_documental": "PARCIAL"},
         {"fabricante": "Milesight", "marcas": "", "especialidad": "Cámaras", "dominios": ["milesight.com"], "comprobado": False, "estado": "pend", "acceso": "NO_VERIFICADO", "login_area_documental": "NO_CONFIRMADO"})


class TestDirectorio(unittest.TestCase):
    def test_dominio_de_normaliza_y_rechaza_lo_raro(self):
        self.assertEqual(F.dominio_de("https://www.2N.com/es/x?y=1"), "2n.com")
        self.assertEqual(F.dominio_de("docs.axis.com"), "docs.axis.com")
        for malo in ("", "localhost", "10.0.0.1", "javascript:alert(1)", "a b.com", None):
            self.assertEqual(F.dominio_de(malo), "", str(malo))

    def test_un_dominio_o_su_subdominio_se_asocian_al_fabricante(self):
        self.assertEqual(F.por_dominio("cdn.2n.com", FILAS)["fabricante"], "2N")
        self.assertIsNone(F.por_dominio("falso2n.com", FILAS))                              # otro dominio que solo termina parecido
        self.assertIsNone(F.por_dominio("malo.com", FILAS))

    def test_la_sugerencia_distingue_comprobado_propuesto_y_desconocido(self):
        a = F.sugerencia("2n.com", 3, FILAS)
        self.assertTrue(a["comprobado"])
        self.assertIn("comprobado", a["recomendacion"])
        m = F.sugerencia("milesight.com", 1, FILAS)
        self.assertFalse(m["comprobado"])
        self.assertIn("NO comprobado", m["recomendacion"])
        x = F.sugerencia("axis.com", 1, FILAS)
        self.assertIn("restricciones", x["recomendacion"])                                  # documentación mixta: se avisa
        d = F.sugerencia("malo.com", 2, FILAS)
        self.assertFalse(d["conocido"])

    def test_los_comprobados_no_incluyen_los_propuestos(self):
        self.assertEqual(F.dominios_comprobados(FILAS), ["2n.com", "axis.com"])

    def test_el_directorio_real_se_lee_y_tiene_comprobados_y_pendientes(self):
        filas = F.directorio()
        self.assertGreater(len(filas), 300)
        self.assertTrue(any(f["comprobado"] for f in filas) and any(not f["comprobado"] for f in filas))
        self.assertEqual(F.por_dominio("www.milesight.com")["fabricante"], "Milesight")
        self.assertFalse(F.por_dominio("milesight.com")["comprobado"])


class TestScript(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.f = Path(self.d.name) / "fichas.yaml"
        self.f.write_text("# comentario\nhosts: []\nmax_mb: 30\n", encoding="utf-8")
        self.p = [mock.patch.object(S, "FICHERO", self.f), mock.patch.object(S, "leer_directorio", lambda ruta=None: [
            {"fabricante": f["fabricante"], "dominios": f["dominios"], "comprobado": f["comprobado"], "acceso": f["acceso"], "login": f["login_area_documental"]} for f in FILAS])]
        for p in self.p:
            p.start()

    def tearDown(self):
        for p in self.p:
            p.stop()
        self.d.cleanup()

    def hosts(self):
        return S.hosts_actuales(self.f.read_text(encoding="utf-8"))

    def test_anade_comprobados_y_conserva_el_resto_del_fichero(self):
        self.assertEqual(S.main(["2n.com"]), 0)
        self.assertEqual(self.hosts(), ["2n.com"])
        t = self.f.read_text(encoding="utf-8")
        self.assertIn("# comentario", t)
        self.assertIn("max_mb: 30", t)

    def test_no_autoriza_a_ciegas_lo_no_comprobado_ni_lo_desconocido(self):
        self.assertEqual(S.main(["milesight.com", "malo.com"]), 1)
        self.assertEqual(self.hosts(), [])
        self.assertEqual(S.main(["milesight.com", "--forzar"]), 0)
        self.assertEqual(self.hosts(), ["milesight.com"])

    def test_un_dominio_invalido_se_rechaza_entero_sin_tocar_nada(self):
        self.assertEqual(S.main(["2n.com", "no es un dominio"]), 2)
        self.assertEqual(self.hosts(), [])

    def test_comprobados_anade_solo_los_comprobados_y_es_idempotente(self):
        self.assertEqual(S.main(["--comprobados"]), 0)
        self.assertEqual(self.hosts(), ["2n.com", "axis.com"])
        self.assertEqual(S.main(["--comprobados"]), 0)
        self.assertEqual(self.hosts(), ["2n.com", "axis.com"])

    def test_quitar_y_listar(self):
        S.main(["2n.com", "axis.com"])
        self.assertEqual(S.main(["2n.com", "--quitar"]), 0)
        self.assertEqual(self.hosts(), ["axis.com"])
        self.assertEqual(S.main(["--listar"]), 0)

    def test_si_el_formato_no_es_el_esperado_no_toca_nada(self):
        self.f.write_text("hosts:\n  - a.com\n", encoding="utf-8")
        with self.assertRaises(SystemExit):
            S.main(["2n.com"])
        self.assertEqual(self.f.read_text(encoding="utf-8"), "hosts:\n  - a.com\n")

    def test_el_fichero_de_configuracion_real_lo_entiende_el_script(self):
        t = (RAIZ / "config" / "fichas.yaml").read_text(encoding="utf-8")
        hosts = S.hosts_actuales(t)                                                        # los que Dirección haya autorizado
        self.assertEqual(hosts, sorted(set(hosts)))
        self.assertTrue(all("." in h and "/" not in h for h in hosts))


class TestRankingFabricantes(unittest.TestCase):
    FILAS = (
        {"sector": "Vídeo", "posicion": 1, "fabricante": "A", "web": "https://www.a.com", "dominio": "a.com", "ventas_musd": None, "otros_ingresos": "", "empleados": "", "nota": "", "fuentes": [], "sin_validar": True},
        {"sector": "Vídeo", "posicion": 2, "fabricante": "B", "web": "https://b.com", "dominio": "b.com", "ventas_musd": 50.0, "otros_ingresos": "", "empleados": "", "nota": "", "fuentes": [], "sin_validar": False},
        {"sector": "Vídeo", "posicion": 3, "fabricante": "C", "web": "https://c.com", "dominio": "c.com", "ventas_musd": 500.0, "otros_ingresos": "", "empleados": "", "nota": "", "fuentes": [], "sin_validar": False},
        {"sector": "Acceso", "posicion": 1, "fabricante": "D", "web": "https://d.com", "dominio": "d.com", "ventas_musd": 1.0, "otros_ingresos": "", "empleados": "", "nota": "", "fuentes": [], "sin_validar": False},
    )
    DIR = ({"fabricante": "B", "marcas": "", "especialidad": "", "dominios": ["b.com"], "comprobado": True, "estado": "", "acceso": "", "login_area_documental": ""},)

    def test_orden_de_seleccion_y_por_ventas(self):
        r = F.top_por_sector("Vídeo", "seleccion", self.FILAS, self.DIR)
        self.assertEqual([f["fabricante"] for f in r["sectores"][0]["fabricantes"]], ["A", "B", "C"])
        r = F.top_por_sector("Vídeo", "ventas", self.FILAS, self.DIR)
        self.assertEqual([f["fabricante"] for f in r["sectores"][0]["fabricantes"]], ["C", "B", "A"])   # sin dato, al final
        self.assertEqual(r["sectores"][0]["con_ventas"], 2)

    def test_directorio_y_todos_los_sectores(self):
        r = F.top_por_sector("", "seleccion", self.FILAS, self.DIR)
        self.assertEqual([s["sector"] for s in r["sectores"]], ["Vídeo", "Acceso"])
        b = r["sectores"][0]["fabricantes"][1]
        self.assertTrue(b["en_directorio"] and b["comprobado"])
        self.assertFalse(r["sectores"][0]["fabricantes"][0]["en_directorio"])

    def test_errores(self):
        with self.assertRaises(ValueError):
            F.top_por_sector("Inventado", "seleccion", self.FILAS, self.DIR)
        with self.assertRaises(ValueError):
            F.top_por_sector("", "raro", self.FILAS, self.DIR)

    def test_el_fichero_real(self):
        r = F.top_por_sector()
        self.assertEqual(len(r["sectores"]), 10)
        self.assertTrue(all(len(s["fabricantes"]) == 10 for s in r["sectores"]))
        hik = next(f for s in r["sectores"] for f in s["fabricantes"] if f["fabricante"] == "Hikvision")
        self.assertEqual(hik["ventas_musd"], 12976.6)
        self.assertIn("no el ranking mundial exacto", r["aviso"])
        tp = next(f for s in r["sectores"] for f in s["fabricantes"] if f["fabricante"] == "TP-Link")
        self.assertIsNone(tp["ventas_musd"])                        # N/D es «no verificado», no cero


if __name__ == "__main__":
    unittest.main()
