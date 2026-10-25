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


if __name__ == "__main__":
    unittest.main()
