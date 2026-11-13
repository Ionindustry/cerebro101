"""Elegir en cada caso cómo se hace Administrativo y Costes (local / Claude o ChatGPT con datos anonimizados / a mano): la confirmación obligatoria, que lo privado salga solo anonimizado y el registro."""
import asyncio
import os
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import _sin_servicios  # noqa: F401

try:
    import psycopg
    from cerebro.licitaciones import ofertas as O, redaccion as R
    from cerebro.licitaciones import redaccion_externa as X
except ImportError as e:      # pragma: no cover
    raise unittest.SkipTest(str(e))

URL = os.environ.get("CEREBRO_TEST_PG")
ESQUEMA = Path(__file__).resolve().parents[2] / "db" / "esquema.sql"
ID = "0b1f7a3e-1111-4222-8333-4444444444aa"
FICHA = {"criterios": [{"tipo": "SUBJ", "descripcion": "Memoria técnica", "peso": 30}, {"tipo": "OBJ", "descripcion": "Oferta económica (precio)", "peso": 70}]}


def ejecutar(c):
    return asyncio.run(c)


class TestValidar(unittest.TestCase):
    def test_lo_local_no_se_anota_y_lo_vacio_tampoco(self):
        self.assertEqual(X.validar_modos(None, None, "albert"), {})
        self.assertEqual(X.validar_modos({"costes": "local"}, [], "albert"), {})

    def test_externo_exige_confirmacion_expresa_de_ese_paso(self):
        with self.assertRaises(O.ErrorOferta) as e:
            X.validar_modos({"costes": "externo"}, [], "albert")
        self.assertIn("confirmar", str(e.exception))
        with self.assertRaises(O.ErrorOferta):
            X.validar_modos({"costes": "externo"}, ["administrativo"], "albert")        # confirmar otro paso no vale
        r = X.validar_modos({"costes": "externo", "administrativo": "manual"}, ["costes"], "albert")
        self.assertEqual(r, {"costes": {"modo": "externo", "confirmado_por": "albert"}, "administrativo": {"modo": "manual", "confirmado_por": "albert"}})

    def test_un_paso_o_un_modo_raros_son_un_error_no_un_local_silencioso(self):
        for modos in ({"memoria": "externo"}, {"costes": "nube"}, "externo", ["costes"]):
            with self.assertRaises(O.ErrorOferta, msg=str(modos)):
                X.validar_modos(modos, ["costes", "memoria"], "albert")

    def test_el_estado_de_confirmados_no_puede_ser_una_cadena(self):
        with self.assertRaises(O.ErrorOferta):
            X.validar_modos({"costes": "externo"}, "costes", "albert")                 # «costes» como texto no es una lista de confirmados


class TestPrivado(unittest.TestCase):
    """`intentar` con texto privado: sale anonimizado, vuelve desanonimizado y, si no se puede garantizar, no sale."""

    def patches(self, anonimizar_ok=True):
        async def preparar(mensajes):
            if not anonimizar_ok:
                return mensajes, {}, ["no se puede garantizar"]
            limpios = [{**m, "content": m["content"].replace("B12345678", "[NIF_1]")} for m in mensajes]
            return limpios, {"equivalencias": {"[NIF_1]": "B12345678"}}, []
        return [mock.patch.object(X, "_documentos_leidos", mock.AsyncMock(return_value=[{"n": 1, "nombre": "PCAP", "paginas": [(1, "Texto del pliego")]}])),
                mock.patch.object(X.pliegos, "requisitos", mock.AsyncMock(return_value={"requisitos": []})),
                mock.patch.object(X.O, "leer", mock.AsyncMock(return_value={"secciones": []})),
                mock.patch.object(X, "conocimiento_de_la_empresa", mock.AsyncMock(return_value="")),
                mock.patch.object(X.externos, "_preparar", preparar),
                mock.patch.object(X.externos, "modelo_elegido", mock.AsyncMock(return_value="prueba")),
                mock.patch.object(X.O, "escribir_seccion", mock.AsyncMock(return_value={}))]

    def correr(self, anonimizar_ok=True):
        vistos = {}

        async def consulta(agente, mensajes, esquema, **kw):
            vistos["texto"] = " ".join(m["content"] for m in mensajes)
            return {"secciones": [{"clave": "declaracion", "contenido": "La sociedad [NIF_1] declara", "citas": []}]}, "claude"
        sel = [{"clave": "declaracion", "sobre": "administrativo", "titulo": "Declaración", "guia": "g"}]
        ps = self.patches(anonimizar_ok)
        for p in ps:
            p.start()
        try:
            res = ejecutar(X.intentar(ID, {"id": "administrativo", "agente": "administrativo-licitaciones", "contexto": "Prepara"}, sel, "Videovigilancia", {}, consulta=consulta,
                                      privado="Sociedad 101 con NIF B12345678"))
            vistos["escrito"] = X.O.escribir_seccion.call_args.args[3] if X.O.escribir_seccion.call_args else None
        finally:
            for p in ps:
                p.stop()
        return res, vistos

    def test_el_texto_privado_sale_anonimizado_y_la_respuesta_vuelve_con_los_datos(self):
        (res, motivo), vistos = self.correr()
        self.assertEqual(motivo, "")
        self.assertIn("[NIF_1]", vistos["texto"])
        self.assertNotIn("B12345678", vistos["texto"])
        self.assertEqual(res["escritas"], ["declaracion"])
        self.assertEqual(vistos["escrito"], "La sociedad B12345678 declara")            # lo escrito vuelve con los datos reales

    def test_si_no_se_puede_anonimizar_no_sale_nada(self):
        (res, motivo), vistos = self.correr(anonimizar_ok=False)
        self.assertIsNone(res)
        self.assertIn("no salen de la empresa", motivo)
        self.assertNotIn("texto", vistos)                                                  # el modelo externo ni se llamó


@unittest.skipUnless(URL, "sin CEREBRO_TEST_PG")
class TestPasos(unittest.TestCase):
    def setUp(self):
        self.schema = f"t_modos_{time.time_ns()}"
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"CREATE SCHEMA {self.schema}")
            c.execute(f"SET search_path = {self.schema}")
            t = ESQUEMA.read_text(encoding="utf-8")
            c.execute(t[t.index("-- Pliegos y otros documentos de una licitación"):])
        sep = "&" if "?" in URL else "?"
        aj = SimpleNamespace(database_url=f"{URL}{sep}options=-csearch_path%3D{self.schema}")
        from cerebro.licitaciones import pliegos
        self.plantillas = mock.AsyncMock(return_value={"documentos": [{"documento": 1, "nombre": "Anexo I", "estado": "lista_para_firma", "rellenados": [{}], "pendientes": []}]})
        self.p = [mock.patch.object(O, "ajustes", aj), mock.patch.object(pliegos, "ajustes", aj), mock.patch.object(R, "_titulo_y_ficha", mock.AsyncMock(return_value=("Videovigilancia", FICHA))),
                  mock.patch.object(R, "_preparar_plantillas", self.plantillas)]
        for p in self.p:
            p.start()
        ejecutar(O.plan(ID, FICHA, "albert"))
        self.llamadas = []

        async def invocar(agente, peticion):
            self.llamadas.append(agente)
            for sobre, clave in {"administrativo-licitaciones": [("administrativo", "declaracion-responsable")], "costes-licitacion": [("economico", "justificacion-precio")]}.get(agente, []):
                await O.escribir_seccion(ID, sobre, clave, f"Borrador de {agente}", agente=agente)
            return {"respuesta": f"Resumen de {agente}"}
        self.invocar = invocar

    def tearDown(self):
        for p in self.p:
            p.stop()
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"DROP SCHEMA {self.schema} CASCADE")

    def pasos(self, e):
        return {p["id"]: p for p in e["pasos"]}

    def lanzar(self, solo, modos, **kw):
        e = ejecutar(R.reservar(ID, "albert", solo=solo, modos=X.validar_modos(modos, kw.get("confirmados"), "albert"))) if solo else None
        return e

    def test_manual_no_llama_a_ningun_agente_y_rellena_las_plantillas(self):
        ejecutar(R.reservar(ID, "albert"))                                            # una primera ejecución para poder repetir un paso
        e0 = ejecutar(R.ultima(ID))
        ejecutar(R.cerrar(e0["id"], ""))
        e = ejecutar(R.reservar(ID, "albert", solo="administrativo", modos=X.validar_modos({"administrativo": "manual"}, [], "albert")))
        self.assertEqual(e["modos"]["administrativo"]["modo"], "manual")
        fin = ejecutar(R.ejecutar(e["id"], self.invocar))
        p = self.pasos(fin)["administrativo"]
        self.assertEqual((p["estado"], p["modo"]), ("omitido", "manual"))
        self.assertIn("A mano", p["resumen"])
        self.assertIn("albert", p["resumen"])
        self.assertIn("Plantillas del concurso", p["resumen"])
        self.assertNotIn("administrativo-licitaciones", self.llamadas)

    def preparar_repeticion(self):
        ejecutar(R.reservar(ID, "albert"))
        ejecutar(R.cerrar(ejecutar(R.ultima(ID))["id"], ""))

    def test_externo_confirmado_envia_lo_privado_y_deja_registro_sin_contenido(self):
        self.preparar_repeticion()
        recibido = {}

        async def externo(motor_id, defin, sel, titulo, ficha, consulta=None, modelo="auto", privado=""):
            recibido["privado"] = privado
            for s in sel:
                await O.escribir_seccion(motor_id, s["sobre"], s["clave"], "Escrito con Claude", agente=defin["agente"])
            return {"escritas": [s["clave"] for s in sel], "omitidas": {}, "resumen": "Redactado con Claude (prueba).", "proveedor": "claude", "modelo": "prueba"}, ""
        e = ejecutar(R.reservar(ID, "albert", solo="administrativo", modos=X.validar_modos({"administrativo": "externo"}, ["administrativo"], "albert")))
        with mock.patch.object(X, "intentar", externo):
            fin = ejecutar(R.ejecutar(e["id"], self.invocar))
        p = self.pasos(fin)["administrativo"]
        self.assertEqual((p["estado"], p["modo"]), ("hecho", "externo"))
        self.assertIn("Anexo I", recibido["privado"])                                  # lo que habría visto el agente local (plantillas) viaja, anonimizado por `intentar`
        self.assertIn("queda registrado", p["resumen"])
        self.assertNotIn("administrativo-licitaciones", self.llamadas)
        env = ejecutar(X.envios(ID))
        self.assertEqual(len(env), 1)
        self.assertEqual((env[0]["paso"], env[0]["sensibilidad"], env[0]["confirmado_por"], env[0]["estado"], env[0]["proveedor"]), ("administrativo", "media", "albert", "enviado", "claude"))
        self.assertGreater(env[0]["caracteres_privados"], 0)
        self.assertNotIn("privado", env[0])

    def test_costes_externo_no_manda_datos_privados_y_su_contexto_prohibe_inventar_cifras(self):
        self.preparar_repeticion()
        visto = {}

        async def externo(motor_id, defin, sel, titulo, ficha, consulta=None, modelo="auto", **kw):
            visto.update(defin=defin, kw=kw)
            return None, "Claude y ChatGPT están desconectados"
        e = ejecutar(R.reservar(ID, "albert", solo="costes", modos=X.validar_modos({"costes": "externo"}, ["costes"], "albert")))
        with mock.patch.object(X, "intentar", externo):
            fin = ejecutar(R.ejecutar(e["id"], self.invocar))
        self.assertEqual(visto["kw"], {})                                              # Costes no lleva texto privado
        self.assertIn("NO inventes ninguna cifra", visto["defin"]["contexto"])
        self.assertNotIn("datos del ERP y del cotizador", visto["defin"]["contexto"])
        p = self.pasos(fin)["costes"]
        self.assertIn("Se ha usado el modelo local", p["resumen"])                      # si el externo falla, lo hace el local
        self.assertEqual(ejecutar(X.envios(ID))[0]["estado"], "no_enviado")

    def test_sin_elegir_nada_el_paso_es_el_de_siempre(self):
        self.preparar_repeticion()
        e = ejecutar(R.reservar(ID, "albert", solo="costes"))
        fin = ejecutar(R.ejecutar(e["id"], self.invocar))
        self.assertEqual(self.pasos(fin)["costes"]["modo"], "local")
        self.assertIn("costes-licitacion", self.llamadas)
        self.assertEqual(ejecutar(X.envios(ID)), [])


if __name__ == "__main__":
    unittest.main()
