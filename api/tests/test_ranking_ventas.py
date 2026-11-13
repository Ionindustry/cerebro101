import asyncio
import unittest
from datetime import date
from decimal import Decimal

from cerebro import ranking_ventas as R

CAT = ({"id": "cctv", "nombre": "CCTV", "grupos": {"cctv"}, "palabras": ["camara", "nvr"]},
       {"id": "acceso", "nombre": "Accesos", "grupos": {"control de accesos"}, "palabras": ["lector"]})


def l(codigo, nombre, importe, qty=1, grupo="", marca="", pedido="SO-1"):
    return {"item_code": codigo, "item_name": nombre, "item_group": grupo, "brand": marca, "qty": qty, "importe": importe, "name": pedido}


class TestClasificar(unittest.TestCase):
    def test_por_grupo_y_por_palabras(self):
        self.assertEqual(R.clasificar(l("A", "x", 1, grupo="CCTV"), CAT), "cctv")
        self.assertEqual(R.clasificar(l("B", "Lector de tarjetas", 1), CAT), "acceso")
        self.assertEqual(R.clasificar(l("C", "Cámara domo", 1), CAT), "cctv")          # sin acento en el fichero, con acento en el nombre
        self.assertEqual(R.clasificar(l("D", "Cable", 1), CAT), "otros")

    def test_el_grupo_manda_sobre_las_palabras(self):
        self.assertEqual(R.clasificar(l("E", "Lector con cámara", 1, grupo="CCTV"), CAT), "cctv")

    def test_no_coincide_por_trozos(self):
        self.assertEqual(R.clasificar(l("F", "Conveniente", 1), ({"id": "t", "nombre": "T", "grupos": set(), "palabras": ["nvr"]},)), "otros")


class TestRanking(unittest.TestCase):
    def test_suma_ordena_y_recorta(self):
        lineas = [l("C1", "Cámara A", "100", 2, marca="Axis"), l("C1", "Cámara A", "50", 1, marca="Axis", pedido="SO-2"),
                  l("C2", "Cámara B", "120", 1, marca="Hikvision"), l("C3", "Cámara C", "10", 1, marca="Axis"), l("L1", "Lector", "300", 3, marca="Suprema")]
        r = R.ranking(lineas, CAT, top=2)
        self.assertEqual([t["tipo"] for t in r["tipos"]], ["acceso", "cctv"])               # por importe: 300 > 280
        cctv = r["tipos"][1]
        self.assertEqual([a["codigo"] for a in cctv["articulos"]], ["C1", "C2"])             # top 2 de 3
        self.assertEqual(cctv["articulos"][0]["importe"], "150.00")
        self.assertEqual(cctv["articulos"][0]["unidades"], "3.00")
        self.assertEqual([m["nombre"] for m in cctv["fabricantes"]], ["Axis", "Hikvision"])   # Axis 160 > Hik 120
        self.assertEqual(cctv["fabricantes"][0]["importe"], "160.00")
        self.assertEqual(cctv["pedidos"], 2)
        self.assertEqual(r["total"], "580.00")

    def test_cuota_y_sin_marca(self):
        r = R.ranking([l("X", "Cámara", "50"), l("Y", "Lector", "50")], CAT)
        self.assertEqual({t["tipo"]: t["cuota_pct"] for t in r["tipos"]}, {"cctv": "50.00", "acceso": "50.00"})
        self.assertEqual(r["tipos"][0]["fabricantes"][0]["nombre"], "(sin marca)")

    def test_empate_se_desempata_por_unidades_y_nombre(self):
        r = R.ranking([l("B", "Cámara B", "100", 1), l("A", "Cámara A", "100", 1), l("C", "Cámara C", "100", 5)], CAT)
        self.assertEqual([a["codigo"] for a in r["tipos"][0]["articulos"]], ["C", "A", "B"])

    def test_valores_raros_no_rompen(self):
        r = R.ranking([l("X", "Cámara", None, None), l("Y", "Cámara", "abc", "x"), l("Z", "Cámara", "10")], CAT)
        self.assertEqual(r["total"], "10.00")

    def test_top_acotado(self):
        r = R.ranking([l(f"C{i}", f"Cámara {i}", str(i)) for i in range(1, 40)], CAT, top=1000)
        self.assertEqual(len(r["tipos"][0]["articulos"]), R.MAX_TOP)
        self.assertEqual(len(R.ranking([l("C", "Cámara", "1")], CAT, top=0)["tipos"][0]["articulos"]), 1)

    def test_vacio(self):
        self.assertEqual(R.ranking([], CAT), {"tipos": [], "total": "0.00", "lineas": 0})


class TestObtener(unittest.TestCase):
    def test_periodo_valido_y_fechas(self):
        self.assertEqual(R.periodo(30, date(2026, 11, 13)), ("2026-10-15", "2026-11-14"))
        with self.assertRaises(ValueError):
            R.periodo(45)

    def test_obtener_usa_la_lectura_inyectada_y_avisa_si_otros_pesa_mucho(self):
        visto = {}

        async def leer(dep, desde, hasta):
            visto.update(dep=dep, desde=desde, hasta=hasta)
            return [l("X", "Tornillo", "90"), l("Y", "Cámara", "10")]
        r = asyncio.run(R.obtener(30, 5, leer, CAT, date(2026, 11, 13)))
        self.assertEqual(visto, {"dep": "direccion", "desde": "2026-10-15", "hasta": "2026-11-14"})
        self.assertIn("90.00 %", r["aviso"])
        self.assertEqual(r["tipos"][0]["tipo"], "otros")

    def test_el_fichero_real_define_los_tipos_pedidos(self):
        ids = {t["id"] for t in R.tipos()}
        for t in ("cctv", "control_acceso", "intrusion", "incendio", "intercom"):
            self.assertIn(t, ids)
        self.assertEqual(R.clasificar(l("Z", "Videograbador NVR 16 canales", 1), R.tipos()), "cctv")
        self.assertEqual(R.clasificar(l("Z", "Central de alarma", 1), R.tipos()), "intrusion")


if __name__ == "__main__":
    unittest.main()
