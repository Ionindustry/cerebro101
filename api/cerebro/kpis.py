"""KPI del panel de cada agente: rendimiento (contadores del propio Cerebro) y KPI del cargo (ERP/CRM y uso de sus herramientas).

El cálculo no sabe de bases de datos ni del ERP: recibe una «fuente» con cuatro consultas, para poder probarlo. La definición de los KPI está en config/kpis.yaml.
Todo es de solo lectura.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

import yaml

log = logging.getLogger("cerebro.kpis")
VENTANAS = (7, 14, 30, 90)


@lru_cache(maxsize=4)
def cargar_config(dir_config: str) -> dict:
    ruta = Path(dir_config) / "kpis.yaml"
    return (yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}) if ruta.exists() else {}


def definiciones(ficha, cfg: dict) -> list[dict]:
    """KPI del cargo de un agente: los suyos (o, si no tiene, los de su departamento) y los de uso de las herramientas de su ficha. Sin repetidos."""
    base = (cfg.get("agentes") or {}).get(ficha.id)
    if base is None:
        base = (cfg.get("departamentos") or {}).get(ficha.departamento) or []
    lista = [{**k, "tipo": k.get("tipo", "erp")} for k in base]
    nombres = {k["nombre"] for k in lista}
    for h in ficha.herramientas:
        for k in (cfg.get("herramientas") or {}).get(h, []):
            if k["nombre"] not in nombres:
                lista.append({**k, "tipo": "uso"})
                nombres.add(k["nombre"])
    return lista


def ventana(dias: int, hoy: date | None = None) -> dict:
    """Periodo actual y el anterior de igual duración. `hasta` es exclusivo (se compara con «<»)."""
    if dias not in VENTANAS:
        raise ValueError(f"El periodo debe ser uno de {', '.join(map(str, VENTANAS))} días")
    hoy = hoy or date.today()
    hasta = hoy + timedelta(days=1)
    desde = hasta - timedelta(days=dias)
    return {"dias": dias, "desde": desde, "hasta": hasta, "desde_ant": desde - timedelta(days=dias), "hasta_ant": desde}


def _suma(uso: dict[str, int], patrones: list[str]) -> int:
    total = 0
    for clave, n in uso.items():
        for p in patrones:
            if clave == p or (p.endswith("*") and clave.startswith(p[:-1])):
                total += n
                break
    return total


def _delta(actual, anterior):
    if anterior in (None, 0) or actual is None:
        return None
    return round((actual - anterior) / anterior * 100)


def _item(id_, nombre, valor, unidad, ayuda="", anterior=None, **extra):
    return {"id": id_, "nombre": nombre, "valor": valor, "unidad": unidad, "ayuda": ayuda, "anterior": anterior, "delta": _delta(valor, anterior), **extra}


async def calcular(ficha, cfg: dict, dias: int, fuente, hoy: date | None = None) -> dict:
    v = ventana(dias, hoy)
    desde, hasta, d0, h0 = (x.isoformat() for x in (v["desde"], v["hasta"], v["desde_ant"], v["hasta_ant"]))
    uso = await fuente.uso(ficha.id, desde, hasta)
    uso_ant = await fuente.uso(ficha.id, d0, h0)
    apr = await fuente.aprobaciones(ficha.id, desde, hasta)
    apr_ant = await fuente.aprobaciones(ficha.id, d0, h0)
    acc = await fuente.acciones(ficha.id, desde, hasta)

    usos, errores = _suma(uso, ["uso:*"]), _suma(uso, ["error:*"])
    usos_ant, errores_ant = _suma(uso_ant, ["uso:*"]), _suma(uso_ant, ["error:*"])
    exito = round(usos / (usos + errores) * 100) if usos + errores else None
    exito_ant = round(usos_ant / (usos_ant + errores_ant) * 100) if usos_ant + errores_ant else None
    resueltas = apr["aprobadas"] + apr["rechazadas"]
    tasa = round(apr["aprobadas"] / resueltas * 100) if resueltas else None
    seg = apr.get("segundos_medios")

    rendimiento = [
        _item("peticiones", "Peticiones atendidas", uso.get("peticion", 0), "peticiones", "veces que ha trabajado en algo", uso_ant.get("peticion", 0)),
        _item("usos", "Usos de herramientas", usos, "usos", "consultas y operaciones que ha hecho", usos_ant),
        _item("exito", "Éxito de sus herramientas", exito, "%", "usos sin error sobre el total", exito_ant),
        _item("propuestas", "Propuestas a aprobación", apr["total"], "propuestas", "lo que ha pedido firmar", apr_ant["total"]),
        _item("aprobadas", "Aprobadas", apr["aprobadas"], "propuestas", "", apr_ant["aprobadas"]),
        _item("rechazadas", "Rechazadas", apr["rechazadas"], "propuestas", "", apr_ant["rechazadas"]),
        _item("tasa", "Tasa de aprobación", tasa, "%", "de lo que se ha resuelto, cuánto se ha aprobado"),
        _item("pendientes", "Esperando tu firma", apr["pendientes"], "propuestas", "ahora mismo"),
        _item("decision", "Tiempo medio hasta la decisión", None if seg is None else round(seg / 60), "min", "desde que lo propone hasta que se resuelve"),
        _item("ejecutadas", "Acciones ejecutadas", acc["ok"], "acciones", "aprobadas y llevadas a cabo", None, errores=acc["error"]),
    ]

    cargo = [await _evaluar_kpi(f"k{i}", k, ficha.departamento, ficha.id, uso, uso_ant, fuente, desde, hasta, d0, h0)
             for i, k in enumerate(definiciones(ficha, cfg))]

    diario = await fuente.uso_diario(ficha.id, desde, hasta)
    dias_lista = [(v["desde"] + timedelta(days=i)).isoformat() for i in range(dias)]
    por_dia = {d: {"peticiones": 0, "usos": 0} for d in dias_lista}
    herr: dict[str, dict] = {}
    for dia, clave, n in diario:
        d = dia.isoformat() if hasattr(dia, "isoformat") else str(dia)
        if d in por_dia:
            if clave == "peticion":
                por_dia[d]["peticiones"] += n
            elif clave.startswith("uso:"):
                por_dia[d]["usos"] += n
        for pref, campo in (("uso:", "usos"), ("error:", "errores")):
            if clave.startswith(pref):
                h = clave[len(pref):].split(".")[0]
                herr.setdefault(h, {"herramienta": h, "usos": 0, "errores": 0})[campo] += n
    return {
        "agente": {"id": ficha.id, "nombre": ficha.nombre, "subarea": ficha.subarea, "departamento": ficha.departamento, "director": ficha.director,
                   "tareas": ficha.tareas, "herramientas": list(ficha.herramientas), "aprobacion": ficha.aprobacion},
        "periodo": {"dias": dias, "desde": desde, "hasta": (v["hasta"] - timedelta(days=1)).isoformat()},
        "rendimiento": rendimiento, "cargo": cargo,
        "serie": [{"dia": d, **por_dia[d]} for d in dias_lista],
        "herramientas": sorted(herr.values(), key=lambda x: -(x["usos"] + x["errores"])),
        "aprobaciones": {"aprobadas": apr["aprobadas"], "rechazadas": apr["rechazadas"], "pendientes": apr["pendientes"]},
    }


async def _evaluar_kpi(id_: str, k: dict, departamento: str, quien: str, uso: dict, uso_ant: dict, fuente, desde: str, hasta: str, d0: str, h0: str) -> dict:
    """Valor de un KPI del cargo (con el del periodo anterior si tiene `periodo`). Si falla, devuelve «no disponible» con el motivo."""
    base = {"nombre": k["nombre"], "unidad": k.get("unidad", ""), "ayuda": k.get("ayuda", "")}
    if k.get("grupo"):
        base["grupo"] = k["grupo"]
    if k["tipo"] == "uso":
        valor, ant = _suma(uso, k["claves"]), _suma(uso_ant, k["claves"])
        return {**_item(id_, base["nombre"], valor, base["unidad"], base["ayuda"], ant), **{x: base[x] for x in ("grupo",) if x in base}, "fuente": "uso", "estado": "ok"}
    try:
        valor = await fuente.erp(departamento, k, desde, hasta)
        ant = await fuente.erp(departamento, k, d0, h0) if k.get("periodo") else None
        return {**_item(id_, base["nombre"], valor, base["unidad"], base["ayuda"], ant), **{x: base[x] for x in ("grupo",) if x in base}, "fuente": "erp", "estado": "ok"}
    except Exception as e:  # noqa: BLE001 — un KPI que falla no tumba el panel: se explica
        log.info("KPI «%s» de %s no disponible: %s", k["nombre"], quien, e)
        return {**_item(id_, base["nombre"], None, base["unidad"], base["ayuda"]), **{x: base[x] for x in ("grupo",) if x in base}, "fuente": "erp", "estado": "no_disponible", "motivo": motivo(e)}


async def calcular_departamento(dep_id: str, reg, cfg: dict, dias: int, fuente, hoy: date | None = None) -> dict:
    """Dashboard de un departamento: sus KPI específicos del ERP/CRM (agrupados), el resumen de actividad de todos sus agentes y el reparto por agente."""
    dep = reg.departamentos[dep_id]
    fichas = reg.del_departamento(dep_id)
    v = ventana(dias, hoy)
    desde, hasta, d0, h0 = (x.isoformat() for x in (v["desde"], v["hasta"], v["desde_ant"], v["hasta_ant"]))
    uso_dep: dict[str, int] = {}
    uso_dep_ant: dict[str, int] = {}
    equipo, tot = [], {"aprobadas": 0, "rechazadas": 0, "pendientes": 0, "total": 0, "seg": 0.0, "n_seg": 0}
    tot_ant = {"total": 0, "aprobadas": 0, "rechazadas": 0}
    por_dia: dict[str, dict] = {(v["desde"] + timedelta(days=i)).isoformat(): {"peticiones": 0, "usos": 0} for i in range(dias)}
    herr: dict[str, dict] = {}
    for f in fichas:
        u, ua = await fuente.uso(f.id, desde, hasta), await fuente.uso(f.id, d0, h0)
        ap, apa = await fuente.aprobaciones(f.id, desde, hasta), await fuente.aprobaciones(f.id, d0, h0)
        for k, n in u.items():
            uso_dep[k] = uso_dep.get(k, 0) + n
        for k, n in ua.items():
            uso_dep_ant[k] = uso_dep_ant.get(k, 0) + n
        for campo in ("aprobadas", "rechazadas", "pendientes", "total"):
            tot[campo] += ap[campo]
        for campo in ("aprobadas", "rechazadas", "total"):
            tot_ant[campo] += apa[campo]
        if ap.get("segundos_medios") is not None and ap["aprobadas"] + ap["rechazadas"]:
            tot["seg"] += ap["segundos_medios"] * (ap["aprobadas"] + ap["rechazadas"])
            tot["n_seg"] += ap["aprobadas"] + ap["rechazadas"]
        usos, errores = _suma(u, ["uso:*"]), _suma(u, ["error:*"])
        equipo.append({"id": f.id, "nombre": f.nombre, "subarea": f.subarea, "director": f.director, "peticiones": u.get("peticion", 0), "usos": usos,
                       "exito": round(usos / (usos + errores) * 100) if usos + errores else None, "propuestas": ap["total"], "pendientes": ap["pendientes"]})
        for dia, clave, n in await fuente.uso_diario(f.id, desde, hasta):
            d = dia.isoformat() if hasattr(dia, "isoformat") else str(dia)
            if d in por_dia:
                if clave == "peticion":
                    por_dia[d]["peticiones"] += n
                elif clave.startswith("uso:"):
                    por_dia[d]["usos"] += n
            for pref, campo in (("uso:", "usos"), ("error:", "errores")):
                if clave.startswith(pref):
                    h = clave[len(pref):].split(".")[0]
                    herr.setdefault(h, {"herramienta": h, "usos": 0, "errores": 0})[campo] += n
    usos, errores = _suma(uso_dep, ["uso:*"]), _suma(uso_dep_ant, ["uso:*"])
    errs = _suma(uso_dep, ["error:*"])
    res = tot["aprobadas"] + tot["rechazadas"]
    rendimiento = [
        _item("peticiones", "Peticiones atendidas", uso_dep.get("peticion", 0), "peticiones", "entre todos los agentes del departamento", uso_dep_ant.get("peticion", 0)),
        _item("usos", "Usos de herramientas", usos, "usos", "", errores),
        _item("exito", "Éxito de sus herramientas", round(usos / (usos + errs) * 100) if usos + errs else None, "%", "usos sin error sobre el total"),
        _item("propuestas", "Propuestas a aprobación", tot["total"], "propuestas", "", tot_ant["total"]),
        _item("aprobadas", "Aprobadas", tot["aprobadas"], "propuestas", "", tot_ant["aprobadas"]),
        _item("rechazadas", "Rechazadas", tot["rechazadas"], "propuestas", "", tot_ant["rechazadas"]),
        _item("tasa", "Tasa de aprobación", round(tot["aprobadas"] / res * 100) if res else None, "%", ""),
        _item("pendientes", "Esperando tu firma", tot["pendientes"], "propuestas", "ahora mismo"),
        _item("decision", "Tiempo medio hasta la decisión", round(tot["seg"] / tot["n_seg"] / 60) if tot["n_seg"] else None, "min", ""),
    ]
    kpis_dep = (cfg.get("paneles_departamento") or {}).get(dep_id) or []
    cargo = [await _evaluar_kpi(f"d{i}", k, dep_id, dep_id, uso_dep, uso_dep_ant, fuente, desde, hasta, d0, h0) for i, k in enumerate(kpis_dep)]
    grupos: list[str] = []
    for k in cargo:
        k.setdefault("grupo", "Indicadores")
        if k["grupo"] not in grupos:
            grupos.append(k["grupo"])
    return {
        "departamento": {"id": dep_id, "nombre": dep["nombre"], "agentes": len(fichas), "director": dep["director"]},
        "periodo": {"dias": dias, "desde": desde, "hasta": (v["hasta"] - timedelta(days=1)).isoformat()},
        "grupos": [{"nombre": g, "kpis": [k for k in cargo if k["grupo"] == g]} for g in grupos],
        "rendimiento": rendimiento,
        "serie": [{"dia": d, **por_dia[d]} for d in por_dia],
        "herramientas": sorted(herr.values(), key=lambda x: -(x["usos"] + x["errores"])),
        "aprobaciones": {"aprobadas": tot["aprobadas"], "rechazadas": tot["rechazadas"], "pendientes": tot["pendientes"]},
        "equipo": sorted(equipo, key=lambda e: (not e["director"], -e["peticiones"], e["nombre"])),
    }


def motivo(e: Exception) -> str:
    if isinstance(e, PermissionError):
        return str(e)[:220]
    estado = getattr(getattr(e, "response", None), "status_code", None)
    if estado == 404:
        return "Este documento no existe en el ERP instalado (¿falta el módulo?)"
    if estado in (417, 500):
        return "El ERP no ha podido calcular este indicador (puede que el documento o un campo no existan en esta versión)"
    if estado in (401, 403):
        return "El usuario técnico del departamento no tiene permiso para leerlo en el ERP"
    return "No se ha podido consultar el ERP ahora mismo"


# --- Fuente real: PostgreSQL y ERP -----------------------------------------------------------------------------------------------

class Fuente:
    def __init__(self):
        from .ajustes import ajustes
        self.url = ajustes.database_url

    async def _con(self):
        import psycopg
        from psycopg.rows import dict_row
        return await psycopg.AsyncConnection.connect(self.url, row_factory=dict_row, connect_timeout=3)

    async def uso(self, agente, desde, hasta):
        async with await self._con() as c:
            filas = await (await c.execute("SELECT clave, sum(n)::int AS n FROM kpi_uso WHERE agente=%s AND dia >= %s AND dia < %s GROUP BY clave", (agente, desde, hasta))).fetchall()
        return {f["clave"]: f["n"] for f in filas}

    async def uso_diario(self, agente, desde, hasta):
        async with await self._con() as c:
            filas = await (await c.execute("SELECT dia, clave, n FROM kpi_uso WHERE agente=%s AND dia >= %s AND dia < %s", (agente, desde, hasta))).fetchall()
        return [(f["dia"], f["clave"], f["n"]) for f in filas]

    async def aprobaciones(self, agente, desde, hasta):
        async with await self._con() as c:
            f = await (await c.execute(
                """SELECT count(*)::int AS total, count(*) FILTER (WHERE estado='aprobada')::int AS aprobadas, count(*) FILTER (WHERE estado='rechazada')::int AS rechazadas,
                          avg(EXTRACT(EPOCH FROM (actualizado - creado))) FILTER (WHERE estado <> 'pendiente') AS segundos_medios
                   FROM aprobaciones WHERE agente=%s AND creado >= %s AND creado < %s""", (agente, desde, hasta))).fetchone()
            p = await (await c.execute("SELECT count(*)::int AS n FROM aprobaciones WHERE agente=%s AND estado='pendiente'", (agente,))).fetchone()
        return {**f, "pendientes": p["n"], "segundos_medios": float(f["segundos_medios"]) if f["segundos_medios"] is not None else None}

    async def acciones(self, agente, desde, hasta):
        async with await self._con() as c:
            f = await (await c.execute(
                """SELECT count(*) FILTER (WHERE resultado LIKE 'OK%%')::int AS ok, count(*) FILTER (WHERE resultado NOT LIKE 'OK%%')::int AS error
                   FROM registro_acciones WHERE agente=%s AND creado >= %s AND creado < %s""", (agente, desde, hasta))).fetchone()
        return f

    async def erp(self, departamento, k, desde, hasta):
        from .herramientas import erpnext
        hoy = date.today().isoformat()

        def sustituir(x):
            return hoy if x == "{hoy}" else [sustituir(i) for i in x] if isinstance(x, list) else x
        return await erpnext.metrica(departamento, k["doctype"], sustituir(k.get("filtros") or []), k.get("agregado", "contar"), k.get("campo"),
                                     k.get("periodo"), desde if k.get("periodo") else None, hasta if k.get("periodo") else None)
