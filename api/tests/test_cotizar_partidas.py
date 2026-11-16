import asyncio
import unittest

from cerebro.licitaciones import cotizar_partidas as C

ALIAS = {"prefijos": [], "exactas": {}, "propias": [], "sin_marca": []}


def fila(i, producto, cantidad="4", coste=None, excluida=False):
    return {"id": i, "producto": producto, "cantidad": cantidad, "coste_unit_eur": coste, "excluida": excluida}


class Puras(unittest.TestCase):
    def test_referencia(self):
        self.assertEqual(C.referencia_de("Cámara domo Milesight MS-C8573-FPB 4MP"), "MS-C8573-FPB")
        self.assertEqual(C.referencia_de("cable utp"), "cable utp")

    def test_marca_de(self):
        marcas = ["Milesight", "Hikvision", "Axis"]
        self.assertEqual(C.marca_de("Cámara domo Milesight MS-C8573", marcas, ALIAS), "Milesight")
        self.assertIsNone(C.marca_de("Cámara domo sin marca XY-1234", marcas, ALIAS))
        self.assertIsNone(C.marca_de("Axisimetrica 1234", marcas, ALIAS))           # palabra entera, no trozo

    def test_elegir_proveedor(self):
        p, _ = C.elegir_proveedor([{"proveedor": "A", "articulos": 5, "email": None}, {"proveedor": "B", "articulos": 2, "email": "b@x.es"}, {"proveedor": "C", "articulos": 9, "email": "c@x.es"}])
        self.assertEqual(p["proveedor"], "C")
        p, m = C.elegir_proveedor([{"proveedor": "A", "articulos": 5, "email": None}])
        self.assertIsNone(p)
        self.assertIn("Falta el correo de A", m)
        p, m = C.elegir_proveedor([])
        self.assertIsNone(p)
        self.assertIn("Ningún proveedor", m)

    def test_pendientes(self):
        filas = [fila(1, "a"), fila(2, "b", coste="10"), fila(3, "c", excluida=True), fila(4, "d", cantidad=None), fila(5, "e")]
        self.assertEqual([f["id"] for f in C.pendientes(filas, [{"partida": 5}])], [1])
        self.assertEqual([f["id"] for f in C.sin_cantidad(filas)], [4])


class Preparar(unittest.TestCase):
    def test_crea_omite_y_no_envia(self):
        filas = [fila(1, "Milesight MS-C8573-FPB"), fila(2, "Marca Rara XZ-9999"), fila(3, "Hikvision DS-2CD2143G2", cantidad=None), fila(4, "Axis P3245-V")]
        hechas = []

        async def listar(_m):
            return {"partidas": filas}

        async def abiertas():
            return []

        async def crear(datos, por):
            hechas.append(datos)
            return {"id": len(hechas), "referencia": datos["referencia"]}
        provs = {"Milesight": [{"proveedor": "A-Secur", "articulos": 30, "email": "ventas@asecur.example"}], "Axis": [{"proveedor": "Otro", "articulos": 3, "email": None}]}
        r = asyncio.run(C.preparar("d9cfcbaa-3f95-4677-961b-6c131e529021", "albert", "manual", "dias", 15, listar=listar, abiertas=abiertas, marcas=["Milesight", "Axis", "Hikvision"], proveedores=provs, crear=crear))
        self.assertEqual([c["producto"] for c in r["creadas"]], ["Milesight MS-C8573-FPB"])
        self.assertEqual(hechas[0]["proveedor"], "A-Secur")
        self.assertEqual(hechas[0]["partida"], 1)
        self.assertEqual(hechas[0]["modo"], "manual")
        motivos = {o["producto"]: o["motivo"] for o in r["omitidas"]}
        self.assertIn("cantidad", motivos["Hikvision DS-2CD2143G2"])
        self.assertIn("marca", motivos["Marca Rara XZ-9999"])
        self.assertIn("Falta el correo de Otro", motivos["Axis P3245-V"])


if __name__ == "__main__":
    unittest.main()
