"""Tope de pasos del agente: 5 para todos y más para el Analista de Pliegos, que lee un documento largo y anota requisitos de uno en uno."""
import asyncio
import unittest
from unittest import mock

import _sin_servicios  # noqa: F401

try:
    from cerebro.grafo import nodos
except ImportError as e:      # pragma: no cover
    raise unittest.SkipTest(str(e))


class Ficha:
    def __init__(self, id):
        self.id, self.sensibilidad, self.modelo = id, "baja", "rapido"


def correr(ficha_id):
    llamadas = []

    async def paso(ficha, estado, mensajes):
        llamadas.append(1)
        return {"tipo": "herramienta", "herramienta": "pliegos", "operacion": "documentos", "argumentos": {}}

    async def usar(ficha, herramienta, operacion, **kw):
        return {"ok": True}

    async def nada(*a, **k):
        return None

    with mock.patch.object(nodos, "_paso_del_agente", paso), mock.patch.object(nodos.H, "usar", usar), mock.patch.object(nodos.H, "disponibles_para", lambda f: []), \
            mock.patch.object(nodos, "sistema_agente", lambda f, d: "sistema"), mock.patch.object(nodos.actividad, "marcar", nada), \
            mock.patch.object(nodos.actividad, "contar", nada), mock.patch.object(nodos, "inyectar", lambda f, e, h, a: a):
        r = asyncio.run(nodos._ejecutar_agente({"peticion": "lee el pliego"}, Ficha(ficha_id)))
    return r, len(llamadas)


class TestPasos(unittest.TestCase):
    def test_un_agente_normal_tiene_cinco_pasos(self):
        r, n = correr("rastreador")
        self.assertEqual(n, 5)
        self.assertIn("número máximo de pasos", r["respuesta"])

    def test_los_agentes_de_la_cadena_de_la_oferta_tienen_margen_para_guardar_sus_secciones(self):
        """Con 5 pasos (uno por llamada a herramienta) se quedaban sin guardar nada: plan, ficha, requisitos y cada sección son 10-15."""
        for a in ("arquitecto-solucion", "redactor-memoria", "administrativo-licitaciones", "costes-licitacion", "precio-licitacion", "evaluador-ofertas"):
            self.assertGreaterEqual(nodos.MAX_PASOS_AGENTE[a], 20, a)

    def test_el_analista_de_pliegos_tiene_mas(self):
        r, n = correr("analista-pliegos")
        self.assertEqual(n, nodos.MAX_PASOS_AGENTE["analista-pliegos"])
        self.assertGreater(n, 15)
        self.assertEqual(len(r["pasos"]), n)


if __name__ == "__main__":
    unittest.main()
