"""Tipo de cambio en línea (cerebro/cambio.py): lectura del XML del BCE, guardado y uso en los precios. El XML es sintético, con la misma estructura que el real."""
import asyncio
import os
import time
import unittest
from datetime import date
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import _sin_servicios  # noqa: F401
import httpx
import psycopg

from cerebro import cambio as C
from cerebro import precios as P

URL = os.environ.get("CEREBRO_TEST_PG")
ESQUEMA = Path(__file__).resolve().parents[2] / "db" / "esquema.sql"

XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01" xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
  <gesmes:subject>Reference rates</gesmes:subject>
  <gesmes:Sender><gesmes:name>European Central Bank</gesmes:name></gesmes:Sender>
  <Cube><Cube time="2026-11-06">
    <Cube currency="USD" rate="1.0800"/><Cube currency="GBP" rate="0.8600"/><Cube currency="JPY" rate="160.00"/><Cube currency="XXX" rate="0"/><Cube currency="MAL" rate="abc"/>
  </Cube></Cube>
</gesmes:Envelope>"""


def ejecutar(c):
    return asyncio.run(c)


class TestParsear(unittest.TestCase):
    def test_el_bce_da_unidades_por_euro_y_se_guarda_euros_por_unidad(self):
        fecha, t = C.parsear(XML)
        self.assertEqual(fecha, date(2026, 11, 6))
        self.assertEqual(t["USD"], D("0.92592593"))                 # 1 ÷ 1,08
        self.assertEqual(t["GBP"], (1 / D("0.86")).quantize(D("0.00000001")))
        self.assertEqual(t["JPY"], D("0.00625000"))
        self.assertNotIn("XXX", t)                                    # tipo cero: descartado
        self.assertNotIn("MAL", t)                                    # no numérico: descartado

    def test_un_xml_malo_es_un_error_no_un_dato_inventado(self):
        for malo in (b"", b"no es xml", b"<a><b/></a>", b'<?xml version="1.0"?><Cube><Cube time="no-fecha"><Cube currency="USD" rate="1.1"/></Cube></Cube>',
                     b'<Cube><Cube time="2026-11-06"/></Cube>'):
            with self.assertRaises(C.ErrorCambio, msg=malo):
                C.parsear(malo)

    def test_entidades_externas_y_bombas_xml_se_rechazan(self):
        xxe = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><Cube><Cube time="2026-11-06"><Cube currency="USD" rate="&e;"/></Cube></Cube>'
        with self.assertRaises(C.ErrorCambio):
            C.parsear(xxe)
        bomba = b'<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;&a;">]><Cube><Cube time="2026-11-06"><Cube currency="USD" rate="1.1">&b;</Cube></Cube></Cube>'
        with self.assertRaises(C.ErrorCambio):
            C.parsear(bomba)


class TestBajar(unittest.TestCase):
    def test_baja_de_la_direccion_fija_con_agente_honesto(self):
        visto = []

        def manejar(req):
            visto.append((str(req.url), req.headers["user-agent"]))
            return httpx.Response(200, content=XML)
        r = ejecutar(C.bajar(httpx.MockTransport(manejar)))
        self.assertEqual(r, XML)
        self.assertEqual(visto[0][0], C.URL_BCE)
        self.assertTrue(visto[0][1].startswith("Cerebro101-Cambio"))

    def test_errores_de_red_o_http_y_respuestas_enormes_son_un_error_claro(self):
        for resp in (httpx.Response(500), httpx.Response(404), httpx.Response(302, headers={"location": "http://interna/"}), httpx.Response(200, content=b"x" * (C.MAX_BYTES + 1))):
            with self.assertRaises(C.ErrorCambio):
                ejecutar(C.bajar(httpx.MockTransport(lambda req, r=resp: r)))

        def cae(req):
            raise httpx.ConnectError("sin red")
        with self.assertRaisesRegex(C.ErrorCambio, "ConnectError"):
            ejecutar(C.bajar(httpx.MockTransport(cae)))


class TestUsoEnLosPrecios(unittest.TestCase):
    def cfg(self, **co):
        return P.configuracion({"margen": {"por_defecto": 0.5}, "canales": {"fabricante": {"moneda": "USD", "logistica_pct": 0.15}}, "cambio_a_eur": {"USD": 0.90},
                                "cambio_online": {"activo": True, **co}, "provisional": ["cambio_a_eur.USD"]})

    def test_el_tipo_en_linea_sustituye_al_de_respaldo_y_deja_de_ser_provisional(self):
        c = P.con_cambios_en_linea(self.cfg(), {"USD": {"fecha": date(2026, 11, 6), "eur_por_unidad": D("0.92592593")}}, date(2026, 11, 9))
        self.assertEqual(c["cambio_a_eur"]["USD"], D("0.92592593"))
        self.assertEqual(c["cambio_info"]["USD"]["origen"], "BCE")
        self.assertNotIn("cambio_a_eur.USD", c["provisional"])
        coste, av = P.coste_en_euros("100", "USD", "fabricante", c)
        self.assertEqual((coste, av), (D("100") * D("0.92592593") * D("1.15"), []))

    def test_si_el_tipo_es_viejo_o_no_hay_se_usa_el_respaldo_y_se_avisa(self):
        viejo = P.con_cambios_en_linea(self.cfg(), {"USD": {"fecha": date(2026, 10, 1), "eur_por_unidad": D("0.50")}}, date(2026, 11, 9))
        self.assertEqual(viejo["cambio_a_eur"]["USD"], D("0.90"))
        _, av = P.coste_en_euros("100", "USD", "fabricante", viejo)
        self.assertIn("de respaldo", av[0])
        self.assertIn("hace 39 días", av[0])
        sin = P.con_cambios_en_linea(self.cfg(), {}, date(2026, 11, 9))
        self.assertIn("sin tipo en línea", P.coste_en_euros("100", "USD", "fabricante", sin)[1][0])

    def test_un_fin_de_semana_no_cuenta_como_viejo(self):
        c = P.con_cambios_en_linea(self.cfg(), {"USD": {"fecha": date(2026, 11, 6), "eur_por_unidad": D("0.92")}}, date(2026, 11, 9))   # viernes → lunes: 3 días
        self.assertEqual(c["cambio_info"]["USD"]["origen"], "BCE")

    def test_el_colchon_encarece_el_cambio(self):
        c = P.con_cambios_en_linea(self.cfg(colchon_pct=0.02), {"USD": {"fecha": date(2026, 11, 6), "eur_por_unidad": D("0.9")}}, date(2026, 11, 9))
        self.assertEqual(c["cambio_a_eur"]["USD"], D("0.9") * D("1.02"))

    def test_desactivado_no_se_usa_y_no_avisa_de_respaldo(self):
        c = P.con_cambios_en_linea(self.cfg(activo=False), {"USD": {"fecha": date(2026, 11, 6), "eur_por_unidad": D("0.5")}}, date(2026, 11, 9))
        self.assertEqual(c["cambio_a_eur"]["USD"], D("0.90"))
        self.assertIn("provisional", P.coste_en_euros("100", "USD", "fabricante", c)[1][0])

    def test_valores_imposibles_de_la_configuracion(self):
        for malo in ({"colchon_pct": 0.9}, {"colchon_pct": -1}, {"max_dias": 0}, {"max_dias": 400}):
            with self.assertRaises(P.ErrorPrecios, msg=str(malo)):
                self.cfg(**malo)

    def test_la_configuracion_real_trae_el_cambio_en_linea(self):
        import yaml
        raw = yaml.safe_load((Path(__file__).resolve().parents[2] / "config" / "precios.yaml").read_text(encoding="utf-8"))
        c = P.configuracion(raw)
        self.assertTrue(c["cambio_online"]["activo"])
        self.assertEqual(c["cambio_online"]["colchon_pct"], D(0))


@unittest.skipUnless(URL and hasattr(psycopg, "AsyncConnection"), "sin CEREBRO_TEST_PG")
class TestEnBase(unittest.TestCase):
    def setUp(self):
        self.schema = f"t_cam_{time.time_ns()}"
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"CREATE SCHEMA {self.schema}")
            c.execute(f"SET search_path = {self.schema}")
            t = ESQUEMA.read_text(encoding="utf-8")
            c.execute(t[t.index("-- Tipos de cambio (api/cerebro/cambio.py)"):t.index("-- Resumen diario de licitaciones")])
        sep = "&" if "?" in URL else "?"
        self.parche = mock.patch.object(C, "ajustes", SimpleNamespace(database_url=f"{URL}{sep}options=-csearch_path%3D{self.schema}"))
        self.parche.start()

    def tearDown(self):
        self.parche.stop()
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"DROP SCHEMA {self.schema} CASCADE")

    def test_actualizar_guarda_y_repetir_no_duplica(self):
        t = httpx.MockTransport(lambda req: httpx.Response(200, content=XML))
        r = ejecutar(C.actualizar(t))
        self.assertEqual((r["fecha"], r["monedas"], r["usd"]), ("2026-11-06", 3, "0.92592593"))
        ejecutar(C.actualizar(t))
        with psycopg.connect(C.ajustes.database_url) as c:
            self.assertEqual(c.execute("SELECT count(*) FROM tipos_cambio").fetchone()[0], 3)

    def test_ultimos_devuelve_el_mas_reciente_de_cada_moneda(self):
        ejecutar(C.guardar(date(2026, 11, 5), {"USD": D("0.90"), "GBP": D("1.15")}))
        ejecutar(C.guardar(date(2026, 11, 6), {"USD": D("0.92")}))
        u = ejecutar(C.ultimos(["USD", "GBP"]))
        self.assertEqual((u["USD"]["fecha"], u["USD"]["eur_por_unidad"]), (date(2026, 11, 6), D("0.92000000")))
        self.assertEqual(u["GBP"]["fecha"], date(2026, 11, 5))
        self.assertEqual(set(ejecutar(C.ultimos())), {"USD", "GBP"})

    def test_configuracion_de_precios_usa_lo_guardado_y_sin_nada_cae_al_respaldo(self):
        raw = {"canales": {"fabricante": {"moneda": "USD", "logistica_pct": 0}}, "cambio_a_eur": {"USD": 0.90}}
        sin = ejecutar(C.configuracion_de_precios(raw))
        self.assertEqual(sin["cambio_a_eur"]["USD"], D("0.90"))
        ejecutar(C.guardar(C.hoy(), {"USD": D("0.93")}))
        con = ejecutar(C.configuracion_de_precios(raw))
        self.assertEqual((con["cambio_a_eur"]["USD"], con["cambio_info"]["USD"]["origen"]), (D("0.93"), "BCE"))

    def test_si_la_base_falla_el_calculo_sigue_con_el_respaldo(self):
        with mock.patch.object(C, "ultimos", side_effect=RuntimeError("sin base")):
            c = ejecutar(C.configuracion_de_precios({"cambio_a_eur": {"USD": 0.90}}))
        self.assertEqual(c["cambio_a_eur"]["USD"], D("0.90"))


if __name__ == "__main__":
    unittest.main()
