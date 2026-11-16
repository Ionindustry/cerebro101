import asyncio
import unittest

import _sin_servicios  # noqa: F401
import httpx

from cerebro import eet as E

CFG = {"url": "https://gw.eet.example/pa", "hosts": ["gw.eet.example"], "cid": "ES", "secretos": {"cliente": "C", "clave": "K"}, "moneda": "EUR", "ampliada": True, "max_referencias": 5}
RESP = b"""<?xml version="1.0" encoding="ISO-8859-1" ?><PAResponse Status="0" Text="OK">
<Item ItemNo="LSU-15" Status="0" Text="OK"><Stock>6</Stock><StockDetails><StockDetail Quantity="2" Type="Local" Available="Now"/><StockDetail Quantity="4" Type="Incoming" Available="7 days"/></StockDetails><Price>24100</Price><EAN>5706998010049</EAN><Description>Wall outlet</Description></Item>
<Item ItemNo="NOPE" Status="7" Text="not found"/></PAResponse>"""


def ejecutar(c):
    return asyncio.run(c)


async def _resolver(url):
    return "https", "gw.eet.example", 443, ["203.0.113.5"]


class TestEET(unittest.TestCase):
    def test_la_peticion_escapa_y_lleva_la_version_ampliada(self):
        x = E.construir_peticion('12"3', "a<b>", "ES", ["LSU-15"], True).decode("latin-1")
        self.assertIn('CustomerNo="12&quot;3"', x)
        self.assertIn("AuthCode=\"a&lt;b&gt;\"", x)
        self.assertIn('Version="Extended"', x)
        self.assertIn("<Item>LSU-15</Item>", x)

    def test_referencias_raras_se_rechazan(self):
        for malo in (["</Item><x>"], [], ["a" * 31]):
            with self.assertRaises(E.ErrorEET):
                E.referencias_validas(malo)
        self.assertEqual(E.referencias_validas(["A-1", " A-1 ", "B"]), ["A-1", "B"])

    def test_la_respuesta_convierte_centimos_y_distingue_lo_que_no_existe(self):
        r = E.interpretar_respuesta(RESP)["articulos"]
        self.assertEqual((r[0]["precio"], r[0]["stock"], r[0]["ean"], len(r[0]["stock_detalle"])), ("241.00", 6, "5706998010049", 2))
        self.assertEqual((r[1]["encontrado"], r[1]["estado"]), (False, "no existe en EET"))

    def test_xml_con_entidades_o_error_general_se_rechaza(self):
        with self.assertRaises(E.ErrorEET):
            E.interpretar_respuesta(b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><PAResponse Status="0"/>')
        with self.assertRaisesRegex(E.ErrorEET, "rechaza"):
            E.interpretar_respuesta(b'<Response Status="20" Text="Authentication not valid"/>')

    def test_consultar_sin_configurar_o_sin_claves_lo_dice(self):
        with self.assertRaisesRegex(E.ErrorEET, "no está configurado"):
            ejecutar(E.consultar(["A"], cfg={**CFG, "url": ""}))
        with self.assertRaisesRegex(E.ErrorEET, "secretos/eet.env"):
            ejecutar(E.consultar(["A"], cfg=CFG, claves={}))

    def test_consultar_hace_post_sin_filtrar_la_clave_en_el_error(self):
        vistos = []

        def manejador(req: httpx.Request):
            vistos.append(req)
            return httpx.Response(200, content=RESP)
        r = ejecutar(E.consultar(["LSU-15"], cfg=CFG, transporte=httpx.MockTransport(manejador), resolver=_resolver, claves={"C": "123", "K": "SECRETO"}))
        self.assertEqual(vistos[0].method, "POST")
        self.assertIn(b"SECRETO", vistos[0].content)
        self.assertEqual(r["articulos"][0]["referencia"], "LSU-15")
        malo = lambda req: httpx.Response(500, content=b"SECRETO")
        with self.assertRaises(E.ErrorEET) as c:
            ejecutar(E.consultar(["A"], cfg=CFG, transporte=httpx.MockTransport(malo), resolver=_resolver, claves={"C": "1", "K": "SECRETO"}))
        self.assertNotIn("SECRETO", str(c.exception))

    def test_dominio_no_permitido_se_rechaza(self):
        with self.assertRaisesRegex(E.ErrorEET, "https"):
            ejecutar(E.consultar(["A"], cfg={**CFG, "hosts": ["otro.example"]}, resolver=_resolver, claves={"C": "1", "K": "2"}))


if __name__ == "__main__":
    unittest.main()
