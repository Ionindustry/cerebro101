import unittest

from cerebro.aprobaciones.logica import DecisionNoValida, Solicitud, anular, decidir


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


class TestAnular(unittest.TestCase):
    """Los tickets antiguos que pedían dos firmas: quien ya firmó una no puede rechazar (la segunda la hace otra persona), así que Dirección puede anularlos con motivo."""

    def test_anular_un_ticket_en_el_que_ya_firme_una_vez(self):
        s = solicitud()
        decidir(s, "albert", {"direccion", "responsable"}, {"licitaciones"}, True, "panel")
        self.assertEqual(s.estado, "pendiente")
        with self.assertRaises(DecisionNoValida):                       # rechazar ya no se puede
            decidir(s, "albert", {"direccion"}, set(), False, "panel")
        anular(s, "albert", {"direccion"}, "  Antigua,   pedía 2 firmas ")
        self.assertEqual(s.estado, "rechazada")
        ultima = s.decisiones[-1]
        self.assertEqual((ultima["usuario"], ultima["aprobado"], ultima["anulada"]), ("albert", False, True))
        self.assertEqual(ultima["comentario"], "Anulada: Antigua, pedía 2 firmas")
        self.assertEqual(len(s.decisiones), 2)                          # la firma anterior sigue en el historial

    def test_solo_direccion_y_siempre_con_motivo(self):
        with self.assertRaisesRegex(DecisionNoValida, "Solo Dirección"):
            anular(solicitud(), "ana", {"responsable"}, "motivo largo")
        for motivo in ("", "  ", "ok", None):
            with self.assertRaisesRegex(DecisionNoValida, "motivo"):
                anular(solicitud(), "albert", {"direccion"}, motivo)

    def test_una_solicitud_ya_resuelta_no_se_anula(self):
        s = solicitud("simple")
        s.aprobadores = ("direccion",)
        decidir(s, "albert", {"direccion"}, set(), True, "panel")
        with self.assertRaisesRegex(DecisionNoValida, "ya está aprobada"):
            anular(s, "albert", {"direccion"}, "motivo largo")
