"""Anonimización antes de enviar nada a la nube: validaciones, capas, bloqueo ante la duda y enganche con Jev."""
import asyncio
import json
import unittest
from pathlib import Path
from unittest import mock

import _sin_servicios  # noqa: F401

from cerebro import anonimizacion as a

CFG = a.configuracion(str(Path(__file__).resolve().parents[2] / "config"))


def limpiar(texto, personas=(), organizaciones=(), **kw):
    return a.anonimizar(texto, a.Entidades(personas=list(personas), organizaciones=list(organizaciones), **kw), cfg=CFG)


class TestValidaciones(unittest.TestCase):
    def test_dni_nie_cif_iban_tarjeta(self):
        self.assertTrue(a.dni_valido("12345678Z"))
        self.assertFalse(a.dni_valido("12345678A"))
        self.assertTrue(a.dni_valido("X1234567L"))
        self.assertTrue(a.iban_valido("ES91 2100 0418 4502 0005 1332"))
        self.assertFalse(a.iban_valido("ES91 2100 0418 4502 0005 1333"))
        self.assertTrue(a.luhn_valido("4539 1488 0343 6467"))
        self.assertFalse(a.luhn_valido("4539 1488 0343 6468"))
        self.assertTrue(a.cif_valido("A58818501"))
        self.assertFalse(a.cif_valido("A58818502"))


class TestCapas(unittest.TestCase):
    def test_datos_con_formato(self):
        t = ("DNI 12345678Z, NIE X1234567L, IBAN ES91 2100 0418 4502 0005 1332, tel +34 612 345 678, "
             "correo ana@ejemplo.cat, matrícula 1234 BCD, IP 192.168.1.20, web https://ejemplo.cat/cliente/9")
        r = limpiar(t)
        for dato in ("12345678Z", "X1234567L", "ES91", "612 345 678", "ana@ejemplo.cat", "1234 BCD", "192.168.1.20", "ejemplo.cat"):
            self.assertNotIn(dato, r.texto)
        self.assertTrue(r.apto, r.motivos)

    def test_direccion_con_y_sin_numero_y_codigo_postal(self):
        r = limpiar("Instalar en Calle Mayor 12, 08001 Barcelona y también en la calle Pau Claris")
        self.assertNotIn("Mayor", r.texto)
        self.assertNotIn("Pau Claris", r.texto)
        self.assertNotIn("08001", r.texto)

    def test_importes_y_cantidades_no_se_confunden_con_datos(self):
        r = limpiar("Presupuesto de 12000 euros, 300 metros de cable y 45 cámaras. Ref 2026-10")
        self.assertEqual(r.texto, "Presupuesto de 12000 euros, 300 metros de cable y 45 cámaras. Ref 2026-10")

    def test_entidades_conocidas_con_tildes_y_mayusculas(self):
        r = limpiar("la comunitat VILANOVA sl pide presupuesto; habló MARTA puig", ["Marta Puig"], ["Comunitat Vilanova SL"])
        self.assertNotIn("VILANOVA", r.texto)
        self.assertNotIn("puig", r.texto.lower())

    def test_la_misma_persona_lleva_la_misma_etiqueta(self):
        r = limpiar("Marta Puig llamó. Más tarde Marta Puig envió el plano; Pere Soler no.", ["Marta Puig", "Pere Soler"])
        self.assertEqual(r.texto.count("[PERSONA_1]"), 2)
        self.assertIn("[PERSONA_2]", r.texto)

    def test_nombre_suelto_de_empleado_conocido(self):
        r = limpiar("Dile a Puig que llame", ["Marta Puig"])
        self.assertNotIn("Puig", r.texto)

    def test_entidad_conocida_manda_sobre_el_detector_de_nombres(self):
        r = limpiar("El cliente Marta Puig de Comunitat Vilanova SL pide cámaras", ["Marta Puig"], ["Comunitat Vilanova SL"])
        self.assertIn("[PERSONA_1]", r.texto)
        self.assertIn("[ORGANIZACION_1]", r.texto)
        self.assertEqual(r.sustituciones.get("PERSONA"), 1)

    def test_nombres_libres_por_tratamiento_y_presentacion(self):
        r = limpiar("Soy Joan Serra Vidal y escribo por la Sra. Núria Pons. Hola, em dic Pau Costa.")
        for nombre in ("Joan Serra", "Núria Pons", "Pau Costa"):
            self.assertNotIn(nombre, r.texto)

    def test_terminos_del_negocio_se_conservan(self):
        t = "Control de Accesos y Contra Incendios para el parking de 101.cat; Jarvis lo revisa. Atención al Cliente."
        self.assertEqual(limpiar(t).texto, t)

    def test_conservar_tiene_prioridad(self):
        r = limpiar("Pregunta a Marta Puig", ["Marta Puig"], conservar=["Marta Puig"])
        self.assertIn("Marta Puig", r.texto)

    def test_los_textos_utiles_sobreviven(self):
        r = limpiar("El grabador de las cámaras lleva 3 días sin grabar y la fibra del polígono cae a menudo")
        self.assertEqual(r.sustituciones, {})
        self.assertIn("grabador", r.texto)


class TestBloqueo(unittest.TestCase):
    def test_categoria_especial_bloquea(self):
        for t in ("El empleado tiene una baja médica larga", "Té un diagnòstic greu", "Afiliación sindical del instalador",
                  "Tiene antecedentes penales"):
            r = limpiar(t)
            self.assertFalse(r.apto, t)
            self.assertTrue(any("categoría especial" in m for m in r.motivos))

    def test_texto_demasiado_largo_bloquea(self):
        self.assertFalse(limpiar("a" * 5000).apto)

    def test_sin_lista_del_erp_bloquea(self):
        r = a.anonimizar("Hola", a.Entidades(disponible=False, origen="erpnext"), cfg=CFG)
        self.assertFalse(r.apto)
        self.assertIn("ERP", r.motivos[0])

    def test_no_guarda_ni_expone_el_texto_original(self):
        r = limpiar("Marta Puig, DNI 12345678Z", ["Marta Puig"])
        resumen = json.dumps(r.resumen())
        self.assertNotIn("Marta", resumen)
        self.assertNotIn("12345678Z", resumen)
        self.assertEqual(len(r.huella), 64)


class TestSpacy(unittest.TestCase):
    def test_sin_spacy_instalado_devuelve_none(self):
        with mock.patch.dict("sys.modules", {"spacy": None}):
            self.assertIsNone(a.detector_spacy())

    def test_detector_spacy_con_modelo_simulado(self):
        ent = mock.Mock(start_char=3, end_char=13, label_="PER", text="Marta Puig")
        nlp = mock.Mock(return_value=mock.Mock(ents=[ent, mock.Mock(start_char=0, end_char=1, label_="MISC", text="x")]))
        with mock.patch.dict("sys.modules", {"spacy": mock.Mock(load=lambda m: nlp)}):
            d = a.detector_spacy()
        self.assertEqual(d("A, Marta Puig"), [(3, 13, "PERSONA", "marta puig")])


class TestEnganchesConJev(unittest.TestCase):
    """Lo que se envía a la API y lo que no."""

    def setUp(self):
        try:
            from cerebro.herramientas import decision as d
        except ImportError as e:
            self.skipTest(f"requiere las dependencias del contenedor: {e}")
        self.d = d
        self.enviado = []

        async def api(url, clave, texto, tipo, opciones, rubrica, transporte=None):
            self.enviado.append({"texto": texto, "rubrica": rubrica, "opciones": opciones})
            return {"eleccion": "soporte", "confianza": 0.9, "motivo": "x"}

        async def local(texto, tipo, opciones, rubrica):
            return {"eleccion": "local", "confianza": 0.5, "motivo": "modelo local"}

        async def entidades(cfg, leer=None):
            return a.Entidades(personas=["Marta Puig"], organizaciones=["Comunitat Vilanova SL"])

        self.patches = [mock.patch.object(d, "_llamar_api", api), mock.patch.object(d, "_local", local),
                        mock.patch.object(d, "cargar_entidades", entidades),
                        mock.patch.object(d.ajustes.__class__, "usar_jev_nube", True, create=True)]
        for p in self.patches:
            p.start()
        d.ajustes.__dict__["usar_jev_nube"] = True
        d.ajustes.__dict__["jev_api_key"] = "clave"
        d.ajustes.__dict__["dir_config"] = Path(__file__).resolve().parents[2] / "config"
        d._detector.cache_clear()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def _decidir(self, texto, **kw):
        h = self.d._crear("jev")
        return asyncio.run(h(texto, tipo="eleccion", opciones=["soporte", "ventas"], **kw))

    def test_a_la_nube_solo_llega_texto_anonimizado(self):
        r = self._decidir("Marta Puig de Comunitat Vilanova SL (12345678Z, 612 345 678) dice que el grabador no graba")
        self.assertEqual(r["via"], "jev (anonimizado)")
        enviado = json.dumps(self.enviado)
        for dato in ("Marta", "Puig", "Vilanova", "12345678Z", "612 345 678"):
            self.assertNotIn(dato, enviado)
        self.assertIn("grabador", enviado)

    def test_categoria_especial_no_sale_y_decide_el_modelo_local(self):
        r = self._decidir("El instalador tiene baja médica y no puede ir")
        self.assertEqual(self.enviado, [])
        self.assertEqual(r["eleccion"], "local")
        self.assertIn("local", r["via"])

    def test_opciones_con_datos_personales_no_salen(self):
        h = self.d._crear("jev")
        r = asyncio.run(h("texto normal", tipo="eleccion", opciones=["Marta Puig", "otro"]))
        self.assertEqual(self.enviado, [])
        self.assertEqual(r["eleccion"], "local")

    def test_jeff_local_no_anonimiza(self):
        h = self.d._crear("jeff")
        asyncio.run(h("Marta Puig llamó", tipo="eleccion", opciones=["a", "b"]))
        self.assertIn("Marta Puig", self.enviado[0]["texto"])


class TestEntidadesErp(unittest.TestCase):
    def setUp(self):
        from cerebro import entidades
        self.e = entidades
        self.e._cache.clear()

    def test_sin_erp_configurado_usa_solo_la_configuracion(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            ent = asyncio.run(self.e.cargar_entidades({"entidades_extra": {"personas": ["Ana Ruiz"]}}))
        self.assertTrue(ent.disponible)
        self.assertEqual(ent.personas, ["Ana Ruiz"])

    def test_si_el_erp_falla_no_hay_lista_y_se_bloquea(self):
        async def falla(cfg):
            raise RuntimeError("caído")
        with mock.patch.dict("os.environ", {"ERPNEXT_TOKEN": "t"}):
            ent = asyncio.run(self.e.cargar_entidades({}, leer=falla))
        self.assertFalse(ent.disponible)

    def test_lista_vieja_en_cache_vale_si_el_erp_cae(self):
        async def ok(cfg):
            return ["Marta Puig"], ["Comunitat Vilanova SL"]

        async def falla(cfg):
            raise RuntimeError("caído")
        with mock.patch.dict("os.environ", {"ERPNEXT_TOKEN": "t"}):
            asyncio.run(self.e.cargar_entidades({"caducidad_lista_segundos": 0}, leer=ok))
            ent = asyncio.run(self.e.cargar_entidades({"caducidad_lista_segundos": 0}, leer=falla))
        self.assertTrue(ent.disponible)
        self.assertIn("Marta Puig", ent.personas)


class TestCorpus(unittest.TestCase):
    """La cobertura medida con los textos sintéticos no puede bajar (scripts/evaluar_anonimizacion.py)."""

    @classmethod
    def setUpClass(cls):
        import sys
        import yaml
        raiz = Path(__file__).resolve().parents[2]
        sys.path.insert(0, str(raiz / "scripts"))
        import evaluar_anonimizacion as ev
        cls.ev, cls.yaml, cls.raiz = ev, yaml, raiz

    def _medir(self, nombre):
        corpus = self.yaml.safe_load((self.raiz / "evaluacion" / f"{nombre}.yaml").read_text(encoding="utf-8"))
        return self.ev.evaluar(corpus, CFG, a.detector_heuristico(CFG["no_son_nombres"]))

    def test_cobertura_minima_en_los_tres_conjuntos(self):
        for nombre in ("anonimizacion_corpus", "anonimizacion_ciego", "anonimizacion_ciego2"):
            r = self._medir(nombre)
            for capa, (hecho, total) in r["capas"].items():
                minimo = 0.9 if capa == "libre" else 1.0
                self.assertGreaterEqual(hecho / total, minimo, f"{nombre}/{capa}: {hecho}/{total}\n" + "\n".join(r["fallos"]))
            self.assertEqual(r["bloqueos"][0], r["bloqueos"][1], f"{nombre}: bloqueos\n" + "\n".join(r["fallos"]))
            self.assertEqual(r["utilidad"][0], r["utilidad"][1], f"{nombre}: utilidad\n" + "\n".join(r["fallos"]))


if __name__ == "__main__":
    unittest.main()
