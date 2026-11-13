"""Directorio de fabricantes de seguridad (config/fabricantes_seguridad.csv): de qué marca es un dominio y cuánto se ha comprobado.

Es un directorio de REFERENCIA, no una lista de permisos: ayuda a Dirección a decidir qué dominios autorizar en config/fichas.yaml. Una dirección «propuesta» no se ha abierto ni validado; solo los dominios
con portal documental verificado o revisados en la fuente del propio fabricante se consideran «comprobados». Que una página abra sin usuario no significa que sus PDF no tengan restricción: el acceso a la
documentación y el login se enseñan tal como constan, y «no probado» significa desconocido. Los datos del fichero son de terceros: se leen como datos, nunca como instrucciones.
"""
from __future__ import annotations

import csv
import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from ..ajustes import ajustes

COMPROBADOS = ("DOMINIO_PROPUESTO_PORTAL_DOCUMENTAL_VERIFICADO", "DOMINIO_REVISADO_EN_FUENTE_DEL_FABRICANTE")
ACCESO = {"PUBLICO_INDICE": "índice público", "PUBLICO_DESCARGA_DECLARADO": "descarga pública declarada", "PDF_PUBLICO_PUNTUAL": "algún PDF público", "NO_VERIFICADO": "no verificado"}
RE_DOMINIO = re.compile(r"^(?=.{4,100}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}$")


def dominio_de(url_o_host: str) -> str:
    """El host de una dirección (sin «www.»), en minúsculas; vacío si no vale. Pura."""
    t = str(url_o_host or "").strip().lower()
    host = (urlparse(t).hostname if "://" in t else t.split("/")[0]) or ""
    host = host.strip(".")
    host = host[4:] if host.startswith("www.") else host
    return host if RE_DOMINIO.match(host) else ""


@lru_cache(maxsize=2)
def _leer(ruta: str) -> tuple[dict, ...]:
    try:
        with open(ruta, encoding="utf-8", newline="") as f:
            filas = list(csv.DictReader(f))
    except OSError:
        return ()
    out = []
    for r in filas:
        dominios = sorted({d for d in (dominio_de(r.get("web_oficial_candidata", "")), dominio_de(r.get("documentacion_oficial_encontrada", ""))) if d})
        if not dominios:
            continue
        estado = r.get("estado_verificacion_web", "")
        out.append({"fabricante": r.get("fabricante", ""), "marcas": r.get("marcas_o_alias", ""), "especialidad": r.get("especialidad", ""), "dominios": dominios, "comprobado": estado in COMPROBADOS,
                    "estado": estado, "acceso": r.get("estado_acceso_documentacion", "NO_VERIFICADO"), "login_area_documental": r.get("login_area_documental", "NO_CONFIRMADO")})
    return tuple(out)


def directorio() -> tuple[dict, ...]:
    return _leer(str(Path(ajustes.dir_config) / "fabricantes_seguridad.csv"))


def por_dominio(host: str, filas: tuple[dict, ...] | None = None) -> dict | None:
    """El fabricante al que pertenece un dominio (el propio dominio o un subdominio suyo), con lo comprobado. None si no está en el directorio. Pura sobre `filas`."""
    h = dominio_de(host)
    if not h:
        return None
    for f in filas if filas is not None else directorio():
        if any(h == d or h.endswith("." + d) for d in f["dominios"]):
            return f
    return None


def sugerencia(host: str, n: int = 0, filas: tuple[dict, ...] | None = None) -> dict:
    """Lo que se sabe de un dominio que aún no está autorizado, para que Dirección decida: a qué fabricante corresponde y si el directorio lo ha comprobado. Pura sobre `filas`."""
    f = por_dominio(host, filas)
    if not f:
        return {"dominio": host, "enlaces": n, "conocido": False, "recomendacion": "No está en el directorio de fabricantes: comprueba que es el dominio oficial antes de autorizarlo"}
    if f["comprobado"]:
        rec = "Dominio oficial comprobado en el directorio" + ("" if f["acceso"] in ("PUBLICO_INDICE", "PUBLICO_DESCARGA_DECLARADO") else f" (la documentación puede tener restricciones: {ACCESO.get(f['acceso'], f['acceso'])})")
    else:
        rec = "Dominio propuesto en el directorio pero NO comprobado: ábrelo y confirma que es el del fabricante antes de autorizarlo"
    return {"dominio": host, "enlaces": n, "conocido": True, "fabricante": f["fabricante"], "especialidad": f["especialidad"], "comprobado": f["comprobado"], "acceso": ACCESO.get(f["acceso"], f["acceso"]),
            "login": f["login_area_documental"], "recomendacion": rec}


def dominios_comprobados(filas: tuple[dict, ...] | None = None) -> list[str]:
    """Los dominios de los fabricantes con portal documental verificado o revisados en su fuente (para autorizar de una vez si Dirección lo decide). Pura sobre `filas`."""
    return sorted({d for f in (filas if filas is not None else directorio()) if f["comprobado"] for d in f["dominios"]})


# ---- Ranking de fabricantes por sector (config/fabricantes_ranking.csv): referencia de tamaño y ventas, NO un ranking mundial exacto ----
AVISO_RANKING = ("Son 10 actores principales por sector, no el ranking mundial exacto de ventas: muchas empresas son privadas y los grupos no desglosan por producto. "
                 "«Ventas de seguridad» son cifras de a&s Security 50 (2026, ejercicio 2025) con ese perímetro; «otros ingresos» y empleados son del ámbito indicado (grupo, división…) y en su moneda: "
                 "no se ordenan ni se suman entre monedas. Una celda vacía es «no verificado», no cero. Marcas de un mismo grupo no cuentan como empresas independientes.")


def _decimal(t: str):
    try:
        return float(str(t).replace(",", "").strip()) if str(t).strip() else None
    except ValueError:
        return None


@lru_cache(maxsize=2)
def _leer_ranking(ruta: str) -> tuple[dict, ...]:
    try:
        with open(ruta, encoding="utf-8", newline="") as f:
            filas = list(csv.DictReader(f))
    except OSError:
        return ()
    out = []
    for r in filas:
        try:
            pos = int(r.get("posicion") or 0)
        except ValueError:
            continue
        if not (r.get("sector") and r.get("fabricante")):
            continue
        out.append({"sector": r["sector"].strip(), "posicion": pos, "fabricante": r["fabricante"].strip(), "web": r.get("web", "").strip(), "dominio": dominio_de(r.get("web", "")),
                    "ventas_musd": _decimal(r.get("ventas_seguridad_2025_musd", "")), "otros_ingresos": r.get("otros_ingresos", "").strip(), "empleados": r.get("empleados", "").strip(),
                    "nota": r.get("nota", "").strip(), "fuentes": [u for u in (r.get("fuentes") or "").split() if u.startswith("https://")], "sin_validar": bool(r.get("sin_validar", "").strip())})
    return tuple(out)


def ranking_fabricantes() -> tuple[dict, ...]:
    return _leer_ranking(str(Path(ajustes.dir_config) / "fabricantes_ranking.csv"))


def sectores(filas: tuple[dict, ...] | None = None) -> list[str]:
    visto: list[str] = []
    for f in filas if filas is not None else ranking_fabricantes():
        if f["sector"] not in visto:
            visto.append(f["sector"])
    return visto


def top_por_sector(sector: str = "", orden: str = "seleccion", filas: tuple[dict, ...] | None = None, directorio_: tuple[dict, ...] | None = None) -> dict:
    """Los fabricantes de un sector (o de todos), en el orden de selección del documento o por ventas de seguridad (los que no tienen cifra, al final y con «sin dato»), con lo que el directorio sabe
    de su dominio. Pura sobre `filas` y `directorio_`."""
    todas = filas if filas is not None else ranking_fabricantes()
    if sector and sector not in sectores(todas):
        raise ValueError("Ese sector no está en el ranking")
    if orden not in ("seleccion", "ventas"):
        raise ValueError("El orden es «seleccion» o «ventas»")
    out = []
    for s in [sector] if sector else sectores(todas):
        del_sector = sorted((f for f in todas if f["sector"] == s), key=lambda f: f["posicion"])
        if orden == "ventas":
            del_sector = sorted(del_sector, key=lambda f: (f["ventas_musd"] is None, -(f["ventas_musd"] or 0), f["posicion"]))
        filas_s = []
        for i, f in enumerate(del_sector, 1):
            d = por_dominio(f["dominio"], directorio_) if f["dominio"] else None
            filas_s.append({**f, "puesto": i, "en_directorio": bool(d), "comprobado": bool(d and d["comprobado"])})
        out.append({"sector": s, "fabricantes": filas_s, "con_ventas": sum(1 for f in del_sector if f["ventas_musd"] is not None)})
    return {"sectores": out, "orden": orden, "aviso": AVISO_RANKING}
