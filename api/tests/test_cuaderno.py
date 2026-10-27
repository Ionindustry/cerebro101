"""Cuadernos de investigación: troceado, citas, quién puede traer páginas web y quién tiene la herramienta."""
import asyncio
import unittest
from unittest import mock

import _sin_servicios  # noqa: F401

from cerebro.grafo.nodos import INYECTAR_DEPARTAMENTO, corregir_por_cuaderno, inyectar
from cerebro.grafo.prompts import sistema_director_general
from cerebro.herramientas import cuaderno
from cerebro.registro import registro


class TestTroceado(unittest.TestCase):
    def test_texto_corto_un_solo_trozo(self):
        self.assertEqual(cuaderno.trocear("  hola  "), ["hola"])
        self.assertEqual(cuaderno.trocear("   "), [])

    def test_no_se_pierde_el_final_y_los_trozos_se_solapan(self):
        texto = "".join(str(i % 10) for i in range(3700))
        trozos = cuaderno.trocear(texto, trozo=1500, solape=200)
        self.assertEqual(trozos[0], texto[:1500])
        self.assertTrue(texto.endswith(trozos[-1]))
        for a, b in zip(trozos, trozos[1:]):
            self.assertEqual(a[-200:], b[:200])

    def test_no_queda_un_trozo_que_solo_repite_el_solape(self):
        self.assertEqual(len(cuaderno.trocear("x" * 1500, trozo=1500, solape=200)), 1)
        self.assertEqual(len(cuaderno.trocear("x" * 1600, trozo=1500, solape=200)), 2)


class TestCitas(unittest.TestCase):
    def test_numera_desde_uno_con_titulo_y_enlace(self):
        c = cuaderno.citas([("Web A", "https://a.test", "texto a", 0.91234), ("Nota", "", "texto b", 0.5)])
        self.assertEqual([x["cita"] for x in c], [1, 2])
        self.assertEqual(c[0], {"cita": 1, "titulo": "Web A", "url": "https://a.test", "texto": "texto a", "similitud": 0.912})


class TestPaginasWeb(unittest.TestCase):
    def test_solo_sensibilidad_baja_trae_paginas_de_internet(self):
        with mock.patch.object(cuaderno.web, "leer") as leer:
            for s in ("media", "alta"):
                with self.assertRaises(PermissionError):
                    asyncio.run(cuaderno.guardar_web("Tema", "https://ejemplo.test", departamento="marketing", sensibilidad=s))
            leer.assert_not_called()

    def test_investigar_tambien_es_solo_para_sensibilidad_baja(self):
        with mock.patch.object(cuaderno.web, "buscar") as buscar:
            with self.assertRaises(PermissionError):
                asyncio.run(cuaderno.investigar("Tema", "cámaras", departamento="direccion", sensibilidad="media"))
            buscar.assert_not_called()

    def test_investigar_salta_las_paginas_que_no_se_pueden_leer_y_para_al_llegar_al_maximo(self):
        resultados = {"resultados": [{"url": f"https://p{i}.test"} for i in range(6)]}

        async def guardar(cuaderno_, url, departamento, sensibilidad):
            if url == "https://p1.test":
                raise PermissionError("El sitio no permite que lo lea un programa (robots.txt)")
            return {"fuente": url, "estado": "guardada"}

        with mock.patch.object(cuaderno.web, "buscar", mock.AsyncMock(return_value=resultados)) as buscar, \
                mock.patch.object(cuaderno, "guardar_web", side_effect=guardar):
            r = asyncio.run(cuaderno.investigar("Tema", "cámaras", departamento="marketing", max_fuentes=3))
        self.assertEqual([g["url"] for g in r["guardadas"]], ["https://p0.test", "https://p2.test", "https://p3.test"])
        self.assertEqual([d["url"] for d in r["descartadas"]], ["https://p1.test"])
        self.assertEqual(buscar.await_args.kwargs["max_resultados"], 6)


class TestPeriodo(unittest.TestCase):
    def test_entiende_como_lo_escriben_los_modelos(self):
        for texto, esperado in [("mes", "month"), ("último año", "year"), ("Último AÑO", "year"), ("past week", "week"), ("últimos 7 días", "week"),
                                ("24 horas", "day"), ("hoy", "day"), ("30 días", "month"), ("", None), ("siempre", None)]:
            self.assertEqual(cuaderno.web.periodo_de(texto), esperado, texto)

    def test_investigar_sigue_aunque_el_periodo_no_se_entienda(self):
        with mock.patch.object(cuaderno.web, "buscar", mock.AsyncMock(return_value={"resultados": []})) as buscar:
            asyncio.run(cuaderno.investigar("Tema", "cámaras", departamento="marketing", periodo="desde siempre"))
        self.assertEqual(buscar.await_args.kwargs["periodo"], "")

    def test_investigar_conserva_el_periodo_que_se_entiende(self):
        with mock.patch.object(cuaderno.web, "buscar", mock.AsyncMock(return_value={"resultados": []})) as buscar:
            asyncio.run(cuaderno.investigar("Tema", "cámaras", departamento="marketing", periodo="último año"))
        self.assertEqual(buscar.await_args.kwargs["periodo"], "último año")


class TestAsignacion(unittest.TestCase):
    def test_la_tienen_los_agentes_que_investigan_y_son_de_sensibilidad_baja(self):
        con = {f.id for f in registro().fichas.values() if "cuaderno" in f.herramientas}
        self.assertEqual(con, {"asistente-general", "analista-noticias", "analista-competencia", "radar-tendencias",
                               "explorador-fabricantes", "inteligencia-competitiva", "viabilidad"})
        for i in con:
            self.assertEqual(registro().fichas[i].sensibilidad, "baja", i)

    def test_el_director_general_no_manda_las_investigaciones_a_conocimiento(self):
        texto = sistema_director_general(registro().departamentos)
        self.assertIn("cuaderno de investigación", texto)
        self.assertIn("«conocimiento» es solo para", texto)
        # cada departamento al que manda las investigaciones tiene algún agente con cuadernos
        con = {f.departamento for f in registro().fichas.values() if "cuaderno" in f.herramientas}
        self.assertEqual(con, {"marketing", "operaciones", "licitaciones", "direccion"})

    def test_si_se_pide_un_cuaderno_se_corrige_hacia_quien_tiene_cuadernos(self):
        p = "Investiga los carteles de videovigilancia y guárdalo en un cuaderno de investigación"
        self.assertEqual(corregir_por_cuaderno(p, "conocimiento"), ("direccion", None))
        self.assertEqual(corregir_por_cuaderno(p, "direccion", "estratega"), ("direccion", "asistente-general"))
        self.assertEqual(corregir_por_cuaderno(p, "marketing", "analista-competencia"), ("marketing", "analista-competencia"))
        self.assertEqual(corregir_por_cuaderno("Fes un quadern sobre càmeres tèrmiques", "tecnologia"), ("direccion", None))

    def test_sin_cuaderno_no_se_toca_el_enrutado(self):
        self.assertEqual(corregir_por_cuaderno("Indexa el acta de ayer", "conocimiento", "bibliotecario"),
                         ("conocimiento", "bibliotecario"))

    def test_el_departamento_lo_pone_el_sistema(self):
        self.assertIn("cuaderno", INYECTAR_DEPARTAMENTO)
        ficha = registro().fichas["analista-competencia"]
        args = inyectar(ficha, {}, "cuaderno", {"cuaderno": "Tema", "departamento": "direccion"})
        self.assertEqual(args["departamento"], "marketing")


if __name__ == "__main__":
    unittest.main()
