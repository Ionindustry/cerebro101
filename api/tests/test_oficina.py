"""La oficina del panel: estados de los agentes y qué detalle ve cada persona."""
import unittest
from datetime import datetime, timezone

import _sin_servicios  # noqa: F401

from cerebro import oficina
from cerebro.registro import cargar

AHORA = datetime.now(timezone.utc)


def snap(**k):
    base = {"actividad": {}, "pendientes": {}, "ultimas": []}
    base.update(k)
    return base


class TestOficina(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reg = cargar()

    def agente(self, r, id):
        return next(a for d in r["departamentos"] for a in d["agentes"] if a["id"] == id)

    def test_estructura_y_totales(self):
        r = oficina.construir(self.reg, snap(), {"direccion"}, set())
        self.assertEqual(len(r["departamentos"]), len(self.reg.departamentos))
        self.assertEqual(r["resumen"]["total"], len(self.reg.fichas))
        self.assertEqual((r["resumen"]["trabajando"], r["resumen"]["esperando"]), (0, 0))
        self.assertTrue(all(a["estado"] == "reposo" for d in r["departamentos"] for a in d["agentes"]))

    def test_estados(self):
        s = snap(actividad={"cobros": {"estado": "trabajando", "detalle": "Usando erpnext · listar", "actualizado": AHORA},
                            "tesorero": {"estado": "reposo", "ultima": "Usó erpnext · leer", "ultima_fecha": AHORA}},
                 pendientes={"seleccion": 2, "cobros": 1})
        r = oficina.construir(self.reg, s, {"direccion"}, set())
        self.assertEqual(self.agente(r, "cobros")["estado"], "trabajando")            # trabajando gana a esperando
        self.assertEqual(self.agente(r, "cobros")["detalle"], "Usando erpnext · listar")
        self.assertEqual(self.agente(r, "seleccion")["estado"], "esperando")
        self.assertEqual(self.agente(r, "seleccion")["detalle"], "Espera 2 aprobaciones")
        self.assertEqual(self.agente(r, "tesorero")["detalle"], "Última tarea: Usó erpnext · leer")
        self.assertEqual((r["resumen"]["trabajando"], r["resumen"]["esperando"]), (1, 1))

    def test_el_detalle_solo_lo_ve_quien_corresponde(self):
        s = snap(actividad={"cobros": {"estado": "trabajando", "detalle": "Usando erpnext · listar", "actualizado": AHORA}})
        propio = oficina.construir(self.reg, s, {"responsable"}, {"finanzas"})
        ajeno = oficina.construir(self.reg, s, {"responsable"}, {"comercial"})
        self.assertEqual(self.agente(propio, "cobros")["detalle"], "Usando erpnext · listar")
        self.assertIsNone(self.agente(ajeno, "cobros")["detalle"])
        self.assertEqual(self.agente(ajeno, "cobros")["estado"], "trabajando")        # el estado sí se ve

    def test_eventos_filtrados_por_departamento(self):
        s = snap(ultimas=[{"agente": "cobros", "herramienta": "erpnext", "operacion": "listar", "creado": AHORA, "ok": True},
                          {"agente": "seleccion", "herramienta": "correo", "operacion": "enviar", "creado": AHORA, "ok": False}])
        self.assertEqual(len(oficina.construir(self.reg, s, {"direccion"}, set())["eventos"]), 2)
        solo = oficina.construir(self.reg, s, set(), {"finanzas"})["eventos"]
        self.assertEqual([e["agente"] for e in solo], ["Cobros"])

    def test_agente_desconocido_en_los_datos_no_rompe(self):
        r = oficina.construir(self.reg, snap(actividad={"fantasma": {"estado": "trabajando"}}, pendientes={"fantasma": 1},
                                             ultimas=[{"agente": "fantasma", "herramienta": "x", "operacion": "y", "creado": AHORA, "ok": True}]),
                              {"direccion"}, set())
        self.assertEqual(r["resumen"]["trabajando"], 0)
        self.assertEqual(r["eventos"], [])


if __name__ == "__main__":
    unittest.main()
