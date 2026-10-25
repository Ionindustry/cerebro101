"""config/modelos.yaml: cada perfil está completo, usa modelos que existen y sus modelos siempre cargados caben en la tarjeta."""
import unittest
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parents[2]
CFG = yaml.safe_load((RAIZ / "config" / "modelos.yaml").read_text(encoding="utf-8"))
CLASES = {"rapido", "principal", "vision", "juez"}
# Tamaño en GB (Q4) según registry.ollama.ai; hay que ampliarlo al usar un modelo nuevo
TAMANO_GB = {"qwen3.5:4b": 3.3, "qwen3.5:9b": 6.6, "ministral-3:3b": 3.0, "qwen3.8:27b": 17.7, "bge-m3": 1.2}
# Memoria de la tarjeta más pequeña a la que va destinado cada perfil
TARJETA_GB = {"minima": 6, "mediana": 12, "pequena": 16, "grande": 24}
MARGEN_GB = 1.5       # contexto (KV), CUDA y la voz


class TestPerfiles(unittest.TestCase):
    def test_hay_los_perfiles_esperados(self):
        self.assertEqual(set(CFG["perfiles"]), set(TARJETA_GB))
        self.assertIn(CFG["perfil_por_defecto"], CFG["perfiles"])

    def test_cada_perfil_define_las_cuatro_clases(self):
        for nombre, perfil in CFG["perfiles"].items():
            self.assertEqual(set(perfil), CLASES, nombre)

    def test_todos_los_modelos_estan_en_la_tabla_de_tamanos_y_ninguno_es_el_inexistente(self):
        for nombre, perfil in CFG["perfiles"].items():
            for clase, d in perfil.items():
                self.assertIn(d["modelo"], TAMANO_GB, f"{nombre}.{clase}: {d['modelo']} sin tamaño conocido (¿existe en Ollama?)")
        self.assertNotIn("prometheus2:7b", {d["modelo"] for p in CFG["perfiles"].values() for d in p.values()})

    def test_lo_que_se_mantiene_cargado_cabe_en_la_tarjeta(self):
        for nombre, perfil in CFG["perfiles"].items():
            residentes = {d["modelo"] for d in perfil.values() if d.get("siempre_cargado")} | {CFG["embeddings"]["modelo"]}
            peso = sum(TAMANO_GB[m] for m in residentes)
            self.assertLessEqual(peso + MARGEN_GB, TARJETA_GB[nombre],
                                 f"{nombre}: {sorted(residentes)} ocupan {peso:.1f} GB y la tarjeta es de {TARJETA_GB[nombre]} GB")

    def test_cada_agente_tiene_modelo_en_todos_los_perfiles(self):
        from cerebro.registro import registro
        from cerebro.router_modelos import asignar
        for nombre in CFG["perfiles"]:
            for ficha in registro().fichas.values():
                self.assertTrue(asignar(ficha, perfil=nombre).modelo, f"{nombre}/{ficha.id}")


if __name__ == "__main__":
    unittest.main()
