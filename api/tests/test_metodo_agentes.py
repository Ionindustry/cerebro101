"""Método de trabajo por agente (config/prompts/metodo_agentes.yaml): entra en el prompt solo de los agentes que lo tienen y no rompe a los demás."""
import unittest
from unittest import mock

try:
    from cerebro import herramientas as base
    from cerebro.grafo import prompts as P
    from cerebro.registro import registro
    HAY = True
except Exception:       # noqa: BLE001 - sin las dependencias del contenedor
    HAY = False

SEIS = ("arquitecto-solucion", "redactor-memoria", "administrativo-licitaciones", "costes-licitacion", "precio-licitacion", "evaluador-ofertas")


@unittest.skipUnless(HAY, "requiere las dependencias del contenedor")
class TestMetodoAgentes(unittest.TestCase):
    def setUp(self):
        P._metodos.cache_clear()
        self.addCleanup(P._metodos.cache_clear)

    def prompt(self, id_):
        f = registro().fichas[id_]
        return P.sistema_agente(f, base.disponibles_para(f))

    def test_los_seis_agentes_de_la_oferta_llevan_su_metodo(self):
        for i in SEIS:
            p = self.prompt(i)
            self.assertIn("Método de trabajo:", p, i)
            self.assertIn(P._metodos()[i][:60], p, i)
            self.assertLess(p.index("Método de trabajo:"), p.index("Normas:"), i)      # después de las tareas y antes de las normas

    def test_un_agente_sin_metodo_queda_como_antes(self):
        self.assertNotIn("Método de trabajo:", self.prompt("viabilidad"))

    def test_todos_los_ids_del_fichero_son_agentes_reales(self):
        self.assertEqual(set(P._metodos()), set(SEIS))
        self.assertTrue(set(P._metodos()) <= set(registro().fichas))

    def test_sin_fichero_o_con_fichero_roto_los_agentes_siguen(self):
        with mock.patch("builtins.open", side_effect=FileNotFoundError):
            P._metodos.cache_clear()
            self.assertEqual(P._metodos(), {})
            self.assertNotIn("Método de trabajo:", self.prompt("arquitecto-solucion"))
        P._metodos.cache_clear()
        with mock.patch("builtins.open", mock.mock_open(read_data="agentes: [esto, no, es, un, mapa")):
            self.assertEqual(P._metodos(), {})

    def test_con_el_metodo_cada_prompt_cabe_con_margen(self):
        for i in SEIS:
            self.assertLess(len(self.prompt(i)), 13500, i)       # margen para catálogo y encargos más largos

    def test_el_metodo_no_contiene_reglas_de_seguridad_que_contradigan_las_fijas(self):
        for i, texto in P._metodos().items():
            self.assertNotIn("fija el precio definitivo", texto.lower(), i)


if __name__ == "__main__":
    unittest.main()
