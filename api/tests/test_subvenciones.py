"""Radar de subvenciones (ARES Funding Intelligence): normalización, deduplicación, tubería de sincronización, conector BDNS (con transporte simulado), catálogo, agentes y base de datos.
NINGUNA prueba toca la red: los datos de BDNS aquí son simulados y sus nombres de campo son los SUPUESTOS del conector, pendientes de verificar con el servicio real."""
import asyncio
import json
import os
import time
import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import _sin_servicios  # noqa: F401

try:
    import httpx
    import yaml
    from cerebro.subvenciones import deduplicar as D
    from cerebro.subvenciones import normalizar as N
    from cerebro.subvenciones import sincronizar as S
    from cerebro.subvenciones.almacen import AlmacenMemoria
    from cerebro.subvenciones.conectores import cargar
    from cerebro.subvenciones.conectores.base import ErrorConector, ErrorRegistro
    from cerebro.subvenciones.conectores.bdns import ConectorBDNS
except ImportError as e:      # pragma: no cover
    raise unittest.SkipTest(str(e))

RAIZ = Path(__file__).resolve().parents[2]
URL = os.environ.get("CEREBRO_TEST_PG")
HOY = date(2026, 11, 20)
PARAMS = {"paginas_maximas_por_ejecucion": 5, "tamano_pagina": 2, "pausa_entre_peticiones_s": 0, "reintentos": 0, "timeout_s": 5}


def ejecutar(c):
    return asyncio.run(c)


class TestNormalizar(unittest.TestCase):
    def test_fechas(self):
        self.assertEqual(N.fecha("2026-03-01"), date(2026, 3, 1))
        self.assertEqual(N.fecha("2026-03-01T10:00:00"), date(2026, 3, 1))
        self.assertEqual(N.fecha("01/03/2026"), date(2026, 3, 1))
        self.assertIsNone(N.fecha("31/02/2026"))
        self.assertIsNone(N.fecha("pronto"))
        self.assertIsNone(N.fecha(None))

    def test_importes(self):
        self.assertEqual(N.importe("1.234,56"), Decimal("1234.56"))
        self.assertEqual(N.importe("1234.56"), Decimal("1234.56"))
        self.assertEqual(N.importe(1500000.5), Decimal("1500000.5"))
        self.assertIsNone(N.importe("-5"))
        self.assertIsNone(N.importe("sin dato"))
        self.assertIsNone(N.importe(True))
        self.assertIsNone(N.importe(None))

    def test_instrumento_distingue_prestamo_participativo(self):
        self.assertEqual(N.instrumento("Subvención a fondo perdido"), "subvencion")
        self.assertEqual(N.instrumento("Préstamo participativo"), "prestamo_participativo")
        self.assertEqual(N.instrumento("Préstamo"), "prestamo")
        self.assertIsNone(N.instrumento(""))
        self.assertIsNone(N.instrumento("algo desconocido"))

    def test_estado_del_ciclo_de_vida(self):
        h = HOY
        d = lambda n: date.fromordinal(h.toordinal() + n)   # noqa: E731
        self.assertEqual(N.estado(None, d(-1), h), "CLOSED")
        self.assertEqual(N.estado(d(3), d(30), h), "OPENING_SOON")
        self.assertEqual(N.estado(d(-3), d(5), h), "CLOSING_SOON")
        self.assertEqual(N.estado(d(-3), d(60), h), "OPEN")
        self.assertEqual(N.estado(None, None, h), "UNKNOWN")
        self.assertEqual(N.estado(None, None, h, abierta_declarada=True), "OPEN")
        self.assertEqual(N.estado(d(-3), d(60), h, cancelada=True), "CANCELLED")
        self.assertEqual(N.estado(None, d(0), h), "CLOSING_SOON")      # el último día aún se puede presentar

    def test_huella_estable_y_cambios(self):
        a = {"title": "A", "deadline": date(2026, 12, 1), "sector": ["x", "y"]}
        b = {"title": "A", "deadline": date(2026, 12, 1), "sector": ["y", "x"]}
        self.assertEqual(N.huella_normalizada(a), N.huella_normalizada(b))
        c = N.cambios(a, {**a, "deadline": date(2026, 12, 20)})
        self.assertEqual([x["field"] for x in c], ["deadline"])
        # que la fuente deje de dar un campo no es un cambio: se conserva lo que ya se sabía
        self.assertEqual(N.cambios(a, {"title": "A", "deadline": None, "sector": []}), [])


class TestDeduplicar(unittest.TestCase):
    def test_identificadores(self):
        self.assertEqual(D.canonico("ES-001", " 900001 "), "BDNS:900001")
        self.assertEqual(D.canonico("EU-001", "HORIZON-X"), "EU:HORIZON-X")
        self.assertIsNone(D.canonico("ES-001", ""))
        self.assertEqual(D.referencias_canonicas({"bdns": "123", "otra": ""}), ["BDNS:123"])

    def test_huella_sin_id_es_exacta_no_difusa(self):
        base = {"issuing_organization": "Ayuntamiento X", "title": "Ayudas al comercio", "deadline": date(2026, 12, 1), "country": "ES"}
        self.assertEqual(D.id_canonico("ES-099", base, None), D.id_canonico("ES-099", {**base, "title": "AYUDAS AL COMERCIO"}, None))
        self.assertNotEqual(D.id_canonico("ES-099", base, None), D.id_canonico("ES-099", {**base, "title": "Ayudas al comercio local"}, None))
        self.assertTrue(D.id_canonico("ES-099", base, None).startswith("FP:"))


def opp(externo="1", titulo="Ayudas a la digitalización", **kw):
    o = {"title": titulo, "description": "d", "program_name": None, "issuing_organization": "Ministerio", "official_url": "https://x.es", "application_url": None,
         "country": "ES", "region": None, "province": None, "municipality": None, "geographic_scope": "nacional", "eligible_beneficiaries": ["PYME"], "company_sizes": [],
         "economic_activities": [], "sector": [], "keywords": [], "funding_objectives": None, "funding_type": "subvencion", "total_budget": Decimal("1000"), "minimum_amount": None,
         "maximum_amount": None, "funding_percentage": None, "currency": "EUR", "cofinancing_required": None, "publication_date": date(2026, 11, 1), "opening_date": date(2026, 11, 2),
         "deadline": date(2026, 12, 31), "last_official_update": None, "legal_basis_url": None, "eligibility_requirements": None, "exclusions": None, "eligible_expenses": None,
         "status": "OPEN", "_confidence": 0.9, "_external_id": externo, "_refs": {}, "_source_url": "https://x.es", "_documents": []}
    o.update(kw)
    return o


FUENTE_A = {"id": "fa", "source_code": "ES-001", "synchronization_frequency": 4}
FUENTE_B = {"id": "fb", "source_code": "ES-002", "synchronization_frequency": 24}
AHORA = datetime(2026, 11, 20, 10, 0, tzinfo=timezone.utc)


class TestGuardarRegistro(unittest.TestCase):
    def test_idempotente_y_con_historial(self):
        a = AlmacenMemoria()
        self.assertEqual(ejecutar(S.guardar_registro(a, FUENTE_A, opp(), {"n": 1}, AHORA)), "nuevo")
        self.assertEqual(ejecutar(S.guardar_registro(a, FUENTE_A, opp(), {"n": 1}, AHORA)), "sin_cambios")      # mismo registro de la fuente: nada
        self.assertEqual(len(a.oportunidades), 1)
        self.assertEqual(ejecutar(S.guardar_registro(a, FUENTE_A, opp(deadline=date(2027, 1, 15)), {"n": 2}, AHORA)), "actualizado")
        self.assertEqual([c["field"] for c in a.cambios], ["deadline"])
        self.assertEqual(len(a.oportunidades), 1)

    def test_otra_fuente_con_referencia_citada_se_une_y_solo_rellena_huecos(self):
        a = AlmacenMemoria()
        ejecutar(S.guardar_registro(a, FUENTE_A, opp("900001", region=None), {"n": 1}, AHORA))
        # el BOE cita el identificador BDNS: es la misma convocatoria; su plazo distinto NO pisa el de la fuente prioritaria, pero sí rellena la región que faltaba
        r = ejecutar(S.guardar_registro(a, FUENTE_B, opp("BOE-1", titulo="Extracto de la convocatoria", region="Cataluña", deadline=date(2027, 6, 1), _refs={"BDNS": "900001"}), {"n": 9}, AHORA))
        self.assertEqual(len(a.oportunidades), 1)
        o = next(iter(a.oportunidades.values()))
        self.assertEqual(o["deadline"], date(2026, 12, 31))
        self.assertEqual(o["title"], "Ayudas a la digitalización")
        self.assertEqual(o["region"], "Cataluña")
        self.assertIn(r, ("actualizado", "sin_cambios"))

    def test_sin_referencia_no_se_fusiona_por_parecido(self):
        a = AlmacenMemoria()
        ejecutar(S.guardar_registro(a, FUENTE_A, opp("1", titulo="Ayudas a la digitalización de pymes"), {"n": 1}, AHORA))
        ejecutar(S.guardar_registro(a, FUENTE_B, opp("2", titulo="Ayudas a la digitalizacion de pymes."), {"n": 2}, AHORA))
        self.assertEqual(len(a.oportunidades), 2)


class ConectorFalso:
    def __init__(self, paginas, error=None):
        self._p, self._error = paginas, error

    async def paginas(self, cursor, hoy):
        from cerebro.subvenciones.conectores.base import Pagina
        for i, regs in enumerate(self._p):
            yield Pagina(regs, {"pagina": i + 1})
        if self._error:
            raise self._error

    def normalizar(self, crudo, hoy):
        if crudo.get("malo"):
            raise ErrorRegistro("sin título")
        return opp(str(crudo["id"]), titulo=f"Convocatoria {crudo['id']}")


class TestSincronizar(unittest.TestCase):
    def test_cuenta_nuevos_invalidos_y_guarda_cursor(self):
        a = AlmacenMemoria()
        r = ejecutar(S.sincronizar_fuente(FUENTE_A, ConectorFalso([[{"id": 1}, {"id": 2}], [{"id": 3}, {"malo": True}]]), a, PARAMS, HOY, "manual"))
        self.assertEqual((r["estado"], r["fetched"], r["inserted"], r["invalid"]), ("ok", 4, 3, 1))
        self.assertEqual(a.cursores["fa"], {"pagina": 2})
        r2 = ejecutar(S.sincronizar_fuente(FUENTE_A, ConectorFalso([[{"id": 1}, {"id": 2}]]), a, PARAMS, HOY))
        self.assertEqual((r2["inserted"], r2["unchanged"]), (0, 2))

    def test_un_fallo_de_la_fuente_no_lanza_y_conserva_lo_importado(self):
        a = AlmacenMemoria()
        r = ejecutar(S.sincronizar_fuente(FUENTE_A, ConectorFalso([[{"id": 1}]], error=ErrorConector("la fuente no responde")), a, PARAMS, HOY))
        self.assertEqual(r["estado"], "error")
        self.assertIn("no responde", r["error"])
        self.assertEqual(len(a.oportunidades), 1)
        self.assertEqual(a.cursores["fa"], {"pagina": 1})       # la página buena quedó como punto de reanudación

    def test_un_error_inesperado_tampoco_lanza(self):
        r = ejecutar(S.sincronizar_fuente(FUENTE_A, ConectorFalso([[{"id": 1}]], error=KeyError("x")), AlmacenMemoria(), PARAMS, HOY))
        self.assertEqual(r["estado"], "error")

    def test_si_casi_todo_es_invalido_queda_parcial(self):
        r = ejecutar(S.sincronizar_fuente(FUENTE_A, ConectorFalso([[{"malo": True}, {"malo": True}, {"id": 1}]]), AlmacenMemoria(), PARAMS, HOY))
        self.assertEqual(r["estado"], "partial")


# ---- Conector BDNS con transporte simulado (campos SUPUESTOS) ----

def servidor(lista_por_pagina, detalles, fallo_detalle=False, peticiones=None):
    def h(req):
        if peticiones is not None:
            peticiones.append(req)
        if req.url.path.endswith("/convocatorias/busqueda"):
            p = int(req.url.params.get("page", 0))
            filas = lista_por_pagina[p] if p < len(lista_por_pagina) else []
            return httpx.Response(200, json={"content": filas, "last": p >= len(lista_por_pagina) - 1})
        if fallo_detalle:
            return httpx.Response(500, json={})
        return httpx.Response(200, json=detalles[req.url.params["numConv"]])
    return httpx.AsyncClient(transport=httpx.MockTransport(h))


FILA = {"numeroConvocatoria": "900001", "descripcion": "Ayudas a la digitalización de pymes", "nivel1": "ESTADO", "nivel2": "MINISTERIO DE INDUSTRIA"}
DETALLE = {"descripcion": "Ayudas a la digitalización de pymes", "presupuestoTotal": 1500000.5, "fechaInicioSolicitud": "2026-11-15", "fechaFinSolicitud": "2026-12-10",
           "sectores": [{"descripcion": "Tecnología"}], "tiposBeneficiarios": [{"descripcion": "PYME"}], "instrumentos": [{"descripcion": "Subvención"}], "sedeElectronica": "https://sede.example.gob.es"}


class TestConectorBDNS(unittest.TestCase):
    def conector(self, cliente, **ajustes):
        return ConectorBDNS({"id": "fa", "source_code": "ES-001", "settings": ajustes}, PARAMS, cliente)

    def test_normaliza_con_detalle(self):
        c = self.conector(servidor([[FILA]], {"900001": DETALLE}))
        pags = []

        async def todo():
            async for p in c.paginas({}, HOY):
                pags.append(p)
        ejecutar(todo())
        self.assertEqual(len(pags), 1)
        o = c.normalizar(pags[0].registros[0], HOY)
        self.assertEqual((o["_external_id"], o["country"], o["geographic_scope"], o["funding_type"]), ("900001", "ES", "nacional", "subvencion"))
        self.assertEqual((o["total_budget"], o["opening_date"], o["deadline"], o["status"]), (Decimal("1500000.5"), date(2026, 11, 15), date(2026, 12, 10), "OPEN"))
        self.assertGreater(o["_confidence"], 0.5)

    def test_solo_con_resumen_baja_la_confianza_y_no_inventa_fechas(self):
        c = self.conector(servidor([[FILA]], {}), con_detalle=False)
        pags = []

        async def todo():
            async for p in c.paginas({}, HOY):
                pags.append(p)
        ejecutar(todo())
        o = c.normalizar(pags[0].registros[0], HOY)
        self.assertLess(o["_confidence"], 0.5)
        self.assertIsNone(o["deadline"])
        self.assertEqual(o["status"], "UNKNOWN")

    def test_respuesta_real_de_la_bdns_verificada_el_19_11_2026(self):
        # Muestra real (datos públicos) devuelta por infosubvenciones.es: abierto=false sin fechas NO significa «cerrada» (el plazo era relativo a una publicación), y el territorio
        # viene como «ES431 - Badajoz» (NUTS3 = provincia).
        resumen = {"id": 1144687, "numeroConvocatoria": "943126", "descripcion": "AYUDAS PARA LA ADQUISICIÓN DE MATERIAL ESCOLAR CURSO 2026-2027", "descripcionLeng": None,
                   "fechaRecepcion": "2026-11-18", "nivel1": "LOCAL", "nivel2": "LLERENA", "nivel3": "AYUNTAMIENTO DE LLERENA"}
        detalle = {"organo": {"nivel1": "LOCAL", "nivel2": "LLERENA", "nivel3": "AYUNTAMIENTO DE LLERENA"}, "sedeElectronica": None, "codigoBDNS": "943126", "fechaRecepcion": "2026-11-18",
                   "instrumentos": [{"descripcion": "SUBVENCIÓN Y ENTREGA DINERARIA SIN CONTRAPRESTACIÓN "}], "presupuestoTotal": 5000,
                   "tiposBeneficiarios": [{"descripcion": "PERSONAS JURÍDICAS QUE NO DESARROLLAN ACTIVIDAD ECONÓMICA"}],
                   "sectores": [{"descripcion": "EDUCACIÓN", "codigo": "Q"}], "regiones": [{"descripcion": "ES431 - Badajoz"}], "descripcionFinalidad": "Educación",
                   "urlBasesReguladoras": "https://sede.llerena.es/", "abierto": False, "fechaInicioSolicitud": None, "fechaFinSolicitud": None,
                   "documentos": [{"id": 1558594, "descripcion": "Documento de la convocatoria", "nombreFic": "x.pdf", "long": 368206}]}
        o = self.conector(None).normalizar({"resumen": resumen, "detalle": detalle}, HOY)
        self.assertEqual((o["_external_id"], o["geographic_scope"], o["funding_type"], o["total_budget"]), ("943126", "local", "subvencion", Decimal("5000")))
        self.assertEqual((o["province"], o["region"], o["status"]), ("Badajoz", None, "UNKNOWN"))
        self.assertEqual(o["issuing_organization"], "LLERENA · AYUNTAMIENTO DE LLERENA")
        self.assertEqual(o["legal_basis_url"], "https://sede.llerena.es/")
        self.assertEqual(o["_documents"], [])               # los documentos de la BDNS no traen dirección de descarga: no se inventa
        a = self.conector(None).normalizar({"resumen": {**resumen, "nivel1": "AUTONOMICA", "nivel2": "PAÍS VASCO"}, "detalle": {**detalle, "regiones": [], "abierto": True,
                                                         "organo": {"nivel1": "AUTONOMICA", "nivel2": "PAÍS VASCO", "nivel3": "X"}}}, HOY)
        self.assertEqual((a["region"], a["status"]), ("País Vasco", "OPEN"))

    def test_registro_sin_id_o_titulo_es_invalido(self):
        c = self.conector(None)
        with self.assertRaises(ErrorRegistro):
            c.normalizar({"resumen": {"descripcion": "x"}, "detalle": None}, HOY)
        with self.assertRaises(ErrorRegistro):
            c.normalizar({"resumen": {"numeroConvocatoria": "5"}, "detalle": None}, HOY)

    def test_formato_inesperado_es_error_del_conector_no_datos_inventados(self):
        cliente = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"algo": "distinto"})))
        c = self.conector(cliente)

        async def todo():
            async for _ in c.paginas({}, HOY):
                pass
        with self.assertRaises(ErrorConector):
            ejecutar(todo())

    def test_error_http_y_no_json(self):
        for resp in (httpx.Response(503), httpx.Response(200, text="<html>")):
            c = self.conector(httpx.AsyncClient(transport=httpx.MockTransport(lambda r, resp=resp: resp)))

            async def todo():
                async for _ in c.paginas({}, HOY):
                    pass
            with self.assertRaises(ErrorConector):
                ejecutar(todo())

    def test_si_falla_la_mayoria_de_detalles_la_ejecucion_falla(self):
        c = self.conector(servidor([[FILA]], {}, fallo_detalle=True))

        async def todo():
            async for _ in c.paginas({}, HOY):
                pass
        with self.assertRaises(ErrorConector):
            ejecutar(todo())

    def test_pagina_y_reanuda_desde_el_cursor(self):
        peticiones = []
        filas = [[{**FILA, "numeroConvocatoria": "1"}, {**FILA, "numeroConvocatoria": "2"}], [{**FILA, "numeroConvocatoria": "3"}, {**FILA, "numeroConvocatoria": "4"}], [{**FILA, "numeroConvocatoria": "5"}]]
        det = {str(i): DETALLE for i in range(1, 6)}
        c = self.conector(servidor(filas, det, peticiones=peticiones))
        cursores = []

        async def todo(cursor):
            async for p in c.paginas(cursor, HOY):
                cursores.append(p.cursor)
        ejecutar(todo({}))
        self.assertEqual(len(cursores), 3)
        self.assertEqual(cursores[-1]["pagina"], 0)                     # al terminar, la siguiente vez empieza de nuevo desde una fecha reciente
        peticiones.clear()
        ejecutar(todo({"desde": "2026-11-01", "pagina": 2}))
        busquedas = [p for p in peticiones if p.url.path.endswith("busqueda")]
        self.assertEqual(busquedas[0].url.params["page"], "2")           # retoma por la página 2

    def test_cabeceras_y_sin_datos_privados(self):
        peticiones = []
        c = self.conector(servidor([[FILA]], {"900001": DETALLE}, peticiones=peticiones))

        async def todo():
            async for _ in c.paginas({}, HOY):
                pass
        ejecutar(todo())
        for p in peticiones:
            self.assertNotIn("authorization", p.headers)
            self.assertIn("ARES", p.headers["user-agent"])

    def test_tuberia_completa_con_el_conector(self):
        a = AlmacenMemoria()
        c = self.conector(servidor([[FILA]], {"900001": DETALLE}))
        r = ejecutar(S.sincronizar_fuente(FUENTE_A, c, a, PARAMS, HOY, "manual"))
        self.assertEqual((r["estado"], r["inserted"]), ("ok", 1))
        o = next(iter(a.oportunidades.values()))
        self.assertEqual(o["canonical_id"], "BDNS:900001")

    def test_el_nombre_del_conector_resuelve_y_el_desconocido_no(self):
        self.assertIs(cargar("bdns"), ConectorBDNS)
        self.assertIsNone(cargar("inventado"))
        self.assertIsNone(cargar(None))


# ---- Catálogo, herramienta y agentes ----

class TestCatalogoYAgentes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = yaml.safe_load((RAIZ / "config" / "subvenciones.yaml").read_text(encoding="utf-8"))

    def test_ninguna_fuente_nace_activa_y_ningun_conector_inexistente(self):
        codigos = [f["code"] for f in self.cfg["fuentes"]]
        self.assertEqual(len(codigos), len(set(codigos)))
        for f in self.cfg["fuentes"]:
            self.assertNotIn(f.get("status"), ("ACTIVE", "VERIFIED"), f["code"])
            if f.get("connector"):
                self.assertIsNotNone(cargar(f["connector"]), f"{f['code']} declara un conector que no existe")

    def test_una_fuente_sin_conector_siempre_esta_pendiente(self):
        # una dirección de API anotada en el catálogo es una pista a comprobar, no una conexión: sin conector, la fuente no puede figurar como conectada
        for f in self.cfg["fuentes"]:
            if not f.get("connector"):
                self.assertTrue(str(f.get("status", "")).startswith("PENDING"), f["code"])

    def test_la_herramienta_es_de_solo_lectura_y_esta_en_los_agentes_correctos(self):
        from cerebro.herramientas import base
        from cerebro.registro import registro
        h = base._REGISTRO["subvenciones"]
        self.assertEqual(set(h.operaciones), {"buscar", "ficha", "radar", "estado_fuentes"})
        reg = registro()
        con = {n for n, f in reg.fichas.items() if "subvenciones" in f.herramientas}
        self.assertTrue({"ayudas", "estratega", "tesorero", "analista-noticias"} <= con, con)
        # los agentes comerciales de otras áreas no la reciben (mínimo privilegio)
        self.assertNotIn("cotizador", con)

    def test_celery_programa_y_enruta_la_sincronizacion(self):
        from cerebro.tareas import celery_app as C
        self.assertEqual(C.app.conf.beat_schedule["subvenciones"]["task"], "cerebro.tareas.celery_app.sincronizar_subvenciones")
        rutas = C.app.conf.task_routes
        self.assertEqual(rutas["cerebro.tareas.celery_app.sincronizar_subvenciones"]["queue"], "lote")
        self.assertEqual(rutas["cerebro.tareas.celery_app.sincronizar_subvencion"]["queue"], "lote")


# ---- Base de datos real ----

@unittest.skipUnless(URL, "sin CEREBRO_TEST_PG")
class TestEnBaseDeDatos(unittest.TestCase):
    def setUp(self):
        import psycopg
        from cerebro.subvenciones import almacen, consulta, registro
        self.schema = f"t_sub_{time.time_ns()}"
        t = (RAIZ / "db" / "esquema.sql").read_text(encoding="utf-8")
        ini, fin = t.index("-- Subvenciones y financiación (ARES"), t.index("-- Fin subvenciones")
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"CREATE SCHEMA {self.schema}")
            c.execute(f"SET search_path = {self.schema}")
            c.execute(t[ini:fin])
            c.execute(t[ini:fin])           # el esquema es idempotente
        sep = "&" if "?" in URL else "?"
        self.ajs = SimpleNamespace(database_url=f"{URL}{sep}options=-csearch_path%3D{self.schema}", dir_config=RAIZ / "config")
        self.parches = [mock.patch.object(m, "ajustes", self.ajs) for m in (registro, almacen, consulta)]
        for p in self.parches:
            p.start()
        self.registro, self.consulta = registro, consulta

    def tearDown(self):
        import psycopg
        for p in self.parches:
            p.stop()
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"DROP SCHEMA {self.schema} CASCADE")

    def test_activacion_solo_tras_sincronizacion_manual_correcta_y_busqueda(self):
        r = self.registro
        ejecutar(r.alta_catalogo())
        ejecutar(r.alta_catalogo())                                   # idempotente: no duplica ni pisa el estado
        with self.assertRaises(r.ErrorFuentes):
            ejecutar(r.cambiar("ES-001", habilitada=True))            # sin sincronización previa
        with self.assertRaises(r.ErrorFuentes):
            ejecutar(r.cambiar("ES-002", habilitada=True))            # sin conector
        res = ejecutar(r.sincronizar_una("ES-001", "manual", cliente=servidor([[FILA]], {"900001": DETALLE})))
        self.assertEqual((res["estado"], res["inserted"]), ("ok", 1))
        res = ejecutar(r.sincronizar_una("ES-001", "manual", cliente=servidor([[FILA]], {"900001": DETALLE})))
        self.assertEqual((res["inserted"], res["unchanged"]), (0, 1))
        b = ejecutar(self.consulta.buscar({"texto": "digitalización"}))
        self.assertEqual(b["total"], 1)
        self.assertEqual(b["resultados"][0]["novedad"], "NEW")
        oid = b["resultados"][0]["id"]
        d2 = json.loads(json.dumps(DETALLE))
        d2["fechaFinSolicitud"] = "2026-12-20"
        ejecutar(r.sincronizar_una("ES-001", "manual", cliente=servidor([[FILA]], {"900001": d2})))
        f = ejecutar(self.consulta.ficha(oid, "ana"))
        self.assertIn("deadline", [h["field"] for h in f["historial"]])
        self.assertEqual(f["fuentes"][0]["source_code"], "ES-001")
        self.assertIsNone(f["guardada"])
        ejecutar(self.consulta.guardar("ana", oid, "seguida", "101.cat", None, "mirar"))
        self.assertEqual(len(ejecutar(self.consulta.guardadas("ana"))), 1)
        self.assertEqual(len(ejecutar(self.consulta.guardadas("otra"))), 0)          # lo guardado es de cada persona
        self.assertEqual(ejecutar(r.cambiar("ES-001", habilitada=True))["is_enabled"], True)
        rd = ejecutar(self.consulta.radar("ana"))
        self.assertEqual(rd["abiertas"]["total"], 1)

    def test_filtros_validados_y_sin_inyeccion(self):
        with self.assertRaises(self.consulta.ErrorConsulta):
            ejecutar(self.consulta.buscar({"orden": "id; DROP TABLE funding_opportunities"}))
        with self.assertRaises(self.consulta.ErrorConsulta):
            ejecutar(self.consulta.buscar({"plazo_desde": "ayer"}))
        with self.assertRaises(self.consulta.ErrorConsulta):
            ejecutar(self.consulta.buscar({"importe_min": "mucho"}))
        self.assertEqual(ejecutar(self.consulta.buscar({"texto": "'; DROP TABLE funding_opportunities; --"}))["total"], 0)
        self.assertEqual(ejecutar(self.consulta.buscar({}))["total"], 0)

    def test_una_fuente_que_falla_queda_anotada_y_no_se_activa(self):
        r = self.registro
        ejecutar(r.alta_catalogo())
        cliente = httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(503)))
        res = ejecutar(r.sincronizar_una("ES-001", "manual", cliente=cliente))
        self.assertEqual(res["estado"], "error")
        with self.assertRaises(r.ErrorFuentes):
            ejecutar(r.cambiar("ES-001", habilitada=True))
        f = next(x for x in ejecutar(r.listar()) if x["source_code"] == "ES-001")
        self.assertTrue(f["last_error"])
        self.assertIsNone(f["last_success_at"])


if __name__ == "__main__":
    unittest.main()
