"""scripts/revisar_enlaces_tarifa.py: dice qué columnas de un CSV traen enlaces, sin imprimir precios ni contenido."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

RUTA = Path(__file__).resolve().parents[2] / "scripts" / "revisar_enlaces_tarifa.py"
if not RUTA.exists():
    raise unittest.SkipTest("se ejecuta desde el repositorio, no desde la imagen")
_spec = importlib.util.spec_from_file_location("revisar_enlaces_tarifa", RUTA)
S = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(S)

FILAS = [["Model", "Name", "Price", "Datasheet", "Image"],
         ["DS-2CD", "Cámara", "123.4", "https://www.example.com/ds/2cd.pdf", "https://img.example.com/a.jpg"],
         ["NVR-8", "Grabador", "300", "", "https://img.example.com/b.jpg"],
         ["CAB", "Cable", "1", "https://www.example.com/cab", ""], ["X", "Sin nada", "5", "no es un enlace", "ftp://otro"]]


class TestRevisar(unittest.TestCase):
    def test_encuentra_las_columnas_con_enlaces_con_su_dominio_y_tipo(self):
        r = {c["columna"]: c for c in S.analizar(FILAS)}
        self.assertEqual(set(r), {"Datasheet", "Image"})                                    # Price, Name y Model no traen enlaces
        self.assertEqual((r["Datasheet"]["enlaces"], r["Datasheet"]["de"]), (2, 4))
        self.assertEqual(r["Datasheet"]["dominios"], [("www.example.com", 2)])
        self.assertEqual(dict(r["Datasheet"]["tipos"]), {"PDF": 1, "página web": 1})
        self.assertEqual(dict(r["Image"]["tipos"]), {"JPG": 2})

    def test_sin_enlaces_o_vacio(self):
        self.assertEqual(S.analizar([["Model", "Price"], ["A", "1"]]), [])
        self.assertEqual(S.analizar([]), [])

    def test_lee_csv_con_punto_y_coma_y_con_tildes_en_cp1252(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "t.csv"
            f.write_bytes("Modelo;Descripción;Ficha\nA;Cámara;https://x.com/a.pdf\n".encode("cp1252"))
            filas = S.leer(str(f))
        self.assertEqual(filas[0], ["Modelo", "Descripción", "Ficha"])
        self.assertEqual(S.analizar(filas)[0]["columna"], "Ficha")

    def test_no_imprime_precios_ni_contenido(self):
        import io
        from contextlib import redirect_stdout
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "t.csv"
            f.write_text("Model,Price,Datasheet\nA,987.65,https://x.com/a.pdf\n", encoding="utf-8")
            salida = io.StringIO()
            with redirect_stdout(salida):
                S.main(["x", str(f)])
        self.assertNotIn("987.65", salida.getvalue())
        self.assertIn("Datasheet", salida.getvalue())


if __name__ == "__main__":
    unittest.main()
