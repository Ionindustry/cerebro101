"""jeff (sustituto local de Jev): formato de las respuestas, validaciones y estado de las vías de decisión (Jev, jeff, local)."""
import asyncio
import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

import _sin_servicios  # noqa: F401

try:
    import fastapi  # noqa: F401
    import httpx
    HAY = hasattr(httpx, "MockTransport")
except ImportError:
    HAY = False

RAIZ = Path(__file__).resolve().parents[2]


def cargar_jeff():
    os.environ.setdefault("CEREBRO_CONFIG", str(RAIZ / "config"))
    spec = importlib.util.spec_from_file_location("jeff_servidor", RAIZ / "servicios" / "jeff" / "servidor.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m                 # pydantic resuelve los tipos por el nombre del módulo
    spec.loader.exec_module(m)
    return m


def ollama_falso(salida: dict, etiquetas=("qwen3.5:9b",), caido=False):
    visto = []

    def manejar(req):
        if caido:
            raise httpx.ConnectError("caído")
        if req.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": n} for n in etiquetas]})
        visto.append(json.loads(req.content))
        return httpx.Response(200, json={"message": {"content": json.dumps(salida)}})
    return httpx.MockTransport(manejar), visto


@unittest.skipUnless(HAY, "requiere fastapi y httpx reales")
class TestServicioJeff(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.j = cargar_jeff()

    def llamar(self, cuerpo, salida=None, **k):
        transporte, visto = ollama_falso(salida or {"si": True, "confianza": 0.9}, **k)
        real = httpx.AsyncClient

        async def ir():
            with mock.patch.object(self.j.httpx, "AsyncClient", lambda **kw: real(transport=transporte, **kw)):
                async with real(transport=httpx.ASGITransport(app=self.j.app), base_url="http://jeff") as c:
                    return await c.post("/v1/systemone", json=cuerpo)
        return asyncio.run(ir()), visto

    def test_si_no_formato_de_jev(self):
        r, visto = self.llamar({"model": "jev-latest", "state": "El grabador lleva tres días sin grabar", "questions": {"q": {"type": "noul", "instructions": "¿Es urgente?"}}},
                               {"si": True, "confianza": 0.8})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["answers"]["q"], {"noul": 0.8})
        self.assertEqual(visto[0]["options"]["temperature"], 0)
        self.assertIs(visto[0]["think"], False)
        self.assertEqual(visto[0]["format"]["required"], ["si", "confianza"])

    def test_no_se_traduce_a_probabilidad_baja(self):
        r, _ = self.llamar({"state": "x", "questions": {"q": {"type": "noul", "instructions": "¿?"}}}, {"si": False, "confianza": 0.9})
        self.assertEqual(r.json()["answers"]["q"]["noul"], 0.1)

    def test_eleccion_con_probabilidades_que_suman_uno(self):
        r, visto = self.llamar({"state": "x", "questions": {"q": {"type": "choice", "instructions": "Elige", "criteria": {"soporte": None, "ventas": None, "otro": None}}}},
                               {"eleccion": "soporte", "confianza": 0.8})
        a = r.json()["answers"]["q"]
        self.assertEqual((a["choice"], a["confidence"]), ("soporte", 0.8))
        self.assertAlmostEqual(sum(a["probabilities"].values()), 1.0, places=2)
        self.assertEqual(visto[0]["format"]["properties"]["eleccion"]["enum"], ["soporte", "ventas", "otro"])

    def test_puntuacion_con_diez_niveles(self):
        niveles = [f"Nivel {i} de 9" for i in range(10)]
        r, _ = self.llamar({"state": "x", "questions": {"q": {"type": "score", "instructions": "Puntúa", "criteria": niveles}}}, {"nivel": 7, "confianza": 0.7})
        a = r.json()["answers"]["q"]
        self.assertEqual((a["score"], len(a["probabilities"])), (7, 10))
        self.assertAlmostEqual(sum(a["probabilities"]), 1.0, places=2)

    def test_validaciones(self):
        for cuerpo, codigo in [({"state": "  ", "questions": {"q": {"type": "noul"}}}, 422),
                               ({"state": "x", "questions": {}}, 422),
                               ({"state": "x", "questions": {"q": {"type": "raro"}}}, 422),
                               ({"state": "x", "questions": {"q": {"type": "choice", "criteria": {}}}}, 422),
                               ({"state": "x" * 30000, "questions": {"q": {"type": "noul"}}}, 413)]:
            with self.subTest(codigo=codigo):
                self.assertEqual(self.llamar(cuerpo)[0].status_code, codigo)

    def test_modelo_que_responde_mal_da_502_y_ollama_caido_503(self):
        r, _ = self.llamar({"state": "x", "questions": {"q": {"type": "noul"}}}, {"cosa": 1})
        self.assertEqual(r.status_code, 502)
        r, _ = self.llamar({"state": "x", "questions": {"q": {"type": "noul"}}}, caido=True)
        self.assertEqual(r.status_code, 503)

    def test_modelo_juez_del_perfil(self):
        os.environ.pop("JEFF_MODELO", None)
        self.j.PERFIL = "minima"
        self.assertEqual(self.j.modelo(), "qwen3.5:4b")
        self.j.PERFIL = "pequena"
        self.assertEqual(self.j.modelo(), "qwen3.5:9b")

    def test_salud_operativa_solo_si_el_modelo_esta_descargado(self):
        async def salud(**k):
            transporte, _ = ollama_falso({}, **k)
            real = httpx.AsyncClient
            with mock.patch.object(self.j.httpx, "AsyncClient", lambda **kw: real(transport=transporte, **kw)):
                async with real(transport=httpx.ASGITransport(app=self.j.app), base_url="http://jeff") as c:
                    return await c.get("/salud")
        self.assertEqual(asyncio.run(salud(etiquetas=("qwen3.5:9b",))).status_code, 200)
        self.assertEqual(asyncio.run(salud(etiquetas=("otro:1b",))).status_code, 503)
        self.assertEqual(asyncio.run(salud(caido=True)).status_code, 503)


@unittest.skipUnless(HAY, "requiere httpx real")
class TestEstadoDeLasVias(unittest.TestCase):
    def setUp(self):
        from types import SimpleNamespace
        from cerebro.herramientas import decision as d
        self.d = d
        d._CACHE.update(cuando=0.0, datos=None)
        self.ajustes = lambda **k: SimpleNamespace(**{"usar_jev_nube": False, "jev_url": "https://jev", "jev_api_key": "", "jeff_url": "http://jeff",
                                                       "ollama_url": "http://ollama", **k})

    def correr(self, aj, jev_ok=True, jeff="ok", ollama="ok"):
        d = self.d

        def nube(req):
            return httpx.Response(200, json={"answers": {"q": {"noul": 0.9}}}) if jev_ok else httpx.Response(401, json={})

        def local(req):
            if req.url.path == "/salud":
                return httpx.Response(200, json={"estado": "ok", "modelo": "qwen3.5:9b"}) if jeff == "ok" else httpx.Response(503, json={"detail": "modelo no descargado"})
            return httpx.Response(200, json={"answers": {"q": {"noul": 0.7}}})

        def caido(req):
            raise httpx.ConnectError("no")
        from cerebro.router_modelos import modelos_necesarios
        t_ollama = ollama_falso({}, etiquetas=tuple(modelos_necesarios()))[0] if ollama == "ok" else httpx.MockTransport(caido)
        with mock.patch.object(d, "ajustes", aj):
            return asyncio.run(d.estado(True, httpx.MockTransport(nube), httpx.MockTransport(caido) if jeff == "ausente" else httpx.MockTransport(local), t_ollama))

    def test_todo_operativo_jev_para_baja_y_media_jeff_para_alta(self):
        r = self.correr(self.ajustes(usar_jev_nube=True, jev_api_key="clave-secreta"))
        self.assertEqual((r["nube"]["estado"], r["jeff"]["estado"], r["local"]["estado"]), ("operativo", "operativo", "operativo"))
        self.assertEqual(r["se_usara"], {"baja": "jev", "media": "jev", "alta": "jeff"})
        self.assertTrue(r["operativo"])
        self.assertNotIn("clave-secreta", json.dumps(r))                      # nunca devuelve la clave

    def test_sin_clave_o_desactivado_decide_jeff(self):
        for aj, estado in [(self.ajustes(), "desactivado"), (self.ajustes(usar_jev_nube=True), "sin_clave")]:
            r = self.correr(aj)
            self.assertEqual(r["nube"]["estado"], estado)
            self.assertEqual(r["se_usara"], {"baja": "jeff", "media": "jeff", "alta": "jeff"})
            self.assertEqual(r["resumen"], "Jev no activo; decide jeff (local)")

    def test_clave_incorrecta_se_explica_y_cae_a_jeff(self):
        r = self.correr(self.ajustes(usar_jev_nube=True, jev_api_key="mala"), jev_ok=False)
        self.assertEqual(r["nube"]["estado"], "caido")
        self.assertIn("clave", r["nube"]["detalle"])
        self.assertEqual(r["se_usara"]["baja"], "jeff")

    def test_sin_jeff_cae_al_modelo_local(self):
        r = self.correr(self.ajustes(), jeff="ausente")
        self.assertEqual(r["jeff"]["estado"], "no_desplegado")
        self.assertEqual(r["se_usara"], {"baja": "local", "media": "local", "alta": "local"})
        self.assertFalse(r["operativo"])

    def test_nada_funciona(self):
        r = self.correr(self.ajustes(), jeff="ausente", ollama="caido")
        self.assertEqual((r["se_usara"]["alta"], r["resumen"]), ("ninguna", "Sin motor de decisiones"))

    def test_el_resultado_se_reutiliza_un_minuto(self):
        d = self.d
        self.correr(self.ajustes())
        with mock.patch.object(d, "_probar", side_effect=AssertionError("no debía volver a probar")):
            self.assertTrue(asyncio.run(d.estado(False))["operativo"])


if __name__ == "__main__":
    unittest.main()
