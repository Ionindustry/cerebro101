"""Alertas de licitaciones: validación, permisos (puros) y almacenamiento en PostgreSQL real (con CEREBRO_TEST_PG; sin ella, esa parte se omite)."""
import asyncio
import os
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import _sin_servicios  # noqa: F401

try:
    import psycopg
    from cerebro.herramientas import licitaciones as motor
    from cerebro.licitaciones import alertas, resumen
    from cerebro.licitaciones.alertas import ErrorAlerta, NoExiste, SinPermiso
except ImportError as e:      # pragma: no cover
    raise unittest.SkipTest(str(e))

URL = os.environ.get("CEREBRO_TEST_PG")
ESQUEMA = Path(__file__).resolve().parents[2] / "db" / "esquema.sql"
AHORA = datetime(2026, 10, 28, 14, 0, tzinfo=timezone.utc)
ID = "0b1f7a3e-1111-4222-8333-444444444444"


def u(id="albert", roles=(), deps=()):
    return SimpleNamespace(id=id, roles=set(roles), departamentos=set(deps))


ALBERT = u("albert", ("usuario",), ("licitaciones",))
RESPONSABLE = u("marta", ("usuario", "responsable"), ("licitaciones",))
DIRECCION = u("direccion1", ("direccion",))
SIN_ACCESO = u("ana", ("usuario",), ("finanzas",))


def entrada(**kw):
    d = {"nombre": "Videovigilancia en Girona", "ambito": "personal", "filtro": {"cpv": ["32323500"], "nuts": ["ES512"]},
         "eventos": ["licitacion.nueva"], "canal": "panel"}
    d.update(kw)
    return d


class TestFiltro(unittest.TestCase):
    def test_filtro_valido_y_normalizado(self):
        f = alertas.limpiar_filtro({"q": " videovigilancia ", "cpv": ["72", "72", "35125300"], "nuts": ["ES512"], "estado": ["abierta"], "importe_max": "250000.50",
                                    "comprador": ["nif:P1708500E", "dir3:L01170001"], "procedimiento": ["abierto"]})
        self.assertEqual(f["q"], "videovigilancia")
        self.assertEqual(f["cpv"], ["72", "35125300"])             # sin repetidos
        self.assertEqual(f["importe_max"], "250000.50")

    def test_rechaza_lo_que_el_motor_rechazaria_o_no_se_puede_evaluar(self):
        malos = [{}, [], "cpv", {"cpv": []}, {"cpv": "72"}, {"cpv": ["7"]}, {"cpv": ["72000000x"]}, {"nuts": ["es51"]}, {"estado": ["rara"]}, {"procedimiento": ["x"]},
                 {"q": "a"}, {"q": "x" * 201}, {"q": "a\nb"}, {"importe_min": "abc"}, {"importe_min": "1,5"}, {"importe_min": 5}, {"comprador": ["otra cosa"]},
                 {"orden": "importe"}, {"actualizada_desde": "2026-01-01T00:00:00Z"}, {"cpv": ["72"] * 21 + ["73"]}, {"cpv": [f"{n:02d}" for n in range(10, 31)]}]
        for f in malos:
            with self.assertRaises(ErrorAlerta, msg=f):
                alertas.limpiar_filtro(f)

    def test_eventos_nombre_canal_departamento(self):
        self.assertEqual(alertas.limpiar_eventos(["licitacion.anulada", "licitacion.nueva", "licitacion.nueva"]), ["licitacion.nueva", "licitacion.anulada"])
        for mal in ([], None, "licitacion.nueva", ["licitacion.rara"], [1]):
            with self.assertRaises(ErrorAlerta, msg=mal):
                alertas.limpiar_eventos(mal)
        for mal in ("", "  ", "x" * 121, None, "a\nb"):
            with self.assertRaises(ErrorAlerta, msg=mal):
                alertas.limpiar_nombre(mal)
        self.assertEqual(alertas.limpiar_canal("panel"), "panel")
        self.assertEqual(alertas.limpiar_canal("resumen_diario", "departamento"), "resumen_diario")
        for mal in ("sms", None, ""):
            with self.assertRaises(ErrorAlerta, msg=mal):
                alertas.limpiar_canal(mal)
        with self.assertRaises(ErrorAlerta):                                       # una personal no puede salir en el resumen que ve Dirección
            alertas.limpiar_canal("resumen_diario", "personal")
        self.assertEqual(alertas.limpiar_canal("panel", "personal"), "panel")
        self.assertEqual(alertas.limpiar_canal("correo", "personal"), "correo")                # el correo lo puede pedir también una alerta personal
        self.assertIsNone(alertas.limpiar_departamento("personal", None))
        self.assertEqual(alertas.limpiar_departamento("departamento", "licitaciones"), "licitaciones")
        for ambito, d in (("personal", "licitaciones"), ("departamento", None), ("departamento", "No Valido"), ("otro", None)):
            with self.assertRaises(ErrorAlerta, msg=(ambito, d)):
                alertas.limpiar_departamento(ambito, d)

    def test_el_correo_de_destino_solo_de_la_empresa(self):
        dom = ["101.cat"]
        self.assertEqual(alertas.limpiar_correo("  Marta.Puig@101.CAT ", dom), "marta.puig@101.cat")
        self.assertEqual(alertas.limpiar_correo("a+b@101.cat"), "a+b@101.cat")                 # con la configuración real (config/buzones.yaml)
        for mal in ("", None, 5, "sin-arroba", "x@gmail.com", "x@101.cat.evil.com", "x@evil101.cat", "x@sub.101.cat", "a@b@101.cat", "x y@101.cat", "x@101.cat\nBcc: z@y.com",
                    "a@101.cat,b@gmail.com", "<x@101.cat>", "x" * 65 + "@101.cat"):
            with self.assertRaises(ErrorAlerta, msg=mal):
                alertas.limpiar_correo(mal, dom)
        self.assertIsNone(alertas.limpiar_destino("panel", "x@101.cat", dom))                  # con otro canal no se guarda
        self.assertEqual(alertas.limpiar_destino("correo", "x@101.cat", dom), "x@101.cat")
        for falta in (None, ""):
            with self.assertRaises(ErrorAlerta):
                alertas.limpiar_destino("correo", falta, dom)

    def test_la_consulta_al_motor_lleva_el_filtro_la_fuente_y_el_id_de_origen(self):
        p = alertas.parametros_de_consulta({"cpv": ["72"]}, "placsp", "https://x/1")
        self.assertEqual(p, {"cpv": ["72"], "fuente": "placsp", "id_origen": "https://x/1", "limit": 1})


class TestPermisos(unittest.TestCase):
    PERSONAL = {"ambito": "personal", "propietario": "albert", "departamento": None}
    DEPTO = {"ambito": "departamento", "propietario": "marta", "departamento": "licitaciones"}

    def test_acceso_a_licitaciones(self):
        for x in (ALBERT, RESPONSABLE, DIRECCION, u("s", ("servicio",))):
            self.assertTrue(alertas.con_acceso(x))
        self.assertFalse(alertas.con_acceso(SIN_ACCESO))

    def test_una_personal_es_solo_de_su_dueno_ni_siquiera_direccion_la_ve(self):
        self.assertTrue(alertas.puede_ver(ALBERT, self.PERSONAL) and alertas.puede_cambiar(ALBERT, self.PERSONAL))
        for otro in (RESPONSABLE, DIRECCION, SIN_ACCESO):
            self.assertFalse(alertas.puede_ver(otro, self.PERSONAL), otro.id)
            self.assertFalse(alertas.puede_cambiar(otro, self.PERSONAL), otro.id)

    def test_una_de_departamento_la_ven_los_miembros_y_direccion_pero_la_cambia_el_responsable_o_direccion(self):
        self.assertTrue(alertas.puede_ver(ALBERT, self.DEPTO))
        self.assertFalse(alertas.puede_cambiar(ALBERT, self.DEPTO))                  # miembro sin ser responsable
        self.assertTrue(alertas.puede_cambiar(RESPONSABLE, self.DEPTO))
        self.assertTrue(alertas.puede_ver(DIRECCION, self.DEPTO) and alertas.puede_cambiar(DIRECCION, self.DEPTO))
        ajeno = u("pep", ("usuario", "responsable"), ("comercial",))                 # responsable, pero de otro departamento
        self.assertFalse(alertas.puede_ver(ajeno, self.DEPTO) or alertas.puede_cambiar(ajeno, self.DEPTO))
        self.assertFalse(alertas.puede_ver(SIN_ACCESO, self.DEPTO))

    def test_quien_puede_crear(self):
        self.assertTrue(alertas.puede_crear(ALBERT, "personal", None))
        self.assertFalse(alertas.puede_crear(SIN_ACCESO, "personal", None))
        self.assertFalse(alertas.puede_crear(ALBERT, "departamento", "licitaciones"))
        self.assertTrue(alertas.puede_crear(RESPONSABLE, "departamento", "licitaciones"))
        self.assertFalse(alertas.puede_crear(RESPONSABLE, "departamento", "comercial"))      # no es de su departamento
        self.assertTrue(alertas.puede_crear(DIRECCION, "departamento", "comercial"))


def ejecutar(coro):
    return asyncio.run(coro)


@unittest.skipUnless(URL and hasattr(psycopg, "AsyncConnection"), "sin CEREBRO_TEST_PG")
class TestEnBase(unittest.TestCase):
    def setUp(self):
        self.schema = f"t_alertas_{time.time_ns()}"
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"CREATE SCHEMA {self.schema}")
            c.execute(f"SET search_path = {self.schema}")
            t = ESQUEMA.read_text(encoding="utf-8")
            self.bloque = t[t.index("-- Alertas de licitaciones"):t.index("-- Resumen diario de licitaciones")]
            c.execute(self.bloque)
        sep = "&" if "?" in URL else "?"
        self.parche = mock.patch.object(alertas, "ajustes", SimpleNamespace(database_url=f"{URL}{sep}options=-csearch_path%3D{self.schema}"))
        self.parche.start()

    def tearDown(self):
        self.parche.stop()
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"DROP SCHEMA {self.schema} CASCADE")

    def datos(self, **kw):
        d = {"motor_id": ID, "titulo": "Videovigilancia del puerto", "organismo": "Girona", "encaje": 82, "importe": None, "fecha_limite": "2026-11-20T10:00:00Z",
             "enlace": "https://x/1", "estado_motor": "abierta"}
        d.update(kw)
        return d

    def test_el_esquema_se_puede_aplicar_dos_veces(self):
        with psycopg.connect(self.url_directa(), autocommit=True) as c:
            c.execute(self.bloque)
            c.execute(self.bloque)

    def url_directa(self):
        sep = "&" if "?" in URL else "?"
        return f"{URL}{sep}options=-csearch_path%3D{self.schema}"

    def test_crear_listar_cambiar_y_borrar(self):
        a = ejecutar(alertas.crear(ALBERT, entrada()))
        self.assertEqual((a["nombre"], a["propietario"], a["ambito"], a["eventos"], a["canal"], a["activa"], a["puede_cambiar"]),
                         ("Videovigilancia en Girona", "albert", "personal", ["licitacion.nueva"], "panel", True, True))
        self.assertEqual(a["filtro"], {"cpv": ["32323500"], "nuts": ["ES512"]})
        self.assertEqual([x["id"] for x in ejecutar(alertas.listar(ALBERT))], [a["id"]])
        b = ejecutar(alertas.cambiar(ALBERT, a["id"], {"nombre": "Otro nombre", "activa": False, "eventos": ["licitacion.nueva", "licitacion.anulada"]}))
        self.assertEqual((b["nombre"], b["activa"], b["eventos"]), ("Otro nombre", False, ["licitacion.nueva", "licitacion.anulada"]))
        self.assertEqual(ejecutar(alertas.activas_para("licitacion.nueva")), [])             # inactiva: no avisa
        ejecutar(alertas.cambiar(ALBERT, a["id"], {"activa": True}))
        self.assertEqual([x["id"] for x in ejecutar(alertas.activas_para("licitacion.anulada"))], [a["id"]])
        self.assertEqual(ejecutar(alertas.activas_para("licitacion.adjudicada")), [])
        ejecutar(alertas.borrar(ALBERT, a["id"]))
        self.assertEqual(ejecutar(alertas.listar(ALBERT)), [])

    def test_lo_ajeno_no_existe_y_lo_que_no_puedes_cambiar_da_permiso_denegado(self):
        a = ejecutar(alertas.crear(ALBERT, entrada()))
        for otro in (RESPONSABLE, DIRECCION):                        # una personal es solo de su dueño
            with self.assertRaises(NoExiste):
                ejecutar(alertas.cambiar(otro, a["id"], {"activa": False}))
            with self.assertRaises(NoExiste):
                ejecutar(alertas.borrar(otro, a["id"]))
            self.assertEqual(ejecutar(alertas.listar(otro)), [])
        d = ejecutar(alertas.crear(RESPONSABLE, entrada(ambito="departamento", departamento="licitaciones")))
        self.assertEqual({x["id"]: x["puede_cambiar"] for x in ejecutar(alertas.listar(ALBERT))}, {a["id"]: True, d["id"]: False})
        with self.assertRaises(SinPermiso):                            # la ve pero no la cambia
            ejecutar(alertas.cambiar(ALBERT, d["id"], {"activa": False}))
        with self.assertRaises(SinPermiso):
            ejecutar(alertas.borrar(ALBERT, d["id"]))
        with self.assertRaises(SinPermiso):
            ejecutar(alertas.listar(SIN_ACCESO))
        with self.assertRaises(NoExiste):
            ejecutar(alertas.cambiar(ALBERT, 99999, {"activa": False}))

    def test_crear_exige_permiso_y_valida(self):
        with self.assertRaises(SinPermiso):
            ejecutar(alertas.crear(ALBERT, entrada(ambito="departamento", departamento="licitaciones")))
        with self.assertRaises(SinPermiso):
            ejecutar(alertas.crear(SIN_ACCESO, entrada()))
        for mal in (entrada(filtro={}), entrada(eventos=[]), entrada(nombre=""), entrada(canal="correo"), entrada(departamento="licitaciones"), entrada(canal="resumen_diario")):
            with self.assertRaises(ErrorAlerta, msg=mal):
                ejecutar(alertas.crear(ALBERT, mal))
        self.assertEqual(ejecutar(alertas.listar(ALBERT)), [])

    def test_el_cambio_solo_admite_ciertos_campos(self):
        a = ejecutar(alertas.crear(ALBERT, entrada()))
        for mal in ({}, {"ambito": "departamento"}, {"propietario": "otro"}, {"activa": "si"}, {"filtro": {}}, {"canal": "correo"}, {"canal": "resumen_diario"}):
            with self.assertRaises(ErrorAlerta, msg=mal):
                ejecutar(alertas.cambiar(ALBERT, a["id"], mal))

    def test_tope_de_alertas_por_persona(self):
        with mock.patch.object(alertas, "MAX_ALERTAS_POR_PERSONA", 2):
            ejecutar(alertas.crear(ALBERT, entrada(nombre="1")))
            ejecutar(alertas.crear(ALBERT, entrada(nombre="2")))
            with self.assertRaises(ErrorAlerta):
                ejecutar(alertas.crear(ALBERT, entrada(nombre="3")))

    def test_un_evento_avisa_una_sola_vez_por_alerta(self):
        a = ejecutar(alertas.crear(ALBERT, entrada()))
        self.assertFalse(ejecutar(alertas.ya_avisada(a["id"], "e1")))
        self.assertTrue(ejecutar(alertas.registrar_aviso(a["id"], "e1", "licitacion.nueva", self.datos(), AHORA)))
        self.assertFalse(ejecutar(alertas.registrar_aviso(a["id"], "e1", "licitacion.nueva", self.datos(), AHORA)))        # reentrega
        self.assertTrue(ejecutar(alertas.ya_avisada(a["id"], "e1")))
        self.assertTrue(ejecutar(alertas.registrar_aviso(a["id"], "e2", "licitacion.nueva", self.datos(), AHORA)))
        r = ejecutar(alertas.listar_avisos(ALBERT))
        self.assertEqual((r["sin_leer"], len(r["items"])), (2, 2))
        self.assertEqual(ejecutar(alertas.listar(ALBERT))[0]["ultima_entrega"], AHORA.isoformat())

    def test_los_avisos_los_ve_quien_ve_la_alerta_y_se_marcan_como_leidos(self):
        mia = ejecutar(alertas.crear(ALBERT, entrada()))
        dep = ejecutar(alertas.crear(RESPONSABLE, entrada(ambito="departamento", departamento="licitaciones", nombre="Del equipo")))
        ejecutar(alertas.registrar_aviso(mia["id"], "e1", "licitacion.nueva", self.datos(), AHORA))
        ejecutar(alertas.registrar_aviso(dep["id"], "e1", "licitacion.nueva", self.datos(), AHORA))
        self.assertEqual({x["alerta"] for x in ejecutar(alertas.listar_avisos(ALBERT))["items"]}, {"Videovigilancia en Girona", "Del equipo"})
        self.assertEqual({x["alerta"] for x in ejecutar(alertas.listar_avisos(RESPONSABLE))["items"]}, {"Del equipo"})      # la personal de Albert no es suya
        self.assertEqual(ejecutar(alertas.listar_avisos(DIRECCION))["sin_leer"], 1)                                       # Dirección ve las de departamento, no las personales
        self.assertEqual(ejecutar(alertas.marcar_leidos(RESPONSABLE)), 1)                                                  # solo toca lo que ve
        self.assertEqual(ejecutar(alertas.listar_avisos(ALBERT))["sin_leer"], 1)                                           # el de departamento ya está leído; el suyo no
        self.assertEqual(ejecutar(alertas.listar_avisos(ALBERT, solo_no_leidos=True))["items"][0]["alerta"], "Videovigilancia en Girona")
        self.assertEqual(ejecutar(alertas.marcar_leidos(ALBERT, [10 ** 9])), 0)
        self.assertEqual(ejecutar(alertas.marcar_leidos(ALBERT)), 1)
        with self.assertRaises(ErrorAlerta):
            ejecutar(alertas.marcar_leidos(ALBERT, ["x"]))

    def test_el_canal_del_resumen_solo_en_alertas_de_departamento_tambien_al_cambiarlo(self):
        dep = ejecutar(alertas.crear(RESPONSABLE, entrada(ambito="departamento", departamento="licitaciones", canal="resumen_diario")))
        self.assertEqual(dep["canal"], "resumen_diario")
        self.assertEqual(ejecutar(alertas.cambiar(RESPONSABLE, dep["id"], {"canal": "panel"}))["canal"], "panel")
        self.assertEqual(ejecutar(alertas.cambiar(RESPONSABLE, dep["id"], {"canal": "resumen_diario"}))["canal"], "resumen_diario")
        mia = ejecutar(alertas.crear(ALBERT, entrada()))
        with self.assertRaises(ErrorAlerta):
            ejecutar(alertas.cambiar(ALBERT, mia["id"], {"canal": "resumen_diario"}))
        # La base de datos lo impide aunque alguien se saltara el código.
        with psycopg.connect(self.url_directa(), autocommit=True) as c, self.assertRaises(psycopg.errors.CheckViolation):
            c.execute("UPDATE licitaciones_alertas SET canal = 'resumen_diario' WHERE id = %s", [mia["id"]])

    def test_canal_correo_crear_cambiar_y_proteger(self):
        a = ejecutar(alertas.crear(ALBERT, entrada(canal="correo", correo_destino="Albert@101.cat")))              # una personal sí puede
        self.assertEqual((a["canal"], a["correo_destino"]), ("correo", "albert@101.cat"))
        for mal in ({"canal": "correo"}, {"canal": "correo", "correo_destino": "x@gmail.com"}, {"canal": "correo", "correo_destino": None}):
            with self.assertRaises(ErrorAlerta, msg=mal):
                ejecutar(alertas.crear(ALBERT, entrada(**mal)))
        self.assertIsNone(ejecutar(alertas.crear(ALBERT, entrada(correo_destino="x@101.cat")))["correo_destino"])      # con canal «panel» se ignora
        b = ejecutar(alertas.cambiar(ALBERT, a["id"], {"correo_destino": "otra@101.cat"}))                             # cambiar solo la dirección
        self.assertEqual((b["canal"], b["correo_destino"]), ("correo", "otra@101.cat"))
        with self.assertRaises(ErrorAlerta):
            ejecutar(alertas.cambiar(ALBERT, a["id"], {"correo_destino": "fuera@gmail.com"}))
        with self.assertRaises(ErrorAlerta):
            ejecutar(alertas.cambiar(ALBERT, a["id"], {"correo_destino": None}))
        c = ejecutar(alertas.cambiar(ALBERT, a["id"], {"canal": "panel"}))                                             # al dejar el correo se borra la dirección
        self.assertEqual((c["canal"], c["correo_destino"]), ("panel", None))
        with self.assertRaises(ErrorAlerta):
            ejecutar(alertas.cambiar(ALBERT, a["id"], {"canal": "correo"}))                                            # sin dirección no se puede pasar a correo
        d = ejecutar(alertas.cambiar(ALBERT, a["id"], {"canal": "correo", "correo_destino": "albert@101.cat"}))
        self.assertEqual((d["canal"], d["correo_destino"]), ("correo", "albert@101.cat"))
        with psycopg.connect(self.url_directa(), autocommit=True) as cn, self.assertRaises(psycopg.errors.CheckViolation):      # y la base lo impide también
            cn.execute("UPDATE licitaciones_alertas SET correo_destino = NULL WHERE id = %s", [a["id"]])
        with psycopg.connect(self.url_directa(), autocommit=True) as cn, self.assertRaises(psycopg.errors.CheckViolation):
            cn.execute("UPDATE licitaciones_alertas SET canal = 'panel' WHERE id = %s", [a["id"]])                      # «panel» con dirección tampoco
        dep = ejecutar(alertas.crear(RESPONSABLE, entrada(ambito="departamento", departamento="licitaciones", canal="correo", correo_destino="licitaciones@101.cat")))
        self.assertEqual(dep["correo_destino"], "licitaciones@101.cat")

    def test_pasar_a_correo_no_envia_los_avisos_que_ya_habia(self):
        a = ejecutar(alertas.crear(ALBERT, entrada()))
        ejecutar(alertas.registrar_aviso(a["id"], "ev1", "licitacion.nueva", self.datos(), AHORA))
        ejecutar(alertas.cambiar(ALBERT, a["id"], {"canal": "correo", "correo_destino": "albert@101.cat"}))
        ejecutar(alertas.registrar_aviso(a["id"], "ev2", "licitacion.nueva", self.datos(), AHORA))
        with psycopg.connect(self.url_directa(), autocommit=True) as cn:
            filas = dict(cn.execute("SELECT evento_id, correo_enviado IS NULL FROM licitaciones_avisos").fetchall())
        self.assertEqual(filas, {"ev1": False, "ev2": True})                                  # el viejo se da por enviado; solo el nuevo queda pendiente

    def test_el_esquema_de_antes_se_actualiza_para_admitir_el_canal_del_resumen(self):
        with psycopg.connect(self.url_directa(), autocommit=True) as c:
            c.execute("ALTER TABLE licitaciones_alertas DROP CONSTRAINT licitaciones_alertas_canal_check")
            c.execute("ALTER TABLE licitaciones_alertas ADD CONSTRAINT licitaciones_alertas_canal_check CHECK (canal IN ('panel'))")     # como era antes
            c.execute(self.bloque)                                                                                                        # el arranque de siempre
        dep = ejecutar(alertas.crear(RESPONSABLE, entrada(ambito="departamento", departamento="licitaciones", canal="resumen_diario")))
        self.assertEqual(dep["canal"], "resumen_diario")

    def test_avisos_para_el_resumen_solo_de_departamento_con_ese_canal_y_del_periodo(self):
        eq = ejecutar(alertas.crear(RESPONSABLE, entrada(ambito="departamento", departamento="licitaciones", canal="resumen_diario", nombre="Del equipo")))
        solo_panel = ejecutar(alertas.crear(RESPONSABLE, entrada(ambito="departamento", departamento="licitaciones", nombre="Solo panel")))
        mia = ejecutar(alertas.crear(ALBERT, entrada(nombre="Personal")))
        desde, hasta = datetime(2026, 10, 27, 15, 0, tzinfo=timezone.utc), datetime(2026, 10, 28, 15, 0, tzinfo=timezone.utc)
        dentro = datetime(2026, 10, 28, 9, 0, tzinfo=timezone.utc)
        for i, encaje in enumerate((60, 90, 75, 50)):
            ejecutar(alertas.registrar_aviso(eq["id"], f"e{i}", "licitacion.nueva", self.datos(motor_id=f"0b1f7a3e-1111-4222-8333-44444444444{i}", titulo=f"T{encaje}", encaje=encaje), dentro))
        ejecutar(alertas.registrar_aviso(eq["id"], "antes", "licitacion.nueva", self.datos(titulo="de ayer por la mañana"), datetime(2026, 10, 27, 9, 0, tzinfo=timezone.utc)))
        ejecutar(alertas.registrar_aviso(eq["id"], "limite", "licitacion.nueva", self.datos(titulo="justo a las 16:00"), hasta))                   # el fin no entra: [desde, hasta)
        ejecutar(alertas.registrar_aviso(solo_panel["id"], "p", "licitacion.nueva", self.datos(), dentro))
        ejecutar(alertas.registrar_aviso(mia["id"], "m", "licitacion.nueva", self.datos(), dentro))
        r = ejecutar(alertas.avisos_para_resumen(desde, hasta, por_alerta=2))
        self.assertEqual(r["total"], 4)
        self.assertEqual(len(r["items"]), 1)                                                                                    # ni la de solo panel ni la personal
        g = r["items"][0]
        self.assertEqual((g["nombre"], g["departamento"], g["total"]), ("Del equipo", "licitaciones", 4))
        self.assertEqual([a["titulo"] for a in g["avisos"]], ["T90", "T75"])                                                  # los 2 de más encaje; el resto se cuenta
        self.assertEqual(ejecutar(alertas.avisos_para_resumen(hasta, hasta.replace(day=29)), ) ["items"][0]["avisos"][0]["titulo"], "justo a las 16:00")

    def test_el_resumen_con_avisos_reales_se_guarda_y_se_lee_incluso_con_el_motor_caido(self):
        with psycopg.connect(self.url_directa(), autocommit=True) as c:
            t = ESQUEMA.read_text(encoding="utf-8")
            c.execute(t[t.index("CREATE TABLE IF NOT EXISTS licitaciones_resumenes"):])                    # el almacén de los resúmenes
        eq = ejecutar(alertas.crear(RESPONSABLE, entrada(ambito="departamento", departamento="licitaciones", canal="resumen_diario", nombre="Del equipo")))
        ahora = datetime(2026, 10, 28, 15, 0, tzinfo=timezone.utc)                                         # las 16:00 en Madrid
        ejecutar(alertas.registrar_aviso(eq["id"], "e1", "licitacion.nueva", self.datos(), datetime(2026, 10, 28, 9, 0, tzinfo=timezone.utc)))
        ajustes = SimpleNamespace(database_url=alertas.ajustes.database_url, zona_horaria="Europe/Madrid", dir_config=resumen.ajustes.dir_config)

        async def motor_caido(ruta, params=None):
            raise motor.MotorNoDisponible("el motor no responde")
        with mock.patch.object(resumen, "ajustes", ajustes):
            doc = ejecutar(resumen.construir(ahora, motor_caido))
            self.assertEqual((doc["estado"], doc["alertas"]["estado"], doc["alertas"]["total"], doc["totales"]["alertas"]), ("sin_datos", "ok", 1, 1))
            rid = ejecutar(resumen.guardar(doc, "programada"))
            leido = ejecutar(resumen.leer(rid))
        g = leido["contenido"]["alertas"]["items"][0]
        self.assertEqual((g["nombre"], g["departamento"], g["total"], g["avisos"][0]["titulo"], g["avisos"][0]["encaje"]), ("Del equipo", "licitaciones", 1, "Videovigilancia del puerto", 82.0))

    def test_borrar_una_alerta_borra_sus_avisos(self):
        a = ejecutar(alertas.crear(ALBERT, entrada()))
        ejecutar(alertas.registrar_aviso(a["id"], "e1", "licitacion.nueva", self.datos(), AHORA))
        ejecutar(alertas.borrar(ALBERT, a["id"]))
        self.assertEqual(ejecutar(alertas.listar_avisos(ALBERT)), {"sin_leer": 0, "items": []})


if __name__ == "__main__":
    unittest.main()
