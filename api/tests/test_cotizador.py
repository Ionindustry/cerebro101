"""El motor debe dar los mismos totales que el contador corregido en Excel
para el ejemplo que traía el fichero (300 m corrugado, 100 m tubo rígido, pareja de lampistas)."""
import unittest

from cerebro.cotizador import Solicitud, calcular


def ejemplo_excel() -> Solicitud:
    return Solicitud(
        cuadrilla_tecnicos="uno",
        metros_cableado={"corrugado": 300, "tubo_rigido": 100},
        cuadrilla_lampistas="pareja",
        materiales={"tubo_rigido_16": 100, "grapas_tubo": 100, "ferreteria": 50,
                    "cat5_ftp": 600, "pequeno_material": 50},
        horas_comerciales={"Ramon": 2},
        precio_definitivo=1608,
    )


class TestCotizador(unittest.TestCase):
    def test_coincide_con_excel_corregido(self):
        r = calcular(ejemplo_excel())
        self.assertAlmostEqual(r.horas_cableado, 23.0, places=2)
        self.assertAlmostEqual(r.venta_base, 1756.10, places=2)        # H99
        self.assertAlmostEqual(r.coste_financiero, 121.93, places=2)   # Q100
        self.assertAlmostEqual(r.venta_con_financiero, 1878.03, places=2)  # H100
        self.assertAlmostEqual(r.venta_total, 2065.83, places=2)       # H101
        self.assertAlmostEqual(r.coste_total, 1341.26, places=2)       # Q101
        self.assertAlmostEqual(r.coste_por_metro, 4.02, places=2)      # H103
        self.assertAlmostEqual(r.margen_definitivo, 0.1659, places=3)

    def test_horas_ajustadas_por_caso(self):
        base = calcular(Solicitud(partidas={"camara_exterior": 4}, cuadrilla_tecnicos="uno"))
        ajustada = calcular(Solicitud(partidas={"camara_exterior": 4}, cuadrilla_tecnicos="uno",
                                      ajuste_horas={"camara_exterior": 3}))
        self.assertEqual(base.horas_instalacion, 8)
        self.assertEqual(ajustada.horas_instalacion, 12)
        self.assertTrue(any("ajustadas" in a for a in ajustada.avisos))

    def test_tarifa_instalador_externo_cambia_solo_el_coste(self):
        s = dict(partidas={"camara_interior": 10}, cuadrilla_tecnicos="uno")
        interno = calcular(Solicitud(**s))
        externo = calcular(Solicitud(**s, tarifa_instalador_externo={"tecnico_primera": 24}))
        self.assertEqual(interno.venta_base, externo.venta_base)
        self.assertLess(externo.coste_total, interno.coste_total)

    def test_aviso_precio_bajo_coste(self):
        r = calcular(Solicitud(**{**ejemplo_excel().__dict__, "precio_definitivo": 1000}))
        self.assertTrue(any("por debajo del coste" in a for a in r.avisos))

    def test_partida_desconocida(self):
        with self.assertRaises(ValueError):
            calcular(Solicitud(partidas={"inventada": 1}))


if __name__ == "__main__":
    unittest.main()
