"""Exportación de evidencias (manifiesto, huellas, verificación) y registro de acciones ejecutadas."""
import asyncio
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

import _sin_servicios  # noqa: F401

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import exportar_evidencias as ev  # noqa: E402


class TestExportador(unittest.TestCase):
    def test_paginar_recorre_todas_las_paginas(self):
        paginas = {1: {"data": [1, 2], "meta": {"totalPages": 3}}, 2: {"data": [3], "meta": {"totalPages": 3}},
                   3: {"data": [4], "meta": {"totalPages": 3}}}
        self.assertEqual(list(ev.paginar(lambda p: paginas[p])), [1, 2, 3, 4])
        self.assertEqual(list(ev.paginar(lambda p: {"data": [9]})), [9])      # sin meta: una sola página

    def test_el_dia_final_entra_entero(self):
        self.assertEqual(ev._iso(date(2026, 10, 31), fin=True), "2026-11-01T00:00:00Z")
        self.assertEqual(ev._iso(date(2026, 10, 1)), "2026-10-01T00:00:00Z")

    def _exportacion(self, carpeta: Path) -> None:
        c = {"trazas.jsonl": ev.escribir_jsonl(carpeta / "trazas.jsonl", iter([{"id": "a"}, {"id": "b"}])),
             "registro_acciones.jsonl": ev.escribir_jsonl(carpeta / "registro_acciones.jsonl", iter([{"id": 1}]))}
        ev.escribir_manifiesto(carpeta, {"desde": "2026-10-01", "hasta": "2026-10-31"}, c)

    def test_exportacion_integra_se_verifica(self):
        with tempfile.TemporaryDirectory() as d:
            self._exportacion(Path(d))
            self.assertEqual(ev.verificar(Path(d)), [])

    def test_detecta_cambios_borrados_y_anexos(self):
        with tempfile.TemporaryDirectory() as d:
            c = Path(d)
            self._exportacion(c)
            (c / "registro_acciones.jsonl").write_text('{"id": 1}\n{"falso": true}\n', encoding="utf-8")
            problemas = ev.verificar(c)
            self.assertTrue(any("huella" in p for p in problemas))
            self.assertTrue(any("registros" in p for p in problemas))
            (c / "trazas.jsonl").unlink()
            self.assertTrue(any("Falta trazas.jsonl" in p for p in ev.verificar(c)))

    def test_manipular_el_manifiesto_tambien_se_detecta(self):
        with tempfile.TemporaryDirectory() as d:
            c = Path(d)
            self._exportacion(c)
            m = json.loads((c / "manifiesto.json").read_text())
            m["hasta"] = "2030-01-01"
            (c / "manifiesto.json").write_text(json.dumps(m), encoding="utf-8")
            self.assertTrue(any("manifiesto.json" in p for p in ev.verificar(c)))


class TestRegistroDeAcciones(unittest.TestCase):
    def setUp(self):
        try:
            from cerebro.grafo import nodos
            from cerebro.registro import registro
        except ImportError as e:      # sin langgraph (portátil sin el contenedor)
            self.skipTest(f"requiere las dependencias del contenedor: {e}")
        self.nodos, self.ficha = nodos, next(iter(registro().fichas.values()))

    def test_ejecutadas_y_fallidas_dejan_constancia_las_rechazadas_no(self):
        n = self.nodos
        guardado = []

        async def registrar(*a):
            guardado.append(a)
            return "ok"

        async def usar(ficha, herramienta, operacion, **k):
            if operacion == "mala":
                raise LookupError("no existe")
            return {"ok": True}

        estado = {"agente": self.ficha.id, "acciones": [
            {"herramienta": "h", "operacion": "buena", "estado": "aprobada", "solicitud_id": "s1", "argumentos": {}},
            {"herramienta": "h", "operacion": "mala", "estado": "aprobada", "solicitud_id": "s2", "argumentos": {}},
            {"herramienta": "h", "operacion": "buena", "estado": "rechazada", "solicitud_id": "s3", "argumentos": {}}]}
        with mock.patch.object(n, "dejar_constancia", registrar), mock.patch.object(n.H, "usar", usar):
            r = asyncio.run(n.ejecutar_acciones(estado, {"configurable": {"thread_id": "hilo-1"}}))
        self.assertEqual([a["estado"] for a in r["acciones"]], ["ejecutada", "error", "rechazada"])
        self.assertEqual([g[4] for g in guardado], ["s1", "s2"])           # aprobación de cada acción registrada
        self.assertTrue(guardado[0][5].startswith("OK:"))
        self.assertTrue(guardado[1][5].startswith("ERROR: LookupError"))
        self.assertNotIn("aviso", r["acciones"][0])                        # con constancia correcta no hay aviso

    def test_si_falla_el_registro_no_se_pierde_el_resultado(self):
        n = self.nodos

        async def insertar(*a):
            raise RuntimeError("base de datos caída")

        async def usar(*a, **k):
            return {"ok": True}

        estado = {"agente": self.ficha.id, "acciones": [
            {"herramienta": "h", "operacion": "buena", "estado": "aprobada", "solicitud_id": "s1", "argumentos": {}}]}
        from cerebro import constancia
        with mock.patch.object(constancia, "_insertar", insertar), mock.patch.object(constancia, "REINTENTOS", (0, 0)), \
                mock.patch.object(constancia, "_guardar_local", return_value=False), mock.patch.object(n.H, "usar", usar), \
                self.assertLogs("cerebro.constancia", level="CRITICAL"):
            r = asyncio.run(n.ejecutar_acciones(estado, {"configurable": {"thread_id": "h"}}))
        self.assertEqual(r["acciones"][0]["estado"], "ejecutada")          # la acción no se pierde
        self.assertIn("no se ha podido guardar", r["acciones"][0]["aviso"])  # y la persona sabe que falta la constancia


if __name__ == "__main__":
    unittest.main()
