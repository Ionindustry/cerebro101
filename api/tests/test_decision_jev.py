"""Conector de Jev/jeff: formato de la petición y traducción de la respuesta (API simulada)."""
import asyncio
import json
import unittest

import _sin_servicios  # noqa: F401
import httpx

from cerebro.herramientas import decision as d

HTTPX_REAL = hasattr(httpx, "MockTransport")


def servidor(respuesta: dict, capturar: list):
    def manejar(req):
        capturar.append((req.url.path, req.headers.get("authorization"), json.loads(req.content)))
        return httpx.Response(200, json={"model": "jev-1", "answers": {"q": respuesta}})
    return httpx.MockTransport(manejar)


def llamar(tipo, respuesta, opciones=None, rubrica=None, clave="k"):
    visto: list = []
    r = asyncio.run(d._llamar_api("https://x", clave, "texto", tipo, opciones, rubrica,
                                  transporte=servidor(respuesta, visto)))
    return r, visto[0]


@unittest.skipUnless(HTTPX_REAL, "requiere httpx real (se ejecuta en el contenedor)")
class TestJev(unittest.TestCase):
    def test_eleccion(self):
        r, (ruta, auth, cuerpo) = llamar("eleccion", {"type": "choice", "choice": "a", "confidence": 0.9,
                                                      "probabilities": {"a": 0.9, "b": 0.1}}, ["a", "b"])
        self.assertEqual((r["eleccion"], r["confianza"]), ("a", 0.9))
        self.assertEqual((ruta, auth), ("/v1/systemone", "Bearer k"))
        self.assertEqual(cuerpo["model"], "jev-latest")
        self.assertEqual(cuerpo["questions"]["q"]["criteria"], {"a": None, "b": None})

    def test_puntuacion_usa_diez_niveles_y_reescala_a_diez(self):
        r, (_, _, cuerpo) = llamar("puntuacion", {"type": "score", "score": 4.5, "confidence": 0.8,
                                                  "probabilities": {}}, rubrica="urgencia")
        self.assertEqual(r["puntuacion"], 5.0)               # 4,5 de 9 → 5,0 de 10
        self.assertEqual(len(cuerpo["questions"]["q"]["criteria"]), 10)   # Jev admite como máximo 10

    def test_si_no(self):
        r, _ = llamar("si_no", {"type": "noul", "noul": 0.2}, clave="")
        self.assertFalse(r["si"])
        self.assertEqual(r["confianza"], 0.8)

    def test_jeff_sin_clave_no_envia_cabecera(self):
        _, (_, auth, _) = llamar("si_no", {"type": "noul", "noul": 0.9}, clave="")
        self.assertIsNone(auth)


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(HTTPX_REAL, "requiere httpx real (se ejecuta en el contenedor)")
class TestEstado(unittest.TestCase):
    """El estado del panel no hace preguntas reales a los modelos salvo que se pida (antes tardaba 15 s y repetía el trabajo cada minuto)."""

    def correr(self, probar, nube=False):
        from unittest import mock
        from cerebro.router_modelos import modelos_necesarios
        preguntas = []

        def jeff(req):
            if req.url.path == "/salud":
                return httpx.Response(200, json={"estado": "ok", "modelo": "qwen3.5:9b"})
            preguntas.append("jeff")
            return httpx.Response(200, json={"answers": {"q": {"type": "noul", "noul": 0.9}}})

        def jev(req):
            preguntas.append("nube")
            return httpx.Response(200, json={"answers": {"q": {"type": "noul", "noul": 0.9}}})

        def ollama(req):
            return httpx.Response(200, json={"models": [{"name": m} for m in modelos_necesarios()]})
        d._CACHE.update(cuando=0.0, datos=None)
        ajuste = {"usar_jev_nube": nube, "jev_api_key": "k" if nube else "", "jev_url": "https://jev.test"}
        with mock.patch.object(d, "ajustes", mock.Mock(**{**ajuste, "jeff_url": "http://jeff", "dir_config": d.ajustes.dir_config})):
            e = asyncio.run(d.estado(probar, httpx.MockTransport(jev), httpx.MockTransport(jeff), httpx.MockTransport(ollama)))
        return e, preguntas

    def test_sin_probar_no_se_pregunta_a_ningun_modelo(self):
        e, preguntas = self.correr(probar=False, nube=True)
        self.assertEqual(preguntas, [])
        self.assertEqual((e["jeff"]["estado"], e["nube"]["estado"], e["local"]["estado"]), ("operativo", "configurado", "operativo"))
        self.assertEqual(e["se_usara"], {"baja": "jev", "media": "jev", "alta": "jeff"})
        self.assertTrue(e["operativo"])
        self.assertIn("sin probar", e["resumen"])

    def test_sin_probar_y_sin_jev_decide_jeff(self):
        e, preguntas = self.correr(probar=False)
        self.assertEqual((preguntas, e["nube"]["estado"], e["se_usara"]["baja"]), ([], "desactivado", "jeff"))

    def test_probar_hace_la_pregunta_de_prueba_a_jeff_y_a_jev(self):
        e, preguntas = self.correr(probar=True, nube=True)
        self.assertEqual(sorted(preguntas), ["jeff", "nube"])
        self.assertEqual((e["jeff"]["estado"], e["nube"]["estado"]), ("operativo", "operativo"))
        self.assertIn("segundos", e["jeff"])
