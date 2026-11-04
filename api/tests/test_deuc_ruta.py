"""El DEUC que se sube al chat va siempre al Administrativo de Licitaciones (el único con la herramienta «plantillas»), decida lo que decida el modelo que enruta."""
import unittest

import _sin_servicios  # noqa: F401

from cerebro.grafo.nodos import corregir_por_deuc
from cerebro.registro import registro


class TestRutaDeuc(unittest.TestCase):
    def test_el_deuc_va_al_administrativo_de_licitaciones_con_la_herramienta_de_plantillas(self):
        self.assertEqual(corregir_por_deuc("Guarda este documento como DEUC base de 101.cat", "legal", "contratos"), ("licitaciones", "administrativo-licitaciones"))
        self.assertEqual(corregir_por_deuc("sube el documento europeo único de contratación", "conocimiento"), ("licitaciones", "administrativo-licitaciones"))
        self.assertEqual(corregir_por_deuc("Tengo este fichero\n\n[Documentos: - id x · «DEUC.docx» · docx · 3 páginas]", "conocimiento", "bibliotecario"), ("licitaciones", "administrativo-licitaciones"))
        self.assertIn("plantillas", registro().fichas["administrativo-licitaciones"].herramientas)

    def test_lo_que_no_es_del_deuc_no_se_toca(self):
        self.assertEqual(corregir_por_deuc("Resume el contrato con el proveedor", "legal", "contratos"), ("legal", "contratos"))
        self.assertEqual(corregir_por_deuc("el deucalión es un mito", "direccion"), ("direccion", None))


if __name__ == "__main__":
    unittest.main()
