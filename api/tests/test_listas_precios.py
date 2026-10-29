"""Importación de listas de precios: leer la tabla del documento, validar, proponer, vista previa y aplicar en el ERP (simulado), repetible sin duplicar."""
import asyncio
import os
import tempfile
import time
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import _sin_servicios  # noqa: F401

try:
    import psycopg
    from cerebro import listas_precios as L
except ImportError as e:      # pragma: no cover
    raise unittest.SkipTest(str(e))

URL = os.environ.get("CEREBRO_TEST_PG")
ESQUEMA = Path(__file__).resolve().parents[2] / "db" / "esquema.sql"
DOC = "0b1f7a3e-1111-4222-8333-444444444444"
CSV = ("Ref;Descripción;PVP;Ud\n"
       "CÁMARAS DOMO\n"
       "A-1;Cámara domo 4K;123,50;ud\n"
       "A-2;Grabador 16 canales;1.410,00;ud\n"
       "A-3;Cable UTP cat6;abc;m\n"
       ";Nota sin referencia;5,00;\n"
       "A-1;Cámara domo 4K (repetida);130,00;ud\n"
       "A 4;Fuente 12V;9,90;ud\n").encode()


def ejecutar(c):
    return asyncio.run(c)


def paginas_csv(texto=CSV):
    return [(1, texto.decode() if isinstance(texto, bytes) else texto)]


class TestLeerLaTabla(unittest.TestCase):
    def test_csv_por_nombre_de_columna_con_titulos_y_filas_malas(self):
        r = L.construir_lineas(paginas_csv(), "csv", {"referencia": "ref", "descripcion": "Descripción", "precio": "pvp", "unidad": "ud"}, 1, "VISIOT")
        self.assertEqual([l["ref"] for l in r["lineas"]], ["A-1", "A-2", "A 4"])
        self.assertEqual([l["precio"] for l in r["lineas"]], ["123.5000", "1410.0000", "9.9000"])
        self.assertEqual([l["codigo"] for l in r["lineas"]], ["VISIOT-A-1", "VISIOT-A-2", "VISIOT-A-4"])
        self.assertEqual(r["omitidas"], 1)                                           # el título de sección «CÁMARAS DOMO»
        motivos = " | ".join(x["motivo"] for x in r["rechazadas"])
        self.assertIn("abc", motivos)                                                # precio que no es número
        self.assertIn("falta la referencia", motivos)
        self.assertIn("repetida", motivos)
        self.assertTrue(any("precio distinto" in a for a in r["avisos"]))
        self.assertEqual(r["columnas"], {"referencia": 1, "descripcion": 2, "precio": 3, "unidad": 4})

    def test_por_numero_de_columna_y_sin_cabecera(self):
        r = L.construir_lineas([(1, "A-1;Cámara;10,00\nA-2;Grabador;20,00")], "csv", {"referencia": 1, "precio": 3, "descripcion": "2"}, 0, "P")
        self.assertEqual([l["precio"] for l in r["lineas"]], ["10.0000", "20.0000"])

    def test_excel_varias_hojas_y_la_cabecera_de_cada_una(self):
        h1 = "[Hoja «Cámaras»]\nRef | Descripción | PVP\nA-1 | Cámara | 12,5"
        h2 = "[Hoja «Cables»]\nRef | Descripción | PVP\nC-1 | Cable | 0,85\nC-2 | Cable 2 | 1,10"
        r = L.construir_lineas([(1, h1), (2, h2)], "xlsx", {"referencia": "Ref", "precio": "PVP"}, 1, "P")
        self.assertEqual([l["ref"] for l in r["lineas"]], ["A-1", "C-1", "C-2"])
        self.assertEqual(r["lineas"][1]["fila"], "p. 2, fila 2")
        solo = L.construir_lineas([(1, h1), (2, h2)][1:], "xlsx", {"referencia": "Ref", "precio": "PVP"}, 1, "P")
        self.assertEqual(len(solo["lineas"]), 2)

    def test_pdf_con_columnas_separadas_por_espacios(self):
        t = "Ref      Descripción         PVP\nA-1      Cámara domo 4K      123,50\nA-2      Grabador            410,00"
        r = L.construir_lineas([(1, t)], "pdf", {"referencia": 1, "descripcion": 2, "precio": 3}, 1, "P")
        self.assertEqual([(l["ref"], l["desc"], l["precio"]) for l in r["lineas"]], [("A-1", "Cámara domo 4K", "123.5000"), ("A-2", "Grabador", "410.0000")])

    def test_iva_incluido_y_descuento(self):
        r = L.construir_lineas([(1, "Ref;PVP;Dto\nA;121,00;10\nB;100,00;")], "csv", {"referencia": "Ref", "precio": "PVP", "descuento": "Dto"}, 1, "P", iva_incluido_pct=21)
        self.assertEqual([l["precio"] for l in r["lineas"]], ["90.0000", "82.6446"])
        with self.assertRaises(L.ErrorImportacion):
            L.construir_lineas([(1, "Ref;PVP;Dto\nA;10;150")], "csv", {"referencia": "Ref", "precio": "PVP", "descuento": "Dto"}, 1, "P")

    def test_columnas_incorrectas_se_explican(self):
        for col, texto in (({"referencia": "Ref"}, "precio"), ({"referencia": "Ref", "precio": "Inexistente"}, "no está"), ({"referencia": "Ref", "precio": "Ref"}, "misma columna"),
                           ({"referencia": "Ref", "precio": "PVP", "color": 4}, "desconocidas"), ({"referencia": "Ref", "precio": True}, "no es válida"), ("x", "objeto")):
            with self.assertRaisesRegex(L.ErrorImportacion, texto, msg=str(col)):
                L.construir_lineas([(1, "Ref;PVP\nA;1,00")], "csv", col, 1, "P")
        with self.assertRaisesRegex(L.ErrorImportacion, "varias veces"):
            L.construir_lineas([(1, "Ref;Precio venta;Precio coste\nA;2;1")], "csv", {"referencia": "Ref", "precio": "Precio"}, 1, "P")
        with self.assertRaisesRegex(L.ErrorImportacion, "ninguna línea"):
            L.construir_lineas([(1, "Ref;PVP\n;\n")], "csv", {"referencia": "Ref", "precio": "PVP"}, 1, "P")
        with self.assertRaisesRegex(L.ErrorImportacion, "no parecen"):
            L.construir_lineas([(1, "Ref;PVP\n" + "\n".join(f"X{i};texto" for i in range(30)) + "\nOK;1,00")], "csv", {"referencia": "Ref", "precio": "PVP"}, 1, "P")
        with self.assertRaises(L.ErrorImportacion):
            L.construir_lineas([(1, "Ref;PVP\nA;1")], "csv", {"referencia": "Ref", "precio": "PVP"}, 99, "P")
        with self.assertRaisesRegex(L.ErrorImportacion, "más de 2 líneas"):
            L.construir_lineas([(1, "Ref;PVP\nA;1,00\nB;2,00\nC;3,00")], "csv", {"referencia": "Ref", "precio": "PVP"}, 1, "P", max_lineas=2)

    def test_precios_ambiguos_o_absurdos_se_rechazan_no_se_adivinan(self):
        for malo in ("1.234", "0", "-5", "abc", "", "99999999999"):
            with self.assertRaises((L.ErrorImportacion,), msg=malo):
                L.a_precio(malo)
        self.assertEqual(L.a_precio("1.234,56"), Decimal("1234.5600"))
        self.assertEqual(L.a_precio("12,5 €"), Decimal("12.5000"))
        self.assertEqual(L.a_precio(12.5), Decimal("12.5000"))

    def test_codigos(self):
        self.assertEqual(L.prefijo_proveedor("Visiotech, S.L."), "VISIOT")
        self.assertEqual(L.prefijo_proveedor("Ñandú & Co"), "NANDUC")
        self.assertEqual(L.prefijo_proveedor("***"), "PROV")
        self.assertEqual(L.codigo_articulo("V", " A 1/2 <x> "), "V-A-1/2-x")
        with self.assertRaises(L.ErrorImportacion):
            L.codigo_articulo("V", "<>")
        with self.assertRaises(L.ErrorImportacion):
            L.codigo_articulo("V", "x" * 200)

    def test_delimitadores(self):
        self.assertEqual(L.detectar_delimitador(["a;b;c", "1;2;3"]), ";")
        self.assertEqual(L.detectar_delimitador(["a,b,c", "1,2,3"]), ",")
        self.assertEqual(L.detectar_delimitador(["a\tb", "1\t2"]), "\t")
        self.assertEqual(L.filas_de_pagina('a,b\n"x, y",2', "csv"), [["a", "b"], ["x, y", "2"]])


class TestProveedor(unittest.TestCase):
    def test_normaliza_y_avisa_si_no_sale_en_el_documento(self):
        p, av = L.validar_proveedor({"nombre": "  Visiotech   SL ", "nif": "b-123.456.78", "email": "a@b.es", "telefono": "+34 600 11 22 33 ext"}, "Tarifa Visiotech SL B12345678")
        self.assertEqual((p["nombre"], p["nif"], p["telefono"]), ("Visiotech SL", "B12345678", "+34 600 11 22 33"))
        self.assertEqual(av, [])
        _, av = L.validar_proveedor({"nombre": "Otra SL", "nif": "B99999999"}, "Tarifa Visiotech")
        self.assertEqual(len(av), 2)
        for malo in ({"nombre": "x"}, {"nombre": "Ok SL", "nif": "12"}, {"nombre": "Ok SL", "email": "no-es-correo"}, "texto", None):
            with self.assertRaises(L.ErrorImportacion, msg=str(malo)):
                L.validar_proveedor(malo, "")


class ErpFalso:
    """Un ERP en memoria con lo justo: proveedores, listas, artículos y precios."""
    def __init__(self):
        self.suppliers, self.listas, self.items, self.precios, self.llamadas, self.falla_items = {}, set(), {}, {}, [], False

    async def listar(self, doctype, departamento, filtros=None, campos=None, limite=50):
        self.llamadas.append(("listar", doctype))
        f = filtros or []
        if doctype == "Supplier":
            campo, _, v = f[0]
            return [{"name": n} for n, d in self.suppliers.items() if d.get(campo) == v]
        if doctype == "Price List":
            return [{"name": f[0][2]}] if f[0][2] in self.listas else []
        if doctype == "Item":
            return [{"item_code": c} for c in f[0][2] if c in self.items]
        if doctype == "Item Price":
            lista, codigos = f[0][2], f[1][2]
            return [{"name": k, "item_code": v["item_code"], "price_list_rate": v["price_list_rate"]} for k, v in self.precios.items() if v["price_list"] == lista and v["item_code"] in codigos]
        raise AssertionError(doctype)

    async def crear_maestro(self, doctype, datos, departamento):
        self.llamadas.append(("crear", doctype))
        if doctype == "Supplier":
            self.suppliers[datos["supplier_name"]] = {**datos, "tax_id": datos.get("tax_id")}
            return {"name": datos["supplier_name"]}
        if doctype == "Price List":
            self.listas.add(datos["price_list_name"])
            return {"name": datos["price_list_name"]}
        raise AssertionError(doctype)

    async def insertar_varios(self, doctype, docs, departamento, tamano=100):
        self.llamadas.append(("insertar", doctype, len(docs)))
        if doctype == "Item":
            if self.falla_items:
                raise RuntimeError("ERPNext: Item Group Products no existe")
            for d in docs:
                self.items[d["item_code"]] = d
        else:
            for d in docs:
                self.precios[f"IP-{len(self.precios) + 1}"] = d
        return [f"n{i}" for i in range(len(docs))]

    async def modificar(self, doctype, nombre, datos, departamento):
        self.llamadas.append(("modificar", nombre))
        self.precios[nombre] = {**self.precios[nombre], **datos}
        return {}


@unittest.skipUnless(URL and hasattr(psycopg, "AsyncConnection"), "sin CEREBRO_TEST_PG")
class TestFlujo(unittest.TestCase):
    def setUp(self):
        self.schema = f"t_precios_{time.time_ns()}"
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"CREATE SCHEMA {self.schema}")
            c.execute(f"SET search_path = {self.schema}")
            t = ESQUEMA.read_text(encoding="utf-8")
            c.execute(t[t.index("-- Importaciones de listas de precios de proveedores"):])
        sep = "&" if "?" in URL else "?"
        self.erp = ErpFalso()
        self.carpeta = tempfile.TemporaryDirectory()
        ficha = {"id": DOC, "nombre": "tarifa.csv", "formato": "csv", "paginas": 1, "unidad": "página", "disponible": True}
        self.p = [mock.patch.object(L, "ajustes", SimpleNamespace(database_url=f"{URL}{sep}options=-csearch_path%3D{self.schema}", dir_config=self.carpeta.name)),
                  mock.patch.object(L.subidas, "paginas", mock.AsyncMock(return_value=(ficha, paginas_csv()))),
                  mock.patch.object(L, "erpnext", self.erp)]
        for p in self.p:
            p.start()

    def tearDown(self):
        for p in self.p:
            p.stop()
        self.carpeta.cleanup()
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"DROP SCHEMA {self.schema} CASCADE")

    def proponer(self, **kw):
        args = dict(proveedor={"nombre": "Visiotech SL", "nif": "B12345678"}, columnas={"referencia": "Ref", "descripcion": "Descripción", "precio": "PVP"}, agente="catalogo-proveedores", departamento="operaciones")
        args.update(kw)
        return ejecutar(L.proponer(DOC, **args))

    def test_proponer_guarda_sin_escribir_en_el_erp(self):
        r = self.proponer()
        self.assertEqual((r["lineas"], r["rechazadas"], r["articulos_nuevos"], r["articulos_existentes"], r["proveedor"]["existe_en_el_erp"]), (3, 3, 3, 0, False))
        self.assertEqual(r["lista"], "Compra Visiotech SL")
        self.assertEqual((r["precio_min"], r["precio_max"]), ("9.9000", "1410.0000"))
        self.assertEqual(len([a for a in r["avisos"] if "no aparece" in a]), 2)               # ni el nombre ni el NIF salen en el texto de este documento de prueba
        self.assertEqual({c[0] for c in self.erp.llamadas}, {"listar"})                 # solo lecturas
        self.assertEqual((self.erp.suppliers, self.erp.items, self.erp.precios), ({}, {}, {}))
        self.assertEqual(ejecutar(L.estado(r["importacion"]))["estado"], "propuesta")

    def test_la_vista_previa_dice_que_se_crea_y_que_ya_existe(self):
        self.erp.items["VISIOT-A-1"] = {"item_code": "VISIOT-A-1"}
        self.erp.suppliers["Visiotech SL"] = {"tax_id": "B12345678"}
        r = self.proponer()
        v = ejecutar(L.vista_aplicar(r["importacion"], "operaciones"))
        texto = "\n".join(f"{k}: {x}" for k, x in v["campos"])
        self.assertIn("YA EXISTE en el ERP", texto)
        self.assertIn("2 nuevos (se crean) · 1 que ya existen", texto)
        self.assertIn("A-2 · Grabador 16 canales · 1410.0000 (nuevo)", texto)
        self.assertIn("Compra Visiotech SL (EUR)", texto)
        self.assertIn(f"importación {r['importacion']}", v["titulo"])

    def test_aplicar_da_de_alta_todo_una_sola_vez(self):
        r = self.proponer(vigente_desde="2026-11-01")
        a = ejecutar(L.aplicar(r["importacion"], "operaciones"))
        self.assertEqual((a["estado"], a["proveedor_creado"], a["lista_creada"], a["articulos_creados"], a["precios_nuevos"]), ("aplicada", True, True, 3, 3))
        self.assertEqual(set(self.erp.items), {"VISIOT-A-1", "VISIOT-A-2", "VISIOT-A-4"})
        self.assertEqual(self.erp.items["VISIOT-A-2"]["supplier_items"], [{"supplier": "Visiotech SL", "supplier_part_no": "A-2"}])
        self.assertEqual(self.erp.suppliers["Visiotech SL"]["tax_id"], "B12345678")
        p = next(v for v in self.erp.precios.values() if v["item_code"] == "VISIOT-A-2")
        self.assertEqual((p["price_list_rate"], p["price_list"], p["buying"], p["supplier"], p["valid_from"]), (1410.0, "Compra Visiotech SL", 1, "Visiotech SL", "2026-11-01"))
        with self.assertRaisesRegex(L.ErrorImportacion, "«aplicada»"):                          # no se aplica dos veces
            ejecutar(L.aplicar(r["importacion"], "operaciones"))
        with self.assertRaisesRegex(L.ErrorImportacion, "«aplicada»"):
            ejecutar(L.vista_aplicar(r["importacion"], "operaciones"))

    def test_una_lista_nueva_del_mismo_proveedor_actualiza_precios_y_no_duplica(self):
        ejecutar(L.aplicar(self.proponer()["importacion"], "operaciones"))
        antes = len(self.erp.precios)
        nueva = CSV.replace(b"123,50", b"119,00")
        with mock.patch.object(L.subidas, "paginas", mock.AsyncMock(return_value=({"id": DOC, "nombre": "t2.csv", "formato": "csv", "paginas": 1}, paginas_csv(nueva)))):
            r2 = self.proponer()
            self.assertEqual((r2["articulos_nuevos"], r2["articulos_existentes"], r2["proveedor"]["existe_en_el_erp"]), (0, 3, True))
            a = ejecutar(L.aplicar(r2["importacion"], "operaciones"))
        self.assertEqual((a["proveedor_creado"], a["lista_creada"], a["articulos_creados"], a["precios_nuevos"], a["precios_actualizados"], a["precios_sin_cambios"]), (False, False, 0, 0, 1, 2))
        self.assertEqual(len(self.erp.precios), antes)
        self.assertEqual(next(v for v in self.erp.precios.values() if v["item_code"] == "VISIOT-A-1")["price_list_rate"], 119.0)

    def test_si_el_erp_falla_se_guarda_lo_hecho_y_se_puede_repetir_sin_duplicar(self):
        r = self.proponer()
        self.erp.falla_items = True
        with self.assertRaisesRegex(L.ErrorImportacion, "Item Group"):
            ejecutar(L.aplicar(r["importacion"], "operaciones"))
        self.assertEqual(ejecutar(L.estado(r["importacion"]))["estado"], "error")
        self.assertEqual(len(self.erp.suppliers), 1)
        self.erp.falla_items = False
        a = ejecutar(L.aplicar(r["importacion"], "operaciones"))
        self.assertEqual((a["estado"], a["proveedor_creado"], a["lista_creada"], a["articulos_creados"], a["precios_nuevos"]), ("aplicada", False, False, 3, 3))
        self.assertEqual(len(self.erp.suppliers), 1)
        self.assertEqual(len(self.erp.precios), 3)

    def test_sin_erp_se_propone_igual_y_avisa(self):
        async def roto(*a, **k):
            raise ConnectionError("ERP caído")
        with mock.patch.object(self.erp, "listar", roto):
            r = self.proponer()
        self.assertIsNone(r["articulos_nuevos"])
        self.assertTrue(any("No se ha podido consultar el ERP" in a for a in r["avisos"]))
        v = ejecutar(L.vista_aplicar(r["importacion"], "operaciones"))
        self.assertIn("no se ha podido comprobar", "\n".join(f"{k}: {x}" for k, x in v["campos"]))

    def test_validaciones_de_la_peticion(self):
        for kw in ({"moneda": "XXX"}, {"iva_incluido_pct": 0}, {"iva_incluido_pct": True}, {"vigente_desde": "1/11/2026"}, {"paginas": ["1"]}, {"proveedor": {"nombre": ""}}):
            with self.assertRaises(L.ErrorImportacion, msg=str(kw)):
                self.proponer(**kw)
        with self.assertRaises(L.NoExiste):
            ejecutar(L.estado(999999))
        with self.assertRaises(L.ErrorImportacion):
            ejecutar(L.estado("1"))
        t = ejecutar(L.tabla(DOC, 1, 5))
        self.assertEqual((t["filas"][0]["celdas"], t["filas"][1]["celdas"], t["formato"]), (["Ref", "Descripción", "PVP", "Ud"], ["CÁMARAS DOMO"], "csv"))
        with self.assertRaises(L.ErrorImportacion):
            ejecutar(L.tabla(DOC, 9))

    def test_descartar(self):
        r = self.proponer()
        self.assertEqual(ejecutar(L.descartar(r["importacion"]))["estado"], "descartada")
        with self.assertRaises(L.ErrorImportacion):
            ejecutar(L.aplicar(r["importacion"], "operaciones"))
        with self.assertRaises(L.ErrorImportacion):
            ejecutar(L.descartar(r["importacion"]))


class TestHerramienta(unittest.TestCase):
    def setUp(self):
        try:
            import cerebro.herramientas  # noqa: F401
            from cerebro.herramientas import base
            from cerebro.registro import registro
            from cerebro.politicas import nivel_para
        except ImportError as e:      # pragma: no cover
            self.skipTest(str(e))
        self.base, self.registro, self.nivel = base, registro(), nivel_para

    def test_operaciones_y_quien_la_tiene(self):
        h = self.base._REGISTRO["listas_precios"]
        self.assertEqual(set(h.operaciones), {"tabla", "proponer", "estado", "aplicar"})
        self.assertEqual(h.externas, frozenset({"aplicar"}))
        self.assertEqual(set(h.vistas), {"aplicar"})
        self.assertEqual({a for a, f in self.registro.fichas.items() if "listas_precios" in f.herramientas}, {"catalogo-proveedores"})

    def test_aplicar_exige_la_aprobacion_de_una_persona(self):
        ficha = self.registro.fichas["catalogo-proveedores"]
        d = self.nivel(ficha, "cargar lista", externa=self.base.es_externa("listas_precios", "aplicar"), herramienta="listas_precios", operacion="aplicar")
        self.assertTrue(d.requiere)
        self.assertEqual(d.clase, "supervisada")
        with self.assertRaises(self.base.OperacionRequiereAprobacion):
            ejecutar(self.base.usar(ficha, "listas_precios", "aplicar", importacion=1))
        # proponer y leer la tabla no escriben en el ERP: no piden aprobación
        self.assertFalse(self.nivel(ficha, "proponer", externa=False, herramienta="listas_precios", operacion="proponer").requiere)

    def test_el_agente_y_el_departamento_los_pone_el_sistema(self):
        from cerebro.grafo import nodos
        ficha = self.registro.fichas["catalogo-proveedores"]
        args = nodos.inyectar(ficha, {}, "listas_precios", {"importacion": 3, "agente": "otro", "departamento": "finanzas"})
        self.assertEqual(args, {"importacion": 3, "departamento": ficha.departamento})


if __name__ == "__main__":
    unittest.main()
