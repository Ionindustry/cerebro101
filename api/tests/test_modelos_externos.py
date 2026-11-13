"""Modelos externos (Claude y ChatGPT): interruptor, anonimización de ida y vuelta, reglas de sensibilidad, tope diario y errores (API simulada)."""
import asyncio
import json
import os
import unittest
from unittest import mock

import _sin_servicios  # noqa: F401
import httpx

from cerebro import anonimizacion as anon
from cerebro import modelos_externos as m
from cerebro.entidades import Entidades

HTTPX_REAL = hasattr(httpx, "MockTransport")
ESQUEMA = {"type": "object", "properties": {"tipo": {"type": "string"}, "respuesta": {"type": "string"}}, "required": ["tipo"]}


class Ficha:
    def __init__(self, id="agente-x", sensibilidad="media"):
        self.id, self.sensibilidad, self.modelo = id, sensibilidad, "rapido"


def msgs(texto="Analiza la propuesta de Marta Puig y compara con la del año pasado"):
    return [{"role": "system", "content": "Eres un agente."}, {"role": "user", "content": texto}]


def claude_ok(visto: list, salida=None):
    def manejar(req):
        visto.append((req.url.path, dict(req.headers), json.loads(req.content)))
        return httpx.Response(200, json={"content": [{"type": "tool_use", "name": "responder",
                                                      "input": salida or {"tipo": "respuesta", "respuesta": "Hecho"}}]})
    return httpx.MockTransport(manejar)


def gpt_ok(visto: list, salida=None):
    def manejar(req):
        visto.append((req.url.path, dict(req.headers), json.loads(req.content)))
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(salida or {"tipo": "respuesta", "respuesta": "Hecho"})}}]})
    return httpx.MockTransport(manejar)


def entorno(**kw):
    base = {"ANTHROPIC_API_KEY": "", "OPENAI_API_KEY": "", "CLAUDE_MODELO": "", "CHATGPT_MODELO": ""}
    return mock.patch.dict(os.environ, {**base, **kw})


def parches(conectados, usadas=0):
    async def activos():
        return conectados

    async def hoy(_p):
        return usadas

    async def nada(*a, **k):
        return None
    return [mock.patch.object(m, "activos", activos), mock.patch.object(m, "usadas_hoy", hoy),
            mock.patch.object(m.actividad, "marcar", nada), mock.patch.object(m.actividad, "contar", nada),
            mock.patch.object(m, "cargar_entidades", lambda cfg: _ent())]


async def _ent():
    return Entidades(personas=["Marta Puig"])


def consultar(ficha, mensajes, conectados, transporte, usadas=0, sens=None):
    ps = parches(conectados, usadas)
    for p in ps:
        p.start()
    try:
        return asyncio.run(m.consultar(ficha, mensajes, ESQUEMA, sens, transporte))
    finally:
        for p in ps:
            p.stop()


class TestComplejidad(unittest.TestCase):
    def test_un_texto_largo_o_que_pide_analisis_es_complejo(self):
        self.assertTrue(m.es_compleja("Analiza esta oferta"))
        self.assertTrue(m.es_compleja("Compara los dos presupuestos"))
        self.assertTrue(m.es_compleja("Necesito una ESTRATÈGIA de captación"))
        self.assertTrue(m.es_compleja("x" * 700))

    def test_una_consulta_simple_no_lo_es(self):
        self.assertFalse(m.es_compleja("¿Qué hora es en la reunión de mañana?"))
        self.assertFalse(m.es_compleja("Busca el teléfono del cliente"))

    def test_la_sensibilidad_alta_nunca_sale(self):
        self.assertTrue(m.permitido_para("baja"))
        self.assertTrue(m.permitido_para("media"))
        self.assertFalse(m.permitido_para("alta"))
        self.assertFalse(m.permitido_para("baja", "alta"))       # una petición marcada como alta también lo impide
        self.assertTrue(m.permitido_para("baja", "media"))


@unittest.skipUnless(HTTPX_REAL, "requiere httpx real (se ejecuta en el contenedor)")
class TestConsultar(unittest.TestCase):
    def test_desconectado_no_sale_nada(self):
        visto: list = []
        with entorno(ANTHROPIC_API_KEY="k"):
            self.assertIsNone(consultar(Ficha(), msgs(), {"claude": False}, claude_ok(visto)))
        self.assertEqual(visto, [])

    def test_sin_clave_no_sale_nada_aunque_este_conectado(self):
        visto: list = []
        with entorno():
            self.assertIsNone(consultar(Ficha(), msgs(), {"claude": True}, claude_ok(visto)))
        self.assertEqual(visto, [])

    def test_agente_de_sensibilidad_alta_no_usa_modelos_externos(self):
        visto: list = []
        with entorno(ANTHROPIC_API_KEY="k"):
            self.assertIsNone(consultar(Ficha(sensibilidad="alta"), msgs(), {"claude": True}, claude_ok(visto)))
        self.assertEqual(visto, [])

    def test_claude_recibe_etiquetas_y_la_respuesta_vuelve_con_los_datos_reales(self):
        visto: list = []
        salida = {"tipo": "respuesta", "respuesta": "Contesta a [PERSONA_1] hoy"}
        with entorno(ANTHROPIC_API_KEY="clave-claude"):
            r = consultar(Ficha(), msgs(), {"claude": True}, claude_ok(visto, salida))
        self.assertEqual(r["respuesta"], "Contesta a Marta Puig hoy")          # se restaura en memoria
        ruta, cabeceras, cuerpo = visto[0]
        self.assertEqual(ruta, "/v1/messages")
        self.assertEqual(cabeceras["x-api-key"], "clave-claude")
        self.assertNotIn("Marta", json.dumps(cuerpo))                          # el nombre real no sale del servidor
        self.assertIn("[PERSONA_1]", cuerpo["messages"][0]["content"])
        self.assertEqual(cuerpo["tool_choice"], {"type": "tool", "name": "responder"})
        self.assertEqual(cuerpo["tools"][0]["input_schema"], ESQUEMA)
        self.assertEqual(cuerpo["model"], "claude-opus-5-5")

    def test_si_claude_olvida_el_tipo_se_deduce_en_vez_de_descartar_la_respuesta(self):
        with entorno(ANTHROPIC_API_KEY="clave-claude"):
            herr = consultar(Ficha(), msgs(), {"claude": True}, claude_ok([], {"herramienta": "ofertas", "operacion": "leer", "argumentos": {}}))
            resp = consultar(Ficha(), msgs(), {"claude": True}, claude_ok([], {"respuesta": "Hecho"}))
            vacia = consultar(Ficha(), msgs(), {"claude": True}, claude_ok([], {"argumentos": {}}))
        self.assertEqual((herr["tipo"], herr["herramienta"]), ("herramienta", "ofertas"))
        self.assertEqual((resp["tipo"], resp["respuesta"]), ("respuesta", "Hecho"))
        self.assertIsNone(vacia)                                               # sin nada que permita deducirlo sigue siendo inválida: se usa el modelo local

    def test_completar_tipo_no_toca_lo_que_ya_lo_trae_ni_esquemas_sin_tipo(self):
        from cerebro.llm import completar_tipo
        con_tipo = {"tipo": "respuesta", "respuesta": "x", "herramienta": "y"}
        self.assertEqual(completar_tipo(con_tipo, ESQUEMA), con_tipo)
        self.assertEqual(completar_tipo({"respuesta": "x"}, {"properties": {"agente": {}}}), {"respuesta": "x"})

    def test_el_modelo_se_puede_cambiar_con_el_entorno(self):
        visto: list = []
        with entorno(ANTHROPIC_API_KEY="k", CLAUDE_MODELO="claude-sonnet-5-5"):
            consultar(Ficha(), msgs(), {"claude": True}, claude_ok(visto))
        self.assertEqual(visto[0][2]["model"], "claude-sonnet-5-5")

    def test_chatgpt_usa_json_y_restaura_los_datos(self):
        visto: list = []
        salida = {"tipo": "respuesta", "respuesta": "Llama a [PERSONA_1]"}
        with entorno(OPENAI_API_KEY="clave-gpt"):
            r = consultar(Ficha(), msgs(), {"chatgpt": True}, gpt_ok(visto, salida))
        self.assertEqual(r["respuesta"], "Llama a Marta Puig")
        ruta, cabeceras, cuerpo = visto[0]
        self.assertEqual(ruta, "/v1/chat/completions")
        self.assertEqual(cabeceras["authorization"], "Bearer clave-gpt")
        self.assertNotIn("Marta", json.dumps(cuerpo))
        self.assertEqual(cuerpo["response_format"], {"type": "json_object"})
        self.assertIn('"required"', cuerpo["messages"][0]["content"])         # el esquema va en las instrucciones

    def test_claude_va_primero_y_si_falla_pasa_a_chatgpt(self):
        visto: list = []
        caido = httpx.MockTransport(lambda req: httpx.Response(429, json={}))

        def enrutar(req):
            return (caido if req.url.host == "api.anthropic.com" else gpt_ok(visto)).handle_request(req)
        with entorno(ANTHROPIC_API_KEY="a", OPENAI_API_KEY="o"):
            r = consultar(Ficha(), msgs(), {"claude": True, "chatgpt": True}, httpx.MockTransport(enrutar))
        self.assertEqual(r["tipo"], "respuesta")
        self.assertEqual(len(visto), 1)

    def test_si_claude_rechaza_forzar_la_herramienta_se_reintenta_sin_forzar(self):
        cuerpos: list = []

        def manejar(req):
            cuerpo = json.loads(req.content)
            cuerpos.append(cuerpo)
            if cuerpo["tool_choice"]["type"] == "tool":
                return httpx.Response(400, json={"error": {"message": "tool_choice no se admite con thinking"}})
            return httpx.Response(200, json={"content": [{"type": "tool_use", "name": "responder", "input": {"tipo": "respuesta", "respuesta": "ok"}}]})
        with entorno(ANTHROPIC_API_KEY="k"):
            r = consultar(Ficha(), msgs(), {"claude": True}, httpx.MockTransport(manejar))
        self.assertEqual(r["respuesta"], "ok")
        self.assertEqual([c["tool_choice"]["type"] for c in cuerpos], ["tool", "auto"])
        self.assertIn("llamando a la herramienta", cuerpos[1]["system"])

    def test_un_error_del_proveedor_explica_el_motivo(self):
        malo = httpx.MockTransport(lambda req: httpx.Response(400, json={"error": {"message": "max_tokens demasiado alto para este modelo"}}))
        with entorno(ANTHROPIC_API_KEY="k"):
            e = asyncio.run(m.probar("claude", malo))
        self.assertFalse(e["prueba"]["ok"])
        self.assertIn("max_tokens demasiado alto", e["prueba"]["detalle"])

    def test_si_todos_fallan_devuelve_none_y_sigue_el_modelo_local(self):
        caido = httpx.MockTransport(lambda req: httpx.Response(500, json={}))
        with entorno(ANTHROPIC_API_KEY="a"):
            self.assertIsNone(consultar(Ficha(), msgs(), {"claude": True}, caido))

    def test_datos_que_no_se_pueden_anonimizar_no_salen(self):
        visto: list = []
        with entorno(ANTHROPIC_API_KEY="a"):
            r = consultar(Ficha(), msgs("Analiza el caso: el empleado tiene una depresión desde marzo"), {"claude": True}, claude_ok(visto))
        self.assertIsNone(r)
        self.assertEqual(visto, [])

    def test_texto_demasiado_largo_no_sale(self):
        visto: list = []
        with entorno(ANTHROPIC_API_KEY="a"):
            self.assertIsNone(consultar(Ficha(), msgs("Analiza " + "palabra " * 700), {"claude": True}, claude_ok(visto)))
        self.assertEqual(visto, [])

    def test_el_tope_diario_manda(self):
        visto: list = []
        with entorno(ANTHROPIC_API_KEY="a"):
            r = consultar(Ficha(), msgs(), {"claude": True}, claude_ok(visto), usadas=m.configuracion()["limite_diario"])
        self.assertIsNone(r)
        self.assertEqual(visto, [])

    def test_la_misma_persona_lleva_la_misma_etiqueta_en_todos_los_mensajes(self):
        visto: list = []
        mensajes = [{"role": "system", "content": "s"}, {"role": "user", "content": "Analiza lo de Marta Puig"},
                    {"role": "assistant", "content": '{"tipo": "herramienta"}'},
                    {"role": "user", "content": "Resultado: Marta Puig tiene 3 pedidos"}]
        with entorno(ANTHROPIC_API_KEY="a"):
            consultar(Ficha(), mensajes, {"claude": True}, claude_ok(visto))
        enviados = visto[0][2]["messages"]
        self.assertEqual([x["role"] for x in enviados], ["user", "assistant", "user"])       # alternan, como exige Claude
        self.assertIn("[PERSONA_1]", enviados[0]["content"])
        self.assertIn("[PERSONA_1]", enviados[2]["content"])


@unittest.skipUnless(HTTPX_REAL, "requiere httpx real (se ejecuta en el contenedor)")
class TestEstadoYPrueba(unittest.TestCase):
    def estado(self, conectados, transporte=None, probar=None):
        ps = parches(conectados)
        for p in ps:
            p.start()
        try:
            return asyncio.run(m.estado(probar, transporte))
        finally:
            for p in ps:
                p.stop()

    def test_el_estado_distingue_sin_clave_desconectado_y_conectado(self):
        with entorno(ANTHROPIC_API_KEY="secreto-claude"):
            e = self.estado({"claude": True})
        por_id = {p["id"]: p for p in e["proveedores"]}
        self.assertEqual(por_id["claude"]["estado"], "conectado")
        self.assertEqual(por_id["chatgpt"]["estado"], "sin_clave")
        with entorno(ANTHROPIC_API_KEY="secreto-claude"):
            self.assertEqual({p["id"]: p["estado"] for p in self.estado({})["proveedores"]}["claude"], "desconectado")

    def test_el_estado_nunca_devuelve_una_clave(self):
        with entorno(ANTHROPIC_API_KEY="secreto-claude", OPENAI_API_KEY="secreto-gpt"):
            texto = json.dumps(self.estado({"claude": True, "chatgpt": True}))
        self.assertNotIn("secreto", texto)

    def test_probar_hace_una_pregunta_sin_datos_y_dice_si_funciona(self):
        visto: list = []
        with entorno(ANTHROPIC_API_KEY="k"):
            e = self.estado({"claude": True}, claude_ok(visto, {"ok": True}), probar="claude")
        self.assertTrue(e["proveedores"][0]["prueba"]["ok"])
        self.assertNotIn("Marta", json.dumps(visto))

    def test_probar_con_clave_mala_explica_el_motivo(self):
        malo = httpx.MockTransport(lambda req: httpx.Response(401, json={}))
        with entorno(OPENAI_API_KEY="mala"):
            e = self.estado({"chatgpt": True}, malo, probar="chatgpt")
        prueba = {p["id"]: p for p in e["proveedores"]}["chatgpt"]["prueba"]
        self.assertFalse(prueba["ok"])
        self.assertIn("clave", prueba["detalle"])


class TestEnElGrafo(unittest.TestCase):
    """`_paso_del_agente`: una consulta compleja va al modelo externo si responde; si no, o si es simple, al local."""

    def paso(self, peticion, externo, local):
        from cerebro.grafo import nodos
        llamadas = {"externo": 0, "local": 0}

        async def consultar_(*a, **k):
            llamadas["externo"] += 1
            return externo

        async def chat_(*a, **k):
            llamadas["local"] += 1
            return local
        mensajes = [{"role": "system", "content": "s"}, {"role": "user", "content": peticion}]
        with mock.patch.object(nodos.modelos_externos, "consultar", consultar_), mock.patch.object(nodos, "chat", chat_):
            return asyncio.run(nodos._paso_del_agente(Ficha(), {"peticion": peticion}, mensajes)), llamadas

    def test_compleja_y_con_respuesta_externa_no_toca_el_local(self):
        r, n = self.paso("Analiza la propuesta", {"tipo": "respuesta", "respuesta": "externo"}, {"tipo": "respuesta", "respuesta": "local"})
        self.assertEqual((r["respuesta"], n), ("externo", {"externo": 1, "local": 0}))

    def test_compleja_sin_respuesta_externa_cae_al_local(self):
        r, n = self.paso("Analiza la propuesta", None, {"tipo": "respuesta", "respuesta": "local"})
        self.assertEqual((r["respuesta"], n), ("local", {"externo": 1, "local": 1}))

    def test_simple_ni_pregunta_al_externo(self):
        r, n = self.paso("¿Qué hora es?", {"tipo": "respuesta", "respuesta": "externo"}, {"tipo": "respuesta", "respuesta": "local"})
        self.assertEqual((r["respuesta"], n), ("local", {"externo": 0, "local": 1}))

    def test_una_respuesta_externa_vacia_o_sin_herramienta_se_descarta(self):
        local = {"tipo": "respuesta", "respuesta": "local"}
        for vacia in ({"tipo": "respuesta"}, {"tipo": "respuesta", "respuesta": "  "}, {"tipo": "herramienta"}):
            r, n = self.paso("Analiza la propuesta", vacia, local)
            self.assertEqual((r["respuesta"], n["local"]), ("local", 1), vacia)
        r, n = self.paso("Analiza la propuesta", {"tipo": "herramienta", "herramienta": "erpnext", "operacion": "leer"}, local)
        self.assertEqual((r["herramienta"], n["local"]), ("erpnext", 0))

    def test_una_respuesta_externa_sin_tipo_valido_se_descarta(self):
        r, n = self.paso("Analiza la propuesta", {"respuesta": "rara"}, {"tipo": "respuesta", "respuesta": "local"})
        self.assertEqual(r["respuesta"], "local")


class TestDesanonimizar(unittest.TestCase):
    def test_ida_y_vuelta_en_texto_listas_y_diccionarios(self):
        sesion: dict = {}
        r = anon.anonimizar("Escribe a marta@ejemplo.com", Entidades(personas=["Marta Puig"]), cfg={}, sesion=sesion)
        self.assertNotIn("marta@ejemplo.com", r.texto)
        etiqueta = next(iter(sesion["equivalencias"]))
        self.assertEqual(anon.desanonimizar({"a": [f"para {etiqueta}"], "n": 3}, sesion), {"a": ["para marta@ejemplo.com"], "n": 3})

    def test_el_resumen_de_auditoria_no_lleva_la_tabla(self):
        sesion: dict = {}
        r = anon.anonimizar("Llama a Marta Puig", Entidades(personas=["Marta Puig"]), cfg={}, sesion=sesion)
        self.assertNotIn("Marta", json.dumps(r.resumen()))

    def test_sin_sesion_se_comporta_como_antes(self):
        r = anon.anonimizar("Llama a Marta Puig", Entidades(personas=["Marta Puig"]), cfg={})
        self.assertIn("[PERSONA_1]", r.texto)


class TestRespuestasRaras(unittest.TestCase):
    """Lo que pasó de verdad: Claude respondió pero sin el campo esperado, o se quedó sin espacio. Ahora se entiende o se explica."""
    ESQUEMA_SEC = {"type": "object", "properties": {"secciones": {"type": "array"}}, "required": ["secciones"]}

    def llamar(self, respuesta_json, normalizar=None, max_tokens=None):
        def manejar(req):
            return httpx.Response(200, json=respuesta_json)
        with entorno(ANTHROPIC_API_KEY="k"):
            return asyncio.run(m._llamar("claude", [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}], self.ESQUEMA_SEC, httpx.MockTransport(manejar),
                                         max_tokens=max_tokens, normalizar=normalizar))

    def test_una_respuesta_cortada_por_tamano_se_distingue_de_una_mal_formada(self):
        with self.assertRaises(m.RespuestaCortada) as c:
            self.llamar({"stop_reason": "max_tokens", "content": [{"type": "tool_use", "name": "responder", "input": {}}]}, max_tokens=4000)
        self.assertIn("4000 tokens", str(c.exception))
        with self.assertRaises(m.RespuestaInvalida) as c:
            self.llamar({"stop_reason": "end_turn", "content": [{"type": "text", "text": "hola"}]})
        self.assertNotIsInstance(c.exception, m.RespuestaCortada)

    def test_si_faltan_campos_el_mensaje_dice_cuales_llegaron(self):
        with self.assertRaises(m.RespuestaInvalida) as c:
            self.llamar({"stop_reason": "tool_use", "content": [{"type": "tool_use", "name": "responder", "input": {"clave": "a", "contenido": "x"}}]})
        self.assertIn("Faltan campos", str(c.exception))
        self.assertIn("llegaron: ['clave', 'contenido']", str(c.exception))

    def test_el_llamador_puede_aceptar_otra_forma_de_la_misma_respuesta(self):
        r = self.llamar({"stop_reason": "tool_use", "content": [{"type": "tool_use", "name": "responder", "input": {"contenido": "x"}}]},
                        normalizar=lambda d: {"secciones": [{"clave": "a", "contenido": d["contenido"]}]})
        self.assertEqual(r["secciones"][0]["contenido"], "x")

    def test_chatgpt_cortado_por_tamano_tambien_se_distingue(self):
        def manejar(req):
            return httpx.Response(200, json={"choices": [{"finish_reason": "length", "message": {"content": "{\"secciones\": [{\"cla"}}]})
        with entorno(OPENAI_API_KEY="k"), self.assertRaises(m.RespuestaCortada):
            asyncio.run(m._llamar("chatgpt", [{"role": "user", "content": "u"}], self.ESQUEMA_SEC, httpx.MockTransport(manejar)))

    def test_consultar_publico_repite_una_vez_con_el_doble_si_se_corta(self):
        usados = []

        async def llamar(p, mensajes, esquema, transporte=None, max_tokens=None, timeout=None, normalizar=None):
            usados.append(max_tokens)
            if max_tokens < 12000:
                raise m.RespuestaCortada("Claude cortó la respuesta")
            return {"secciones": []}

        async def activos():
            return {"claude": True}

        async def cero(p):
            return 0

        async def nada(*a, **k):
            return None
        with entorno(ANTHROPIC_API_KEY="k"), mock.patch.object(m, "_llamar", llamar), mock.patch.object(m, "activos", activos), mock.patch.object(m, "usadas_hoy", cero), \
                mock.patch.object(m.actividad, "contar", nada):
            r = asyncio.run(m.consultar_publico("t", [{"role": "user", "content": "x"}], {"type": "object"}, max_tokens=6000))
        self.assertEqual((r, usados), (({"secciones": []}, "claude"), [6000, 12000]))
        usados.clear()

        async def siempre_corta(*a, **k):
            usados.append(k.get("max_tokens"))
            raise m.RespuestaCortada("Claude cortó la respuesta: el límite se quedó corto")
        with entorno(ANTHROPIC_API_KEY="k"), mock.patch.object(m, "_llamar", siempre_corta), mock.patch.object(m, "activos", activos), mock.patch.object(m, "usadas_hoy", cero), \
                mock.patch.object(m.actividad, "contar", nada), self.assertRaises(m.ErrorExterno) as c:
            asyncio.run(m.consultar_publico("t", [{"role": "user", "content": "x"}], {"type": "object"}, max_tokens=6000))
        self.assertEqual(usados, [6000, 12000])                                                    # solo UN reintento
        self.assertIn("cortó la respuesta", str(c.exception))


class TestEleccionDelModelo(unittest.TestCase):
    def test_los_modelos_posibles_incluyen_siempre_el_de_por_defecto(self):
        with entorno(CLAUDE_MODELO="", CHATGPT_MODELO=""):
            c = m.modelos_posibles("claude")
            self.assertIn("claude-opus-5-5", c)
            self.assertIn("claude-sonnet-5-5", c)
            self.assertEqual(c[0] if m.modelo("claude") not in m.configuracion()["proveedores"]["claude"].get("modelos", []) else m.modelo("claude"), m.modelo("claude"))
        with entorno(CLAUDE_MODELO="mi-modelo-propio"):
            self.assertEqual(m.modelos_posibles("claude")[0], "mi-modelo-propio")         # el del .env siempre se puede elegir

    def test_un_modelo_que_no_esta_permitido_se_rechaza_antes_de_tocar_la_base(self):
        with self.assertRaises(ValueError) as c:
            asyncio.run(m.poner_modelo("claude", "gpt-5", "albert"))
        self.assertIn("no es uno de los modelos permitidos", str(c.exception))
        with self.assertRaises(ValueError):
            asyncio.run(m.poner_modelo("chatgpt", "'; DROP TABLE x; --", "albert"))

    def test_sin_base_se_usa_el_de_por_defecto(self):
        async def sin_base():
            raise OSError("sin base")
        with mock.patch.object(m, "_conectar", sin_base), entorno(CLAUDE_MODELO=""):
            self.assertEqual(asyncio.run(m.modelo_elegido("claude")), m.modelo("claude"))

    def test_el_modelo_elegido_es_el_que_se_envia_al_proveedor(self):
        visto: list = []

        async def elegido(p):
            return "claude-sonnet-5-5"
        with entorno(ANTHROPIC_API_KEY="k"), mock.patch.object(m, "modelo_elegido", elegido):
            consultar(Ficha(), msgs(), {"claude": True}, claude_ok(visto))
        self.assertEqual(visto[0][2]["model"], "claude-sonnet-5-5")


URL_PG = os.environ.get("CEREBRO_TEST_PG")


@unittest.skipUnless(URL_PG, "sin CEREBRO_TEST_PG")
class TestEleccionDelModeloEnBD(unittest.TestCase):
    def setUp(self):
        import time
        from pathlib import Path
        from types import SimpleNamespace
        import psycopg
        self.schema = f"t_mext_{time.time_ns()}"
        with psycopg.connect(URL_PG, autocommit=True) as c:
            c.execute(f"CREATE SCHEMA {self.schema}")
            c.execute(f"SET search_path = {self.schema}")
            t = (Path(__file__).resolve().parents[2] / "db" / "esquema.sql").read_text(encoding="utf-8")
            c.execute(t[t.index("CREATE TABLE IF NOT EXISTS modelos_externos"):t.index("-- Registro de acciones ejecutadas")])
        sep = "&" if "?" in URL_PG else "?"
        self.parche = mock.patch.object(m, "ajustes", SimpleNamespace(database_url=f"{URL_PG}{sep}options=-csearch_path%3D{self.schema}", dir_config=m.ajustes.dir_config))
        self.parche.start()

    def tearDown(self):
        import psycopg
        self.parche.stop()
        with psycopg.connect(URL_PG, autocommit=True) as c:
            c.execute(f"DROP SCHEMA {self.schema} CASCADE")

    def test_elegir_cambiar_y_volver_al_de_por_defecto_sin_tocar_la_conexion(self):
        with entorno(CLAUDE_MODELO=""):
            por_defecto = m.modelo("claude")
            asyncio.run(m.poner("claude", True, "albert"))
            self.assertEqual(asyncio.run(m.modelo_elegido("claude")), por_defecto)
            asyncio.run(m.poner_modelo("claude", "claude-sonnet-5-5", "albert"))
            self.assertEqual(asyncio.run(m.modelo_elegido("claude")), "claude-sonnet-5-5")
            self.assertTrue(asyncio.run(m.activos())["claude"])                          # elegir modelo no desconecta
            asyncio.run(m.poner_modelo("claude", "auto", "albert"))
            self.assertEqual(asyncio.run(m.modelo_elegido("claude")), por_defecto)
            asyncio.run(m.poner_modelo("chatgpt", "gpt-5-mini", "albert"))               # elegir sin haberlo conectado nunca: queda desconectado
            self.assertFalse(asyncio.run(m.activos())["chatgpt"])
            e = asyncio.run(m.estado())
            self.assertEqual([p["modelo"] for p in e["proveedores"] if p["id"] == "chatgpt"], ["gpt-5-mini"])
            self.assertIn("gpt-5", [p["modelos"] for p in e["proveedores"] if p["id"] == "chatgpt"][0])

    def test_el_endpoint_solo_lo_cambia_direccion_y_solo_a_un_modelo_permitido(self):
        from cerebro.api import main
        from cerebro.api.main import Usuario, usuario_actual
        from fastapi.testclient import TestClient
        c = TestClient(main.app)
        try:
            main.app.dependency_overrides[usuario_actual] = lambda: Usuario("marta", {"usuario"}, {"licitaciones"})
            self.assertEqual(c.post("/modelos-externos/claude/modelo", json={"modelo": "claude-sonnet-5-5"}).status_code, 403)
            main.app.dependency_overrides[usuario_actual] = lambda: Usuario("albert", {"direccion"}, set())
            self.assertEqual(c.post("/modelos-externos/gemini/modelo", json={"modelo": "x"}).status_code, 404)
            self.assertEqual(c.post("/modelos-externos/claude/modelo", json={"modelo": "gpt-5"}).status_code, 422)
            with mock.patch.object(main.constancia, "dejar_constancia", mock.AsyncMock()):
                r = c.post("/modelos-externos/claude/modelo", json={"modelo": "claude-sonnet-5-5"})
            self.assertEqual(r.status_code, 200)
            self.assertEqual([p["modelo"] for p in r.json()["proveedores"] if p["id"] == "claude"], ["claude-sonnet-5-5"])
        finally:
            main.app.dependency_overrides.clear()


if __name__ == "__main__":
    unittest.main()
