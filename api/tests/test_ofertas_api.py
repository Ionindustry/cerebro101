"""Rutas de la oferta: «Preparar la oferta» con los agentes, las sociedades del ERP y la documentación administrativa (quién las ve y cómo traducen los errores)."""
import base64
import sys
import types
import unittest
from unittest import mock

import _sin_servicios  # noqa: F401

try:
    from cerebro.api import main
    from cerebro.licitaciones import empresa as E, ofertas as O, plantillas as PL, redaccion as R
    from test_licitaciones_api import como
except ImportError as e:      # pragma: no cover
    raise unittest.SkipTest(str(e))

ID = "0b1f7a3e-1111-4222-8333-444444444444"
OFERTA = {"existe": True, "licitacion": ID, "empresa": None, "secciones": []}
EJEC = {"id": 4, "licitacion": ID, "estado": "en_curso", "pasos": [{"id": "solucion", "estado": "pendiente"}]}
EMPRESAS = [{"nombre": "101 Telecom S.L.", "razon_social": "101 S.L.", "nif": "B1"}, {"nombre": "Ion S.A.", "razon_social": "Ion", "nif": "A2"}]


def celery_falso(error=None):
    """Sin Celery instalado (o sin Redis) se prueba que se encola lo correcto."""
    app = mock.Mock()
    if error:
        app.send_task.side_effect = error
    modulo = types.ModuleType("cerebro.tareas.celery_app")
    modulo.app = app
    return mock.patch.dict(sys.modules, {"cerebro.tareas.celery_app": modulo}), app


class TestRedactar(unittest.TestCase):
    def tearDown(self):
        main.app.dependency_overrides.clear()

    def parches(self, **kw):
        return [mock.patch.object(main.motor_lic, "_get", mock.AsyncMock(return_value={})), mock.patch.object(main.ofertas_licitaciones, "plan", mock.AsyncMock(return_value=OFERTA)),
                mock.patch.object(main.ofertas_licitaciones, "fijar_empresa", kw.get("fijar", mock.AsyncMock())),
                mock.patch.object(main.empresa_erp, "elegir", kw.get("elegir", mock.AsyncMock(return_value="101 Telecom S.L."))),
                mock.patch.object(main.redaccion_ofertas, "reservar", kw.get("reservar", mock.AsyncMock(return_value=EJEC))),
                mock.patch.object(main.redaccion_ofertas, "cerrar", kw.get("cerrar", mock.AsyncMock()))]

    def con(self, parches, f):
        for p in parches:
            p.start()
        try:
            return f()
        finally:
            for p in parches:
                p.stop()

    def test_encola_la_redaccion_y_responde_202_con_la_ejecucion(self):
        fijar = mock.AsyncMock()
        ctx, app = celery_falso()
        with ctx:
            r = self.con(self.parches(fijar=fijar), lambda: como(("direccion",)).post(f"/licitaciones/ofertas/{ID}/redactar", json={"rehacer": True, "empresa": "101 Telecom S.L."}))
        self.assertEqual(r.status_code, 202)
        self.assertEqual(r.json()["ejecucion"]["id"], 4)
        app.send_task.assert_called_once_with("cerebro.tareas.celery_app.redactar_oferta", args=[4], queue="peticiones")
        fijar.assert_awaited_once_with(ID, "101 Telecom S.L.")                       # la sociedad queda guardada en la oferta

    def test_con_varias_sociedades_sin_elegir_devuelve_409_con_la_lista_y_no_encola(self):
        reservar = mock.AsyncMock()
        ctx, app = celery_falso()
        with ctx:
            r = self.con(self.parches(elegir=mock.AsyncMock(side_effect=E.VariasEmpresas(EMPRESAS)), reservar=reservar), lambda: como(("direccion",)).post(f"/licitaciones/ofertas/{ID}/redactar"))
        self.assertEqual(r.status_code, 409)
        self.assertEqual([e["nif"] for e in r.json()["detail"]["empresas"]], ["B1", "A2"])
        reservar.assert_not_called()
        app.send_task.assert_not_called()

    def test_si_el_erp_no_responde_la_redaccion_sigue(self):
        ctx, app = celery_falso()
        with ctx:
            r = self.con(self.parches(elegir=mock.AsyncMock(side_effect=E.ErrorEmpresa("No se ha podido leer el ERP"))), lambda: como(("direccion",)).post(f"/licitaciones/ofertas/{ID}/redactar"))
        self.assertEqual(r.status_code, 202)
        app.send_task.assert_called_once()

    def test_ya_en_curso_es_409_y_sin_cola_se_deshace(self):
        ctx, app = celery_falso()
        with ctx:
            r = self.con(self.parches(reservar=mock.AsyncMock(side_effect=R.Conflicto("Los agentes ya están trabajando"))), lambda: como(("direccion",)).post(f"/licitaciones/ofertas/{ID}/redactar"))
            self.assertEqual((r.status_code, r.json()["detail"]), (409, "Los agentes ya están trabajando"))
        cerrar = mock.AsyncMock()
        ctx, app = celery_falso(error=ConnectionError("sin redis"))
        with ctx:
            r = self.con(self.parches(cerrar=cerrar), lambda: como(("direccion",)).post(f"/licitaciones/ofertas/{ID}/redactar"))
        self.assertEqual(r.status_code, 503)
        cerrar.assert_awaited_once()                                                 # la ejecución no se queda «en curso» para siempre

    def test_los_demas_reciben_403_y_no_se_toca_nada(self):
        reservar = mock.AsyncMock()
        for ruta, metodo in ((f"/licitaciones/ofertas/{ID}/redactar", "post"), (f"/licitaciones/ofertas/{ID}/ejecucion", "get"), ("/licitaciones/empresas", "get"),
                             (f"/licitaciones/ofertas/{ID}/plantillas", "get"), (f"/licitaciones/ofertas/{ID}/plantillas", "post"), (f"/licitaciones/ofertas/{ID}/plantillas/1/fichero", "get")):
            r = self.con(self.parches(reservar=reservar), lambda: getattr(como(("usuario",), ("finanzas",)), metodo)(ruta))
            self.assertEqual(r.status_code, 403, ruta)
        reservar.assert_not_called()

    def test_la_ultima_ejecucion(self):
        with mock.patch.object(main.redaccion_ofertas, "ultima", mock.AsyncMock(return_value=EJEC)):
            self.assertEqual(como(("direccion",)).get(f"/licitaciones/ofertas/{ID}/ejecucion").json(), {"ejecucion": EJEC})


class TestPlantillas(unittest.TestCase):
    def tearDown(self):
        main.app.dependency_overrides.clear()

    def test_empresas_del_erp_y_su_error(self):
        with mock.patch.object(main.empresa_erp, "empresas", mock.AsyncMock(return_value=EMPRESAS)):
            self.assertEqual(como(("direccion",)).get("/licitaciones/empresas").json(), {"empresas": EMPRESAS})
        with mock.patch.object(main.empresa_erp, "empresas", mock.AsyncMock(side_effect=E.ErrorEmpresa("No se ha podido leer el ERP: inténtalo de nuevo"))):
            self.assertEqual(como(("direccion",)).get("/licitaciones/empresas").status_code, 503)

    def test_preparar_las_plantillas_con_la_sociedad_elegida(self):
        preparar = mock.AsyncMock(return_value={"documentos": []})
        with mock.patch.object(main.motor_lic, "_get", mock.AsyncMock(return_value={"titulo": "T"})), mock.patch.object(PL, "preparar", preparar):
            r = como(("direccion",)).post(f"/licitaciones/ofertas/{ID}/plantillas", json={"empresa": "Ion S.A."})
        self.assertEqual(r.status_code, 200)
        preparar.assert_awaited_once_with(ID, {"titulo": "T"}, "albert", "Ion S.A.")

    def test_los_errores_se_traducen(self):
        c = como(("direccion",))
        with mock.patch.object(main.motor_lic, "_get", mock.AsyncMock(return_value={})):
            for error, estado in ((E.VariasEmpresas(EMPRESAS), 409), (O.NoExiste("Esta licitación aún no tiene la oferta preparada"), 404), (PL.ErrorPlantilla("El documento 7 no está"), 422),
                                  (E.ErrorEmpresa("La empresa «x» no existe en el ERP"), 422)):
                with mock.patch.object(PL, "preparar", mock.AsyncMock(side_effect=error)):
                    self.assertEqual(c.post(f"/licitaciones/ofertas/{ID}/plantillas").status_code, estado, type(error).__name__)

    def test_descargar_entrega_el_fichero_en_base64(self):
        with mock.patch.object(PL, "fichero", mock.AsyncMock(return_value=("01 - Anexo (rellenado).docx", b"PK\x03\x04datos", PL.MIME["docx"]))):
            r = como(("direccion",)).get(f"/licitaciones/ofertas/{ID}/plantillas/3/fichero")
        d = r.json()
        self.assertEqual((r.status_code, d["nombre"], d["tipo"]), (200, "01 - Anexo (rellenado).docx", PL.MIME["docx"]))
        self.assertEqual(base64.b64decode(d["base64"]), b"PK\x03\x04datos")
        for error, estado in ((O.NoExiste("Ese documento no está preparado"), 404), (PL.ErrorPlantilla("El fichero no coincide"), 422)):
            with mock.patch.object(PL, "fichero", mock.AsyncMock(side_effect=error)):
                self.assertEqual(como(("direccion",)).get(f"/licitaciones/ofertas/{ID}/plantillas/3/fichero").status_code, estado)
        self.assertEqual(como(("direccion",)).get(f"/licitaciones/ofertas/{ID}/plantillas/no-es-numero/fichero").status_code, 422)


class TestFijarPrecio(unittest.TestCase):
    OFERTA = {"existe": True, "licitacion": ID, "precio_sin_iva": 125000.0, "iva_pct": 21.0}

    def setUp(self):
        p = mock.patch.object(main.crm_licitaciones, "anotar_por_oferta", mock.AsyncMock(return_value=None))      # el CRM no es lo que se prueba aquí
        self.crm = p.start()
        self.addCleanup(p.stop)

    def tearDown(self):
        main.app.dependency_overrides.clear()

    def post(self, listar, preparar):
        with mock.patch.object(main.ofertas_licitaciones, "fijar_precio", mock.AsyncMock(return_value=dict(self.OFERTA))) as fijar, mock.patch.object(PL, "listar", listar), \
                mock.patch.object(PL, "preparar", preparar), mock.patch.object(main.motor_lic, "_get", mock.AsyncMock(return_value={})):
            r = como(("direccion",)).post(f"/licitaciones/ofertas/{ID}/precio", json={"precio": 125000, "iva_pct": 21})
        return r, fijar

    def test_al_fijar_el_precio_los_modelos_ya_preparados_se_rellenan_con_el_importe(self):
        preparar = mock.AsyncMock(return_value={"documentos": [{}, {}]})
        r, fijar = self.post(mock.AsyncMock(return_value={"documentos": [{}]}), preparar)
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.json()["precio_sin_iva"], r.json()["plantillas_actualizadas"]), (125000.0, 2))
        fijar.assert_awaited_once_with(ID, 125000.0, 21.0, "albert")                      # lo fija la persona que pulsa, no un agente
        self.assertEqual(self.crm.await_args.args[0], ID)                                 # y queda anotado en el trato del CRM
        preparar.assert_awaited_once()

    def test_sin_plantillas_preparadas_no_se_toca_nada(self):
        preparar = mock.AsyncMock()
        r, _ = self.post(mock.AsyncMock(return_value={"documentos": []}), preparar)
        self.assertEqual(r.json()["plantillas_actualizadas"], 0)
        preparar.assert_not_called()

    def test_si_las_plantillas_fallan_el_precio_ya_esta_fijado(self):
        r, _ = self.post(mock.AsyncMock(return_value={"documentos": [{}]}), mock.AsyncMock(side_effect=E.ErrorEmpresa("No se ha podido leer el ERP")))
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.json()["plantillas_actualizadas"])
        self.assertEqual(r.json()["precio_sin_iva"], 125000.0)

    def test_precio_no_valido_y_permisos(self):
        with mock.patch.object(main.ofertas_licitaciones, "fijar_precio", mock.AsyncMock(side_effect=O.ErrorOferta("El precio no es válido"))):
            self.assertEqual(como(("direccion",)).post(f"/licitaciones/ofertas/{ID}/precio", json={"precio": -5}).status_code, 422)
        fijar = mock.AsyncMock()
        with mock.patch.object(main.ofertas_licitaciones, "fijar_precio", fijar):
            self.assertEqual(como(("usuario",), ("finanzas",)).post(f"/licitaciones/ofertas/{ID}/precio", json={"precio": 5}).status_code, 403)
        fijar.assert_not_called()


if __name__ == "__main__":
    unittest.main()
