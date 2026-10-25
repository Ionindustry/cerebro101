"""El contexto que se manda al modelo cabe en su ventana y nunca pierde el sistema ni la petición."""
import unittest
from unittest import mock

import _sin_servicios  # noqa: F401

try:
    from cerebro.grafo import contexto as c
except ImportError:        # sin langgraph en este equipo: se ejecuta en el contenedor
    c = None


def conversacion(*tamanos):
    m = [{"role": "system", "content": "S" * 6000}, {"role": "user", "content": "petición original"}]
    for i, t in enumerate(tamanos):
        m += [{"role": "assistant", "content": f"paso {i}"}, {"role": "user", "content": f"Resultado {i}: " + "x" * t}]
    return m


@unittest.skipIf(c is None, "requiere las dependencias del contenedor")
class TestContexto(unittest.TestCase):
    def test_lo_que_cabe_no_se_toca(self):
        m = conversacion(500)
        self.assertEqual(c.recortar(m, 10_000), m)

    def test_recorta_primero_el_resultado_mas_grande_y_deja_marca(self):
        m = conversacion(300, 9000, 800)
        r = c.recortar(m, 3000)
        self.assertLessEqual(c.estimar_tokens(r), 3000)
        self.assertEqual(r[0], m[0])                               # el sistema intacto
        self.assertEqual(r[1], m[1])                               # la petición intacta
        self.assertIn("recortado", r[5]["content"])               # el resultado de 9000 es el que se acorta
        self.assertEqual(r[3]["content"], m[3]["content"])        # el pequeño no
        self.assertEqual(len(m[5]["content"]), 9000 + len("Resultado 1: "))      # no se modifica la lista original

    def test_si_nada_se_puede_acortar_se_descartan_los_pasos_mas_antiguos(self):
        m = conversacion(*[1000] * 6)
        r = c.recortar(m, 2500, minimo=1000)
        self.assertEqual(r[0], m[0])
        self.assertEqual(r[1], m[1])
        self.assertEqual(r[-1], m[-1])
        self.assertLess(len(r), len(m))

    def test_nunca_se_queda_sin_sistema_ni_peticion_aunque_no_quepa(self):
        r = c.recortar(conversacion(20000, 20000), 100)
        self.assertEqual([m["role"] for m in r[:2]], ["system", "user"])

    def test_limite_de_resultado(self):
        self.assertEqual(c.limite_resultado(), 6000)
        with mock.patch.dict("os.environ", {"OLLAMA_RESULTADO_MAX": "1000"}):
            self.assertEqual(c.limite_resultado(), 1000)
        with mock.patch.dict("os.environ", {"OLLAMA_RESULTADO_MAX": "mucho"}):
            self.assertEqual(c.limite_resultado(), 6000)


if __name__ == "__main__":
    unittest.main()
