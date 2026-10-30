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
        self.assertEqual([p["id"] for p in e["pasos"]], ["solucion", "memoria", "administrativo", "costes", "precio", "evaluacion"])
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
        self.assertEqual([p["id"] for p in R.PASOS], ["solucion", "memoria", "administrativo", "costes", "precio", "evaluacion"])
        self.assertEqual([p["id"] for p in R.PASOS if p.get("informe")], ["precio", "evaluacion"])
        self.assertEqual(R.seleccion(R.PASOS[4], [{"sobre": "economico", "clave": "x", "estado": "vacia", "por": "", "version": 0}], False), [])


if __name__ == "__main__":
    unittest.main()
