"""Pantalla de revisión de precios de venta: filtros, qué se enseña y que solo Dirección vea, ajuste y aplique (con confirmación expresa y constancia)."""
import unittest
from decimal import Decimal
from unittest import mock

import _sin_servicios  # noqa: F401

try:
    from cerebro import precios_venta as V
except ImportError as e:      # pragma: no cover
    raise unittest.SkipTest(str(e))


def linea(codigo, ref="R", familia="Cámaras", cambio="sube", margen="0.5000", excluida=False, desc="Cámara domo", marca="Milesight", **kw):
    return {"codigo": codigo, "ref": ref, "desc": desc, "familia": familia, "marca": marca, "proveedor": "P", "coste_eur": "100", "calculado": "200", "venta": "200", "ajustado": False,
            "excluida": excluida, "margen": margen, "actual": "190", "cambio": cambio, "variacion_pct": "5", "avisos": [], "mercado": None, "pvp_fabricante": None,
            "estrategias": {"competitivo": {"precio": "195", "x": 1}, "premium": {"precio": "230"}}, **kw}


LINEAS = [linea("A", "MS-1", "Cámaras", "sube"), linea("B", "NV-2", "Grabadores", "baja", desc="Grabador 16 canales", marca="Hikvision"), linea("C", "MS-3", "Cámaras", "igual", margen="0.1000"),
          linea("D", "MS-4", "Cámaras", "nuevo", margen="0.0500", excluida=True)]


class TestFiltros(unittest.TestCase):
    def codigos(self, **kw):
        return [l["codigo"] for l in V.filtrar_lineas(LINEAS, **kw)]

    def test_sin_filtros_salen_todas(self):
        self.assertEqual(self.codigos(), ["A", "B", "C", "D"])

    def test_por_familia_cambio_y_texto(self):
        self.assertEqual(self.codigos(familia="camaras"), ["A", "C", "D"])             # sin acentos ni mayúsculas
        self.assertEqual(self.codigos(cambio="baja"), ["B"])
        self.assertEqual(self.codigos(texto="grabador"), ["B"])
        self.assertEqual(self.codigos(texto="hikvision"), ["B"])
        self.assertEqual(self.codigos(texto="ms-3"), ["C"])

    def test_bajo_el_margen_minimo_no_cuenta_lo_excluido(self):
        self.assertEqual(self.codigos(solo_bajo_minimo=True, minimo=Decimal("0.30")), ["C"])      # D está bajo el mínimo pero excluida

    def test_la_linea_publica_aplana_las_estrategias_a_su_precio(self):
        p = V._linea_publica(LINEAS[0])
        self.assertEqual(p["estrategias"], {"competitivo": "195", "premium": "230"})
        self.assertEqual(p["coste_eur"], "100")                                              # la pantalla es de Dirección: sí lleva el coste


class TestRutas(unittest.TestCase):
    def setUp(self):
        try:
            from fastapi.testclient import TestClient
            from cerebro.api import main
            from cerebro.api.auth import Usuario, usuario_actual
            import cerebro.herramientas  # noqa: F401
        except ImportError as e:      # pragma: no cover
            self.skipTest(str(e))
        self.main, self.Usuario, self.actual = main, Usuario, usuario_actual
        self.c = TestClient(main.app)
        self.como(roles={"direccion"})
        self.pv = main.precios_venta_pantalla

    def como(self, roles):
        self.main.app.dependency_overrides[self.actual] = lambda: self.Usuario("marta", set(roles), {"licitaciones"})

    def tearDown(self):
        self.main.app.dependency_overrides.clear()

    def test_solo_direccion_entra_aunque_sea_de_licitaciones(self):
        self.como(roles={"usuario"})
        for r in (self.c.get("/precios/propuestas"), self.c.get("/precios/propuestas/1"), self.c.post("/precios/propuestas", json={}), self.c.post("/precios/propuestas/1/ajustar", json={}),
                  self.c.post("/precios/propuestas/1/estrategia", json={"estrategia": "premium"}), self.c.post("/precios/propuestas/1/descartar"),
                  self.c.post("/precios/propuestas/1/aplicar", json={"confirmo": True})):
            self.assertEqual(r.status_code, 403, r.request.url)

    def test_aplicar_exige_la_confirmacion_expresa_y_no_toca_el_erp_sin_ella(self):
        with mock.patch.object(self.pv, "aplicar", mock.AsyncMock()) as ap, mock.patch.object(self.pv, "vista_aplicar", mock.AsyncMock(return_value={"titulo": "t"})):
            self.assertEqual(self.c.post("/precios/propuestas/1/aplicar", json={}).status_code, 422)
            self.assertEqual(self.c.post("/precios/propuestas/1/aplicar", json={"confirmo": False}).status_code, 422)
            ap.assert_not_awaited()

    def test_aplicar_con_confirmacion_deja_constancia_de_quien_firmo(self):
        with mock.patch.object(self.pv, "aplicar", mock.AsyncMock(return_value={"precios_nuevos": 3})) as ap, mock.patch.object(self.pv, "vista_aplicar", mock.AsyncMock(return_value={"titulo": "Aplicar lista Venta"})), \
                mock.patch.object(self.main.constancia, "dejar_constancia", mock.AsyncMock(return_value="ok")) as cons:
            r = self.c.post("/precios/propuestas/7/aplicar", json={"confirmo": True})
            self.assertEqual((r.status_code, r.json()["resultado"]), (200, {"precios_nuevos": 3}))
            ap.assert_awaited_once_with(7, "operaciones")
            args = cons.await_args.args
            self.assertEqual((args[1], args[2], args[3]), ("usuario:marta", "listas_precios", "aplicar_venta"))
            self.assertIn("marta", args[4])
            self.assertIn("Aplicar lista Venta", args[5])

    def test_un_error_de_negocio_es_un_422_y_un_inexistente_un_404(self):
        from cerebro import listas_precios as LP
        with mock.patch.object(self.pv, "ajustar", mock.AsyncMock(side_effect=V.ErrorVenta("ya no se puede ajustar"))):
            r = self.c.post("/precios/propuestas/1/ajustar", json={"ajustes": {"A": 10}})
            self.assertEqual((r.status_code, r.json()["detail"]), (422, "ya no se puede ajustar"))
        with mock.patch.object(self.pv, "ver", mock.AsyncMock(side_effect=LP.NoExiste("No existe esa propuesta de precios"))):
            self.assertEqual(self.c.get("/precios/propuestas/99").status_code, 404)

    def test_ajustar_y_estrategia_dejan_constancia(self):
        with mock.patch.object(self.pv, "ajustar", mock.AsyncMock(return_value={"propuesta": 1})), mock.patch.object(self.pv, "elegir_estrategia", mock.AsyncMock(return_value={"articulos": 4})), \
                mock.patch.object(self.main.constancia, "dejar_constancia", mock.AsyncMock(return_value="ok")) as cons:
            self.assertEqual(self.c.post("/precios/propuestas/1/ajustar", json={"ajustes": {"A": 199.5}, "excluir": ["B"]}).status_code, 200)
            self.assertEqual(self.c.post("/precios/propuestas/1/estrategia", json={"estrategia": "premium", "familia": "Cámaras"}).status_code, 200)
            self.assertEqual([c.args[3] for c in cons.await_args_list], ["ajustar_venta", "elegir_estrategia"])

    def test_los_parametros_raros_se_rechazan(self):
        self.assertEqual(self.c.post("/precios/propuestas/1/ajustar", json={"ajustes": {"A": "mucho"}}).status_code, 422)
        self.assertEqual(self.c.post("/precios/propuestas/1/estrategia", json={"estrategia": "x"}).status_code, 422)


if __name__ == "__main__":
    unittest.main()
