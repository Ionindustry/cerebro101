import unittest

from cerebro.politicas import AccionProhibida, HerramientaNoPermitida, herramienta_efectiva, nivel_para
from cerebro.registro import cargar
from cerebro.router_modelos import asignar


class TestRegistro(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = cargar()

    def test_totales_del_documento(self):
        self.assertEqual(len(self.r.departamentos), 13)
        self.assertEqual(len(self.r.fichas), 114)
        self.assertEqual(sum(len(d["subareas"]) for d in self.r.departamentos.values()), 60)

    def test_cada_departamento_tiene_director(self):
        for dep in self.r.departamentos:
            self.assertTrue(self.r.director_de(dep).director)

    def test_seleccion_no_usa_servicios_externos(self):
        f = self.r.fichas["seleccion"]
        self.assertNotIn("jev", f.herramientas)
        self.assertNotIn("grok", f.herramientas)


class TestPoliticas(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = cargar()

    def test_impacto_externo_sube_de_libre_a_simple(self):
        d = nivel_para(self.r.fichas["radar-tendencias"], "enviar_correo")
        self.assertEqual(d.nivel, "simple")
        self.assertTrue(d.requiere)

    def test_doble_no_se_aprueba_por_voz(self):
        d = nivel_para(self.r.fichas["precio-licitacion"], "presentar_licitacion")
        self.assertEqual(d.nivel, "doble")
        self.assertFalse(d.voz_permitida)

    def test_acciones_prohibidas(self):
        with self.assertRaises(AccionProhibida):
            nivel_para(self.r.fichas["contable"], "validar_documento_erp")

    def test_jev_con_datos_altos_pasa_a_jeff(self):
        f = self.r.fichas["retencion-cartera"]
        self.assertEqual(herramienta_efectiva(f, "jev", "baja"), "jev")
        self.assertEqual(herramienta_efectiva(f, "jev", "alta"), "jeff")

    def test_grok_no_admite_datos_sensibles(self):
        f = self.r.fichas["radar-tendencias"]
        with self.assertRaises(HerramientaNoPermitida):
            herramienta_efectiva(f, "grok", "media")

    def test_herramienta_fuera_de_ficha(self):
        with self.assertRaises(HerramientaNoPermitida):
            herramienta_efectiva(self.r.fichas["contable"], "grok")


class TestRouter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = cargar()

    def test_imagenes_van_a_vision(self):
        a = asignar(self.r.fichas["analista-pliegos"], con_imagenes=True, perfil="pequena")
        self.assertEqual(a.clase, "vision")

    def test_rapido_sube_si_es_dificil(self):
        a = asignar(self.r.fichas["rastreador"], dificil=True, perfil="pequena")
        self.assertEqual(a.clase, "principal")

    def test_prioridad_jarvis(self):
        a = asignar(self.r.fichas["director-general"], origen="jarvis", perfil="grande")
        self.assertEqual(a.prioridad, 0)
        self.assertEqual(a.mantener_cargado, "-1")
