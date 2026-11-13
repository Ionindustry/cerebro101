"""«Qué hacer hoy»: una lista por persona, ordenada por urgencia, con lo que ve cada una según sus permisos; una fuente rota no la tumba."""
import asyncio
import os
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import _sin_servicios  # noqa: F401

try:
    import psycopg
    from cerebro import hoy as H
    from cerebro.aprobaciones import bandeja
except ImportError as e:      # pragma: no cover
    raise unittest.SkipTest(str(e))

URL = os.environ.get("CEREBRO_TEST_PG")
ESQUEMA = Path(__file__).resolve().parents[2] / "db" / "esquema.sql"
AHORA = datetime(2026, 11, 5, 8, 0, tzinfo=timezone.utc)


def ejecutar(c):
    return asyncio.run(c)


def fuente(valor):
    async def f(*a):
        return valor
    return f


def lic(i, estado="en_estudio", dias=10, urgente=False, vencido=False, borradores=0, bloqueos=0):
    return {"id": i, "motor_id": f"0b1f7a3e-1111-4222-8333-44444444444{i}", "titulo": f"Licitación {i}", "organismo": "Ayto", "estado": estado, "dias_plazo": dias, "urgente": urgente,
            "vencido": vencido, "requisitos": {"borrador": borradores, "confirmado": 0}, "bloqueos": bloqueos}


SEG = {"estado": "ok", "items": [lic(1, dias=1, urgente=True, borradores=3, bloqueos=1), lic(2, dias=-2, vencido=True), lic(3, "presentada", None), lic(4, dias=20, borradores=2)]}
APROB = [{"creado": AHORA - timedelta(hours=30), "accion": "correo.enviar", "datos": {"resumen": "Enviar el presupuesto a X"}}, {"creado": AHORA - timedelta(hours=1), "accion": "otra", "datos": {}}]
AV_MAL = {"estado": "viejas", "edad_horas": 53.5, "limite_horas": 48, "motivo": "Las firmas del antivirus tienen 53 horas"}
COP_MAL = {"alerta": True, "motivo": "Hace 4 días de la última copia de seguridad correcta", "ultima": {"ok": True}}
MOTOR_OK = {"estado": "ok", "edad_h": 0.2, "poniendose_al_dia": False}


class TestPuros(unittest.TestCase):
    def test_aprobaciones_pendientes_urgentes_si_alguna_espera_mas_de_24_horas(self):
        r = H.de_aprobaciones(APROB, AHORA)
        self.assertEqual((r[0]["nivel"], r[0]["titulo"], r[0]["href"]), ("urgente", "2 aprobaciones pendientes", "/aprobaciones"))
        self.assertIn("30 h", r[0]["detalle"])
        self.assertEqual(H.de_aprobaciones(APROB[1:], AHORA)[0]["nivel"], "aviso")
        self.assertEqual(H.de_aprobaciones([], AHORA), [])

    def test_licitaciones_plazos_urgentes_vencidos_y_requisitos_por_revisar(self):
        r = H.de_licitaciones(SEG)
        titulos = [i["titulo"] for i in r]
        self.assertIn("Plazo mañana: Licitación 1", titulos)
        self.assertIn("Plazo vencido: Licitación 2", titulos)
        self.assertIn("5 requisitos del pliego por revisar", titulos)                 # 3 + 2; las presentadas no cuentan
        self.assertEqual(len(r), 3)
        self.assertIn("1 probablemente no se cumplen", next(i["detalle"] for i in r if "requisitos" in i["titulo"]))
        self.assertEqual(H.de_licitaciones({"estado": "error"}), [])
        self.assertEqual(H.de_licitaciones(None), [])

    def test_novedades_del_ultimo_resumen(self):
        r = H.de_novedades({"fecha": "2026-11-04", "contenido": {"totales": {"oportunidades": 7}, "oportunidades": [{"encaje": 92, "titulo": "Renting de cámaras"}]}})
        self.assertEqual((r[0]["nivel"], r[0]["titulo"]), ("info", "7 oportunidades nuevas en el último resumen (2026-11-04)"))
        self.assertIn("Renting de cámaras", r[0]["detalle"])
        self.assertEqual(H.de_novedades({"contenido": {"oportunidades": []}}), [])
        self.assertEqual(H.de_novedades(None), [])

    def test_sistema_antivirus_copias_y_motor(self):
        r = H.del_sistema(AV_MAL, COP_MAL, {"estado": "no_responde"})
        self.assertEqual([(i["nivel"], i["titulo"].split(":")[0]) for i in r], [("urgente", "Antivirus"), ("urgente", "Copias de seguridad"), ("urgente", "El motor de licitaciones no responde")])
        self.assertEqual(H.del_sistema({**AV_MAL, "edad_horas": 40}, None, None)[0]["nivel"], "aviso")                 # aún se aceptan documentos
        self.assertEqual(H.del_sistema({"estado": "ok"}, {"alerta": False, "ultima": {"ok": False, "mensaje": "pg_dump falló"}}, MOTOR_OK)[0]["titulo"], "La última copia de seguridad falló")
        self.assertEqual(H.del_sistema(None, None, {"estado": "ok", "edad_h": 5.4})[0]["titulo"], "El motor lleva 5 h sin ingesta correcta")
        self.assertEqual(H.del_sistema(None, None, {"estado": "ok", "edad_h": 0.1, "poniendose_al_dia": True})[0]["nivel"], "info")
        self.assertEqual(H.del_sistema({"estado": "ok"}, {"alerta": False, "ultima": {"ok": True}}, MOTOR_OK), [])


class TestPrecios(unittest.TestCase):
    def fila(self, id_=7, dias=1, estado="propuesta", **r):
        return {"id": id_, "estado": estado, "creado": AHORA - timedelta(days=dias), "resumen": {"incluidos": 40, "sube": 5, "baja": 2, **r}}

    def test_propuesta_reciente_es_un_aviso_con_enlace_directo(self):
        [i] = H.de_precios([self.fila()], AHORA)
        self.assertEqual((i["nivel"], i["categoria"], i["href"]), ("aviso", "precios", "/precios?propuesta=7"))
        self.assertIn("40 artículos listos", i["detalle"])
        self.assertIn("5 suben, 2 bajan", i["detalle"])

    def test_bajo_minimo_y_provisional_se_dicen(self):
        [i] = H.de_precios([self.fila(bajo_minimo=3, provisional=["costes de respaldo"])], AHORA)
        self.assertIn("3 artículos por debajo del margen mínimo", i["detalle"])
        self.assertIn("provisionales", i["detalle"])
        [i] = H.de_precios([self.fila(bajo_minimo=1)], AHORA)
        self.assertIn("1 artículo por debajo", i["detalle"])

    def test_sin_revisar_hace_dias_avisa_de_desactualizada_y_urgente_a_las_dos_semanas(self):
        [i] = H.de_precios([self.fila(dias=8)], AHORA)
        self.assertEqual(i["nivel"], "aviso")
        self.assertIn("hace 8 días", i["detalle"])
        self.assertIn("desactualizados", i["detalle"])
        [i] = H.de_precios([self.fila(dias=15)], AHORA)
        self.assertEqual(i["nivel"], "urgente")

    def test_con_error_es_urgente(self):
        [i] = H.de_precios([self.fila(estado="error")], AHORA)
        self.assertEqual(i["nivel"], "urgente")
        self.assertIn("se puede repetir", i["detalle"])

    def test_solo_las_tres_mas_nuevas_y_vacio(self):
        filas = [self.fila(id_=n) for n in (9, 8, 7, 6, 5)]
        self.assertEqual([i["href"] for i in H.de_precios(filas, AHORA)], ["/precios?propuesta=9", "/precios?propuesta=8", "/precios?propuesta=7"])
        self.assertEqual(H.de_precios([], AHORA), [])
        self.assertEqual(H.de_precios(None, AHORA), [])

    def test_solo_direccion_los_ve_en_hoy(self):
        base = {"aprobaciones": fuente([]), "seguimiento": fuente(SEG), "ultimo_resumen": fuente(None), "antivirus": fuente(AV_MAL), "copias": fuente(COP_MAL), "motor": fuente(MOTOR_OK),
                "tarifas": fuente([]), "precios_venta": fuente([self.fila()])}
        d = ejecutar(H.construir(["direccion"], [], AHORA, **base))
        self.assertTrue(any(i["categoria"] == "precios" for i in d["items"]))
        d = ejecutar(H.construir([], ["operaciones"], AHORA, **base))
        self.assertFalse(any(i["categoria"] == "precios" for i in d["items"]))


class TestConstruir(unittest.TestCase):
    def lista(self, roles, deps, **kw):
        base = {"aprobaciones": fuente(APROB), "seguimiento": fuente(SEG), "ultimo_resumen": fuente(None), "antivirus": fuente(AV_MAL), "copias": fuente(COP_MAL), "motor": fuente(MOTOR_OK), "tarifas": fuente([]), "precios_venta": fuente([])}
        return ejecutar(H.construir(roles, deps, AHORA, **{**base, **kw}))

    def test_direccion_lo_ve_todo_ordenado_por_urgencia(self):
        r = self.lista({"direccion"}, set())
        niveles = [i["nivel"] for i in r["items"]]
        self.assertEqual(niveles, sorted(niveles, key={"urgente": 0, "aviso": 1, "info": 2}.get))
        self.assertEqual(niveles[0], "urgente")
        cats = {i["categoria"] for i in r["items"]}
        self.assertEqual(cats, {"aprobaciones", "licitaciones", "sistema"})
        self.assertEqual((r["urgentes"], r["secciones"]), (sum(1 for n in niveles if n == "urgente"), {"licitaciones": True, "sistema": True}))

    def test_cada_persona_solo_ve_lo_de_sus_departamentos(self):
        r = self.lista({"usuario"}, {"licitaciones"})
        self.assertEqual({i["categoria"] for i in r["items"]}, {"aprobaciones", "licitaciones"})        # sin Tecnología no se ven los avisos del sistema
        self.assertEqual(r["secciones"], {"licitaciones": True, "sistema": False})
        r = self.lista({"usuario"}, {"tecnologia"})
        self.assertEqual({i["categoria"] for i in r["items"]}, {"aprobaciones", "sistema"})
        r = self.lista({"usuario"}, {"marketing"}, aprobaciones=fuente([]))
        self.assertEqual((r["items"], r["secciones"]), ([], {"licitaciones": False, "sistema": False}))

    def test_a_las_aprobaciones_se_les_pasan_los_departamentos_de_la_persona(self):
        vistos = []

        async def aprob(deps):
            vistos.append(deps)
            return []
        self.lista({"direccion"}, {"a"}, aprobaciones=aprob)
        self.lista({"usuario"}, {"a", "b"}, aprobaciones=aprob)
        self.lista({"usuario"}, set(), aprobaciones=aprob)
        self.assertEqual(vistos, [None, {"a", "b"}, set()])                                  # Dirección: todas; sin departamentos: un conjunto vacío (ninguna)

    def test_una_fuente_rota_se_omite_con_aviso_y_el_resto_sigue(self):
        async def rota(*a):
            raise RuntimeError("sin base de datos")
        r = self.lista({"direccion"}, set(), aprobaciones=rota, antivirus=rota)
        self.assertEqual(sorted(r["avisos"]), ["No se ha podido leer: antivirus", "No se ha podido leer: aprobaciones"])
        self.assertTrue(any(i["categoria"] == "licitaciones" for i in r["items"]))


class TestCacheDelEndpoint(unittest.TestCase):
    def test_la_misma_lista_se_reutiliza_30_segundos_y_depende_solo_de_los_permisos(self):
        from cerebro.api import main
        from cerebro.api.main import Usuario, usuario_actual
        from fastapi.testclient import TestClient
        llamadas = []

        async def construir(roles, deps, ahora=None, **kw):
            llamadas.append((frozenset(roles), frozenset(deps)))
            return {"items": [], "urgentes": 0, "avisos": [], "secciones": {}}
        main._CACHE_HOY.clear()
        try:
            with mock.patch.object(main.hoy, "construir", construir):
                for quien, roles, deps in (("a", {"usuario"}, {"licitaciones"}), ("b", {"usuario"}, {"licitaciones"}), ("c", {"direccion"}, set())):
                    main.app.dependency_overrides[usuario_actual] = lambda q=quien, r=roles, d=deps: Usuario(q, r, d)
                    self.assertEqual(TestClient(main.app).get("/hoy").status_code, 200)
                self.assertEqual(len(llamadas), 2)                                  # a y b (mismos permisos) comparten la lista; Dirección tiene la suya
                with mock.patch.object(main.time, "monotonic", lambda: 10_000_000.0):
                    main.app.dependency_overrides[usuario_actual] = lambda: Usuario("a", {"usuario"}, {"licitaciones"})
                    TestClient(main.app).get("/hoy")
                self.assertEqual(len(llamadas), 3)                                  # pasados los 30 s se vuelve a construir
        finally:
            main.app.dependency_overrides.clear()
            main._CACHE_HOY.clear()


@unittest.skipUnless(URL and hasattr(psycopg, "AsyncConnection"), "sin CEREBRO_TEST_PG")
class TestBandeja(unittest.TestCase):
    def setUp(self):
        self.schema = f"t_hoy_{time.time_ns()}"
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"CREATE SCHEMA {self.schema}")
            c.execute(f"SET search_path = {self.schema}")
            t = ESQUEMA.read_text(encoding="utf-8")
            c.execute(t[t.index("CREATE TABLE IF NOT EXISTS aprobaciones ("):t.index("CREATE INDEX IF NOT EXISTS aprobaciones_estado_idx")])
            for i, dep in enumerate(("licitaciones", "finanzas")):
                c.execute("INSERT INTO aprobaciones (id, hilo, agente, departamento, accion, nivel, aprobadores, datos) VALUES (gen_random_uuid(), %s, 'x', %s, 'a', 'simple', '{}', '{}')", [f"h{i}", dep])
        sep = "&" if "?" in URL else "?"
        self.parche = mock.patch.object(bandeja, "ajustes", SimpleNamespace(database_url=f"{URL}{sep}options=-csearch_path%3D{self.schema}"))
        self.parche.start()

    def tearDown(self):
        self.parche.stop()
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"DROP SCHEMA {self.schema} CASCADE")

    def test_pendientes_none_es_todas_y_un_conjunto_vacio_es_ninguna(self):
        self.assertEqual(len(ejecutar(bandeja.pendientes(None))), 2)
        self.assertEqual([f["departamento"] for f in ejecutar(bandeja.pendientes({"licitaciones"}))], ["licitaciones"])
        self.assertEqual(ejecutar(bandeja.pendientes(set())), [])                         # antes devolvía las dos: una persona sin departamentos veía todo

    def test_el_endpoint_responde_a_una_persona_identificada(self):
        from cerebro.api import main
        from cerebro.api.main import Usuario, usuario_actual
        from fastapi.testclient import TestClient
        main.app.dependency_overrides[usuario_actual] = lambda: Usuario("albert", {"usuario"}, {"finanzas"})
        try:
            r = TestClient(main.app).get("/hoy")
        finally:
            main.app.dependency_overrides.clear()
        self.assertEqual(r.status_code, 200)
        self.assertEqual([i["categoria"] for i in r.json()["items"]], ["aprobaciones"])      # solo la de Finanzas


class TestArchivo(unittest.TestCase):
    def test_solo_los_vencidos_se_pueden_archivar_y_llevan_su_clave(self):
        items = H.de_licitaciones(SEG)
        vencidos = [i for i in items if i["archivable"]]
        self.assertEqual([i["titulo"] for i in vencidos], ["Plazo vencido: Licitación 2"])
        self.assertEqual(vencidos[0]["clave"], "plazo-vencido:0b1f7a3e-1111-4222-8333-444444444442")
        self.assertTrue(all(i["clave"] is None for i in items if not i["archivable"]))

    def test_la_lista_sin_archivados_recalcula_contadores_y_no_toca_el_original(self):
        datos = {"items": [{"nivel": "urgente", "clave": None}, {"nivel": "aviso", "clave": "plazo-vencido:a"}, {"nivel": "urgente", "clave": "plazo-vencido:b"}], "urgentes": 2}
        r = H.sin_archivados(datos, {"plazo-vencido:b"})
        self.assertEqual([r["urgentes"], r["archivados"], len(r["items"])], [1, 1, 2])
        self.assertEqual(len(datos["items"]), 3)

    def test_clave_valida(self):
        self.assertTrue(H.CLAVE_VALIDA.match("plazo-vencido:0b1f7a3e-1111"))
        for mala in ("", "plazo vencido:1", "x:'; drop", "sin-dos-puntos", "a:" + "b" * 65):
            self.assertIsNone(H.CLAVE_VALIDA.match(mala), mala)


@unittest.skipUnless(URL and hasattr(psycopg, "AsyncConnection"), "sin CEREBRO_TEST_PG")
class TestArchivoEnBD(unittest.TestCase):
    def setUp(self):
        self.schema = f"t_hoyarch_{time.time_ns()}"
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"CREATE SCHEMA {self.schema}")
            c.execute(f"SET search_path = {self.schema}")
            t = ESQUEMA.read_text(encoding="utf-8")
            c.execute(t[t.index("CREATE TABLE IF NOT EXISTS hoy_archivados"):])
        sep = "&" if "?" in URL else "?"
        self.parche = mock.patch.object(H, "ajustes", SimpleNamespace(database_url=f"{URL}{sep}options=-csearch_path%3D{self.schema}"))
        self.parche.start()

    def tearDown(self):
        self.parche.stop()
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"DROP SCHEMA {self.schema} CASCADE")

    def test_archivar_listar_y_recuperar_es_por_persona(self):
        item = [i for i in H.de_licitaciones(SEG) if i["archivable"]][0]
        ejecutar(H.archivar("ana", item))
        ejecutar(H.archivar("ana", item))                                                      # repetir no duplica
        self.assertEqual([f["titulo"] for f in ejecutar(H.archivo("ana"))], ["Plazo vencido: Licitación 2"])
        self.assertEqual(ejecutar(H.archivo("luis")), [])                                       # lo de Ana no es de Luis
        self.assertEqual(ejecutar(H.claves_archivadas("ana")), {item["clave"]})
        self.assertFalse(ejecutar(H.desarchivar("luis", item["clave"])))
        self.assertTrue(ejecutar(H.desarchivar("ana", item["clave"])))
        self.assertEqual(ejecutar(H.archivo("ana")), [])

    def test_lo_que_no_es_archivable_se_rechaza(self):
        with self.assertRaises(ValueError):
            ejecutar(H.archivar("ana", H.de_aprobaciones([{"creado": AHORA, "accion": "x", "datos": {}}], AHORA)[0]))

    def test_el_endpoint_archiva_oculta_y_recupera(self):
        from cerebro.api import main
        from cerebro.api.main import Usuario, usuario_actual
        from fastapi.testclient import TestClient

        async def construir(roles, deps, ahora=None, **kw):
            items = H.de_licitaciones(SEG)
            return {"items": items, "urgentes": sum(1 for i in items if i["nivel"] == "urgente"), "avisos": [], "secciones": {}}
        main._CACHE_HOY.clear()
        main.app.dependency_overrides[usuario_actual] = lambda: Usuario("ana", {"direccion"}, set())
        try:
            with mock.patch.object(main.hoy, "construir", construir):
                c = TestClient(main.app)
                clave = [i["clave"] for i in c.get("/hoy").json()["items"] if i["clave"]][0]
                self.assertEqual(c.post("/hoy/archivar", json={"clave": "plazo-vencido:no-existe"}).status_code, 404)
                self.assertEqual(c.post("/hoy/archivar", json={"clave": clave}).status_code, 200)
                d = c.get("/hoy").json()
                self.assertNotIn(clave, [i["clave"] for i in d["items"]])
                self.assertEqual(d["archivados"], 1)
                self.assertEqual([i["clave"] for i in c.get("/hoy/archivo").json()["items"]], [clave])
                self.assertEqual(c.post("/hoy/desarchivar", json={"clave": clave}).status_code, 200)
                self.assertEqual(c.post("/hoy/desarchivar", json={"clave": clave}).status_code, 404)
                self.assertIn(clave, [i["clave"] for i in c.get("/hoy").json()["items"]])
        finally:
            main.app.dependency_overrides.clear()
            main._CACHE_HOY.clear()


if __name__ == "__main__":
    unittest.main()
