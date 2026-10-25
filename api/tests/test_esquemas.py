"""Esquema exacto de las herramientas: prompt, validación previa y límites que fija el sistema (no el modelo)."""
import asyncio
import dataclasses
import unittest
from unittest import mock

import _sin_servicios  # noqa: F401

try:
    import cerebro.herramientas  # noqa: F401 - registra todas
    from cerebro.herramientas import base, esquemas
    from cerebro.registro import registro
    from cerebro.grafo.prompts import sistema_agente
    HAY_DEPENDENCIAS = True
except ImportError:      # portátil sin las dependencias del contenedor
    HAY_DEPENDENCIAS = False


@unittest.skipUnless(HAY_DEPENDENCIAS, "requiere las dependencias del contenedor")
class TestEsquemas(unittest.TestCase):
    def tool(self, nombre):
        return base._REGISTRO[nombre]

    def test_nombres_de_tipo(self):
        n = esquemas.nombre_tipo
        self.assertEqual((n("str"), n("int"), n("float"), n("bool")), ("texto", "entero", "número", "sí/no"))
        self.assertEqual(n("list[str] | None"), "lista de textos")
        self.assertEqual(n("dict[str, Any]"), "objeto")
        self.assertEqual(n("list[str] | str"), "lista de textos o texto")

    def test_firma_oculta_lo_que_pone_el_sistema(self):
        f = esquemas.firma("listar", self.tool("erpnext").operaciones["listar"])
        self.assertEqual(f, 'listar(doctype: texto, filtros?: lista, campos?: lista de textos, limite?: entero = 50)')
        self.assertNotIn("departamento", f)
        self.assertNotIn("sensibilidad", esquemas.firma("buscar", self.tool("conocimiento").operaciones["buscar"]))

    def test_todas_las_herramientas_se_pueden_describir_y_sus_metadatos_son_coherentes(self):
        for nombre, h in base._REGISTRO.items():
            self.assertIn(nombre, esquemas.describir(h))
            for campo in (h.ayuda, h.ejemplos, h.campos):
                self.assertLessEqual(set(campo), set(h.operaciones), f"{nombre}: operación inexistente en {campo}")

    def test_cada_ejemplo_del_prompt_es_valido_segun_su_propio_esquema(self):
        for nombre, h in base._REGISTRO.items():
            for op, args in h.ejemplos.items():
                esquemas.validar(h, op, args)       # no debe lanzar

    def test_operacion_inventada_dice_cuales_existen(self):
        with self.assertRaises(LookupError) as e:
            esquemas.validar(self.tool("erpnext"), "buscar_articulos", {})
        self.assertIn("listar, leer, crear_borrador", str(e.exception))

    def test_argumento_inventado_dice_cuales_estan_permitidos(self):
        with self.assertRaises(esquemas.ArgumentosNoValidos) as e:
            esquemas.validar(self.tool("erpnext"), "listar", {"doctype": "Customer", "entidad": "x", "tabla": "y"})
        m = str(e.exception)
        self.assertIn("«entidad», «tabla»", m)
        self.assertIn("doctype, filtros, campos, limite", m)
        self.assertNotIn("departamento", m)

    def test_faltan_obligatorios_y_tipos(self):
        with self.assertRaises(esquemas.ArgumentosNoValidos) as e:
            esquemas.validar(self.tool("erpnext"), "leer", {"doctype": "Customer"})
        self.assertIn("nombre", str(e.exception))
        with self.assertRaises(esquemas.ArgumentosNoValidos) as e:
            esquemas.validar(self.tool("plataformas_contratacion"), "novedades", {"cpv": "35125000"})
        self.assertIn("lista de textos", str(e.exception))
        with self.assertRaises(esquemas.ArgumentosNoValidos):
            esquemas.validar(self.tool("calendario"), "huecos", {"desde": "a", "hasta": "b", "duracion_min": "sesenta"})
        esquemas.validar(self.tool("correo"), "preparar_borrador", {"para": "a@b.c", "asunto": "x", "cuerpo": "y"})   # unión: texto o lista
        esquemas.validar(self.tool("correo"), "preparar_borrador", {"para": ["a@b.c"], "asunto": "x", "cuerpo": "y"})

    def test_cotizador_con_campos_libres_documentados(self):
        h = self.tool("cotizador")
        esquemas.validar(h, "cotizar", {"partidas": {"camara_exterior": 2}})
        with self.assertRaises(esquemas.ArgumentosNoValidos) as e:
            esquemas.validar(h, "cotizar", {"camaras": 2})
        self.assertIn("partidas", str(e.exception))
        self.assertIn("camara_exterior", esquemas.describir(h))        # ids del catálogo real, no escritos a mano

    def test_el_modelo_no_puede_decidir_departamento_ni_sensibilidad(self):
        h = self.tool("erpnext")
        esquemas.validar(h, "listar", {"doctype": "Customer", "departamento": "finanzas"})     # se ignora en la validación
        from cerebro.grafo import nodos
        ficha = registro().fichas["inventario"]
        args = nodos.inyectar(ficha, {"sensibilidad": "baja"}, "erpnext", {"doctype": "Customer", "departamento": "finanzas", "sensibilidad": "baja"})
        self.assertEqual(args, {"doctype": "Customer", "departamento": ficha.departamento})
        self.assertEqual(nodos.inyectar(ficha, {}, "calculo", {"x": 1}), {"x": 1})

    def test_usar_fuerza_la_sensibilidad_en_el_conocimiento(self):
        recibido = {}

        async def falsa(consulta, departamento, sensibilidad="media", k=6):
            recibido.update(sensibilidad=sensibilidad)
            return []
        ficha = next(f for f in registro().fichas.values() if "conocimiento" in f.herramientas)
        with mock.patch.dict(self.tool("conocimiento").operaciones, {"buscar": falsa}):
            asyncio.run(base.usar(ficha, "conocimiento", "buscar", sensibilidad="baja", consulta="x", departamento=ficha.departamento))
        self.assertEqual(recibido["sensibilidad"], "baja")
        with mock.patch.dict(self.tool("conocimiento").operaciones, {"buscar": falsa}):
            asyncio.run(base.usar(ficha, "conocimiento", "buscar", consulta="x", departamento=ficha.departamento))
        self.assertEqual(recibido["sensibilidad"], ficha.sensibilidad)         # sin dato de la petición: la de la ficha

    def test_validar_llamada_sin_ejecutar(self):
        ficha = registro().fichas["inventario"]
        self.assertIsNone(base.validar_llamada(ficha, "erpnext", "listar", {"doctype": "Item"}))
        self.assertIn("campo", base.validar_llamada(ficha, "erpnext", "listar", {"doctype": "Item", "campo": "x"}))
        self.assertIn("no tiene la herramienta", base.validar_llamada(ficha, "correo", "enviar", {}))

    def test_llamada_directa_a_operacion_externa_explica_como_proceder(self):
        ficha = next(f for f in registro().fichas.values() if "correo" in f.herramientas)
        with self.assertRaises(base.OperacionRequiereAprobacion) as e:
            asyncio.run(base.usar(ficha, "correo", "enviar", departamento=ficha.departamento, para="a@b.c", asunto="x", cuerpo="y"))
        self.assertIn("propónla en «acciones»", str(e.exception))


@unittest.skipUnless(HAY_DEPENDENCIAS, "requiere las dependencias del contenedor")
class TestPrompt(unittest.TestCase):
    def test_el_prompt_lleva_operaciones_y_argumentos_exactos(self):
        ficha = registro().fichas["inventario"]
        p = sistema_agente(ficha, base.disponibles_para(ficha))
        self.assertIn("listar(doctype: texto", p)
        self.assertIn("EXACTAMENTE", p)
        self.assertNotIn("departamento: texto", p)
        self.assertIn("ejemplo:", p)

    def test_modo_antiguo_sigue_disponible_para_comparar(self):
        ficha = registro().fichas["inventario"]
        p = sistema_agente(ficha, base.disponibles_para(ficha), con_esquema=False)
        self.assertNotIn("EXACTAMENTE", p)
        self.assertNotIn("listar(doctype: texto", p)

    def test_el_prompt_cabe_en_el_contexto_de_un_modelo_pequeno(self):
        mayor = max(len(sistema_agente(f, base.disponibles_para(f))) for f in registro().fichas.values())
        self.assertLess(mayor, 14000, f"prompt de {mayor} caracteres")


@unittest.skipUnless(HAY_DEPENDENCIAS, "requiere las dependencias del contenedor")
class TestAccionesPropuestas(unittest.TestCase):
    def test_una_accion_mal_formada_no_llega_a_la_bandeja(self):
        from cerebro.grafo import nodos
        ficha = next(f for f in registro().fichas.values() if "correo" in f.herramientas)

        async def crear(*a, **k):
            raise AssertionError("no debía pedir aprobación")
        estado = {"agente": ficha.id, "acciones": [
            {"accion": "enviar_correo", "herramienta": "correo", "operacion": "enviar", "resumen": "r", "argumentos": {"destinatario": "a@b.c"}}]}
        with mock.patch.object(nodos.bandeja, "crear", crear):
            r = asyncio.run(nodos.registrar_aprobaciones(estado, {"configurable": {"thread_id": "h"}}))
        a = r["acciones"][0]
        self.assertEqual(a["estado"], "error")
        self.assertIn("no válida", a["resultado"])
        self.assertIn("destinatario", a["resultado"])


@unittest.skipUnless(HAY_DEPENDENCIAS, "requiere las dependencias del contenedor")
class TestCasosDeHerramientas(unittest.TestCase):
    def test_cada_agente_del_banco_de_pruebas_tiene_la_herramienta_que_se_espera(self):
        from pathlib import Path
        import yaml
        ruta = Path(__file__).resolve().parents[2] / "evaluacion" / "herramientas_casos.yaml"
        casos = yaml.safe_load(ruta.read_text(encoding="utf-8"))["casos"]
        self.assertGreaterEqual(len(casos), 16)
        for c in casos:
            ficha = registro().fichas[c["agente"]]
            for correcta in c["aceptar"]:
                herramienta, operacion = correcta.split(".")
                self.assertIn(herramienta, ficha.herramientas, c["id"])
                self.assertIn(operacion, base._REGISTRO[herramienta].operaciones, c["id"])


if __name__ == "__main__":
    unittest.main()
