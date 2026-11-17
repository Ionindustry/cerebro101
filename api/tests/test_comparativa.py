"""Comparativa de productos y ventaja competitiva: la evidencia, la comprobación de lo que dice el modelo, el aviso de que faltan fichas y su uso por los agentes."""
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
    from cerebro.licitaciones import comparativa as C
    from cerebro.licitaciones import encargos as E
    from cerebro.licitaciones import ofertas as O
    from cerebro.licitaciones import redaccion_externa as X
except ImportError as e:      # pragma: no cover
    raise unittest.SkipTest(str(e))

URL = os.environ.get("CEREBRO_TEST_PG")
ESQUEMA = Path(__file__).resolve().parents[2] / "db" / "esquema.sql"
ID = "0b1f7a3e-1111-4222-8333-444444444444"
FICHA = {"id": ID, "titulo": "Suministro de cámaras", "comprador": "Ayuntamiento de Girona", "cpv": ["35125300"],
         "criterios": [{"tipo": "juicio_valor", "descripcion": "Memoria técnica", "peso": 30}, {"tipo": "automatico", "descripcion": "Precio", "peso": 70}]}


def ev(*ids):
    return [{"id": i, "origen": "ficha", "titulo": f"Ficha {i}", "fuente": "doc", "texto": f"texto {i}"} for i in ids]


class TestEvidencia(unittest.TestCase):
    def test_las_lineas_de_proveedor_van_por_parecido_sin_precio_ni_duplicados(self):
        lineas = [{"ref": "DS-2CD", "desc": "Cámara domo IP 4 megapíxeles con visión nocturna", "precio": 123.4}, {"ref": "DS-2CD", "desc": "Cámara domo IP 4 megapíxeles con visión nocturna", "precio": 99},
                  {"ref": "NVR-8", "desc": "Grabador de vídeo en red de 8 canales", "precio": 300}, {"ref": "CAB", "desc": "Cable de red categoría 6", "precio": 1}, {"ref": "X", "desc": "", "precio": 5}, "basura"]
        r = C.lineas_relevantes(lineas, ["La cámara debe tener visión nocturna", "Grabador con 8 canales"])
        self.assertEqual([x["ref"] for x in r], ["DS-2CD", "NVR-8"])
        self.assertTrue(all("precio" not in x for x in r))
        self.assertEqual(C.lineas_relevantes(lineas, []), [])

    def test_una_familia_con_muchas_coincidencias_no_tapa_a_las_demas(self):
        teclados = [{"ref": f"KB-{i}", "desc": f"Teclado de control para grabador NVR de 8 canales modelo {i}"} for i in range(40)]
        camaras = [{"ref": "CAM-LPR", "desc": "Cámara bullet LPR matrícula 4MP"}, {"ref": "ROUT", "desc": "Router 4G industrial carril DIN"}]
        r = C.lineas_relevantes(teclados + camaras, ["Grabador NVR de 8 canales teclado de control", "Cámara bullet LPR de matrícula", "Router 4G industrial"], maximo=8)
        refs = {x["ref"] for x in r}
        self.assertIn("CAM-LPR", refs)
        self.assertIn("ROUT", refs)

    def test_una_tarifa_en_ingles_se_encuentra_con_un_pliego_en_castellano(self):
        lineas = [{"ref": "MS-C8", "desc": "4MP Outdoor Dome Network Camera", "precio": 1}, {"ref": "MS-N8", "desc": "8 channels Network Video Recorder", "precio": 2}, {"ref": "CAB", "desc": "Cat6 patch cable", "precio": 3}]
        r = C.lineas_relevantes(lineas, ["Cámara domo de exterior", "Grabador de 8 canales"])
        self.assertEqual({x["ref"] for x in r}, {"MS-C8", "MS-N8"})
        self.assertEqual(C.lineas_relevantes([{"ref": "A", "desc": "Cámara domo exterior"}], ["Outdoor dome camera"])[0]["ref"], "A")   # y al revés

    def test_las_caracteristicas_pedidas_van_primero_y_caben_las_de_una_tarifa_larga(self):
        esp = {f"Dato{i}": f"valor{i}" for i in range(1, 20)}
        esp["Protection level"] = "IP67 IK10"
        esp["NDAA"] = "Yes"
        r = C.lineas_relevantes([{"ref": "MS", "desc": "Outdoor Dome Camera", "especificaciones": esp}], ["Cámara domo de exterior con protección IP67"])
        d = r[0]["desc"]
        self.assertIn("Protection level: IP67 IK10", d)
        self.assertLess(d.index("Protection level"), d.index("Dato1:"))                  # lo pedido, antes que el resto
        self.assertIn("NDAA: Yes", d)                                                        # ya no se pierde el final de la lista
        self.assertLessEqual(len(d), C.MAX_TEXTO_LINEA)

    def test_especificaciones_utiles_respeta_el_tope(self):
        esp = {f"K{i}": "v" for i in range(60)}
        self.assertEqual(len(C._especificaciones_utiles(esp, set())), C.MAX_ESPECIFICACIONES_EVIDENCIA)

    def test_la_evidencia_se_numera_y_se_toma_de_las_dos_fuentes(self):
        async def buscar(q, dep, sens, k):
            self.assertEqual((dep, sens), ("licitaciones", "media"))
            return [{"titulo": "Ficha DS-2CD", "fuente": "ds.pdf", "texto": "Cámara 4 MP visión nocturna 30 m"}, {"titulo": "Ficha DS-2CD", "fuente": "ds.pdf", "texto": "Cámara 4 MP visión nocturna 30 m"}]

        async def lineas():
            return [{"ref": "NVR-8", "desc": "Grabador de vídeo en red de 8 canales", "precio": 300}]
        r = asyncio.run(C.reunir_evidencias(["Grabador de 8 canales", "Cámara nocturna"], buscar=buscar, lineas=lineas))
        self.assertEqual([e["id"] for e in r], ["P1", "P2"])
        self.assertEqual([e["origen"] for e in r], ["ficha", "lista de proveedor"])             # la ficha repetida se cuenta una vez
        self.assertNotIn("300", C.texto_de_evidencias(r))

    def test_las_fichas_no_se_comen_el_cupo_de_las_lineas_de_tarifa(self):
        n = iter(range(1000))

        async def buscar(q, dep, sens, k):
            return [{"titulo": f"Ficha {next(n)}", "fuente": "x.pdf", "texto": "Texto de ficha " + "a" * 900} for _ in range(3)]

        async def vectoriales(consultas):
            return [{"ref": "DS-2DE4A425IWG-E", "desc": "Cámara PTZ IP de 4 Mpx", "similitud": 0.64}]
        r = asyncio.run(C.reunir_evidencias([f"requisito {i}" for i in range(15)], buscar=buscar, vectoriales=vectoriales, lineas=lambda: asyncio.sleep(0, result=[])))
        self.assertIn("DS-2DE4A425IWG-E", [e["titulo"] for e in r])
        self.assertLessEqual(sum(e["origen"] == "ficha" for e in r), C.MAX_FICHAS)

    def test_si_falla_la_base_de_conocimiento_se_sigue_con_las_listas(self):
        async def buscar(*a):
            raise OSError("sin embeddings")

        async def lineas():
            return [{"ref": "NVR-8", "desc": "Grabador de vídeo en red de 8 canales"}]
        r = asyncio.run(C.reunir_evidencias(["Grabador de 8 canales"], buscar=buscar, lineas=lineas))
        self.assertEqual([e["origen"] for e in r], ["lista de proveedor"])


class TestVerificar(unittest.TestCase):
    DATOS = {"estrategia": "Se puntúa por la memoria.", "requisitos": [
        {"requisito": "[R1] Visión nocturna 30 m", "candidatos": [
            {"producto": "DS-2CD", "cumple": "si", "detalle": "30 m", "evidencia": ["P1", "[P9]"]},
            {"producto": "Otra", "cumple": "si", "detalle": "creo que sí", "evidencia": ["P7"]},               # evidencia que no existe
            {"producto": "Sin ficha", "cumple": "parcial", "detalle": "", "evidencia": []},
            {"producto": "Rara", "cumple": "quizá", "evidencia": ["P1"]}], "recomendado": "DS-2CD", "brecha": ""},
        {"requisito": "Grabador", "candidatos": [{"producto": "NVR-8", "cumple": "no", "evidencia": ["P2"]}], "recomendado": "NVR-8"}],
        "ventajas": [{"criterio": "Memoria técnica", "peso": "30", "ventaja": "Visión nocturna de 30 m", "evidencia": ["P1"], "como_destacarla": "Tabla de requisito → cómo se cumple"},
                     {"criterio": "Memoria técnica", "ventaja": "El mejor del mercado", "evidencia": []},                                 # sin evidencia: se descarta
                     {"criterio": "x", "ventaja": "inventada", "evidencia": ["P99"]}],
        "riesgos": [{"riesgo": "Plazo de entrega", "mitigacion": "Stock"}, {"riesgo": ""}], "pendientes": ["Ficha del grabador", ""]}

    def test_una_afirmacion_sin_evidencia_valida_no_se_da_por_cierta(self):
        r = C.verificar(self.DATOS, {"P1", "P2"})
        c1 = {c["producto"]: c for c in r["requisitos"][0]["candidatos"]}
        self.assertEqual((c1["DS-2CD"]["cumple"], c1["DS-2CD"]["evidencia"], c1["DS-2CD"]["degradado"]), ("si", ["P1"], False))     # [P9] no existe y se quita; P1 vale
        self.assertEqual((c1["Otra"]["cumple"], c1["Otra"]["degradado"]), ("sin_datos", True))                                       # «sí» con una evidencia inventada
        self.assertEqual((c1["Sin ficha"]["cumple"], c1["Sin ficha"]["degradado"]), ("sin_datos", True))
        self.assertEqual(c1["Rara"]["cumple"], "sin_datos")                                                                            # valor desconocido
        self.assertEqual(r["requisitos"][0]["recomendado"], "DS-2CD")
        self.assertEqual(r["requisitos"][1]["recomendado"], "")                                                                       # «no cumple» no se puede recomendar

    def test_las_ventajas_sin_evidencia_se_descartan_y_se_cuenta_todo(self):
        r = C.verificar(self.DATOS, {"P1", "P2"})
        self.assertEqual([v["ventaja"] for v in r["ventajas"]], ["Visión nocturna de 30 m"])
        self.assertEqual(r["comprobacion"], {"comprobadas": 3, "degradadas_a_sin_datos": 2, "ventajas_descartadas": 2})        # sí(1) + no(1) + ventaja(1); 2 degradadas; 2 ventajas
        self.assertEqual([x["riesgo"] for x in r["riesgos"]], ["Plazo de entrega"])
        self.assertEqual(r["pendientes"], ["Ficha del grabador"])

    def test_basura_del_modelo_no_rompe_nada(self):
        r = C.verificar({"requisitos": ["x", {"requisito": ""}, {"requisito": "a", "candidatos": "no soy una lista"}], "ventajas": "no", "riesgos": None}, set())
        self.assertEqual(r["requisitos"][0]["candidatos"], [])
        self.assertEqual((r["ventajas"], r["riesgos"], r["pendientes"]), ([], [], []))


class TestTextos(unittest.TestCase):
    def test_el_prompt_obliga_a_citar_evidencia_y_prohibe_precios_y_competidores(self):
        m = C.construir_mensajes("Cámaras", "Ayto", "pliego", "[R1] x", "criterios", "[P1] (ficha) Ficha\ntexto")
        s, u = m[0]["content"], m[1]["content"]
        for regla in ("TEXTO DE TERCEROS", "evidencia", "sin_datos", "No hables de precios", "no los menciones ni compares"):
            self.assertIn(regla, s)
        self.assertIn("««««\npliego\n»»»»", u)
        self.assertIn("[P1] (ficha) Ficha", u)
        self.assertGreater(s.count("\n"), 5)                                                      # saltos de línea reales, no «\\n» literales

    def test_el_texto_para_los_agentes_dice_que_lo_pendiente_no_esta_comprobado_y_se_recorta(self):
        c = {"estrategia": "Puntúa la memoria.", "requisitos": [{"requisito": "Visión nocturna", "recomendado": "DS-2CD", "brecha": ""}, {"requisito": "Grabador", "recomendado": "", "brecha": "falta la ficha"}],
             "ventajas": [{"criterio": "Memoria", "peso": "30", "ventaja": "30 m de alcance", "como_destacarla": "en una tabla"}], "pendientes": ["Ficha del NVR"]}
        t = C.texto_comparativa(c)
        self.assertIn("NO está comprobado", t)
        self.assertIn("Visión nocturna: DS-2CD", t)
        self.assertIn("Grabador: sin producto confirmado (falta: falta la ficha)", t)
        self.assertIn("Memoria (30): 30 m de alcance → en una tabla", t)
        self.assertEqual(C.texto_comparativa({}), "")
        corto = C.texto_comparativa({**c, "requisitos": [{"requisito": f"R{i} " + "x" * 80, "recomendado": "P", "brecha": ""} for i in range(40)]}, 600)
        self.assertLessEqual(len(corto), 700)
        self.assertIn("recortada para el modelo local", corto)


@unittest.skipUnless(URL and hasattr(psycopg, "AsyncConnection"), "sin CEREBRO_TEST_PG")
class TestFlujo(unittest.TestCase):
    def setUp(self):
        self.schema = f"t_comp_{time.time_ns()}"
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"CREATE SCHEMA {self.schema}")
            c.execute(f"SET search_path = {self.schema}")
            t = ESQUEMA.read_text(encoding="utf-8")
            c.execute(t[t.index("-- Pliegos y otros documentos de una licitación"):])
        sep = "&" if "?" in URL else "?"
        aj = SimpleNamespace(database_url=f"{URL}{sep}options=-csearch_path%3D{self.schema}", dir_config=E.ajustes.dir_config)
        from cerebro.licitaciones import pliegos
        self.p = [mock.patch.object(O, "ajustes", aj), mock.patch.object(pliegos, "ajustes", aj), mock.patch.object(X, "_documentos_leidos", self.docs),
                  mock.patch.object(pliegos, "requisitos", self.reqs), mock.patch.object(C.externos, "modelo_elegido", mock.AsyncMock(return_value="claude-prueba")),
                  mock.patch.object(C.externos, "_preparar", self.sin_datos_personales)]
        for p in self.p:
            p.start()
        asyncio.run(O.plan(ID, FICHA, "albert"))

    def tearDown(self):
        for p in self.p:
            p.stop()
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"DROP SCHEMA {self.schema} CASCADE")

    @staticmethod
    async def docs(motor_id):
        return [{"n": 1, "nombre": "PPT", "paginas": [(1, "La cámara tendrá visión nocturna de 30 m.")]}]

    @staticmethod
    async def reqs(motor_id):
        return {"requisitos": [{"id": 4, "estado": "confirmado", "tipo": "tecnico", "resumen": "Cámara con visión nocturna de 30 metros", "cita": "visión nocturna de 30 m", "documento": 1, "pagina": 1}]}

    @staticmethod
    async def sin_datos_personales(mensajes):
        return mensajes, {}, []

    @staticmethod
    async def buscar(q, dep, sens, k):
        return [{"titulo": "Ficha DS-2CD", "fuente": "ds.pdf", "texto": "Cámara domo 4 MP con visión nocturna de 30 m"}]

    def preparar(self, consulta=None, buscar=None, lineas=None):
        async def sin_lineas():
            return []
        return asyncio.run(C.preparar(ID, "Suministro de cámaras", FICHA, consulta=consulta, buscar=buscar or self.buscar, lineas=lineas or sin_lineas))

    def test_con_evidencia_y_modelo_se_guarda_la_comparativa_comprobada(self):
        visto = {}

        async def modelo(agente, mensajes, esquema, max_tokens=None, timeout=None, preferido=None, normalizar=None):
            visto["m"] = mensajes
            return {"estrategia": "Se puntúa por la memoria.", "requisitos": [{"requisito": "Visión nocturna 30 m", "candidatos": [
                {"producto": "DS-2CD", "cumple": "si", "detalle": "30 m", "evidencia": ["P1"]}, {"producto": "X", "cumple": "si", "evidencia": ["P5"]}], "recomendado": "DS-2CD"}],
                "ventajas": [{"criterio": "Memoria", "ventaja": "30 m", "evidencia": ["P1"]}, {"criterio": "Memoria", "ventaja": "mejor del mercado", "evidencia": []}], "pendientes": ["Ficha del NVR"]}, "claude"
        r = self.preparar(consulta=modelo)
        self.assertEqual((r["estado"], r["proveedor"], r["modelo"]), ("hecha", "claude", "claude-prueba"))
        self.assertIn("1 pasadas a «sin datos»", r["resumen"])
        self.assertIn("1 ventajas descartadas", r["resumen"])
        self.assertIn("[P1] (ficha) Ficha DS-2CD", visto["m"][1]["content"])
        self.assertIn("Ayuntamiento de Girona", visto["m"][1]["content"])
        g = asyncio.run(C.leer(ID))
        self.assertEqual((g["proveedor"], len(g["contenido"]["ventajas"])), ("claude", 1))
        self.assertEqual(g["evidencias"], [{"id": "P1", "origen": "ficha", "titulo": "Ficha DS-2CD", "fuente": "ds.pdf"}])             # solo el título, no el texto
        self.assertEqual({c["producto"]: c["cumple"] for c in g["contenido"]["requisitos"][0]["candidatos"]}, {"DS-2CD": "si", "X": "sin_datos"})

    def test_sin_ninguna_ficha_no_se_compara_y_se_dice_que_faltan(self):
        async def vacio(*a):
            return []

        async def nunca(*a, **k):
            raise AssertionError("no debe llamar al modelo sin evidencia")
        r = self.preparar(consulta=nunca, buscar=vacio)
        self.assertEqual(r["estado"], "omitida")
        self.assertIn("fichas técnicas", r["resumen"])
        self.assertIsNone(asyncio.run(C.leer(ID)))

    def test_sin_modelo_externo_queda_omitida_con_el_motivo(self):
        async def desconectado(*a, **k):
            raise C.externos.ErrorExterno("Claude y ChatGPT están desconectados")
        r = self.preparar(consulta=desconectado)
        self.assertEqual(r["estado"], "omitida")
        self.assertIn("desconectados", r["resumen"])
        self.assertIn("Necesita Claude o ChatGPT", r["resumen"])

    def test_si_los_datos_de_producto_no_se_pueden_anonimizar_no_salen(self):
        async def no_apto(mensajes):
            return mensajes, {}, ["categoría especial del RGPD"]

        async def nunca(*a, **k):
            raise AssertionError("no debe llamar al modelo")
        with mock.patch.object(C.externos, "_preparar", no_apto):
            r = self.preparar(consulta=nunca)
        self.assertEqual(r["estado"], "omitida")
        self.assertIn("anonimizar", r["resumen"])

    def test_un_fallo_interno_no_tumba_la_cadena_y_dice_cual(self):
        async def roto(*a, **k):
            raise KeyError("campo")
        r = self.preparar(consulta=roto)
        self.assertEqual(r["estado"], "omitida")
        self.assertIn("fallo interno (KeyError", r["resumen"])

    def test_los_encargos_y_los_agentes_reciben_la_comparativa(self):
        async def modelo(*a, **k):
            return {"estrategia": "Puntúa la memoria.", "requisitos": [{"requisito": "Visión nocturna", "candidatos": [{"producto": "DS-2CD", "cumple": "si", "evidencia": ["P1"]}], "recomendado": "DS-2CD"}],
                    "ventajas": [{"criterio": "Memoria", "ventaja": "30 m", "evidencia": ["P1"]}]}, "claude"
        self.preparar(consulta=modelo)
        t = asyncio.run(C.texto_para(ID))
        self.assertIn("COMPARATIVA DE PRODUCTOS", t)
        self.assertIn("Visión nocturna: DS-2CD", t)
        enviado = {}

        async def director(agente, mensajes, esquema, max_tokens=None, timeout=None, preferido=None, normalizar=None):
            enviado["u"] = mensajes[1]["content"]
            return {"encargos": []}, "claude"
        with mock.patch.object(E.externos, "modelo_elegido", mock.AsyncMock(return_value="m")):
            asyncio.run(E.preparar(ID, "Suministro de cámaras", FICHA, consulta=director))
        self.assertIn("COMPARATIVA DE PRODUCTOS", enviado.get("u", ""))                         # el director la tiene en cuenta al repartir el trabajo

    def test_el_endpoint_solo_para_licitaciones(self):
        from cerebro.api import main
        from cerebro.api.main import Usuario, usuario_actual
        from fastapi.testclient import TestClient
        c = TestClient(main.app)
        try:
            main.app.dependency_overrides[usuario_actual] = lambda: Usuario("pepe", {"usuario"}, {"finanzas"})
            self.assertEqual(c.get(f"/licitaciones/ofertas/{ID}/comparativa").status_code, 403)
            main.app.dependency_overrides[usuario_actual] = lambda: Usuario("marta", {"usuario"}, {"licitaciones"})
            self.assertEqual(c.get(f"/licitaciones/ofertas/{ID}/comparativa").json(), {"comparativa": None})
        finally:
            main.app.dependency_overrides.clear()


class TestPrepararEvidencias(unittest.TestCase):
    def test_cada_fragmento_pasa_la_comprobacion_por_separado_no_el_bloque_entero(self):
        """El límite de 4.000 caracteres de la anonimización es por texto: 12 fragmentos de 1.000 suman más y deben poder salir igualmente."""
        recibidos = []

        async def preparar(mensajes):
            recibidos.append([len(m["content"]) for m in mensajes])
            motivos = ["texto demasiado largo"] if any(len(m["content"]) > 4000 for m in mensajes) else []
            return mensajes, {"x": 1}, motivos

        evid = [{"id": f"P{i}", "origen": "lista de proveedor", "titulo": f"REF-{i}", "fuente": "", "texto": "cámara bullet 4 MP " * 50} for i in range(1, 13)]
        with mock.patch.object(C.externos, "_preparar", preparar):
            texto, sesion, motivos = asyncio.run(C.preparar_evidencias(evid))
        self.assertEqual(motivos, [])
        self.assertEqual(len(recibidos[0]), 12)                         # un mensaje por fragmento
        self.assertGreater(len(texto), 4000)                            # el total supera el límite que antes lo bloqueaba entero
        self.assertEqual(sesion, {"x": 1})
        for i in range(1, 13):
            self.assertIn(f"[P{i}] (lista de proveedor) REF-{i}", texto)

    def test_si_un_fragmento_no_se_puede_anonimizar_no_sale_nada(self):
        async def preparar(mensajes):
            return mensajes, {}, ["categoría especial de datos: salud"]

        with mock.patch.object(C.externos, "_preparar", preparar):
            _t, _s, motivos = asyncio.run(C.preparar_evidencias([{"id": "P1", "origen": "ficha", "titulo": "t", "fuente": "", "texto": "x"}]))
        self.assertEqual(motivos, ["categoría especial de datos: salud"])


if __name__ == "__main__":
    unittest.main()
