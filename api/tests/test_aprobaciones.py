import unittest

from cerebro.aprobaciones.logica import DecisionNoValida, Solicitud, decidir


def solicitud(nivel="doble"):
    aprob = ("responsable_departamento", "direccion") if nivel == "doble" else ("responsable_departamento",)
    return Solicitud(id="1", agente="precio-licitacion", departamento="licitaciones",
                     accion="presentar_licitacion", nivel=nivel, aprobadores=aprob,
                     voz_permitida=nivel == "simple")


class TestFirmaUnica(unittest.TestCase):
    """Con la política actual solo hace falta la firma de Dirección, de una persona, en cualquier departamento."""

    def sol(self, voz=True):
        return Solicitud(id="2", agente="cobros", departamento="finanzas", accion="enviar_correo", nivel="simple",
                         aprobadores=("direccion",), voz_permitida=voz)

    def test_direccion_firma_sola_y_queda_la_fecha(self):
        s = self.sol()
        decidir(s, "albert", {"direccion"}, set(), True, "panel", "ok")
        self.assertEqual(s.estado, "aprobada")
        self.assertIn("fecha", s.decisiones[0])

    def test_quien_no_es_de_direccion_no_firma(self):
        with self.assertRaises(DecisionNoValida):
            decidir(self.sol(), "ana", {"responsable"}, {"finanzas"}, True, "panel")

    def test_una_firma_cerrada_no_admite_otra(self):
        s = self.sol()
        decidir(s, "albert", {"direccion"}, set(), True, "panel")
        with self.assertRaises(DecisionNoValida):
            decidir(s, "otra", {"direccion"}, set(), True, "panel")

    def test_rechazo_de_direccion(self):
        s = self.sol()
        decidir(s, "albert", {"direccion"}, set(), False, "panel", "no")
        self.assertEqual(s.estado, "rechazada")

    def test_lo_delicado_no_se_firma_por_voz(self):
        with self.assertRaises(DecisionNoValida):
            decidir(self.sol(voz=False), "albert", {"direccion"}, set(), True, "voz")


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
