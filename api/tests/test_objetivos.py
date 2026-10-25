"""Objetivos permanentes: validación y cómo evitan pedir la firma de cada acción (sin base de datos)."""
import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import _sin_servicios  # noqa: F401

try:
    from cerebro import herramientas  # noqa: F401  (registra las herramientas)
    from cerebro.aprobaciones import objetivos
    from cerebro.grafo import nodos
    from cerebro.registro import registro
    HAY = True
except ImportError:
    HAY = False


def ejecutar(c):
    return asyncio.run(c)


@unittest.skipUnless(HAY, "requiere las dependencias del contenedor")
class TestObjetivos(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reg = registro()
        cls.dep = "finanzas"

    def nuevo(self, **kw):
        base = dict(titulo="Reclamar facturas vencidas", departamentos=[self.dep], agentes=[], operaciones=["correo.enviar"],
                    max_acciones=10, dias=7, reg=self.reg, ahora=datetime(2026, 1, 1, tzinfo=timezone.utc))
        return objetivos.validar_nuevo(**{**base, **kw})

    def test_objetivo_valido_caduca_y_tiene_tope(self):
        o = self.nuevo()
        self.assertEqual(o["caduca"], datetime(2026, 1, 8, tzinfo=timezone.utc))
        self.assertEqual((o["operaciones"], o["max_acciones"]), (["correo.enviar"], 10))

    def test_lo_reservado_no_se_cubre(self):
        with self.assertRaisesRegex(objetivos.ObjetivoNoValido, "reservada"):
            self.nuevo(operaciones=["mayorista.alta"])

    def test_lo_estandar_no_necesita_objetivo(self):
        with self.assertRaisesRegex(objetivos.ObjetivoNoValido, "estándar"):
            self.nuevo(operaciones=["web.buscar"])

    def test_limites_y_datos_obligatorios(self):
        for kw in ({"dias": 0}, {"dias": objetivos.MAX_DIAS + 1}, {"max_acciones": 0}, {"max_acciones": objetivos.MAX_ACCIONES + 1},
                   {"titulo": "ya"}, {"departamentos": []}, {"departamentos": ["inventado"]}, {"operaciones": []},
                   {"operaciones": ["correo.inventada"]}, {"agentes": ["no-existe"]}):
            with self.assertRaises(objetivos.ObjetivoNoValido, msg=str(kw)):
                self.nuevo(**kw)

    def preparar(self, oid):
        import dataclasses
        ficha = next(f for f in self.reg.fichas.values() if f.departamento == self.dep and "correo" in f.herramientas)
        creadas = []

        async def crear(hilo, agente, departamento, accion, nivel, aprobadores, voz, datos):
            creadas.append(accion)
            return "sid-1"

        async def consumir(departamento, agente, herramienta, operacion):
            return oid
        estado = {"agente": ficha.id, "acciones": [{"accion": "x", "herramienta": "correo", "operacion": "enviar", "resumen": "r",
                                                    "argumentos": {"para": "c@ejemplo.es", "asunto": "a", "cuerpo": "b"}}]}
        with mock.patch.object(nodos.bandeja, "crear", crear), mock.patch.object(nodos.objetivos, "consumir", consumir):
            r = ejecutar(nodos.registrar_aprobaciones(estado, {"configurable": {"thread_id": "h"}}))
        return r["acciones"][0], creadas

    def test_con_objetivo_vigente_no_se_pide_firma(self):
        a, creadas = self.preparar("obj-1")
        self.assertEqual((a["estado"], a["objetivo_id"]), ("aprobada", "obj-1"))
        self.assertEqual(creadas, [])

    def test_sin_objetivo_se_pide_firma(self):
        a, creadas = self.preparar(None)
        self.assertEqual(a["estado"], "pendiente")
        self.assertEqual(len(creadas), 1)

    def test_lo_reservado_nunca_consulta_objetivos(self):
        ficha = next(f for f in self.reg.fichas.values() if "mayorista" in f.herramientas)
        llamadas = []

        async def consumir(*a):
            llamadas.append(a)
            return "obj"

        async def crear(*a):
            return "sid"
        estado = {"agente": ficha.id, "acciones": [{"accion": "alta_mayorista", "herramienta": "mayorista", "operacion": "alta",
                                                    "resumen": "r", "argumentos": {}}]}
        with mock.patch.object(nodos.bandeja, "crear", crear), mock.patch.object(nodos.objetivos, "consumir", consumir):
            ejecutar(nodos.registrar_aprobaciones(estado, {"configurable": {"thread_id": "h"}}))
        self.assertEqual(llamadas, [])


if __name__ == "__main__":
    unittest.main()
