"""Pruebas de las partes de las integraciones que no necesitan servidor."""
import unittest

import _sin_servicios  # noqa: F401
from datetime import date, datetime

from cerebro.herramientas.calendario import calcular_huecos
from cerebro.herramientas.contratacion import filtrar, leer_feed
from cerebro.herramientas.correo import construir_mensaje, resumir_mensaje

FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:cac="urn:dgpe:names:draft:codice:schema:xsd:CommonAggregateComponents-2"
      xmlns:cbc="urn:dgpe:names:draft:codice:schema:xsd:CommonBasicComponents-2">
  <entry>
    <id>https://contratacion.example/1</id>
    <title>Instalaci\xc3\xb3n de videovigilancia en el ayuntamiento</title>
    <link href="https://contratacion.example/1"/>
    <summary>Suministro e instalaci\xc3\xb3n</summary>
    <updated>2026-10-01T08:00:00Z</updated>
    <cac:ContractFolderStatus>
      <cbc:ContractFolderID>EXP-2026-15</cbc:ContractFolderID>
      <cac:ProcurementProject>
        <cac:BudgetAmount><cbc:TaxExclusiveAmount>48000</cbc:TaxExclusiveAmount></cac:BudgetAmount>
        <cac:RequiredCommodityClassification><cbc:ItemClassificationCode>45312200</cbc:ItemClassificationCode></cac:RequiredCommodityClassification>
      </cac:ProcurementProject>
      <cac:TenderSubmissionDeadlinePeriod><cbc:EndDate>2026-10-20</cbc:EndDate></cac:TenderSubmissionDeadlinePeriod>
    </cac:ContractFolderStatus>
  </entry>
  <entry>
    <id>https://contratacion.example/2</id>
    <title>Limpieza de oficinas</title>
    <cac:RequiredCommodityClassification><cbc:ItemClassificationCode>90910000</cbc:ItemClassificationCode></cac:RequiredCommodityClassification>
  </entry>
</feed>"""


class TestContratacion(unittest.TestCase):
    def test_lee_campos_codice(self):
        l = leer_feed(FEED)[0]
        self.assertEqual(l["expediente"], "EXP-2026-15")
        self.assertEqual(l["cpv"], ["45312200"])
        self.assertEqual(l["importe"], 48000.0)
        self.assertEqual(l["fecha_limite"], "2026-10-20")

    def test_filtra_por_cpv_e_importe(self):
        todas = leer_feed(FEED)
        self.assertEqual([l["expediente"] for l in filtrar(todas, ["4531"])], ["EXP-2026-15"])
        self.assertEqual(filtrar(todas, ["4531"], importe_max=10000), [])


class TestCorreo(unittest.TestCase):
    def test_comercial_lleva_pie_de_baja(self):
        m = construir_mensaje("comercial@101.cat", ["cliente@ejemplo.es"], "Oferta", "Hola", comercial=True,
                              pie="Responde BAJA para no recibir más mensajes.")
        self.assertIn("BAJA", m.get_content())

    def test_comercial_sin_pie_no_se_construye(self):
        with self.assertRaises(ValueError):
            construir_mensaje("comercial@101.cat", "x@ejemplo.es", "Oferta", "Hola", comercial=True)

    def test_resumen_decodifica_asunto(self):
        crudo = ("From: Ana <ana@ejemplo.es>\r\nSubject: =?utf-8?q?Presupuesto_c=C3=A1maras?=\r\n"
                 "Date: Thu, 01 Oct 2026 09:00:00 +0200\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n"
                 "Necesito un presupuesto.").encode()
        r = resumir_mensaje("7", crudo)
        self.assertEqual(r["asunto"], "Presupuesto cámaras")
        self.assertIn("presupuesto", r["texto"])


class TestCalendario(unittest.TestCase):
    def test_huecos_evitan_lo_ocupado(self):
        lunes = date(2026, 10, 5)
        ocupado = [(datetime(2026, 10, 5, 8, 0), datetime(2026, 10, 5, 12, 0))]
        libres = calcular_huecos(ocupado, lunes, lunes, 60)
        self.assertEqual(libres[0][0], datetime(2026, 10, 5, 12, 0))
        self.assertTrue(all(b <= datetime(2026, 10, 5, 18, 0) for _, b in libres))

    def test_sin_fines_de_semana(self):
        sabado = date(2026, 10, 10)
        self.assertEqual(calcular_huecos([], sabado, sabado, 60), [])
