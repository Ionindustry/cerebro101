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

    def test_puntuacion_usa_once_niveles(self):
        r, (_, _, cuerpo) = llamar("puntuacion", {"type": "score", "score": 7.456, "confidence": 0.8,
                                                  "probabilities": {}}, rubrica="urgencia")
        self.assertEqual(r["puntuacion"], 7.46)
        self.assertEqual(len(cuerpo["questions"]["q"]["criteria"]), 11)

    def test_si_no(self):
        r, _ = llamar("si_no", {"type": "noul", "noul": 0.2}, clave="")
        self.assertFalse(r["si"])
        self.assertEqual(r["confianza"], 0.8)

    def test_jeff_sin_clave_no_envia_cabecera(self):
        _, (_, auth, _) = llamar("si_no", {"type": "noul", "noul": 0.9}, clave="")
        self.assertIsNone(auth)


if __name__ == "__main__":
    unittest.main()
