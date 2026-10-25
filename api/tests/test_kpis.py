"""KPI del panel de cada agente: cálculo, tolerancia a fallos del ERP y coherencia de config/kpis.yaml con la política de acceso."""
import asyncio
import unittest
from datetime import date
from pathlib import Path

import _sin_servicios  # noqa: F401
import yaml

from cerebro import kpis
from cerebro.registro import cargar

RAIZ = Path(__file__).resolve().parents[2]
CFG = yaml.safe_load((RAIZ / "config" / "kpis.yaml").read_text(encoding="utf-8"))
POL = yaml.safe_load((RAIZ / "config" / "erp_acceso.yaml").read_text(encoding="utf-8"))["departamentos"]
REG = cargar()
HOY = date(2026, 10, 25)


class FuenteFalsa:
    """Datos de ejemplo: 5 peticiones, 8 usos y 2 errores; 3 propuestas (2 aprobadas, 1 pendiente). El ERP responde 100 salvo lo que se marque como roto."""
    def __init__(self, rotos=()):
        self.rotos, self.consultas_erp, self.n_uso, self.n_apr = set(rotos), [], 0, 0

    async def uso(self, agente, desde, hasta):
        self.n_uso += 1
        if self.n_uso % 2 == 0:                               # el cálculo pide primero el periodo actual y después el anterior
            return {"peticion": 4, "uso:correo.leer_bandeja": 2}
        return {"peticion": 5, "uso:correo.leer_bandeja": 3, "uso:correo.leer_adjunto": 2, "uso:erpnext.listar": 3, "error:erpnext.leer": 2,
                "propuesta:correo.responder": 2}

    async def uso_diario(self, agente, desde, hasta):
        return [(date(2026, 10, 24), "peticion", 3), (date(2026, 10, 25), "peticion", 2), (date(2026, 10, 25), "uso:correo.leer_bandeja", 3),
                (date(2026, 10, 25), "error:erpnext.leer", 2), (date(2020, 1, 1), "peticion", 99)]

    async def aprobaciones(self, agente, desde, hasta):
        self.n_apr += 1
        if self.n_apr % 2 == 0:
            return {"total": 1, "aprobadas": 1, "rechazadas": 0, "pendientes": 0, "segundos_medios": 60.0}
        return {"total": 3, "aprobadas": 2, "rechazadas": 0, "pendientes": 1, "segundos_medios": 600.0}

    async def acciones(self, agente, desde, hasta):
        return {"ok": 2, "error": 1}

    async def erp(self, departamento, k, desde, hasta):
        self.consultas_erp.append((departamento, k["doctype"], k.get("periodo") and (desde, hasta)))
        if k["doctype"] in self.rotos:
            raise PermissionError("sin permiso")
        return 100.0


def calcular(agente, fuente=None, dias=30):
    return asyncio.run(kpis.calcular(REG.fichas[agente], CFG, dias, fuente or FuenteFalsa(), HOY))


class TestCalculo(unittest.TestCase):
    def test_rendimiento(self):
        r = {k["id"]: k for k in calcular("cobros")["rendimiento"]}
        self.assertEqual(r["peticiones"]["valor"], 5)
        self.assertEqual(r["peticiones"]["delta"], 25)              # de 4 a 5
        self.assertEqual((r["usos"]["valor"], r["exito"]["valor"]), (8, 80))
        self.assertEqual((r["propuestas"]["valor"], r["aprobadas"]["valor"], r["pendientes"]["valor"]), (3, 2, 1))
        self.assertEqual((r["tasa"]["valor"], r["decision"]["valor"]), (100, 10))
        self.assertEqual((r["ejecutadas"]["valor"], r["ejecutadas"]["errores"]), (2, 1))

    def test_sin_actividad_no_inventa_cifras(self):
        class Vacia(FuenteFalsa):
            async def uso(self, *a): return {}
            async def uso_diario(self, *a): return []
            async def aprobaciones(self, *a): return {"total": 0, "aprobadas": 0, "rechazadas": 0, "pendientes": 0, "segundos_medios": None}
            async def acciones(self, *a): return {"ok": 0, "error": 0}
        r = {k["id"]: k for k in calcular("cobros", Vacia())["rendimiento"]}
        self.assertEqual(r["peticiones"]["valor"], 0)
        for k in ("exito", "tasa", "decision"):
            self.assertIsNone(r[k]["valor"], k)
        self.assertIsNone(r["peticiones"]["delta"])

    def test_kpi_de_cargo_del_erp_y_de_uso(self):
        d = calcular("cobros")
        nombres = [k["nombre"] for k in d["cargo"]]
        self.assertIn("Pendiente de cobro", nombres)
        self.assertIn("Correos leídos", nombres)                    # de la herramienta correo de su ficha
        uso = next(k for k in d["cargo"] if k["nombre"] == "Correos leídos")
        self.assertEqual((uso["valor"], uso["fuente"]), (3, "uso"))
        erp = next(k for k in d["cargo"] if k["nombre"] == "Pendiente de cobro")
        self.assertEqual((erp["valor"], erp["fuente"], erp["estado"]), (100.0, "erp", "ok"))

    def test_la_ventana_es_la_elegida_y_compara_con_la_anterior(self):
        f = FuenteFalsa()
        calcular("control-gastos", f, 7)
        con_periodo = [c for c in f.consultas_erp if c[2]]
        self.assertTrue(con_periodo)
        desde, hasta = con_periodo[0][2]
        self.assertEqual((desde, hasta), ("2026-10-19", "2026-10-26"))
        self.assertIn(("2026-10-12", "2026-10-19"), [c[2] for c in con_periodo])      # y el periodo anterior
        with self.assertRaises(ValueError):
            kpis.ventana(45)

    def test_un_kpi_que_falla_no_rompe_el_panel(self):
        d = calcular("cobros", FuenteFalsa(rotos={"Sales Invoice"}))
        rotos = [k for k in d["cargo"] if k["estado"] == "no_disponible"]
        self.assertTrue(rotos and all(k["valor"] is None and k["motivo"] for k in rotos))
        self.assertTrue(any(k["estado"] == "ok" for k in d["cargo"]), "los de uso siguen funcionando")
        self.assertEqual(d["rendimiento"][0]["valor"], 5)

    def test_series_y_herramientas(self):
        d = calcular("cobros", dias=7)
        self.assertEqual(len(d["serie"]), 7)
        self.assertEqual([s["dia"] for s in d["serie"]][-1], "2026-10-25")
        self.assertEqual([(s["peticiones"], s["usos"]) for s in d["serie"]][-2:], [(3, 0), (2, 3)])
        self.assertNotIn("2020-01-01", [s["dia"] for s in d["serie"]], "lo de fuera de la ventana no cuenta")
        h = {x["herramienta"]: x for x in d["herramientas"]}
        self.assertEqual((h["erpnext"]["usos"], h["erpnext"]["errores"]), (0, 2))
        self.assertEqual(h["correo"]["usos"], 3)

    def test_cobros_incluye_recuperado_y_retraso_medio(self):
        nombres = [k["nombre"] for k in calcular("cobros")["cargo"]]
        self.assertEqual(nombres[:2], ["Cobros recuperados", "Media de retraso en facturas vencidas"])

    def test_comodines_de_uso(self):
        self.assertEqual(kpis._suma({"uso:calendario.huecos": 2, "uso:calendario.proponer_cita": 3, "uso:otra.x": 9}, ["uso:calendario.*"]), 5)
        self.assertEqual(kpis._suma({"uso:a.b": 1}, ["uso:a.c"]), 0)

    def test_motivos_comprensibles(self):
        class R(Exception):
            response = type("x", (), {"status_code": 404})()
        self.assertIn("no existe", kpis.motivo(R()))
        R.response = type("x", (), {"status_code": 417})()
        self.assertIn("no ha podido calcular", kpis.motivo(R()))
        self.assertIn("No se ha podido", kpis.motivo(RuntimeError("x")))


class TestDashboardDeDepartamento(unittest.TestCase):
    def dep(self, dep="finanzas", fuente=None, dias=30):
        return asyncio.run(kpis.calcular_departamento(dep, REG, CFG, dias, fuente or FuenteFalsa(), HOY))

    def test_estructura_grupos_y_equipo(self):
        d = self.dep()
        self.assertEqual(d["departamento"]["id"], "finanzas")
        self.assertEqual([g["nombre"] for g in d["grupos"]], ["Cartera de clientes", "Proveedores y pagos", "Actividad del periodo"])
        self.assertEqual(sum(len(g["kpis"]) for g in d["grupos"]), len(CFG["paneles_departamento"]["finanzas"]))
        self.assertEqual(len(d["equipo"]), len(REG.del_departamento("finanzas")))
        self.assertTrue(d["equipo"][0]["director"], "el director va el primero")
        self.assertTrue(all(k["grupo"] for g in d["grupos"] for k in g["kpis"]))

    def test_suma_la_actividad_de_todos_sus_agentes(self):
        n = len(REG.del_departamento("finanzas"))

        class F(FuenteFalsa):                                   # cada agente: 5 peticiones y 3 propuestas en el periodo actual
            async def uso(self, agente, desde, hasta):
                self.n_uso += 1
                return {"peticion": 5, "uso:erpnext.listar": 4, "error:erpnext.leer": 1} if self.n_uso % 2 else {"peticion": 1}
        d = self.dep(fuente=F())
        r = {k["id"]: k for k in d["rendimiento"]}
        self.assertEqual(r["peticiones"]["valor"], 5 * n)
        self.assertEqual((r["usos"]["valor"], r["exito"]["valor"]), (4 * n, 80))
        self.assertEqual((r["propuestas"]["valor"], r["pendientes"]["valor"]), (3 * n, 1 * n))
        self.assertEqual(r["decision"]["valor"], 10)

    def test_un_kpi_roto_no_rompe_el_dashboard(self):
        d = self.dep(fuente=FuenteFalsa(rotos={"Sales Invoice"}))
        kpis_ = [k for g in d["grupos"] for k in g["kpis"]]
        self.assertTrue(any(k["estado"] == "no_disponible" for k in kpis_))
        self.assertTrue(any(k["estado"] == "ok" for k in kpis_))

    def test_todos_los_departamentos_se_calculan(self):
        for dep in REG.departamentos:
            with self.subTest(dep):
                d = self.dep(dep)
                self.assertTrue(d["grupos"] and d["equipo"])

    def test_departamento_de_solo_uso_cuenta_las_consultas(self):
        class F(FuenteFalsa):
            async def uso(self, agente, desde, hasta):
                return {"uso:conocimiento.buscar": 2, "peticion": 1}
        d = self.dep("conocimiento", F())
        k = d["grupos"][0]["kpis"][0]
        self.assertEqual((k["fuente"], k["valor"]), ("uso", 2 * len(REG.del_departamento("conocimiento"))))


class TestConfiguracion(unittest.TestCase):
    def test_todo_agente_tiene_kpis_de_cargo(self):
        sin = [f.id for f in REG.fichas.values() if not kpis.definiciones(f, CFG)]
        self.assertEqual(sin, [], f"agentes sin ningún KPI de cargo: {sin}")

    def test_los_agentes_y_departamentos_de_la_config_existen(self):
        self.assertEqual(sorted(set(CFG["agentes"]) - set(REG.fichas)), [])
        self.assertEqual(sorted(set(CFG["departamentos"]) - set(REG.departamentos)), [])
        self.assertEqual(sorted(set(REG.departamentos) - set(CFG["departamentos"])), [], "falta la lista de algún departamento (puede ser [])")

    def test_los_kpi_del_erp_solo_usan_documentos_que_la_politica_permite(self):
        errores = []
        for f in REG.fichas.values():
            for k in kpis.definiciones(f, CFG):
                if k["tipo"] == "erp" and k["doctype"] not in (POL.get(f.departamento) or {}).get("leer", []):
                    errores.append(f"{f.id} ({f.departamento}): {k['doctype']}")
        self.assertEqual(errores, [], "KPI cuyo documento el departamento no puede leer según erp_acceso.yaml")

    def test_todo_departamento_tiene_su_dashboard_y_solo_con_documentos_permitidos(self):
        self.assertEqual(sorted(set(REG.departamentos) - set(CFG["paneles_departamento"])), [])
        errores = []
        for dep, lista in CFG["paneles_departamento"].items():
            self.assertTrue(lista, f"el dashboard de {dep} está vacío")
            for k in lista:
                self.assertTrue(k.get("grupo"), f"{dep}: «{k['nombre']}» sin grupo")
                if k["tipo"] == "erp" and k["doctype"] not in (POL.get(dep) or {}).get("leer", []):
                    errores.append(f"{dep}: {k['doctype']}")
        self.assertEqual(errores, [], "KPI de departamento con documentos que el departamento no puede leer")

    def test_la_mayoria_de_los_agentes_tienen_kpi_propios(self):
        propios = [f.id for f in REG.fichas.values() if f.id in CFG["agentes"]]
        self.assertGreaterEqual(len(propios), 60, f"solo {len(propios)} agentes tienen KPI propios")

    def test_definiciones_bien_formadas(self):
        todos = (list(CFG["agentes"].values()) + list(CFG["departamentos"].values()) + list(CFG["herramientas"].values())
                 + list(CFG["paneles_departamento"].values()))
        for lista in todos:
            for k in lista:
                self.assertTrue(k.get("nombre"))
                tipo = k.get("tipo", "uso" if "claves" in k else "erp")
                if tipo == "erp":
                    self.assertIn(k.get("agregado", "contar"), ("contar", "sumar", "retraso_medio"))
                    if k.get("agregado") in ("sumar", "retraso_medio"):
                        self.assertTrue(k.get("campo"), k["nombre"])
                else:
                    self.assertTrue(k["claves"] and all(c.startswith(("uso:", "propuesta:", "error:")) for c in k["claves"]), k["nombre"])

    def test_las_herramientas_de_uso_existen(self):
        try:
            from cerebro import herramientas  # noqa: F401
            from cerebro.herramientas import base
        except ImportError:
            self.skipTest("requiere las dependencias del contenedor")
        for lista in CFG["herramientas"].values():
            for k in lista:
                for c in k["claves"]:
                    herr, _, op = c.split(":", 1)[1].partition(".")
                    self.assertIn(herr, base._REGISTRO, c)
                    if op != "*":
                        self.assertIn(op, base._REGISTRO[herr].operaciones, c)


try:
    import httpx
    HAY_HTTPX = hasattr(httpx, "MockTransport")
except ImportError:
    HAY_HTTPX = False


@unittest.skipUnless(HAY_HTTPX, "requiere httpx")
class TestMetricasDelErp(unittest.TestCase):
    """Las cifras que se piden al ERP: retraso medio, suma y recuento, con la clave y la política del departamento."""

    def lanzar(self, respuesta, **k):
        import os
        from datetime import timedelta
        from types import SimpleNamespace
        from unittest import mock
        from cerebro.herramientas import erpnext as E
        E._politica.cache_clear()
        E._METRICAS.clear()
        peticiones = []

        def manejar(req):
            peticiones.append(req)
            return httpx.Response(200, json=respuesta(date.today(), timedelta))
        real = httpx.AsyncClient
        with mock.patch.dict(os.environ, {"ERPNEXT_TOKEN_FINANZAS": "k:s"}), \
                mock.patch.object(E.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(manejar), **kw)), \
                mock.patch.object(E, "ajustes", SimpleNamespace(erpnext_url="http://erp", dir_config=E.ajustes.dir_config)):
            valor = asyncio.run(E.metrica("finanzas", "Sales Invoice", [["docstatus", "=", 1]], **k))
        return valor, peticiones

    def test_retraso_medio_en_dias(self):
        v, p = self.lanzar(lambda hoy, td: {"data": [{"due_date": (hoy - td(days=10)).isoformat()}, {"due_date": (hoy - td(days=20)).isoformat()}, {"due_date": None}]},
                           agregado="retraso_medio", campo="due_date")
        self.assertEqual(v, 15.0)
        self.assertIn("due_date", p[0].url.params["fields"])

    def test_retraso_medio_sin_facturas_es_cero(self):
        self.assertEqual(self.lanzar(lambda *a: {"data": []}, agregado="retraso_medio", campo="due_date")[0], 0.0)

    def test_suma_y_recuento(self):
        v, p = self.lanzar(lambda *a: {"data": [{"v": 1210.5}]}, agregado="sumar", campo="outstanding_amount")
        self.assertEqual(v, 1210.5)
        self.assertIn('"SUM"', p[0].url.params["fields"])
        self.assertEqual(self.lanzar(lambda *a: {"message": 7}, agregado="contar")[0], 7.0)

    def test_la_politica_y_los_campos_se_respetan(self):
        with self.assertRaises(PermissionError):
            self.lanzar(lambda *a: {}, agregado="sumar", campo="x; drop table")
        with self.assertRaises(PermissionError):
            from cerebro.herramientas import erpnext as E
            E._politica.cache_clear()
            asyncio.run(E.metrica("comercial", "Bank Account"))


if __name__ == "__main__":
    unittest.main()
