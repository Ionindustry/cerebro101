"""Líneas de tarifa vectorizadas: qué se vectoriza, qué falta, y que la búsqueda por significado alimente la evidencia (con Postgres + pgvector, sin Ollama)."""
import asyncio
import hashlib
import os
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import _sin_servicios  # noqa: F401

try:
    import psycopg
    from psycopg.types.json import Jsonb
    from cerebro import lineas_vectores as LV
    from cerebro.licitaciones import comparativa as C
except ImportError as e:      # pragma: no cover
    raise unittest.SkipTest(str(e))

URL = os.environ.get("CEREBRO_TEST_PG")
ESQUEMA = Path(__file__).resolve().parents[2] / "db" / "esquema.sql"


def vector_falso(texto: str) -> list[float]:
    """Embedding de mentira: bolsa de palabras en 1024 posiciones; dos textos que comparten palabras se parecen."""
    v = [0.0] * 1024
    for w in texto.lower().replace("|", " ").replace(":", " ").split():
        v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 1024] += 1.0
    n = sum(x * x for x in v) ** 0.5 or 1.0
    return [x / n for x in v]


async def embed_falso(textos):
    return [vector_falso(t) for t in textos]


class TestTexto(unittest.TestCase):
    def test_lleva_marca_referencia_descripcion_y_caracteristicas_pero_no_precio(self):
        t = LV.texto_de_linea({"ref": "DS-2CD", "marca": "Hikvision", "desc": "Cámara bullet LPR 4MP", "precio": "123.40", "codigo": "HIK-DS-2CD", "especificaciones": {"Lente": "8-32 mm", "IP": "IP67", "vacio": ""}})
        self.assertIn("Hikvision", t)
        self.assertIn("DS-2CD", t)
        self.assertIn("Lente: 8-32 mm", t)
        self.assertNotIn("123", t)
        self.assertNotIn("HIK-DS-2CD", t)
        self.assertNotIn("vacio", t)

    def test_pendientes_solo_lo_nuevo_o_cambiado_y_sin_repetir(self):
        a = {"ref": "A", "desc": "Cámara domo"}
        b = {"ref": "B", "desc": "Grabador 8 canales"}
        existentes = {"A": LV.huella(LV.texto_de_linea(a))}
        r = LV.pendientes([a, b, b, {"ref": "", "desc": "sin ref"}, "basura"], existentes)
        self.assertEqual([x["ref"] for x in r], ["B"])
        a2 = {"ref": "A", "desc": "Cámara domo 4MP"}
        self.assertEqual([x["ref"] for x in LV.pendientes([a2], existentes)], ["A"])


class TestEvidencia(unittest.TestCase):
    def test_lo_vectorial_entra_primero_y_no_se_repite_con_las_palabras(self):
        async def buscar(_q, _d, _s, _k):
            return []

        async def vectoriales(_consultas):
            return [{"ref": "LPR-1", "desc": "Bullet LPR 4MP 8-32mm", "similitud": 0.8}]

        async def lineas():
            return [{"ref": "LPR-1", "desc": "Bullet LPR 4MP 8-32mm"}, {"ref": "OTRA", "desc": "Cámara bullet LPR de exterior"}]

        r = asyncio.run(C.reunir_evidencias(["Cámara bullet LPR"], buscar=buscar, lineas=lineas, vectoriales=vectoriales))
        self.assertEqual([e["titulo"] for e in r], ["LPR-1", "OTRA"])
        self.assertTrue(all(e["origen"] == "lista de proveedor" for e in r))

    def test_si_los_vectores_fallan_se_sigue_por_palabras(self):
        async def buscar(_q, _d, _s, _k):
            return []

        async def vectoriales(_c):
            raise OSError("sin embeddings")

        async def lineas():
            return [{"ref": "X", "desc": "Cámara domo exterior"}]

        r = asyncio.run(C.reunir_evidencias(["Cámara domo"], buscar=buscar, lineas=lineas, vectoriales=vectoriales))
        self.assertEqual([e["titulo"] for e in r], ["X"])


def hay_pgvector() -> bool:
    if not URL:
        return False
    try:
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute("CREATE EXTENSION IF NOT EXISTS vector")
        return True
    except Exception:      # noqa: BLE001
        return False


@unittest.skipUnless(hay_pgvector(), "sin CEREBRO_TEST_PG con pgvector")
class TestBase(unittest.TestCase):
    def setUp(self):
        self.schema = f"t_lv_{time.time_ns()}"
        t = ESQUEMA.read_text(encoding="utf-8")
        ini = t.index("CREATE TABLE IF NOT EXISTS importaciones_precios")
        fin = t.index(");", ini) + 2
        ini2 = t.index("CREATE TABLE IF NOT EXISTS lineas_vectores")
        fin2 = t.index("hnsw (embedding vector_cosine_ops);", ini2) + len("hnsw (embedding vector_cosine_ops);")
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"CREATE SCHEMA {self.schema}")
            c.execute(f"SET search_path = {self.schema}, public")
            c.execute(t[ini:fin])
            c.execute(t[ini2:fin2])
        sep = "&" if "?" in URL else "?"
        aj = SimpleNamespace(database_url=f"{URL}{sep}options=-csearch_path%3D{self.schema},public")
        self.p = mock.patch.object(LV, "ajustes", aj)
        self.p.start()
        self.addCleanup(self.p.stop)
        self.addCleanup(self.limpiar)
        self.url = aj.database_url

    def limpiar(self):
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"DROP SCHEMA {self.schema} CASCADE")

    def tarifa(self, lineas, proveedor="Visiotech", lista="Compra Visiotech", estado="aplicada"):
        with psycopg.connect(self.url, autocommit=True) as c:
            c.execute("INSERT INTO importaciones_precios (agente, departamento, proveedor, lista, lineas, estado) VALUES ('a','operaciones',%s,%s,%s,%s)",
                      [Jsonb({"nombre": proveedor}), lista, Jsonb(lineas), estado])

    def test_indexa_busca_por_significado_y_no_recalcula_lo_que_no_cambia(self):
        self.tarifa([{"ref": "LPR-1", "marca": "Hikvision", "desc": "Cámara bullet LPR 4MP lente 8-32mm", "precio": "100"},
                     {"ref": "CAB-1", "marca": "Generico", "desc": "Cable UTP categoría 6 bobina", "precio": "1"}])
        r = asyncio.run(LV.indexar_pendientes(embed=embed_falso))
        self.assertEqual((r["indexadas"], r["pendientes"]), (2, 0))
        llamadas = []

        async def contado(textos):
            llamadas.append(len(textos))
            return await embed_falso(textos)
        r2 = asyncio.run(LV.indexar_pendientes(embed=contado))
        self.assertEqual(r2["indexadas"], 0)
        self.assertEqual(llamadas, [])                                   # nada cambió: ni una llamada al modelo
        res = asyncio.run(LV.buscar(["cámara bullet LPR con lente 8-32mm"], embed=embed_falso))
        self.assertEqual(res[0]["ref"], "LPR-1")
        self.assertNotIn("100", res[0]["desc"])                          # sin precio

    def test_el_codigo_baja_al_que_incumple_el_requisito_y_lo_anota(self):
        self.tarifa([{"ref": "DOS", "desc": "Cámara bullet exterior 2 MP lente 4 mm IP67"},
                     {"ref": "CUATRO", "desc": "Cámara bullet exterior 4 MP lente 4 mm IP67"}])
        asyncio.run(LV.indexar_pendientes(embed=embed_falso))
        res = asyncio.run(LV.buscar(["Cámara bullet exterior de 4 MP lente 4 mm IP67"], por_consulta=1, embed=embed_falso))
        self.assertEqual([r["ref"] for r in res], ["CUATRO"])
        self.assertIn("Comprobado por el código", res[0]["desc"])
        res = asyncio.run(LV.buscar(["Cámara bullet exterior de 4 MP lente 4 mm IP67"], por_consulta=2, embed=embed_falso))
        dos = next(r for r in res if r["ref"] == "DOS")
        self.assertIn("NO cumple resolución", dos["desc"])
        with psycopg.connect(self.url) as c:
            self.assertEqual(c.execute("SELECT atributos->>'resolucion_mp' FROM lineas_vectores WHERE ref='CUATRO'").fetchone()[0], "4.0")

    def test_cada_consulta_aporta_su_mejor_producto_antes_de_que_una_repita(self):
        self.tarifa([{"ref": "LIC-1", "desc": "Licencia plataforma gestion"}, {"ref": "LIC-2", "desc": "Licencia plataforma gestion ampliada"},
                     {"ref": "LIC-3", "desc": "Licencia plataforma gestion enterprise"},
                     {"ref": "DOMO-1", "desc": "Domo PTZ zoom optico exterior con ranura tarjeta carcasa metalica antivandalica cable soporte pared"}])
        asyncio.run(LV.indexar_pendientes(embed=embed_falso))
        res = asyncio.run(LV.buscar(["Licencia plataforma gestion", "Domo PTZ zoom optico"], por_consulta=3, embed=embed_falso))
        refs = [r["ref"] for r in res]
        self.assertLess(refs.index("DOMO-1"), 2)                         # entre los dos primeros, aunque las licencias puntúen más en su consulta

    def test_el_modelo_ve_el_producto_entero_y_unido_de_todas_las_listas_sin_dinero(self):
        """El índice guarda solo 400 caracteres y 6 características; el zoom suele estar al final. Lo que se enseña al modelo sale de la línea original, de TODAS las listas del producto."""
        largo = "Cámara PTZ de gama alta " + "con muchas prestaciones de ejemplo " * 12
        self.tarifa([{"ref": "DOMO-32", "marca": "Hik", "desc": largo, "precio": "999",
                      "especificaciones": {"a1": "x", "a2": "x", "a3": "x", "a4": "x", "a5": "x", "a6": "x", "a7": "x", "Zoom óptico": "32x", "Precio neto": "1234", "Coste": "800"}}],
                    lista="Lista A")
        self.tarifa([{"ref": "DOMO-32", "marca": "Hik", "desc": "Cámara PTZ óptica varifocal motorizada (zoom)", "precio": "950"}], proveedor="Otro", lista="Lista B")
        asyncio.run(LV.indexar_pendientes(embed=embed_falso))
        with mock.patch.object(LV, "SIMILITUD_MINIMA", 0.0):               # el vector de pruebas es de bolsa de palabras: aquí no se prueba el umbral
            res = asyncio.run(LV.buscar(["Cámara PTZ gama alta con zoom óptico"], embed=embed_falso))
        self.assertEqual([r["ref"] for r in res], ["DOMO-32"])             # un producto, aunque venga en dos listas
        d = res[0]["desc"]
        self.assertIn("Zoom óptico: 32x", d)                                 # la característica del final llegó
        self.assertIn("varifocal motorizada", d)                             # y lo que aporta la otra lista
        for dinero in ("999", "950", "1234", "800", "Precio", "Coste"):
            self.assertNotIn(dinero, d)

    def test_si_no_se_encuentra_la_linea_original_se_usa_el_texto_del_indice(self):
        self.tarifa([{"ref": "X-1", "desc": "Cámara bullet LPR 4MP lente 8-32mm"}])
        asyncio.run(LV.indexar_pendientes(embed=embed_falso))
        with mock.patch.object(LV, "_lineas_de", mock.AsyncMock(return_value={})):
            res = asyncio.run(LV.buscar(["cámara bullet LPR con lente 8-32mm"], embed=embed_falso))
        self.assertEqual(res[0]["ref"], "X-1")
        self.assertIn("LPR", res[0]["desc"])

    def test_respeta_el_maximo_por_pasada_y_continua_en_la_siguiente(self):
        self.tarifa([{"ref": f"R{i}", "desc": f"Producto numero{i}"} for i in range(70)])
        r = asyncio.run(LV.indexar_pendientes(maximo=32, embed=embed_falso))
        self.assertEqual(r["indexadas"], 32)
        self.assertEqual(r["pendientes"], 38)
        r2 = asyncio.run(LV.indexar_pendientes(maximo=1000, embed=embed_falso))
        self.assertEqual(r2["indexadas"], 38)

    def test_borra_las_lineas_que_ya_no_estan_en_la_tarifa(self):
        self.tarifa([{"ref": "A", "desc": "Cámara domo"}, {"ref": "B", "desc": "Grabador"}])
        asyncio.run(LV.indexar_pendientes(embed=embed_falso))
        self.tarifa([{"ref": "A", "desc": "Cámara domo"}])               # tarifa más reciente, sin B
        asyncio.run(LV.indexar_pendientes(embed=embed_falso))
        with psycopg.connect(self.url) as c:
            refs = {r for (r,) in c.execute("SELECT ref FROM lineas_vectores")}
        self.assertEqual(refs, {"A"})

    def test_si_ollama_falla_lo_hecho_se_conserva_y_se_avisa(self):
        self.tarifa([{"ref": f"R{i}", "desc": f"Producto numero{i}"} for i in range(40)])
        llamadas = []

        async def falla_a_la_segunda(textos):
            llamadas.append(1)
            if len(llamadas) == 2:
                raise OSError("ollama caído")
            return await embed_falso(textos)
        r = asyncio.run(LV.indexar_pendientes(embed=falla_a_la_segunda))
        self.assertEqual(r["indexadas"], 32)
        self.assertEqual(r["error"], "OSError")
        self.assertEqual(r["pendientes"], 8)

    def test_una_tabla_vacia_no_devuelve_nada(self):
        self.assertEqual(asyncio.run(LV.buscar(["cualquier cosa"], embed=embed_falso)), [])


if __name__ == "__main__":
    unittest.main()
