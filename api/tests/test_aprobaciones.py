import unittest

from cerebro.aprobaciones.logica import DecisionNoValida, Solicitud, decidir


def solicitud(nivel="doble"):
    aprob = ("responsable_departamento", "direccion") if nivel == "doble" else ("responsable_departamento",)
    return Solicitud(id="1", agente="precio-licitacion", departamento="licitaciones",
                     accion="presentar_licitacion", nivel=nivel, aprobadores=aprob,
                     voz_permitida=nivel == "simple")


class TestAprobaciones(unittest.TestCase):
    def test_doble_necesita_dos_personas(self):
        s = solicitud()
        decidir(s, "ana", {"responsable"}, {"licitaciones"}, True, "panel")
        self.assertEqual(s.estado, "pendiente")
        decidir(s, "jordi", {"direccion"}, set(), True, "panel")
        self.assertEqual(s.estado, "aprobada")

    def test_la_misma_persona_no_firma_dos_veces(self):
        s = solicitud()
        decidir(s, "jordi", {"direccion", "responsable"}, {"licitaciones"}, True, "panel")
        with self.assertRaises(DecisionNoValida):
            decidir(s, "jordi", {"direccion", "responsable"}, {"licitaciones"}, True, "panel")

    def test_doble_no_por_voz(self):
        with self.assertRaises(DecisionNoValida):
            decidir(solicitud(), "jordi", {"direccion"}, set(), True, "voz")

    def test_simple_por_voz(self):
        s = solicitud("simple")
        decidir(s, "ana", {"responsable"}, {"licitaciones"}, True, "voz")
        self.assertEqual(s.estado, "aprobada")

    def test_responsable_de_otro_departamento(self):
        with self.assertRaises(DecisionNoValida):
            decidir(solicitud("simple"), "pere", {"responsable"}, {"marketing"}, True, "panel")

    def test_rechazo(self):
        s = solicitud()
        decidir(s, "ana", {"responsable"}, {"licitaciones"}, False, "panel", "Precio demasiado bajo")
        self.assertEqual(s.estado, "rechazada")
