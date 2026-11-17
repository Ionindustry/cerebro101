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

    def test_cada_paso_y_la_tarea_dejan_constancia_del_tiempo(self):
        """Para saber dónde se va el tiempo de un agente lento: una línea por paso y un resumen con modelo y herramientas por separado."""
        with self.assertLogs("cerebro.grafo", level="INFO") as g:
            correr("rastreador")
        texto = "\n".join(g.output)
        self.assertEqual(texto.count("paso "), 5)
        self.assertIn("paso 1/5 · modelo", texto)
        self.assertIn("pliegos.documentos", texto)
        self.assertRegex(texto, r"sin terminar en 5 pasos · \d+ s en total \(modelo \d+ s, herramientas \d+ s\)")

    def test_el_resumen_de_una_tarea_terminada_cuenta_el_paso_de_la_respuesta(self):
        async def paso(ficha, estado, mensajes):
            return {"tipo": "respuesta", "respuesta": "listo"}

        async def nada(*a, **k):
            return None

        with mock.patch.object(nodos, "_paso_del_agente", paso), mock.patch.object(nodos.H, "disponibles_para", lambda f: []), mock.patch.object(nodos, "sistema_agente", lambda f, d: "s"), \
                mock.patch.object(nodos.actividad, "marcar", nada), self.assertLogs("cerebro.grafo", level="INFO") as g:
            r = asyncio.run(nodos._ejecutar_agente({"peticion": "hola"}, Ficha("rastreador")))
        self.assertEqual(r["respuesta"], "listo")
        self.assertIn("respuesta en 1 pasos", "\n".join(g.output))


def correr_con(decisiones, ficha_id="rastreador"):
    """Ejecuta el agente con una lista de decisiones del modelo; devuelve (resultado, mensajes que vio el modelo en cada vuelta, llamadas reales a herramientas)."""
    vistos, reales, it = [], [], iter(decisiones)

    async def paso(ficha, estado, mensajes):
        vistos.append([dict(m) for m in mensajes])
        return next(it)

    async def usar(ficha, herramienta, operacion, **kw):
        reales.append((herramienta, operacion, kw))
        return {"ok": True, "texto": "x" * 3000}

    async def nada(*a, **k):
        return None

    with mock.patch.object(nodos, "_paso_del_agente", paso), mock.patch.object(nodos.H, "usar", usar), mock.patch.object(nodos.H, "disponibles_para", lambda f: []), \
            mock.patch.object(nodos, "sistema_agente", lambda f, d: "sistema"), mock.patch.object(nodos.actividad, "marcar", nada), \
            mock.patch.object(nodos.actividad, "contar", nada), mock.patch.object(nodos, "inyectar", lambda f, e, h, a: a):
        r = asyncio.run(nodos._ejecutar_agente({"peticion": "lee el pliego"}, Ficha(ficha_id)))
    return r, vistos, reales


def llamada(op, **args):
    return {"tipo": "herramienta", "herramienta": "pliegos", "operacion": op, "argumentos": args}


class TestAtascos(unittest.TestCase):
    def test_la_misma_llamada_con_los_mismos_argumentos_no_se_vuelve_a_ejecutar_y_se_le_dice_que_avance(self):
        r, vistos, reales = correr_con([llamada("texto", n=1), llamada("texto", n=1), {"tipo": "respuesta", "respuesta": "listo"}])
        self.assertEqual(len(reales), 1)                                  # la repetida no llegó a la herramienta
        self.assertIn("NO la repitas", vistos[2][-1]["content"])
        self.assertEqual(r["respuesta"], "listo")

    def test_con_otros_argumentos_si_se_ejecuta(self):
        _r, _v, reales = correr_con([llamada("texto", n=1), llamada("texto", n=2), {"tipo": "respuesta", "respuesta": "listo"}])
        self.assertEqual(len(reales), 2)

    def test_los_resultados_viejos_se_recortan_y_los_ultimos_no(self):
        _r, vistos, _reales = correr_con([llamada("texto", n=i) for i in range(1, 7)] + [{"tipo": "respuesta", "respuesta": "listo"}])
        resultados = [m["content"] for m in vistos[-1] if m["content"].startswith("Resultado: ")]
        self.assertIn("recortado", resultados[0])
        self.assertNotIn("recortado", resultados[-1])
        self.assertEqual(vistos[-1][0]["content"], "sistema")             # lo del principio (reglas) nunca se toca

    def test_en_los_ultimos_pasos_se_le_avisa_de_que_guarde(self):
        m = nodos.MAX_PASOS                                              # 5 para un agente normal
        _r, vistos, _reales = correr_con([llamada("texto", n=i) for i in range(1, m)] + [{"tipo": "respuesta", "respuesta": "listo"}])
        ultimos = [v[-1]["content"] for v in vistos[1:]]
        self.assertTrue(all("AVISO DEL SISTEMA" in c for c in ultimos[-nodos.AVISO_ULTIMOS_PASOS + 1:]))
        self.assertNotIn("AVISO DEL SISTEMA", vistos[1][-1]["content"].split("x" * 10)[0])


if __name__ == "__main__":
    unittest.main()
