"""Direcciones públicas en los enlaces de los correos: PANEL_URL y CRM_URL_PUBLICA del .env, con prioridad para lo que se ponga a mano en la configuración."""
import os
import unittest
from unittest import mock

import _sin_servicios  # noqa: F401

from cerebro import enlaces, hoy_correo as HC
from cerebro.licitaciones import crm


class TestEnlaces(unittest.TestCase):
    def test_valida(self):
        self.assertEqual(enlaces.valida("https://jarvis.101.cat/"), "https://jarvis.101.cat")
        for malo in ("javascript:x", "", None, "ftp://x", "https://user:clave@jarvis.101.cat", "https://a b.cat"):
            self.assertIsNone(enlaces.valida(malo), malo)

    def test_es_local(self):
        for u in ("http://localhost:3000", "http://127.0.0.1:3000", "http://0.0.0.0:3000"):
            self.assertTrue(enlaces.es_local(u), u)
        self.assertFalse(enlaces.es_local("https://jarvis.101.cat"))

    def test_el_enlace_del_correo_usa_el_panel_del_env(self):
        with mock.patch.dict(os.environ, {"PANEL_URL": "https://jarvis.101.cat/"}):
            self.assertEqual(HC.configuracion({"resumen_hoy": {}})["url_panel"], "https://jarvis.101.cat")
            self.assertEqual(HC.configuracion({"resumen_hoy": {"url_panel": "https://otro.101.cat"}})["url_panel"], "https://otro.101.cat")   # lo de la configuración manda
            self.assertEqual(HC.configuracion({"resumen_hoy": {"url_panel": "javascript:x"}})["url_panel"], "https://jarvis.101.cat")

    def test_sin_env_queda_localhost_y_avisa(self):
        with mock.patch.dict(os.environ, {"PANEL_URL": ""}), self.assertLogs("cerebro.hoy_correo", level="WARNING") as g:
            self.assertEqual(HC.configuracion({"resumen_hoy": {}})["url_panel"], "http://localhost:3000")
        self.assertIn("PANEL_URL", "\n".join(g.output))

    def test_el_enlace_al_trato_del_crm_usa_la_direccion_publica(self):
        with mock.patch.dict(os.environ, {"CRM_URL_PUBLICA": "https://crm.101.cat/crm"}):
            self.assertEqual(crm.url_del_trato("T1", {"url_publica": ""}), "https://crm.101.cat/crm/deals/T1")
            self.assertEqual(crm.url_del_trato("T1", {"url_publica": "https://x.cat/crm"}), "https://x.cat/crm/deals/T1")
            self.assertIsNone(crm.url_del_trato("T1", {"url_publica": "javascript:x"}))
        with mock.patch.dict(os.environ, {"CRM_URL_PUBLICA": ""}):
            self.assertEqual(crm.url_del_trato("T1", {"url_publica": ""}), "http://localhost:8081/crm/deals/T1")


if __name__ == "__main__":
    unittest.main()
