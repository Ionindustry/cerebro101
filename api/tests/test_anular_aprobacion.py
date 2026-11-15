"""Anular una aprobación pendiente (Dirección): base de datos con su protección del historial y el endpoint."""
import asyncio
import os
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import _sin_servicios  # noqa: F401

try:
    import psycopg
    from cerebro.aprobaciones import bandeja
except ImportError as e:      # pragma: no cover
    raise unittest.SkipTest(str(e))

URL = os.environ.get("CEREBRO_TEST_PG")
ESQUEMA = Path(__file__).resolve().parents[2] / "db" / "esquema.sql"


def ejecutar(c):
    return asyncio.run(c)


@unittest.skipUnless(URL, "sin CEREBRO_TEST_PG")
class TestAnularEnBase(unittest.TestCase):
    def setUp(self):
        self.schema = f"t_anul_{time.time_ns()}"
        t = ESQUEMA.read_text(encoding="utf-8")
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"CREATE SCHEMA {self.schema}")
            c.execute(f"SET search_path = {self.schema}")
            c.execute(t[t.index("CREATE TABLE IF NOT EXISTS aprobaciones ("):t.index("-- Red de instaladores")])
            c.execute("INSERT INTO aprobaciones (id, hilo, agente, departamento, accion, nivel, aprobadores, datos, decisiones) VALUES "
                      "('11111111-1111-1111-1111-111111111111', 'h1', 'precio', 'operaciones', 'oferta', 'doble', '{responsable_departamento,direccion}', '{}', "
                      "'[{\"usuario\": \"albert\", \"rol\": \"direccion\", \"aprobado\": true, \"canal\": \"panel\", \"comentario\": \"\", \"fecha\": \"2026-10-01T10:00:00+00:00\"}]')")
        sep = "&" if "?" in URL else "?"
        self.parche = mock.patch.object(bandeja, "ajustes", SimpleNamespace(database_url=f"{URL}{sep}options=-csearch_path%3D{self.schema}"))
        self.parche.start()
        self.sid = "11111111-1111-1111-1111-111111111111"

    def tearDown(self):
        self.parche.stop()
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"DROP SCHEMA {self.schema} CASCADE")

    def test_anula_un_ticket_con_una_firma_previa_y_queda_en_el_historial(self):
        s, hilo = ejecutar(bandeja.anular_solicitud(self.sid, "albert", {"direccion"}, "Antigua: pedía 2 firmas"))
        self.assertEqual((s.estado, hilo), ("rechazada", "h1"))
        self.assertEqual(ejecutar(bandeja.pendientes(None)), [])
        h = ejecutar(bandeja.historial(None, "rechazada"))
        self.assertEqual(len(h["items"]), 1)
        fila = h["items"][0]
        self.assertEqual(len(fila["decisiones"]), 2)                    # la firma de antes y la anulación
        self.assertEqual(fila["decisiones"][-1]["comentario"], "Anulada: Antigua: pedía 2 firmas")

    def test_no_se_anula_dos_veces_ni_sin_ser_direccion_ni_lo_inexistente(self):
        from cerebro.aprobaciones.logica import DecisionNoValida
        with self.assertRaises(DecisionNoValida):
            ejecutar(bandeja.anular_solicitud(self.sid, "ana", {"responsable"}, "motivo largo"))
        ejecutar(bandeja.anular_solicitud(self.sid, "albert", {"direccion"}, "motivo largo"))
        with self.assertRaisesRegex(DecisionNoValida, "ya está rechazada"):
            ejecutar(bandeja.anular_solicitud(self.sid, "albert", {"direccion"}, "motivo largo"))
        with self.assertRaises(LookupError):
            ejecutar(bandeja.anular_solicitud("22222222-2222-2222-2222-222222222222", "albert", {"direccion"}, "motivo largo"))

    def test_endpoint_permisos_motivo_y_aunque_el_agente_no_conteste(self):
        from cerebro.api import main
        from cerebro.api.main import Usuario, usuario_actual
        from fastapi.testclient import TestClient
        cl = TestClient(main.app)
        try:
            main.app.dependency_overrides[usuario_actual] = lambda: Usuario("ana", {"responsable"}, {"operaciones"})
            self.assertEqual(cl.post(f"/aprobaciones/{self.sid}/anular", json={"motivo": "motivo largo"}).status_code, 403)
            main.app.dependency_overrides[usuario_actual] = lambda: Usuario("albert", {"direccion"}, set())
            r = cl.post(f"/aprobaciones/{self.sid}/anular", json={"motivo": ""})
            self.assertEqual(r.status_code, 403)
            self.assertIn("motivo", r.json()["detail"])
            r = cl.post(f"/aprobaciones/{self.sid}/anular", json={"motivo": "Antigua, pedía 2 firmas"})      # el grafo de los agentes no está en las pruebas: la anulación vale igual
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(r.json()["estado"], "rechazada")
            self.assertEqual(cl.post("/aprobaciones/22222222-2222-2222-2222-222222222222/anular", json={"motivo": "motivo largo"}).status_code, 404)
        finally:
            main.app.dependency_overrides.clear()


if __name__ == "__main__":
    unittest.main()
