"""Un problema de Ollama debe producir un error claro y rápido, nunca un 500 sin explicación ni una espera infinita."""
import asyncio
import json
import os
import unittest
from unittest import mock

import _sin_servicios  # noqa: F401

try:
    import httpx
    from cerebro import llm
    from cerebro.router_modelos import Asignacion
    HAY_HTTPX = hasattr(httpx, "MockTransport")
except ImportError:
    HAY_HTTPX = False

ASIGNACION = Asignacion(clase="rapido", modelo="ministral-3:3b", prioridad=0, mantener_cargado="-1") if HAY_HTTPX else None
OK = {"message": {"content": "hola"}, "done_reason": "stop", "prompt_eval_count": 5, "eval_count": 2, "total_duration": 1_000_000}
ESQUEMA = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}


def respuesta(cuerpo, estado=200):
    return httpx.Response(estado, json=cuerpo)


class Servidor:
    """Transporte simulado: una lista de comportamientos, uno por llamada (excepción o respuesta)."""

    def __init__(self, *pasos):
        self.pasos, self.llamadas, self.cuerpos = list(pasos), 0, []

    async def __call__(self, request: httpx.Request):
        self.llamadas += 1
        self.cuerpos.append(json.loads(request.content or b"{}"))
        paso = self.pasos.pop(0) if len(self.pasos) > 1 else self.pasos[0]
        if isinstance(paso, Exception):
            raise paso
        return paso

    @property
    def transporte(self):
        return httpx.MockTransport(self)


@unittest.skipUnless(HAY_HTTPX, "requiere httpx real (se ejecuta en el contenedor)")
class TestLlmRobusto(unittest.TestCase):
    def setUp(self):
        llm.circuito.reiniciar()
        llm._semaforos.clear()
        self.espera = []

        async def dormir(s):
            self.espera.append(s)
        self.parches = [mock.patch.object(llm, "_dormir", dormir),
                        mock.patch.dict(os.environ, {"OLLAMA_REINTENTOS": "2", "OLLAMA_FALLOS_CIRCUITO": "3", "OLLAMA_ENFRIAMIENTO": "20",
                                                     "OLLAMA_CONCURRENCIA": "2", "OLLAMA_ESPERA_MAX": "5"})]
        for p in self.parches:
            p.start()

    def tearDown(self):
        for p in self.parches:
            p.stop()
        llm.circuito.reiniciar()

    def chat(self, servidor, **k):
        return asyncio.run(llm.chat(ASIGNACION, [{"role": "user", "content": "x"}], transporte=servidor.transporte, **k))

    # --- caso feliz
    def test_respuesta_normal_y_limites_por_defecto(self):
        s = Servidor(respuesta(OK))
        self.assertEqual(self.chat(s), "hola")
        opciones = s.cuerpos[0]["options"]
        self.assertEqual(opciones["num_predict"], 4096)          # sin tope, un modelo en bucle genera hasta agotar el tiempo
        self.chat(Servidor(respuesta(OK)), max_tokens=100)

    def test_con_esquema_devuelve_el_json(self):
        s = Servidor(respuesta({**OK, "message": {"content": '{"a": "b"}'}}))
        self.assertEqual(self.chat(s, esquema=ESQUEMA), {"a": "b"})
        self.assertEqual(s.cuerpos[0]["format"], ESQUEMA)

    # --- Ollama caído o reiniciándose
    def test_ollama_caido_reintenta_con_espera_y_da_un_mensaje_claro(self):
        s = Servidor(httpx.ConnectError("no route"))
        with self.assertRaises(llm.ModeloNoDisponible) as e:
            self.chat(s)
        self.assertEqual(s.llamadas, 3)                          # 1 intento + 2 reintentos
        self.assertEqual(self.espera, [1, 2])                    # espera creciente
        self.assertEqual((e.exception.http, e.exception.codigo), (503, "modelo_no_disponible"))
        self.assertIn("Ollama", str(e.exception))
        self.assertIsNotNone(e.exception.reintentar_en)

    def test_fallo_transitorio_y_luego_funciona(self):
        s = Servidor(httpx.RemoteProtocolError("Server disconnected"), respuesta({"error": "x"}, 500), respuesta(OK))
        self.assertEqual(self.chat(s), "hola")
        self.assertEqual(s.llamadas, 3)

    def test_error_500_persistente(self):
        s = Servidor(respuesta({"error": "llama runner process has terminated"}, 500))
        with self.assertRaises(llm.ErrorModelo) as e:
            self.chat(s)
        self.assertIn("500", str(e.exception))
        self.assertEqual(s.llamadas, 3)

    # --- tiempo agotado
    def test_timeout_no_se_reintenta(self):
        s = Servidor(httpx.ReadTimeout("lento"))
        with self.assertRaises(llm.ModeloTimeout) as e:
            self.chat(s, timeout=7)
        self.assertEqual(s.llamadas, 1)                          # repetir una llamada de minutos solo empeora la cola
        self.assertEqual(e.exception.http, 504)
        self.assertIn("7 s", str(e.exception))
        self.assertEqual(self.espera, [])

    def test_timeout_de_conexion_si_es_transitorio(self):
        s = Servidor(httpx.ConnectTimeout("x"))
        with self.assertRaises(llm.ModeloNoDisponible):
            self.chat(s)
        self.assertEqual(s.llamadas, 3)

    # --- modelo no descargado y peticiones rechazadas
    def test_modelo_no_descargado_dice_como_descargarlo(self):
        s = Servidor(respuesta({"error": "model 'ministral-3:3b' not found"}, 404))
        with self.assertRaises(llm.ModeloNoEncontrado) as e:
            self.chat(s)
        self.assertIn("ollama pull ministral-3:3b", str(e.exception))
        self.assertEqual(s.llamadas, 1)

    def test_peticion_rechazada_no_se_reintenta(self):
        s = Servidor(respuesta({"error": "bad"}, 400))
        with self.assertRaises(llm.ErrorModelo) as e:
            self.chat(s)
        self.assertEqual((s.llamadas, e.exception.http), (1, 502))

    # --- respuestas que no sirven
    def test_respuestas_invalidas(self):
        casos = {"no JSON": "esto no es json", "lista": "[1, 2]", "faltan campos": '{"b": 1}'}
        for nombre, contenido in casos.items():
            with self.subTest(nombre), self.assertRaises(llm.RespuestaInvalida):
                self.chat(Servidor(respuesta({**OK, "message": {"content": contenido}})), esquema=ESQUEMA)

    def test_respuesta_cortada_por_el_limite_de_tokens(self):
        corte = respuesta({**OK, "message": {"content": '{"a": "tex'}, "done_reason": "length"})
        with self.assertRaises(llm.RespuestaInvalida) as e:
            self.chat(Servidor(corte), esquema=ESQUEMA, max_tokens=50)
        self.assertIn("50 tokens", str(e.exception))
        self.assertEqual(self.chat(Servidor(corte)), '{"a": "tex')            # sin esquema, un texto cortado se devuelve

    # --- cortacircuitos
    def test_el_cortacircuitos_responde_al_instante_y_se_recupera(self):
        reloj = [100.0]
        with mock.patch.object(llm, "_reloj", lambda: reloj[0]), mock.patch.dict(os.environ, {"OLLAMA_REINTENTOS": "0", "OLLAMA_FALLOS_CIRCUITO": "2"}):
            caido = Servidor(httpx.ConnectError("x"))
            for _ in range(2):
                with self.assertRaises(llm.ModeloNoDisponible):
                    self.chat(caido)
            self.assertEqual(caido.llamadas, 2)
            with self.assertRaises(llm.ModeloNoDisponible) as e:       # abierto: ni siquiera llega a Ollama
                self.chat(caido)
            self.assertEqual(caido.llamadas, 2)
            self.assertLessEqual(e.exception.reintentar_en, 20)
            reloj[0] += 21                                              # pasa el enfriamiento: se prueba otra vez
            self.assertEqual(self.chat(Servidor(respuesta(OK))), "hola")
            self.assertEqual(llm.circuito.fallos, 0)
            reloj[0] += 1
            with self.assertRaises(llm.ModeloNoDisponible):             # si la prueba falla, se vuelve a abrir enseguida
                self.chat(caido)
                self.chat(caido)

    def test_un_timeout_no_cuenta_para_el_cortacircuitos(self):
        with mock.patch.dict(os.environ, {"OLLAMA_REINTENTOS": "0", "OLLAMA_FALLOS_CIRCUITO": "2"}):
            for _ in range(4):
                with self.assertRaises(llm.ModeloTimeout):
                    self.chat(Servidor(httpx.ReadTimeout("x")))
            self.assertEqual(self.chat(Servidor(respuesta(OK))), "hola")

    # --- concurrencia
    def test_demasiadas_peticiones_a_la_vez_dan_modelo_ocupado(self):
        async def probar():
            libre = asyncio.Event()

            async def lento(request):
                await libre.wait()
                return respuesta(OK)
            transporte = httpx.MockTransport(lento)
            with mock.patch.dict(os.environ, {"OLLAMA_CONCURRENCIA": "1", "OLLAMA_ESPERA_MAX": "0.05"}):
                primera = asyncio.create_task(llm.chat(ASIGNACION, [{"role": "user", "content": "a"}], transporte=transporte))
                await asyncio.sleep(0.02)
                with self.assertRaises(llm.ModeloOcupado) as e:
                    await llm.chat(ASIGNACION, [{"role": "user", "content": "b"}], transporte=transporte)
                self.assertEqual(e.exception.http, 503)
                libre.set()
                self.assertEqual(await primera, "hola")
                self.assertEqual(await llm.chat(ASIGNACION, [{"role": "user", "content": "c"}], transporte=transporte), "hola")   # el turno se liberó
        asyncio.run(probar())

    # --- diagnóstico
    def test_estado_de_los_modelos(self):
        ok = httpx.MockTransport(lambda r: httpx.Response(200, json={"models": [{"name": "bge-m3:latest"}, {"name": "ministral-3:3b"}]}))
        r = asyncio.run(llm.estado_modelos(["ministral-3:3b", "bge-m3", "qwen3.5:9b"], transporte=ok))
        self.assertEqual((r["ollama"], r["faltan"]), ("ok", ["qwen3.5:9b"]))
        caido = httpx.MockTransport(lambda r: (_ for _ in ()).throw(httpx.ConnectError("x")))
        self.assertEqual(asyncio.run(llm.estado_modelos(["a"], transporte=caido))["ollama"], "caido")

    def test_un_diagnostico_correcto_cierra_el_cortacircuitos(self):
        with mock.patch.dict(os.environ, {"OLLAMA_REINTENTOS": "0", "OLLAMA_FALLOS_CIRCUITO": "1"}):
            with self.assertRaises(llm.ModeloNoDisponible):
                self.chat(Servidor(httpx.ConnectError("x")))
            self.assertTrue(llm.circuito.abierto_hasta > llm._reloj())
            ok = httpx.MockTransport(lambda r: httpx.Response(200, json={"models": []}))
            self.assertFalse(asyncio.run(llm.estado_modelos([], transporte=ok))["circuito_abierto"])
            self.assertEqual(self.chat(Servidor(respuesta(OK))), "hola")

    def test_embeddings_tambien_usan_reintentos(self):
        s = Servidor(httpx.ConnectError("x"), respuesta({"embeddings": [[0.1]], "prompt_eval_count": 1}))
        self.assertEqual(asyncio.run(llm.embeddings(["t"], transporte=s.transporte)), [[0.1]])
        self.assertEqual(s.llamadas, 2)


@unittest.skipUnless(HAY_HTTPX, "requiere httpx real (se ejecuta en el contenedor)")
class TestIntegracion(unittest.TestCase):
    def test_modelos_necesarios_del_perfil(self):
        from pathlib import Path
        from cerebro.router_modelos import modelos_necesarios
        m = modelos_necesarios("pequena", Path(__file__).resolve().parents[2] / "config")
        self.assertIn("bge-m3", m)
        self.assertEqual(m, sorted(m))

    def test_la_api_traduce_los_errores_del_modelo(self):
        try:
            from fastapi.testclient import TestClient
            from cerebro.api import main
        except ImportError as e:
            self.skipTest(str(e))

        def lanza(e):
            async def ruta():
                raise e
            return ruta
        casos = {"/_p/caido": (llm.ModeloNoDisponible("Ollama no responde", reintentar_en=30), 503),
                 "/_p/lento": (llm.ModeloTimeout("Tardó demasiado", reintentar_en=60), 504),
                 "/_p/ocupado": (llm.ModeloOcupado("Demasiadas peticiones", reintentar_en=15), 503),
                 "/_p/falta": (llm.ModeloNoEncontrado("Falta el modelo"), 503),
                 "/_p/mal": (llm.RespuestaInvalida("JSON roto"), 502)}
        for ruta, (error, _) in casos.items():
            main.app.add_api_route(ruta, lanza(error))
        cliente = TestClient(main.app)            # sin «with»: no arranca la base de datos
        for ruta, (error, estado) in casos.items():
            r = cliente.get(ruta)
            self.assertEqual(r.status_code, estado, ruta)
            self.assertEqual(r.json()["detail"], str(error))        # el panel muestra «detail»
            self.assertEqual(r.json()["codigo"], error.codigo)
            self.assertEqual(r.headers.get("retry-after"), str(error.reintentar_en) if error.reintentar_en else None)

    def test_el_grafo_solo_cambia_de_modelo_si_la_respuesta_era_invalida(self):
        try:
            from cerebro.grafo import nodos
        except ImportError as e:
            self.skipTest(str(e))
        llamadas = []

        async def invalida_y_luego_bien(asignacion, mensajes, esquema=None, **k):
            llamadas.append(asignacion.clase)
            if len(llamadas) == 1:
                raise llm.RespuestaInvalida("JSON roto")
            return {"departamento": "finanzas", "motivo": "x"}

        async def caido(*a, **k):
            llamadas.append("caido")
            raise llm.ModeloNoDisponible("Ollama no responde")
        with mock.patch.object(nodos, "chat", invalida_y_luego_bien):
            self.assertEqual(asyncio.run(nodos.enrutar({"peticion": "x"})), {"departamento": "finanzas"})
        self.assertEqual(len(llamadas), 2)                          # una respuesta inválida sí se reintenta con otro modelo
        llamadas.clear()
        with mock.patch.object(nodos, "chat", caido), self.assertRaises(llm.ModeloNoDisponible):
            asyncio.run(nodos.enrutar({"peticion": "x"}))
        self.assertEqual(llamadas, ["caido"])                       # si Ollama está caído, cambiar de modelo no sirve de nada

    def test_las_tareas_programadas_reintentan_mas_tarde(self):
        try:
            from cerebro.tareas import celery_app
        except ImportError as e:
            self.skipTest(str(e))
        tarea = celery_app.ejecutar_programada
        self.assertIn(llm.ModeloNoDisponible, tarea.autoretry_for)
        self.assertIn(llm.ModeloTimeout, tarea.autoretry_for)
        self.assertEqual(tarea.max_retries, 4)


if __name__ == "__main__":
    unittest.main()
