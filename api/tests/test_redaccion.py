"""«Preparar la oferta»: la cadena de agentes (Arquitecto, Redactor, Administrativo, Costes, Precio, Evaluador) con una ejecución reanudable, comprobando lo que de verdad queda escrito
(con CEREBRO_TEST_PG)."""
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
    from cerebro.licitaciones import ofertas as O, redaccion as R
    from cerebro.llm import ModeloNoDisponible
except ImportError as e:      # pragma: no cover
    raise unittest.SkipTest(str(e))

URL = os.environ.get("CEREBRO_TEST_PG")
ESQUEMA = Path(__file__).resolve().parents[2] / "db" / "esquema.sql"
ID = "0b1f7a3e-1111-4222-8333-444444444444"
FICHA = {"criterios": [{"tipo": "SUBJ", "descripcion": "Memoria técnica", "peso": 30}, {"tipo": "OBJ", "descripcion": "Oferta económica (precio)", "peso": 70}]}


def ejecutar(c):
    return asyncio.run(c)


def agentes_que_escriben(claves_por_agente):
    """Un invocador falso: cada agente guarda borradores en sus secciones (como haría con la herramienta «ofertas») y responde con un resumen."""
    llamadas = []

    async def invocar(agente, peticion):
        llamadas.append((agente, peticion))
        for sobre, clave in claves_por_agente.get(agente, []):
            await O.escribir_seccion(ID, sobre, clave, f"Borrador de {agente} para {clave}", agente=agente)
        return {"respuesta": f"Resumen de {agente}"}
    invocar.llamadas = llamadas
    return invocar


TODOS = {"arquitecto-solucion": [("tecnico", "descripcion-solucion")], "redactor-memoria": [("tecnico", "crit-1")],
         "administrativo-licitaciones": [("administrativo", "declaracion-responsable"), ("administrativo", "solvencia"), ("administrativo", "otros-documentos")],
         "costes-licitacion": [("economico", "justificacion-precio")]}


@unittest.skipUnless(URL, "sin CEREBRO_TEST_PG")
class TestRedaccion(unittest.TestCase):
    def setUp(self):
        self.schema = f"t_redac_{time.time_ns()}"
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"CREATE SCHEMA {self.schema}")
            c.execute(f"SET search_path = {self.schema}")
            t = ESQUEMA.read_text(encoding="utf-8")
            c.execute(t[t.index("-- Pliegos y otros documentos de una licitación"):])
        sep = "&" if "?" in URL else "?"
        ajustes = SimpleNamespace(database_url=f"{URL}{sep}options=-csearch_path%3D{self.schema}")
        from cerebro.licitaciones import pliegos
        self.plantillas = mock.AsyncMock(return_value={"documentos": [{"documento": 1, "nombre": "Anexo I", "estado": "faltan_datos", "rellenados": [{}] * 5,
                                                                      "pendientes": [{"id": "t4", "etiqueta": "Observaciones", "motivo": "No está claro", "bloquea": True}]}]})
        self.p = [mock.patch.object(O, "ajustes", ajustes), mock.patch.object(pliegos, "ajustes", ajustes), mock.patch.object(R, "_titulo_y_ficha", mock.AsyncMock(return_value=("Videovigilancia", FICHA))),
                  mock.patch.object(R, "_preparar_plantillas", self.plantillas)]
        for p in self.p:
            p.start()
        ejecutar(O.plan(ID, FICHA, "albert"))

    def tearDown(self):
        for p in self.p:
            p.stop()
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"DROP SCHEMA {self.schema} CASCADE")

    def reservar(self, **kw):
        return ejecutar(R.reservar(ID, "albert", **kw))

    def pasos(self, e):
        return {p["id"]: p for p in e["pasos"]}

    def test_reservar_prepara_los_pasos_y_omite_lo_que_no_hay_que_escribir(self):
        e = self.reservar()
        self.assertEqual([p["id"] for p in e["pasos"]], ["encargos", "solucion", "memoria", "administrativo", "costes", "precio", "evaluacion"])
        self.assertEqual(e["estado"], "en_curso")
        p = self.pasos(e)
        self.assertEqual(p["solucion"]["secciones"], ["descripcion-solucion"])
        self.assertEqual(p["memoria"]["secciones"], ["crit-1"])
        self.assertEqual(p["costes"]["secciones"], ["justificacion-precio"])                # la proposición económica y los criterios automáticos no los escribe ningún agente
        self.assertEqual(p["administrativo"]["secciones"], ["declaracion-responsable", "solvencia", "otros-documentos"])
        self.assertEqual({p[k]["estado"] for k in p}, {"pendiente"})

    def test_solo_una_en_curso_y_la_perdida_se_sustituye(self):
        e = self.reservar()
        with self.assertRaises(R.Conflicto):
            self.reservar()
        ahora = datetime.now(timezone.utc) + R.VENTANA + timedelta(minutes=1)
        nueva = ejecutar(R.reservar(ID, "albert", ahora=ahora))
        self.assertNotEqual(nueva["id"], e["id"])
        self.assertEqual(ejecutar(R._cargar(e["id"]))["estado"], "error")
        with self.assertRaises(O.NoExiste):
            ejecutar(R.reservar("1c2f7a3e-1111-4222-8333-444444444444", "albert"))

    def test_la_cadena_completa_escribe_borradores_prepara_plantillas_y_deja_informes(self):
        e = self.reservar()
        inv = agentes_que_escriben(TODOS)
        fin = ejecutar(R.ejecutar(e["id"], inv))
        self.assertEqual(fin["estado"], "completa")
        self.assertEqual([a for a, _ in inv.llamadas], ["arquitecto-solucion", "redactor-memoria", "administrativo-licitaciones", "costes-licitacion", "precio-licitacion", "evaluador-ofertas"])
        p = self.pasos(fin)
        self.assertEqual({k: v["estado"] for k, v in p.items()}, {k: "hecho" for k in p})
        self.assertEqual(p["solucion"]["escritas"], 1)
        self.assertIn("Resumen de precio-licitacion", p["precio"]["resumen"])
        self.assertIn("1 con datos pendientes", p["administrativo"]["resumen"])
        o = ejecutar(O.leer(ID))
        s = {x["clave"]: x for x in o["secciones"]}
        self.assertEqual(s["crit-1"]["por"], "agente:redactor-memoria")
        self.assertEqual(s["crit-1"]["estado"], "borrador")                                 # nunca revisada ni aprobada por un agente
        self.assertEqual(s["proposicion-economica"]["contenido"], "")                       # la proposición económica y el precio, de una persona
        self.assertIsNone(o["precio_sin_iva"])
        self.plantillas.assert_awaited_once()

    def test_lo_que_se_le_pide_a_cada_agente(self):
        e = self.reservar()
        inv = agentes_que_escriben(TODOS)
        ejecutar(R.ejecutar(e["id"], inv))
        por = dict(inv.llamadas)
        arq = por["arquitecto-solucion"]
        for esperado in (ID, "Videovigilancia", "descripcion-solucion", "[PENDIENTE", "No inventes", "guardar_seccion", "no escribas la proposición económica", "no firmes"):
            self.assertIn(esperado, arq)
        for agente in ("arquitecto-solucion", "redactor-memoria", "administrativo-licitaciones", "costes-licitacion"):
            self.assertIn("nadie va a contestar", por[agente], agente)                       # trabajan solos: no deben preguntar (un agente se quedó esperando una confirmación)
            self.assertIn("guarda CADA sección", por[agente], agente)
        self.assertIn("nadie va a contestar", por["precio-licitacion"])
        self.assertIn("descripcion-solucion", por["redactor-memoria"])                      # el Redactor sabe que la solución ya está escrita
        adm = por["administrativo-licitaciones"]
        self.assertIn("Plantillas del concurso", adm)
        self.assertIn("t4", adm)                                                           # el hueco dudoso, para que el agente elija el dato
        self.assertIn("Nunca escribas el valor", adm)
        self.assertIn("firma", adm.lower())
        self.assertIn("NO fijes el precio", por["precio-licitacion"].replace("No fijes", "NO fijes"))
        ev = por["evaluador-ofertas"]
        self.assertIn("Borrador de arquitecto-solucion para descripcion-solucion", ev)       # el Evaluador recibe lo escrito, porque no tiene la herramienta
        self.assertIn("Memoria técnica (30 puntos)", ev)
        self.assertNotIn("proposicion", ev.lower().replace("proposición económica", ""))

    def test_con_modelo_externo_los_pasos_de_memoria_no_llaman_al_agente_local_y_el_resto_si(self):
        from cerebro.licitaciones import redaccion_externa as X
        e = self.reservar()

        async def externo(motor_id, defin, sel, titulo, ficha, consulta=None, modelo="auto"):
            for s in sel:
                await O.escribir_seccion(motor_id, s["sobre"], s["clave"], f"Escrito con Claude: {s['clave']}", agente=defin["agente"])
            return {"escritas": [s["clave"] for s in sel], "omitidas": {}, "resumen": "Redactado con Claude (prueba): bien.", "proveedor": "claude", "modelo": "prueba"}, ""
        inv = agentes_que_escriben(TODOS)
        with mock.patch.object(X, "intentar", externo):
            fin = ejecutar(R.ejecutar(e["id"], inv))
        self.assertEqual([a for a, _ in inv.llamadas], ["administrativo-licitaciones", "costes-licitacion", "precio-licitacion", "evaluador-ofertas"])    # solucion y memoria: modelo externo
        p = self.pasos(fin)
        self.assertEqual((p["solucion"]["estado"], p["memoria"]["estado"]), ("hecho", "hecho"))
        self.assertIn("Redactado con Claude", p["solucion"]["resumen"])
        s = {x["clave"]: x for x in ejecutar(O.leer(ID))["secciones"]}
        self.assertEqual(s["crit-1"]["contenido"], "Escrito con Claude: crit-1")
        self.assertEqual(s["crit-1"]["estado"], "borrador")                                  # sigue siendo un borrador para una persona

    def test_si_el_modelo_externo_no_procede_lo_hace_el_local_y_el_resumen_lo_dice(self):
        from cerebro.licitaciones import redaccion_externa as X
        e = self.reservar()

        async def sin_externo(*a, **k):
            return None, "Claude y ChatGPT están desconectados"
        inv = agentes_que_escriben(TODOS)
        with mock.patch.object(X, "intentar", sin_externo):
            fin = ejecutar(R.ejecutar(e["id"], inv))
        self.assertEqual(fin["estado"], "completa")
        self.assertEqual([a for a, _ in inv.llamadas][:2], ["arquitecto-solucion", "redactor-memoria"])
        self.assertIn("Se ha usado el modelo local: Claude y ChatGPT están desconectados", self.pasos(fin)["solucion"]["resumen"])

    def test_el_modelo_elegido_se_guarda_en_la_ejecucion_y_llega_a_los_pasos_de_memoria(self):
        from cerebro.licitaciones import redaccion_externa as X
        e = ejecutar(R.reservar(ID, "albert", modelo="chatgpt"))
        self.assertEqual(e["modelo"], "chatgpt")
        pedidos = []

        async def externo(motor_id, defin, sel, titulo, ficha, consulta=None, modelo="auto"):
            pedidos.append((defin["id"], modelo))
            for s in sel:
                await O.escribir_seccion(motor_id, s["sobre"], s["clave"], "x", agente=defin["agente"])
            return {"escritas": [], "omitidas": {}, "resumen": "ok", "proveedor": "chatgpt", "modelo": "p"}, ""
        with mock.patch.object(X, "intentar", externo):
            ejecutar(R.ejecutar(e["id"], agentes_que_escriben(TODOS)))
        self.assertEqual(pedidos, [("solucion", "chatgpt"), ("memoria", "chatgpt")])

    def test_un_modelo_raro_se_guarda_como_automatico(self):
        self.assertEqual(ejecutar(R.reservar(ID, "albert", modelo="gemini"))["modelo"], "auto")

    def test_el_director_hace_los_encargos_primero_y_cada_agente_recibe_el_suyo(self):
        e = self.reservar()
        inv = agentes_que_escriben(TODOS)
        fin = ejecutar(R.ejecutar(e["id"], inv))
        p = self.pasos(fin)
        self.assertEqual(fin["estado"], "completa")
        self.assertEqual(p["encargos"]["estado"], "hecho")
        self.assertIn("Encargos de la plantilla para 6 agentes", p["encargos"]["resumen"])
        self.assertEqual([a for a, _ in inv.llamadas][0], "arquitecto-solucion")                 # el director no es un agente que se invoque: sus encargos se guardan
        peticiones = dict(inv.llamadas)
        for agente in ("arquitecto-solucion", "redactor-memoria", "administrativo-licitaciones", "costes-licitacion", "precio-licitacion", "evaluador-ofertas"):
            self.assertIn("ENCARGO ESPECÍFICO DE ESTA LICITACIÓN", peticiones[agente], agente)
            self.assertIn("nunca las sustituye", peticiones[agente], agente)
        self.assertLess(peticiones["costes-licitacion"].index("ENCARGO"), peticiones["costes-licitacion"].index("Reglas:"))     # las reglas fijas van después y mandan

    def test_un_encargo_escrito_por_una_persona_es_el_que_recibe_el_agente(self):
        from cerebro.licitaciones import encargos
        e = self.reservar()
        ejecutar(encargos.escribir_persona(ID, "costes-licitacion", "Desglosa la formación aparte.", "albert"))
        inv = agentes_que_escriben(TODOS)
        ejecutar(R.ejecutar(e["id"], inv))
        peticion = dict(inv.llamadas)["costes-licitacion"]
        self.assertIn("Desglosa la formación aparte.", peticion)
        self.assertIn("una persona de Licitaciones", peticion)

    def test_repetir_un_solo_paso_no_vuelve_a_hacer_los_demas_y_conserva_lo_que_dieron(self):
        primera = self.reservar()
        inv = agentes_que_escriben({**TODOS, "redactor-memoria": []})                       # el Redactor «dice hecho» sin guardar nada: error
        fin = ejecutar(R.ejecutar(primera["id"], inv))
        self.assertEqual(self.pasos(fin)["memoria"]["estado"], "error")
        e = ejecutar(R.reservar(ID, "albert", solo="memoria"))
        p = self.pasos(e)
        self.assertEqual(p["memoria"]["estado"], "pendiente")                                # solo ese paso vuelve a empezar
        self.assertEqual((p["solucion"]["estado"], p["costes"]["estado"], p["encargos"]["estado"]), ("hecho", "hecho", "hecho"))
        self.assertEqual(p["solucion"]["escritas"], 1)                                      # conserva lo que dio la ejecución anterior
        inv2 = agentes_que_escriben(TODOS)
        fin2 = ejecutar(R.ejecutar(e["id"], inv2))
        self.assertEqual([a for a, _ in inv2.llamadas], ["redactor-memoria"])                # solo se invoca al agente repetido
        self.assertEqual(self.pasos(fin2)["memoria"]["estado"], "hecho")
        self.assertEqual(fin2["estado"], "completa")

    def test_repetir_un_informe_vuelve_a_pedirlo_y_lo_demas_queda_igual(self):
        primera = self.reservar()
        ejecutar(R.ejecutar(primera["id"], agentes_que_escriben(TODOS)))
        e = ejecutar(R.reservar(ID, "albert", solo="precio"))
        inv = agentes_que_escriben(TODOS)
        fin = ejecutar(R.ejecutar(e["id"], inv))
        self.assertEqual([a for a, _ in inv.llamadas], ["precio-licitacion"])
        self.assertEqual(fin["estado"], "completa")

    def test_repetir_requiere_haberla_preparado_y_un_paso_que_exista_y_no_hay_dos_a_la_vez(self):
        with self.assertRaises(O.ErrorOferta):
            ejecutar(R.reservar(ID, "albert", solo="no-existe"))
        with self.assertRaises(O.NoExiste):
            ejecutar(R.reservar(ID, "albert", solo="memoria"))                                # nunca se ha preparado con los agentes
        self.reservar()
        with self.assertRaises(R.Conflicto):
            ejecutar(R.reservar(ID, "albert", solo="memoria"))                                # ya hay una en curso

    def test_un_paso_de_la_ejecucion_anterior_que_no_llego_a_hacerse_queda_como_error_con_su_boton(self):
        ant = [{"id": "solucion", "estado": "hecho", "resumen": "ok", "error": ""}, {"id": "memoria", "estado": "en_curso", "resumen": "", "error": ""},
               {"id": "costes", "estado": "pendiente", "resumen": "", "error": ""}]
        inicial = R.pasos_iniciales([], False)
        nuevos = {p["id"]: p for p in R.pasos_de_repeticion(inicial, ant, "precio")}
        self.assertEqual((nuevos["solucion"]["estado"], nuevos["solucion"]["resumen"]), ("hecho", "ok"))
        self.assertEqual((nuevos["memoria"]["estado"], nuevos["costes"]["estado"]), ("error", "error"))
        self.assertIn("repítelo con su botón", nuevos["memoria"]["error"])
        self.assertEqual(nuevos["precio"]["estado"], "pendiente")
        self.assertEqual(nuevos["encargos"]["estado"], "omitido")                            # no estaba en la ejecución anterior

    def test_el_endpoint_de_repetir_un_paso_valida_permisos_y_encola_solo_ese_trabajo(self):
        from cerebro.api import main
        from cerebro.api.main import Usuario, usuario_actual
        from fastapi.testclient import TestClient
        primera = self.reservar()
        ejecutar(R.ejecutar(primera["id"], agentes_que_escriben(TODOS)))
        c = TestClient(main.app)
        enviados = []
        try:
            main.app.dependency_overrides[usuario_actual] = lambda: Usuario("pepe", {"usuario"}, {"finanzas"})
            self.assertEqual(c.post(f"/licitaciones/ofertas/{ID}/redactar/memoria", json={}).status_code, 403)
            main.app.dependency_overrides[usuario_actual] = lambda: Usuario("marta", {"usuario"}, {"licitaciones"})
            self.assertEqual(c.post(f"/licitaciones/ofertas/{ID}/redactar/no-existe", json={}).status_code, 422)
            from cerebro.tareas import celery_app
            with mock.patch.object(celery_app.app, "send_task", lambda nombre, args=None, queue=None, **k: enviados.append((nombre, args, queue))):
                r = c.post(f"/licitaciones/ofertas/{ID}/redactar/memoria", json={"rehacer": True, "modelo": "claude"})
                self.assertEqual(r.status_code, 202)
                self.assertEqual(c.post(f"/licitaciones/ofertas/{ID}/redactar/costes", json={}).status_code, 409)       # ya hay una en curso
        finally:
            main.app.dependency_overrides.clear()
        e = r.json()["ejecucion"]
        self.assertEqual([enviados[0][0], enviados[0][1], enviados[0][2]], ["cerebro.tareas.celery_app.redactar_oferta", [e["id"]], "peticiones"])
        self.assertEqual((e["modelo"], e["rehacer"]), ("claude", True))
        self.assertEqual({p["id"]: p["estado"] for p in e["pasos"]}["memoria"], "pendiente")
        self.assertEqual({p["id"]: p["estado"] for p in e["pasos"]}["solucion"], "hecho")

    def test_un_agente_que_dice_hecho_sin_guardar_nada_es_un_error_y_la_cadena_sigue(self):
        e = self.reservar()
        ejecutar(O.escribir_seccion(ID, "tecnico", "crit-1", "x", agente="redactor-memoria"))       # ya tenía contenido: no se toca sin «rehacer»
        inv = agentes_que_escriben({**TODOS, "costes-licitacion": []})
        fin = ejecutar(R.ejecutar(e["id"], inv))
        p = self.pasos(fin)
        self.assertEqual(p["costes"]["estado"], "error")
        self.assertIn("no ha guardado", p["costes"]["error"])
        self.assertEqual(p["memoria"]["estado"], "omitido")                                   # ya tenía contenido
        self.assertEqual(p["precio"]["estado"], "hecho")
        self.assertEqual(fin["estado"], "parcial")

    def test_escribir_solo_una_parte_queda_como_parcial_con_lo_que_falta(self):
        e = self.reservar()
        inv = agentes_que_escriben({**TODOS, "administrativo-licitaciones": [("administrativo", "solvencia")]})
        fin = ejecutar(R.ejecutar(e["id"], inv))
        a = self.pasos(fin)["administrativo"]
        self.assertEqual((a["estado"], a["escritas"], a["faltan"]), ("parcial", 1, ["declaracion-responsable", "otros-documentos"]))
        self.assertEqual(fin["estado"], "parcial")

    def test_lo_de_una_persona_no_se_toca_y_rehacer_solo_rehace_borradores_de_agentes(self):
        ejecutar(O.escribir_seccion(ID, "tecnico", "crit-1", "Texto de una persona", usuario="albert"))
        ejecutar(O.escribir_seccion(ID, "tecnico", "descripcion-solucion", "Borrador viejo", agente="arquitecto-solucion"))
        e = self.reservar()
        self.assertEqual(self.pasos(e)["memoria"]["estado"], "omitido")
        self.assertEqual(self.pasos(e)["solucion"]["estado"], "omitido")                   # sin «rehacer», lo ya escrito se respeta
        ejecutar(R.cerrar(e["id"]))
        e = self.reservar(rehacer=True)
        self.assertEqual(self.pasos(e)["solucion"]["secciones"], ["descripcion-solucion"])  # el borrador de un agente sí se rehace
        self.assertEqual(self.pasos(e)["memoria"]["estado"], "omitido")                   # lo de una persona, nunca

    def test_si_el_modelo_no_esta_disponible_se_reanuda_sin_repetir_lo_hecho(self):
        e = self.reservar()
        inv = agentes_que_escriben(TODOS)
        base = inv

        async def cae_en_costes(agente, peticion):
            if agente == "costes-licitacion" and not getattr(cae_en_costes, "ya", False):
                cae_en_costes.ya = True
                raise ModeloNoDisponible("el modelo no responde")
            return await base(agente, peticion)

        with self.assertRaises(ModeloNoDisponible):
            ejecutar(R.ejecutar(e["id"], cae_en_costes))
        a = ejecutar(R._cargar(e["id"]))
        self.assertEqual(a["estado"], "en_curso")
        p = self.pasos(a)
        self.assertEqual([p[k]["estado"] for k in ("solucion", "memoria", "administrativo")], ["hecho"] * 3)
        self.assertEqual(p["costes"]["estado"], "pendiente")                               # el paso que falló vuelve a pendiente
        antes = len(inv.llamadas)
        fin = ejecutar(R.ejecutar(e["id"], cae_en_costes))
        self.assertEqual(fin["estado"], "completa")
        agentes = [a_ for a_, _ in inv.llamadas[antes:]]
        self.assertEqual(agentes, ["costes-licitacion", "precio-licitacion", "evaluador-ofertas"])    # no repite arquitecto, redactor ni administrativo
        self.assertEqual(self.plantillas.await_count, 1)

    def test_un_fallo_inesperado_deja_ese_paso_en_error_y_sigue(self):
        e = self.reservar()
        base = agentes_que_escriben(TODOS)

        async def roto(agente, peticion):
            if agente == "precio-licitacion":
                raise RuntimeError("secreto interno")
            return await base(agente, peticion)

        fin = ejecutar(R.ejecutar(e["id"], roto))
        p = self.pasos(fin)
        self.assertEqual(p["precio"]["estado"], "error")
        self.assertNotIn("secreto", p["precio"]["error"])                                   # el detalle interno no llega al panel
        self.assertEqual(p["evaluacion"]["estado"], "hecho")
        self.assertEqual(fin["estado"], "parcial")

    def test_las_plantillas_que_fallan_se_dicen_y_las_secciones_siguen(self):
        self.plantillas.side_effect = ValueError("Hay varias empresas en el ERP: elige con cuál se presenta la oferta")
        e = self.reservar()
        inv = agentes_que_escriben(TODOS)
        fin = ejecutar(R.ejecutar(e["id"], inv))
        a = self.pasos(fin)["administrativo"]
        self.assertEqual(a["estado"], "hecho")
        self.assertIn("no se han podido rellenar", a["resumen"])
        self.assertIn("varias empresas", dict(inv.llamadas)["administrativo-licitaciones"])

    def test_cerrar_con_pasos_sin_hacer_es_parcial_o_error_nunca_completa(self):
        e = self.reservar()
        cerrada = ejecutar(R.cerrar(e["id"], "No se pudo"))
        self.assertEqual(cerrada["estado"], "error")
        self.assertEqual(cerrada["error"], "No se pudo")
        self.assertEqual(ejecutar(R.cerrar(e["id"]))["estado"], "error")                    # cerrar otra vez no cambia nada
        self.assertEqual(ejecutar(R.ultima(ID))["id"], e["id"])
        self.assertIsNone(ejecutar(R.ultima("1c2f7a3e-1111-4222-8333-444444444444")))

    def test_el_evaluador_sin_contenido_se_omite(self):
        e = self.reservar()
        inv = agentes_que_escriben({})                                                      # nadie escribe nada
        fin = ejecutar(R.ejecutar(e["id"], inv))
        self.assertEqual(self.pasos(fin)["evaluacion"]["estado"], "omitido")
        self.assertNotIn("evaluador-ofertas", [a for a, _ in inv.llamadas])


class TestTextos(unittest.TestCase):
    def test_texto_de_plantillas(self):
        self.assertIn("no se han podido rellenar (el ERP no responde)", R.texto_plantillas(None, "el ERP no responde"))
        self.assertIn("ninguno de los documentos", R.texto_plantillas({"documentos": []}))
        t = R.texto_plantillas({"documentos": [{"documento": 3, "nombre": "Anexo II", "estado": "lista_para_firma", "rellenados": [{}] * 7, "pendientes": [{"id": "t9", "etiqueta": "x", "motivo": "m", "bloquea": False}]}]})
        self.assertIn("Documento 3 «Anexo II»: lista_para_firma, 7 huecos rellenados", t)
        self.assertNotIn("Pendientes:", t)                                                  # lo que no bloquea (la fecha) no se le pide al agente

    def test_las_pasos_estan_en_el_orden_del_trabajo_y_los_informes_no_escriben(self):
        self.assertEqual([p["id"] for p in R.PASOS], ["encargos", "solucion", "memoria", "administrativo", "costes", "precio", "evaluacion"])
        self.assertEqual([p["id"] for p in R.PASOS if p.get("informe")], ["precio", "evaluacion"])
        self.assertEqual(R.seleccion(R.PASOS[5], [{"sobre": "economico", "clave": "x", "estado": "vacia", "por": "", "version": 0}], False), [])


if __name__ == "__main__":
    unittest.main()
