"""Redacción de la memoria técnica con Claude o ChatGPT: el prompt adaptado a cada licitación, lo que se guarda y cuándo se usa (sin red ni base de datos)."""
import asyncio
import unittest

import _sin_servicios  # noqa: F401

try:
    from cerebro.licitaciones import ofertas as O
    from cerebro.licitaciones import redaccion_externa as R
except ImportError as e:      # pragma: no cover
    raise unittest.SkipTest(str(e))

FICHA = {"cpv": ["35125300"], "criterios": [{"descripcion": "Memoria técnica", "peso": 30, "tipo": "juicio_valor"}, {"descripcion": "Plan de mantenimiento", "peso": 10, "tipo": "juicio_valor"},
                                              {"descripcion": "Precio", "peso": 60, "tipo": "automatico"}]}
SEL = [{"clave": "descripcion-solucion", "sobre": "tecnico", "titulo": "Descripción de la solución", "guia": "Qué se instala"},
       {"clave": "plan-trabajo", "sobre": "tecnico", "titulo": "Plan de trabajo", "guia": "Fases"}]


# La ficha tal como la devuelve la herramienta «licitaciones → ficha» (herramientas/licitaciones.py): `comprador` es el NOMBRE, no un diccionario
FICHA_REAL = {"id": "0b1f7a3e-1111-4222-8333-444444444441", "titulo": "Suministro de cámaras", "expediente": "EXP-1", "comprador": "Ayuntamiento de Girona", "estado": "abierta",
              "importe": {"valor": "250000.00", "moneda": "EUR"}, "plazo_presentacion": "2026-12-01T10:00:00Z", "cpv": ["35125300"], "nuts": ["ES512"], "procedimiento": "abierto",
              "criterios": [{"tipo": "juicio_valor", "descripcion": "Memoria técnica", "peso": 30}, {"tipo": "automatico", "descripcion": "Precio", "peso": 70}],
              "documentos": [{"nombre": "PPT", "tipo": "pliego", "url": "https://contrataciondelestado.es/a"}]}


class TestNormalizar(unittest.TestCase):
    UNA = [{"clave": "descripcion-solucion", "sobre": "tecnico"}]
    DOS = UNA + [{"clave": "plan-trabajo", "sobre": "tecnico"}]

    def test_la_lista_de_siempre_no_se_toca(self):
        d = {"secciones": [{"clave": "a", "contenido": "x"}]}
        self.assertIs(R.normalizar_secciones(d, self.UNA), d)

    def test_una_seccion_plana_se_acepta_si_solo_se_pidio_una(self):
        r = R.normalizar_secciones({"contenido": "Texto", "citas": [4], "resumen": "ok"}, self.UNA)
        self.assertEqual(r["secciones"], [{"clave": "descripcion-solucion", "contenido": "Texto", "citas": [4]}])
        self.assertEqual(r["resumen"], "ok")
        r = R.normalizar_secciones({"clave": "descripcion-solucion", "contenido": "T"}, self.DOS)         # con varias, vale si dice cuál es
        self.assertEqual(r["secciones"][0]["clave"], "descripcion-solucion")
        self.assertNotIn("secciones", R.normalizar_secciones({"contenido": "T"}, self.DOS))               # ambigua: no se adivina

    def test_un_diccionario_por_clave_se_acepta(self):
        r = R.normalizar_secciones({"descripcion-solucion": "Texto A", "plan-trabajo": {"contenido": "Texto B", "citas": [1]}, "otra": "no pedida"}, self.DOS)
        self.assertEqual(r["secciones"], [{"clave": "descripcion-solucion", "contenido": "Texto A"}, {"clave": "plan-trabajo", "contenido": "Texto B", "citas": [1]}])
        r = R.normalizar_secciones({"secciones": {"descripcion-solucion": "Texto A"}}, self.UNA)
        self.assertEqual(r["secciones"], [{"clave": "descripcion-solucion", "contenido": "Texto A"}])

    def test_lo_que_no_se_entiende_se_deja_como_esta(self):
        d = {"algo": "raro"}
        self.assertEqual(R.normalizar_secciones(d, self.UNA), d)


class TestOrganismo(unittest.TestCase):
    def test_vale_la_ficha_de_la_herramienta_la_del_motor_y_lo_raro(self):
        self.assertEqual(R.organismo_de(FICHA_REAL), "Ayuntamiento de Girona")                          # texto (el caso real que antes fallaba con AttributeError)
        self.assertEqual(R.organismo_de({"comprador": {"nombre": "Diputació de Girona"}}), "Diputació de Girona")
        self.assertEqual(R.organismo_de({"organismo": "Ayto"}), "Ayto")
        self.assertEqual(R.organismo_de({"comprador": None}), "")
        self.assertEqual(R.organismo_de(None), "")
        self.assertEqual(R.organismo_de({"comprador": 5}), "5")

    def test_la_adaptacion_y_el_prompt_funcionan_con_la_ficha_real(self):
        a = R.adaptacion(FICHA_REAL, "Texto del pliego")
        self.assertEqual((a["tipo"], a["sectores"], a["idioma"]), ("suministros", ["35"], "es"))
        m = R.construir_mensajes("Suministro", R.organismo_de(FICHA_REAL), "pliego", "[R1] x", "c", "- s", "", "perfil", "diseña", FICHA_REAL)
        self.assertIn("Órgano de contratación: Ayuntamiento de Girona", m[1]["content"])


class TestAdaptacion(unittest.TestCase):
    def test_tipo_de_contrato_por_el_cpv_o_por_la_ficha(self):
        self.assertEqual(R.tipo_de_contrato({"cpv": ["35125300"]}), "suministros")
        self.assertEqual(R.tipo_de_contrato({"cpv": ["45310000"]}), "obras")
        self.assertEqual(R.tipo_de_contrato({"cpv": ["72000000"]}), "servicios")
        self.assertEqual(R.tipo_de_contrato({"tipo_contrato": "Servicios", "cpv": ["35125300"]}), "servicios")
        self.assertEqual(R.tipo_de_contrato({}), "")

    def test_idioma_del_pliego(self):
        self.assertEqual(R.idioma_del_pliego("El adjudicatario deberá suministrar los equipos en el plazo indicado."), "es")
        ca = "La licitació té un pressupost de 100.000 €. L'adjudicatari lliurarà les ofertes d'un termini de 30 dies. " * 4
        self.assertEqual(R.idioma_del_pliego(ca), "ca")

    def test_limite_de_extension(self):
        self.assertIn("25 páginas", R.limite_de_extension("La memoria técnica tendrá un máximo de 25 páginas a una cara."))
        self.assertEqual(R.limite_de_extension("Sin límite alguno."), "")

    def test_el_reparto_de_palabras_sigue_los_puntos_y_los_automaticos_no_se_redactan(self):
        plan = R.plan_de_criterios(FICHA, 4000, 150)
        self.assertEqual([(c["criterio"], c["automatico"], c["palabras"]) for c in plan], [("Memoria técnica", False, 3000), ("Plan de mantenimiento", False, 1000), ("Precio", True, 0)])
        self.assertEqual(R.plan_de_criterios({}, 4000, 150), [])
        sin_peso = R.plan_de_criterios({"criterios": [{"descripcion": "x", "tipo": "juicio_valor"}]}, 4000, 150)
        self.assertEqual(sin_peso[0]["palabras"], 150)


class TestPrompt(unittest.TestCase):
    def mensajes(self, ficha=FICHA, pliego="Texto del pliego."):
        return R.construir_mensajes("Cámaras", "Ayto", pliego, "[R1] x", "c", R.texto_de_secciones(SEL), "", "perfil", "diseña", ficha)

    def test_las_reglas_de_honradez_van_siempre_aunque_se_edite_el_prompt(self):
        s = self.mensajes()[0]["content"]
        for regla in ("NO inventes", "[PENDIENTE", "TEXTO DE TERCEROS", "No hables de precios", "BORRADOR"):
            self.assertIn(regla, s)

    def test_se_adapta_al_tipo_al_sector_y_al_limite(self):
        m = self.mensajes(pliego="La oferta técnica tendrá un máximo de 25 páginas.")
        self.assertIn("SUMINISTROS", m[0]["content"])
        self.assertIn("Seguridad:", m[0]["content"])                           # división CPV 35
        self.assertIn("máximo de 25 páginas", m[1]["content"])
        self.assertIn("Precio (60 puntos): AUTOMÁTICO", m[1]["content"])
        self.assertIn("Memoria técnica (30 puntos): unas 2625 palabras", m[1]["content"])

    def test_otro_pliego_otro_prompt(self):
        a = self.mensajes({"cpv": ["72000000"], "criterios": []}, "Sin límite")
        self.assertIn("SERVICIOS", a[0]["content"])
        self.assertNotIn("SUMINISTROS", a[0]["content"])
        self.assertIn("La ficha no trae criterios", a[1]["content"])
        ca = self.mensajes(FICHA, "La licitació té un pressupost. L'adjudicatari lliurarà les ofertes d'un termini. " * 6)
        self.assertIn("CATALÁN", ca[0]["content"])

    def test_el_pliego_va_marcado_como_datos(self):
        self.assertIn("««««\nTexto del pliego.\n»»»»", self.mensajes()[1]["content"])


class TestMaterial(unittest.TestCase):
    def test_los_requisitos_solo_los_confirmados_y_con_su_id(self):
        t, ids = R.texto_de_requisitos([{"id": 4, "estado": "confirmado", "tipo": "tecnico", "resumen": "Garantía de 5 años", "cita": "garantía de cinco años", "documento": 1, "pagina": 3},
                                        {"id": 5, "estado": "borrador", "tipo": "tecnico", "resumen": "x", "cita": "y", "documento": 1, "pagina": 1}])
        self.assertIn("[R4]", t)
        self.assertNotIn("[R5]", t)
        self.assertEqual(ids, {4})
        self.assertIn("ninguno confirmado", R.texto_de_requisitos([])[0])

    def test_el_texto_del_pliego_lleva_marcas_y_se_recorta_avisando(self):
        docs = [{"n": 2, "nombre": "PPT", "paginas": [(i, "x" * 900) for i in range(1, 40)]}]
        t, avisos = R.texto_de_pliegos(docs, 6000)
        self.assertIn("[Documento 2 «PPT» · página 1]", t)
        self.assertLessEqual(len(t), 6000)
        self.assertEqual(len(avisos), 1)

    def test_lo_ya_escrito_no_incluye_las_secciones_que_se_van_a_escribir(self):
        sec = [{"sobre": "tecnico", "clave": "a", "titulo": "A", "estado": "borrador", "contenido": "texto a"}, {"sobre": "tecnico", "clave": "b", "titulo": "B", "estado": "borrador", "contenido": "texto b"},
               {"sobre": "economico", "clave": "c", "titulo": "C", "estado": "borrador", "contenido": "precio"}]
        t = R.texto_ya_escrito(sec, {"b"})
        self.assertIn("texto a", t)
        self.assertNotIn("texto b", t)
        self.assertNotIn("precio", t)


class TestAplicar(unittest.TestCase):
    def aplicar(self, respuesta, falla=()):
        guardado = []

        async def escribir(sobre, clave, contenido, citas):
            if clave in falla:
                raise O.ErrorOferta("ya la ha revisado una persona")
            guardado.append((sobre, clave, contenido, citas))
        escritas, omitidas = asyncio.run(R.aplicar(respuesta, SEL, {4, 7}, escribir))
        return escritas, omitidas, guardado

    def test_guarda_solo_las_claves_pedidas_y_las_citas_que_son_requisitos_confirmados(self):
        e, o, g = self.aplicar({"secciones": [{"clave": "descripcion-solucion", "contenido": "Texto", "citas": [7, 99, True, "4", 4]}, {"clave": "inventada", "contenido": "x"},
                                              {"clave": "plan-trabajo", "contenido": "Fases"}]})
        self.assertEqual((e, o), (["descripcion-solucion", "plan-trabajo"], {}))
        self.assertEqual(g[0], ("tecnico", "descripcion-solucion", "Texto", [4, 7]))
        self.assertNotIn("inventada", [x[1] for x in g])

    def test_una_seccion_que_no_se_puede_guardar_no_impide_las_demas(self):
        e, o, g = self.aplicar({"secciones": [{"clave": "descripcion-solucion", "contenido": "A"}, {"clave": "plan-trabajo", "contenido": "B"}]}, falla=("descripcion-solucion",))
        self.assertEqual(e, ["plan-trabajo"])
        self.assertIn("revisado", o["descripcion-solucion"])

    def test_lo_que_el_modelo_no_escribe_queda_como_omitido(self):
        e, o, g = self.aplicar({"secciones": [{"clave": "descripcion-solucion", "contenido": "   "}, "basura"]})
        self.assertEqual((e, set(o)), ([], {"descripcion-solucion", "plan-trabajo"}))


class TestEleccionDeModelo(unittest.TestCase):
    def test_lo_que_elige_la_persona_manda_y_lo_raro_es_automatico(self):
        self.assertEqual([R.modelo_pedido(x) for x in ("claude", " ChatGPT ", "auto", "gemini", None, "")], ["claude", "chatgpt", "auto", "auto", "auto", "auto"])
        self.assertEqual(R.proveedor_preferido("memoria", "chatgpt"), "chatgpt")
        self.assertEqual(R.proveedor_preferido("solucion", "claude"), "claude")

    def test_en_automatico_manda_la_configuracion_por_paso_y_si_no_hay_el_orden_general(self):
        from unittest import mock
        with mock.patch.object(R, "configuracion", lambda: {**R.DEFECTO, "proveedor_por_paso": {"solucion": "claude", "memoria": "chatgpt", "otro": "gemini"}}):
            self.assertEqual(R.proveedor_preferido("solucion"), "claude")
            self.assertEqual(R.proveedor_preferido("memoria", "auto"), "chatgpt")
            self.assertIsNone(R.proveedor_preferido("otro"))                  # un proveedor desconocido se ignora
            self.assertEqual(R.proveedor_preferido("memoria", "claude"), "claude")   # la persona manda sobre la configuración
        self.assertIsNone(R.proveedor_preferido("memoria"))                    # sin configuración: el orden general

    def test_el_preferido_va_primero_y_el_otro_queda_de_respaldo(self):
        from cerebro import modelos_externos as E
        self.assertEqual(E.ordenar(["claude", "chatgpt"], "chatgpt"), ["chatgpt", "claude"])
        self.assertEqual(E.ordenar(["claude", "chatgpt"], "claude"), ["claude", "chatgpt"])
        self.assertEqual(E.ordenar(["claude"], "chatgpt"), ["claude"])           # el preferido no está conectado: se usa el que haya
        self.assertEqual(E.ordenar(["chatgpt", "claude"], None), ["chatgpt", "claude"])
        self.assertEqual(E.ordenar([], "claude"), [])


class TestConsultaConRespaldo(unittest.TestCase):
    """consultar_publico: respeta la preferencia y pasa al otro proveedor si el preferido falla."""
    def probar(self, preferido, fallan=()):
        from unittest import mock
        from cerebro import modelos_externos as E
        orden = []

        async def llamar(p, mensajes, esquema, transporte=None, max_tokens=None, timeout=None, normalizar=None):
            orden.append(p)
            if p in fallan:
                raise E.ErrorExterno(f"{p} no responde")
            return {"ok": True}

        async def activos():
            return {"claude": True, "chatgpt": True}

        async def usadas(p):
            return 0

        async def contar(*a, **k):
            return None
        with mock.patch.object(E, "clave", lambda p: "k"), mock.patch.object(E, "activos", activos), mock.patch.object(E, "usadas_hoy", usadas), \
                mock.patch.object(E, "_llamar", llamar), mock.patch.object(E.actividad, "contar", contar):
            r = asyncio.run(E.consultar_publico("t", [{"role": "user", "content": "x"}], {"type": "object"}, preferido=preferido))
        return r, orden

    def test_el_preferido_responde(self):
        self.assertEqual(self.probar("chatgpt"), (({"ok": True}, "chatgpt"), ["chatgpt"]))
        self.assertEqual(self.probar("claude"), (({"ok": True}, "claude"), ["claude"]))

    def test_si_el_preferido_falla_responde_el_otro(self):
        self.assertEqual(self.probar("chatgpt", fallan=("chatgpt",)), (({"ok": True}, "claude"), ["chatgpt", "claude"]))

    def test_si_fallan_los_dos_lanza_un_motivo_legible(self):
        from cerebro import modelos_externos as E
        with self.assertRaises(E.ErrorExterno) as c:
            self.probar("claude", fallan=("claude", "chatgpt"))
        self.assertIn("no responde", str(c.exception))


class TestConfiguracion(unittest.TestCase):
    def test_pasos_activos_por_defecto(self):
        self.assertTrue(R.paso_activo("solucion"))
        self.assertTrue(R.paso_activo("memoria"))
        self.assertFalse(R.paso_activo("costes"))
        self.assertFalse(R.paso_activo("precio"))                          # el precio y los costes nunca salen a la nube


if __name__ == "__main__":
    unittest.main()
