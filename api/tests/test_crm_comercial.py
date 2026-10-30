"""Constancia en el CRM de los correos de Comercial: direcciones, texto escapado y el flujo con un CRM de mentira."""
import asyncio
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import _sin_servicios  # noqa: F401
from cerebro import crm_comercial as C

CONFIG = Path(__file__).resolve().parents[2] / "config"


def ejecutar(coro):
    return asyncio.run(coro)


class ErpDoble:
    def __init__(self, leads=None, tratos=None, falla=False):
        self.leads, self.tratos, self.falla, self.notas = leads or {}, tratos or {}, falla, []

    async def listar(self, doctype, dep, filtros=None, campos=None, limite=50):
        if self.falla:
            raise RuntimeError("caído")
        valor = filtros[0][2]
        if doctype == "CRM Lead":
            return [{"name": n} for n in self.leads.get(valor, [])]
        return [{"name": n} for n in self.tratos.get(valor, [])]

    async def crear_borrador(self, doctype, datos, dep):
        assert (doctype, dep) == ("FCRM Note", "comercial")
        self.notas.append(datos)
        return {"name": "N"}


class TestComercial(unittest.TestCase):
    def setUp(self):
        C._config.cache_clear()
        self.p = mock.patch.object(C, "ajustes", SimpleNamespace(dir_config=CONFIG))
        self.p.start()

    def tearDown(self):
        self.p.stop()
        C._config.cache_clear()

    def con(self, erp):
        return mock.patch.object(C, "_erp", lambda: erp)

    def test_direcciones(self):
        self.assertEqual(C.direcciones('Ana <ANA@x.es>, "Bo, Luis" <bo@x.es>, ana@x.es'), ["ana@x.es", "bo@x.es"])
        self.assertEqual(C.direcciones(["a@b.cat", "basura"]), ["a@b.cat"])

    def test_el_texto_va_escapado_y_acotado(self):
        h = C.cuerpo_nota("Oferta <b>", "Hola & adiós\n\n" + "x" * 5000, 100)
        self.assertIn("Correo enviado: Oferta &lt;b&gt;", h)
        self.assertIn("Hola &amp; adiós", h)
        self.assertLess(len(h), 400)

    def test_nota_en_el_lead_y_en_sus_tratos(self):
        erp = ErpDoble(leads={"ana@x.es": ["CRM-LEAD-1"]}, tratos={"CRM-LEAD-1": ["CRM-DEAL-1", "CRM-DEAL-2"]})
        with self.con(erp):
            n = ejecutar(C.anotar_correo("comercial", "Ana <ana@x.es>", "Presupuesto", "Adjunto el presupuesto"))
        self.assertEqual(n, 3)
        self.assertEqual([(x["reference_doctype"], x["reference_docname"]) for x in erp.notas], [("CRM Lead", "CRM-LEAD-1"), ("CRM Deal", "CRM-DEAL-1"), ("CRM Deal", "CRM-DEAL-2")])

    def test_destinatario_que_no_es_lead_no_anota_nada(self):
        erp = ErpDoble()
        with self.con(erp):
            self.assertEqual(ejecutar(C.anotar_correo("comercial", "otro@x.es", "Hola", "x")), 0)
        self.assertEqual(erp.notas, [])

    def test_solo_los_departamentos_de_la_configuracion(self):
        erp = ErpDoble(leads={"ana@x.es": ["L"]})
        with self.con(erp):
            self.assertEqual(ejecutar(C.anotar_correo("rrhh", "ana@x.es", "Hola", "x")), 0)
        self.assertEqual(erp.notas, [])

    def test_si_el_crm_falla_el_correo_no_se_ve_afectado(self):
        with self.con(ErpDoble(falla=True)):
            self.assertEqual(ejecutar(C.anotar_correo("comercial", "ana@x.es", "Hola", "x")), 0)


if __name__ == "__main__":
    unittest.main()
