"""Documentos subidos al chat: cualquier agente puede leerlos en esa petición, se tratan siempre en local y los largos se leen buscando primero."""
import asyncio
import unittest
from unittest import mock

import _sin_servicios  # noqa: F401

try:
    from cerebro import herramientas as H
    from cerebro import subidas as S
    from cerebro.grafo import nodos
    from cerebro.registro import Ficha
except ImportError as e:      # pragma: no cover
    raise unittest.SkipTest(str(e))

NOTA = "\n\n" + S.MARCA_ADJUNTOS + " y puedes leer con la herramienta «documentos_subidos»: ...]"


def ficha(herramientas=("conocimiento",)):
    return Ficha(id="agente-x", nombre="X", departamento="comercial", subarea="s", tareas="t", modelo="principal", herramientas=tuple(herramientas), aprobacion="simple",
                 horario=None, sensibilidad="media", director=False)


class TestFicha(unittest.TestCase):
    def test_sin_adjuntos_la_ficha_no_cambia(self):
        f = ficha()
        self.assertIs(nodos.con_adjuntos(f, "Hola"), f)
        self.assertFalse(S.hay_adjuntos("Hola"))
        self.assertFalse(S.hay_adjuntos(None))

    def test_con_adjuntos_el_agente_recibe_la_herramienta_solo_para_esa_peticion(self):
        f = ficha()
        g = nodos.con_adjuntos(f, "Resume esto" + NOTA)
        self.assertIn("documentos_subidos", g.herramientas)
        self.assertNotIn("documentos_subidos", f.herramientas)                    # la ficha original (la del registro) no se toca
        self.assertIn("documentos_subidos", H.disponibles_para(g))
        self.assertIs(nodos.con_adjuntos(g, "x" + NOTA), g)                       # no se duplica

    def test_si_ya_la_tiene_no_se_cambia(self):
        f = ficha(("documentos_subidos",))
        self.assertIs(nodos.con_adjuntos(f, "x" + NOTA), f)

    def test_la_herramienta_esta_permitida_a_ese_agente_por_la_politica(self):
        from cerebro.politicas import herramienta_efectiva
        g = nodos.con_adjuntos(ficha(), "x" + NOTA)
        self.assertEqual(herramienta_efectiva(g, "documentos_subidos", "alta"), "documentos_subidos")       # local y sin tope de sensibilidad


class TestLocal(unittest.TestCase):
    def correr(self, peticion):
        ext = mock.AsyncMock(return_value={"tipo": "respuesta", "respuesta": "desde la nube"})
        local = mock.AsyncMock(return_value={"tipo": "respuesta", "respuesta": "desde local"})
        with mock.patch.object(nodos.modelos_externos, "es_compleja", return_value=True), mock.patch.object(nodos.modelos_externos, "consultar", ext), \
                mock.patch.object(nodos, "chat", local), mock.patch.object(nodos, "asignar", lambda *a, **k: "m"):
            d = asyncio.run(nodos._paso_del_agente(ficha(), {"peticion": peticion, "sensibilidad": "baja"}, [{"role": "system", "content": "s"}, {"role": "user", "content": peticion}]))
        return d, ext

    def test_una_consulta_compleja_sin_adjuntos_puede_ir_al_modelo_externo(self):
        d, ext = self.correr("Analiza esto")
        self.assertEqual(d["respuesta"], "desde la nube")
        ext.assert_awaited()

    def test_con_documentos_subidos_nunca_va_al_modelo_externo(self):
        d, ext = self.correr("Analiza esto" + NOTA)
        self.assertEqual(d["respuesta"], "desde local")
        ext.assert_not_awaited()

    def test_ni_siquiera_como_ultimo_recurso(self):
        from cerebro.llm import RespuestaInvalida
        ext = mock.AsyncMock(return_value={"tipo": "respuesta", "respuesta": "desde la nube"})
        local = mock.AsyncMock(side_effect=RespuestaInvalida("mal"))
        with mock.patch.object(nodos.modelos_externos, "es_compleja", return_value=False), mock.patch.object(nodos.modelos_externos, "consultar", ext), \
                mock.patch.object(nodos, "chat", local), mock.patch.object(nodos, "asignar", lambda *a, **k: "m"):
            with self.assertRaises(RespuestaInvalida):
                asyncio.run(nodos._paso_del_agente(ficha(), {"peticion": "x" + NOTA, "sensibilidad": "baja"}, [{"role": "system", "content": "s"}, {"role": "user", "content": "x"}]))
        ext.assert_not_awaited()


class TestNota(unittest.TestCase):
    """La nota que añade `para_chat`: con la marca, y los documentos largos se leen buscando primero."""
    def nota(self, paginas):
        async def conectar():
            class C:
                async def __aenter__(s): return s
                async def __aexit__(s, *a): return False
                async def execute(s, *a, **k):
                    class Cur:
                        async def fetchone(s2):
                            return {"id": "0b1f7a3e-1111-4222-8333-444444444444", "usuario": "marta", "nombre": "anexo.pdf", "formato": "pdf", "bytes": 1, "estado": "limpio", "motivo": "",
                                    "unidad": "página", "paginas": paginas, "aviso": "", "creado": None}
                    return Cur()
            return C()
        with mock.patch.object(S, "_conectar", conectar):
            return asyncio.run(S.para_chat("marta", ["0b1f7a3e-1111-4222-8333-444444444444"]))

    def test_la_nota_lleva_la_marca_y_dice_que_se_trata_en_local(self):
        n = self.nota(2)
        self.assertTrue(S.hay_adjuntos(n))
        self.assertIn("en local", n)
        self.assertNotIn("usa primero «buscar»", n)

    def test_un_documento_largo_se_busca_antes_de_leer(self):
        n = self.nota(80)
        self.assertIn("usa primero «buscar»", n)
        self.assertIn("80 páginas", n)


if __name__ == "__main__":
    unittest.main()
