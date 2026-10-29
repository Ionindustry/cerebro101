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



class TestRutasDelEmbudo(unittest.TestCase):
    FILA = {"id": 7, "motor_id": "0b1f7a3e-1111-4222-8333-444444444444", "estado": "en_estudio"}

    def tearDown(self):
        main.app.dependency_overrides.clear()

    def test_los_demas_reciben_403_y_no_se_toca_nada(self):
        e = main.embudo_licitaciones
        espias = {n: mock.AsyncMock() for n in ("resumen", "listar", "estudiar", "cambiar_estado")}
        with mock.patch.multiple(e, **espias):
            c = como(("usuario", "responsable"), ("finanzas", "comercial"))
            for metodo, ruta, cuerpo in (("get", "/licitaciones/embudo/resumen", None), ("get", "/licitaciones/embudo", None),
                                         ("post", "/licitaciones/embudo/estudiar", {"motor_id": "x"}), ("post", "/licitaciones/embudo/7/estado", {"estado": "presentada"})):
                r = getattr(c, metodo)(ruta, json=cuerpo) if cuerpo else getattr(c, metodo)(ruta)
                self.assertEqual(r.status_code, 403, ruta)
        for n, espia in espias.items():
            espia.assert_not_called()

    def test_direccion_y_licitaciones_lo_ven_y_lo_cambian(self):
        e = main.embudo_licitaciones
        with mock.patch.object(e, "resumen", mock.AsyncMock(return_value={"dias": 30})), mock.patch.object(e, "listar", mock.AsyncMock(return_value=[self.FILA])), \
                mock.patch.object(e, "estudiar", mock.AsyncMock(return_value=self.FILA)), mock.patch.object(e, "cambiar_estado", mock.AsyncMock(return_value=self.FILA)) as cambiar:
            for roles, deps in ((("direccion",), ()), ((), ("licitaciones",))):
                c = como(roles, deps)
                self.assertEqual(c.get("/licitaciones/embudo/resumen?dias=7").json(), {"dias": 30})
                lista = c.get("/licitaciones/embudo?estado=en_estudio").json()
                self.assertEqual(lista["items"], [self.FILA])
                self.assertIn("precio", lista["motivos_perdida"])
                self.assertEqual(lista["transiciones"]["presentada"], ["ganada", "perdida"])
                self.assertEqual(c.post("/licitaciones/embudo/estudiar", json={"motor_id": self.FILA["motor_id"]}).json(), self.FILA)
                self.assertEqual(c.post("/licitaciones/embudo/7/estado", json={"estado": "perdida", "motivo_perdida": "precio"}).status_code, 200)
            cambiar.assert_awaited_with(7, "perdida", "precio")

    def test_errores_de_validacion_y_de_existencia(self):
        e = main.embudo_licitaciones
        c = como(("direccion",))
        with mock.patch.object(e, "resumen", mock.AsyncMock(side_effect=e.ErrorEmbudo("dias debe estar entre 1 y 365"))):
            self.assertEqual(c.get("/licitaciones/embudo/resumen?dias=0").status_code, 422)
        with mock.patch.object(e, "cambiar_estado", mock.AsyncMock(side_effect=e.ErrorEmbudo("No se puede"))):
            self.assertEqual(c.post("/licitaciones/embudo/7/estado", json={"estado": "ganada"}).status_code, 422)
        with mock.patch.object(e, "cambiar_estado", mock.AsyncMock(side_effect=e.NoExiste("No existe"))):
            self.assertEqual(c.post("/licitaciones/embudo/99/estado", json={"estado": "presentada"}).status_code, 404)
        self.assertEqual(c.post("/licitaciones/embudo/7/estado", json={}).status_code, 422)          # falta el estado
        self.assertEqual(c.post("/licitaciones/embudo/no-es-numero/estado", json={"estado": "presentada"}).status_code, 422)

    def test_pedir_viabilidad_encola_y_traduce_los_rechazos(self):
        e = main.embudo_licitaciones
        peticion = {"estado": "en_curso", "por": "u", "en": "2026-10-28T10:00:00+00:00"}
        c = como(("usuario", "responsable"), ("finanzas", "comercial"))
        with mock.patch.object(e, "reservar_peticion_viabilidad", mock.AsyncMock()) as reservar:
            self.assertEqual(c.post("/licitaciones/embudo/7/viabilidad").status_code, 403)
            reservar.assert_not_called()
        c = como(("direccion",))
        with mock.patch.object(e, "reservar_peticion_viabilidad", mock.AsyncMock(return_value=peticion)) as reservar, mock.patch("cerebro.tareas.celery_app.app.send_task") as encolar:
            r = c.post("/licitaciones/embudo/7/viabilidad", json={"reemplazar": True})
            self.assertEqual((r.status_code, r.json()["viabilidad_peticion"]), (202, peticion))
            self.assertEqual(reservar.await_args.args[0], 7)
            self.assertTrue(reservar.await_args.args[2])
            encolar.assert_called_once_with("cerebro.tareas.celery_app.pedir_viabilidad", args=[7], queue="peticiones")
            self.assertEqual(c.post("/licitaciones/embudo/7/viabilidad").status_code, 202)         # sin cuerpo: no reemplaza
            self.assertFalse(reservar.await_args.args[2])
        for fallo, codigo in ((e.NoExiste("x"), 404), (e.Conflicto("x"), 409), (e.ErrorEmbudo("x"), 422)):
            with mock.patch.object(e, "reservar_peticion_viabilidad", mock.AsyncMock(side_effect=fallo)), mock.patch("cerebro.tareas.celery_app.app.send_task") as encolar:
                self.assertEqual(c.post("/licitaciones/embudo/7/viabilidad").status_code, codigo)
                encolar.assert_not_called()

    def test_si_no_se_puede_encolar_se_deshace_la_reserva(self):
        e = main.embudo_licitaciones
        c = como(("direccion",))
        with mock.patch.object(e, "reservar_peticion_viabilidad", mock.AsyncMock(return_value={})), mock.patch.object(e, "cerrar_peticion_viabilidad", mock.AsyncMock()) as cerrar, \
                mock.patch("cerebro.tareas.celery_app.app.send_task", side_effect=OSError("sin cola")):
            self.assertEqual(c.post("/licitaciones/embudo/7/viabilidad").status_code, 503)
            cerrar.assert_awaited_once()

    def test_calendario_de_plazos_permisos_y_errores(self):
        cp = main.calendario_plazos
        e = main.embudo_licitaciones
        c = como(("usuario", "responsable"), ("finanzas", "comercial"))
        with mock.patch.object(cp, "poner", mock.AsyncMock()) as poner, mock.patch.object(cp, "quitar", mock.AsyncMock()) as quitar:
            self.assertEqual(c.post("/licitaciones/embudo/7/calendario").status_code, 403)
            self.assertEqual(c.post("/licitaciones/embudo/7/calendario/quitar").status_code, 403)
            poner.assert_not_called()
            quitar.assert_not_called()
        c = como(("direccion",))
        with mock.patch.object(cp, "poner", mock.AsyncMock(return_value=self.FILA)), mock.patch.object(cp, "quitar", mock.AsyncMock(return_value=self.FILA)):
            self.assertEqual(c.post("/licitaciones/embudo/7/calendario").json(), self.FILA)
            self.assertEqual(c.post("/licitaciones/embudo/7/calendario/quitar").json(), self.FILA)
        for fallo, codigo in ((e.NoExiste("x"), 404), (e.ErrorEmbudo("x"), 422), (cp.ErrorCalendario("x"), 503)):
            with mock.patch.object(cp, "poner", mock.AsyncMock(side_effect=fallo)):
                self.assertEqual(c.post("/licitaciones/embudo/7/calendario").status_code, codigo)
        with mock.patch.object(cp, "quitar", mock.AsyncMock(side_effect=cp.ErrorCalendario("x"))):
            self.assertEqual(c.post("/licitaciones/embudo/7/calendario/quitar").status_code, 503)

    def test_simulador_permisos_y_errores(self):
        sm = main.simulador_licitaciones
        c = como(("usuario", "responsable"), ("finanzas", "comercial"))
        with mock.patch.object(sm, "simular", mock.AsyncMock(return_value={})) as espia:
            self.assertEqual(c.post("/licitaciones/simulador", json={"motor_id": "x"}).status_code, 403)
            espia.assert_not_called()
        c = como(("direccion",))
        ok = {"muestra": {"n": 40}, "apto_para_decidir": True}
        with mock.patch.object(sm, "simular", mock.AsyncMock(return_value=ok)) as espia:
            self.assertEqual(c.post("/licitaciones/simulador", json={"motor_id": "x", "coste": 1000}).json(), ok)
            self.assertEqual(espia.await_args.args[:2], ("x", 1000.0))
        for fallo, codigo in ((sm.ErrorSimulador("sin presupuesto"), 422), (main.MotorNoDisponible("x"), 503), (LookupError("No existe"), 404)):
            with mock.patch.object(sm, "simular", mock.AsyncMock(side_effect=fallo)):
                self.assertEqual(c.post("/licitaciones/simulador", json={"motor_id": "x"}).status_code, codigo, repr(fallo))
        self.assertEqual(c.post("/licitaciones/simulador", json={"coste": 5}).status_code, 422)                # falta la licitación

    def test_matriz_de_cumplimiento_permisos_rutas_y_errores(self):
        pl = main.pliegos_licitaciones
        espias = {n: mock.AsyncMock(return_value={}) for n in ("matriz", "marcar_cumplimiento")}
        with mock.patch.multiple(pl, **espias):
            c = como(("usuario", "responsable"), ("finanzas", "comercial"))
            self.assertEqual(c.get("/licitaciones/pliegos/x/matriz").status_code, 403)
            self.assertEqual(c.post("/licitaciones/pliegos/requisitos/3/cumplimiento", json={"estado": "cumple"}).status_code, 403)
        for espia in espias.values():
            espia.assert_not_called()
        c = como(("direccion",))
        with mock.patch.multiple(pl, matriz=mock.AsyncMock(return_value={"total": 2, "filas": []}),
                                 marcar_cumplimiento=mock.AsyncMock(return_value={"id": 3, "cumplimiento": "parcial"})):
            self.assertEqual(c.get("/licitaciones/pliegos/x/matriz").json(), {"total": 2, "filas": []})
            self.assertEqual(c.post("/licitaciones/pliegos/requisitos/3/cumplimiento", json={"estado": "parcial", "nota": "falta un año"}).json()["cumplimiento"], "parcial")
            pl.marcar_cumplimiento.assert_awaited_with(3, "parcial", "falta un año", "albert")
        for fallo, codigo in ((pl.ErrorPliego("confirma primero"), 422), (pl.NoExiste("No existe ese requisito"), 404)):
            with mock.patch.object(pl, "marcar_cumplimiento", mock.AsyncMock(side_effect=fallo)):
                self.assertEqual(c.post("/licitaciones/pliegos/requisitos/9/cumplimiento", json={"estado": "cumple"}).status_code, codigo)

    def test_pliegos_permisos_rutas_y_errores(self):
        pl = main.pliegos_licitaciones
        espias = {n: mock.AsyncMock(return_value={"requisitos": [], "documentos": []}) for n in ("documentos", "requisitos", "obtener", "leer", "revisar_requisito")}
        c = como(("usuario", "responsable"), ("finanzas", "comercial"))
        with mock.patch.multiple(pl, **espias):
            for metodo, ruta, cuerpo in (("get", "/licitaciones/pliegos/x", None), ("post", "/licitaciones/pliegos/x/descargar", {"n": 1}),
                                         ("get", "/licitaciones/pliegos/x/documentos/1/paginas/1", None), ("post", "/licitaciones/pliegos/requisitos/3/revisar", {"estado": "confirmado"})):
                r = getattr(c, metodo)(ruta, json=cuerpo) if cuerpo else getattr(c, metodo)(ruta)
                self.assertEqual(r.status_code, 403, ruta)
        for n, espia in espias.items():
            espia.assert_not_called()
        c = como(("direccion",))
        with mock.patch.multiple(pl, documentos=mock.AsyncMock(return_value={"licitacion": "x", "documentos": [{"n": 1}]}),
                                 requisitos=mock.AsyncMock(return_value={"requisitos": [{"id": 4}]}), obtener=mock.AsyncMock(return_value={"estado": "limpio"}),
                                 leer=mock.AsyncMock(return_value={"texto": "t"}), revisar_requisito=mock.AsyncMock(return_value={"id": 3, "estado": "confirmado"})) as _:
            self.assertEqual(c.get("/licitaciones/pliegos/x").json(), {"licitacion": "x", "documentos": [{"n": 1}], "requisitos": [{"id": 4}]})
            self.assertEqual(c.post("/licitaciones/pliegos/x/descargar", json={"n": 1}).json(), {"estado": "limpio"})
            self.assertEqual(c.get("/licitaciones/pliegos/x/documentos/1/paginas/2").json(), {"texto": "t"})
            self.assertEqual(c.post("/licitaciones/pliegos/requisitos/3/revisar", json={"estado": "confirmado"}).json()["estado"], "confirmado")
            pl.revisar_requisito.assert_awaited_with(3, "confirmado", "albert")
        for fallo, codigo in ((pl.ErrorPliego("x"), 422), (pl.SinPermisoDescarga("x"), 403), (LookupError("x"), 404), (main.MotorNoDisponible("x"), 503)):
            with mock.patch.object(pl, "obtener", mock.AsyncMock(side_effect=fallo)):
                self.assertEqual(c.post("/licitaciones/pliegos/x/descargar", json={"n": 1}).status_code, codigo, repr(fallo))
        with mock.patch.object(pl, "revisar_requisito", mock.AsyncMock(side_effect=pl.NoExiste("No existe ese requisito"))):
            self.assertEqual(c.post("/licitaciones/pliegos/requisitos/9/revisar", json={"estado": "confirmado"}).status_code, 404)
        with mock.patch.object(pl, "revisar_requisito", mock.AsyncMock(side_effect=pl.ErrorPliego("estado debe ser"))):
            self.assertEqual(c.post("/licitaciones/pliegos/requisitos/9/revisar", json={"estado": "raro"}).status_code, 422)
        self.assertEqual(c.post("/licitaciones/pliegos/x/descargar", json={}).status_code, 422)             # falta n

    def test_estudiar_sin_motor_o_con_un_expediente_que_no_existe(self):
        e = main.embudo_licitaciones
        c = como(("direccion",))
        with mock.patch.object(e, "estudiar", mock.AsyncMock(side_effect=main.MotorNoDisponible("no responde"))):
            r = c.post("/licitaciones/embudo/estudiar", json={"motor_id": "0b1f7a3e-1111-4222-8333-444444444444"})
            self.assertEqual(r.status_code, 503)
            self.assertIn("no responde", r.json()["detail"])
        with mock.patch.object(e, "estudiar", mock.AsyncMock(side_effect=LookupError("x"))):
            self.assertEqual(c.post("/licitaciones/embudo/estudiar", json={"motor_id": "0b1f7a3e-1111-4222-8333-444444444444"}).status_code, 404)
        with mock.patch.object(e, "estudiar", mock.AsyncMock(side_effect=e.ErrorEmbudo("motor_id no es un identificador válido"))):
            self.assertEqual(c.post("/licitaciones/embudo/estudiar", json={"motor_id": "mal"}).status_code, 422)


class TestRutasDeAlertas(unittest.TestCase):
    ALERTA = {"id": 3, "nombre": "Videovigilancia", "ambito": "personal", "puede_cambiar": True}
    ENTRADA = {"nombre": "Videovigilancia", "ambito": "personal", "filtro": {"cpv": ["32"]}, "eventos": ["licitacion.nueva"], "canal": "panel"}

    def tearDown(self):
        main.app.dependency_overrides.clear()

    def test_sin_acceso_a_licitaciones_todo_es_403(self):
        sin = como(("usuario",), ("finanzas",))
        for metodo, ruta, cuerpo in (("get", "/licitaciones/alertas", None), ("post", "/licitaciones/alertas", self.ENTRADA), ("post", "/licitaciones/alertas/3", {"activa": False}),
                                     ("post", "/licitaciones/alertas/3/borrar", None), ("get", "/licitaciones/avisos", None), ("post", "/licitaciones/avisos/leer", {})):
            r = getattr(sin, metodo)(ruta, json=cuerpo) if cuerpo is not None else getattr(sin, metodo)(ruta)
            self.assertEqual(r.status_code, 403, ruta)

    def test_listar_crear_cambiar_y_borrar(self):
        a = main.alertas_licitaciones
        with mock.patch.object(a, "listar", mock.AsyncMock(return_value=[self.ALERTA])), mock.patch.object(a, "crear", mock.AsyncMock(return_value=self.ALERTA)) as crear, \
                mock.patch.object(a, "cambiar", mock.AsyncMock(return_value=self.ALERTA)) as cambiar, mock.patch.object(a, "borrar", mock.AsyncMock()) as borrar:
            c = como(("usuario",), ("licitaciones",))
            lista = c.get("/licitaciones/alertas").json()
            self.assertEqual((lista["items"], lista["canales"], "licitacion.nueva" in lista["eventos"]), ([self.ALERTA], ["panel", "resumen_diario", "correo"], True))
            self.assertEqual(c.post("/licitaciones/alertas", json=self.ENTRADA).json(), self.ALERTA)
            self.assertEqual(crear.await_args.args[1]["filtro"], {"cpv": ["32"]})
            self.assertEqual(c.post("/licitaciones/alertas/3", json={"activa": False}).status_code, 200)
            cambiar.assert_awaited_once()
            self.assertEqual(cambiar.await_args.args[1:], (3, {"activa": False}))          # solo lo que se manda: no se pisa nada con valores por defecto
            c.post("/licitaciones/alertas/3", json={"canal": "resumen_diario"})
            self.assertEqual(cambiar.await_args.args[1:], (3, {"canal": "resumen_diario"}))
            self.assertEqual(c.post("/licitaciones/alertas/3/borrar").json(), {"borrada": 3})
            borrar.assert_awaited_once()

    def test_errores_se_traducen_a_codigos_http(self):
        a = main.alertas_licitaciones
        c = como(("usuario",), ("licitaciones",))
        for exc, codigo in ((a.ErrorAlerta("mal"), 422), (a.SinPermiso("no"), 403)):
            with mock.patch.object(a, "crear", mock.AsyncMock(side_effect=exc)):
                self.assertEqual(c.post("/licitaciones/alertas", json=self.ENTRADA).status_code, codigo)
        with mock.patch.object(a, "cambiar", mock.AsyncMock(side_effect=a.NoExiste("no hay"))):
            self.assertEqual(c.post("/licitaciones/alertas/9", json={"activa": True}).status_code, 404)
        with mock.patch.object(a, "borrar", mock.AsyncMock(side_effect=a.SinPermiso("no"))):
            self.assertEqual(c.post("/licitaciones/alertas/9/borrar").status_code, 403)
        self.assertEqual(c.post("/licitaciones/alertas", json={"nombre": "x"}).status_code, 422)            # faltan campos: lo rechaza la validación de la entrada
        self.assertEqual(c.post("/licitaciones/alertas/no-es-numero", json={"activa": True}).status_code, 422)

    def test_avisos(self):
        a = main.alertas_licitaciones
        with mock.patch.object(a, "listar_avisos", mock.AsyncMock(return_value={"sin_leer": 2, "items": []})) as listar, \
                mock.patch.object(a, "marcar_leidos", mock.AsyncMock(return_value=2)) as leer:
            c = como(("usuario",), ("licitaciones",))
            self.assertEqual(c.get("/licitaciones/avisos?no_leidos=true&limite=10").json(), {"sin_leer": 2, "items": []})
            self.assertEqual(listar.await_args.args[1:], (True, 10))
            self.assertEqual(c.post("/licitaciones/avisos/leer", json={}).json(), {"leidos": 2})
            self.assertIsNone(leer.await_args.args[1])                                                       # sin ids: todos los que ve
            c.post("/licitaciones/avisos/leer", json={"ids": [1, 2]})
            self.assertEqual(leer.await_args.args[1], [1, 2])
        with mock.patch.object(a, "marcar_leidos", mock.AsyncMock(side_effect=a.ErrorAlerta("ids"))):
            self.assertEqual(c.post("/licitaciones/avisos/leer", json={"ids": [1]}).status_code, 422)


if __name__ == "__main__":
    unittest.main()
