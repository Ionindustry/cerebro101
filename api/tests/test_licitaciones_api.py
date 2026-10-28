"""Rutas del resumen de licitaciones en la API del Cerebro: quién las ve y qué devuelven (con el almacén simulado)."""
import unittest
from unittest import mock

import _sin_servicios  # noqa: F401

try:
    from fastapi.testclient import TestClient
    from cerebro.api import main
    from cerebro.api.auth import Usuario, usuario_actual
except ImportError as e:      # pragma: no cover — en el contenedor están todas las dependencias
    raise unittest.SkipTest(str(e))

LISTA = [{"id": 2, "fecha": "2026-10-28", "origen": "programada", "estado": "ok", "totales": {"oportunidades": 3}, "mejor_encaje": 88, "aviso": False}]
FICHA = {"id": 2, "fecha": "2026-10-28", "estado": "ok", "contenido": {"oportunidades": []}}


def como(roles=(), departamentos=()):
    main.app.dependency_overrides[usuario_actual] = lambda: Usuario("albert", set(roles), set(departamentos))
    return TestClient(main.app)             # sin «with»: no arranca la base de datos


class TestRutas(unittest.TestCase):
    def tearDown(self):
        main.app.dependency_overrides.clear()

    def test_la_ven_direccion_y_el_departamento_de_licitaciones(self):
        with mock.patch.object(main.resumen_licitaciones, "listar", mock.AsyncMock(return_value=LISTA)), \
                mock.patch.object(main.resumen_licitaciones, "leer", mock.AsyncMock(return_value=FICHA)):
            for roles, deps in ((("direccion",), ()), ((), ("licitaciones",)), (("usuario", "responsable"), ("licitaciones", "finanzas"))):
                c = como(roles, deps)
                self.assertEqual(c.get("/licitaciones/resumenes").json(), LISTA, (roles, deps))
                self.assertEqual(c.get("/licitaciones/resumenes/ultimo").json(), FICHA)
                self.assertEqual(c.get("/licitaciones/resumenes/2").json(), FICHA)

    def test_los_demas_reciben_403_en_todas_las_rutas(self):
        listar = mock.AsyncMock(return_value=LISTA)
        generar = mock.AsyncMock()
        with mock.patch.object(main.resumen_licitaciones, "listar", listar), mock.patch.object(main.resumen_licitaciones, "generar", generar):
            c = como(("usuario", "responsable"), ("finanzas", "comercial"))
            for metodo, ruta in (("get", "/licitaciones/resumenes"), ("get", "/licitaciones/resumenes/ultimo"), ("get", "/licitaciones/resumenes/1"),
                                 ("post", "/licitaciones/resumenes")):
                self.assertEqual(getattr(c, metodo)(ruta).status_code, 403, ruta)
        listar.assert_not_called()
        generar.assert_not_called()          # quien no tiene permiso no provoca ni una consulta al motor

    def test_sin_resumenes_el_ultimo_es_404_y_uno_inexistente_tambien(self):
        with mock.patch.object(main.resumen_licitaciones, "leer", mock.AsyncMock(return_value=None)):
            c = como(("direccion",))
            self.assertEqual(c.get("/licitaciones/resumenes/ultimo").status_code, 404)
            self.assertEqual(c.get("/licitaciones/resumenes/99").status_code, 404)
            self.assertEqual(c.get("/licitaciones/resumenes/no-es-numero").status_code, 422)

    def test_generar_a_mano_devuelve_el_resumen_completo(self):
        generar = mock.AsyncMock(return_value={"id": 2, "estado": "ok"})
        with mock.patch.object(main.resumen_licitaciones, "generar", generar), mock.patch.object(main.resumen_licitaciones, "leer", mock.AsyncMock(return_value=FICHA)):
            r = como(("direccion",)).post("/licitaciones/resumenes")
        self.assertEqual((r.status_code, r.json()), (200, FICHA))
        generar.assert_awaited_once_with("manual")


if __name__ == "__main__":
    unittest.main()
