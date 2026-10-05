"""El registro de llamadas a modelos en Langfuse nunca debe romper ni alterar la llamada."""
import os
import unittest
from unittest import mock

from cerebro import observabilidad as o


class Falso:
    def __init__(self):
        self.actualizaciones = []
        self.salida = None

    def update(self, **k):
        self.actualizaciones.append(k)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.salida = a
        return False


class TestGeneracion(unittest.TestCase):
    def test_sin_langfuse_entrega_none_y_no_falla(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with o.generacion("x", "m", "entrada") as obs:
                self.assertIsNone(obs)
            o.anotar(None, output="a")   # no debe fallar

    def test_registra_y_propaga_errores_del_cuerpo(self):
        falso = Falso()
        cliente = mock.Mock()
        cliente.start_as_current_observation.return_value = falso
        env = {"LANGFUSE_HOST": "h", "LANGFUSE_PUBLIC_KEY": "p", "LANGFUSE_SECRET_KEY": "s"}
        with mock.patch.dict(os.environ, env), mock.patch.dict("sys.modules", {"langfuse": mock.Mock(get_client=lambda: cliente)}):
            with self.assertRaises(ValueError):
                with o.generacion("ollama.chat:rapido", "m", "hola", parametros={"temperature": 0}, clase="rapido"):
                    raise ValueError("fallo")
        args = cliente.start_as_current_observation.call_args.kwargs
        self.assertEqual((args["as_type"], args["model"], args["input"]), ("generation", "m", "hola"))
        self.assertEqual(args["model_parameters"], {"temperature": 0})
        self.assertEqual(falso.actualizaciones[0]["level"], "ERROR")
        self.assertIsNotNone(falso.salida[0])      # la observación se cierra con el error

    def test_no_registrar_contenido(self):
        env = {"LANGFUSE_REGISTRAR_CONTENIDO": "false"}
        with mock.patch.dict(os.environ, env):
            self.assertEqual(o._contenido("secreto"), "[contenido no registrado]")
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(o._contenido("visible"), "visible")

    def test_anotar_oculta_la_salida_si_se_pide(self):
        falso = Falso()
        with mock.patch.dict(os.environ, {"LANGFUSE_REGISTRAR_CONTENIDO": "false"}):
            o.anotar(falso, output="secreto", usage_details={"input": 1})
        self.assertEqual(falso.actualizaciones[0]["output"], "[contenido no registrado]")
        self.assertEqual(falso.actualizaciones[0]["usage_details"], {"input": 1})


class TestHerramientas(unittest.TestCase):
    def test_usar_herramienta_sigue_funcionando_con_el_registro(self):
        import asyncio
        import _sin_servicios  # noqa: F401
        from cerebro.herramientas import base
        from cerebro.registro import registro

        async def eco(x):
            return {"eco": x}
        base.registrar(base.Herramienta(nombre="eco_prueba", descripcion="t", operaciones={"decir": eco}))
        ficha = registro().fichas["director-general"]
        with mock.patch.object(base, "herramienta_efectiva", lambda f, n, s: n):
            r = asyncio.run(base.usar(ficha, "eco_prueba", "decir", x=3))
        self.assertEqual(r, {"eco": 3})


if __name__ == "__main__":
    unittest.main()
