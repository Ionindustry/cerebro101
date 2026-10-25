"""Auditoría: ¿cada departamento ve en el ERP y el CRM solo lo de su área?

Compara tres cosas y avisa de lo que no cuadra:
  1. QUÉ agentes usan el ERP (fichas de config/agentes) y de qué departamento son.
  2. QUÉ debería poder tocar cada departamento (config/erp_acceso.yaml: la política que aplica el código).
  3. QUÉ puede leer de verdad cada usuario técnico en el ERP (se prueba con su clave, solo lectura; no se crea ni cambia nada).
     Si el ERP deja leer más de lo que dice la política, el código lo bloquea, pero ese usuario tiene más roles de los necesarios.

Uso:  python3 scripts/auditar_acceso_erp.py [--url http://localhost:8081] [--env .env] [--roles] [--json]
  --roles  además lista los roles de cada usuario cerebro.* (necesita ERPNEXT_ADMIN_PASSWORD en el .env)
Sale con código 1 si hay incidencias. Solo usa la biblioteca estándar y PyYAML.
"""
from __future__ import annotations

import argparse
import glob
import http.cookiejar
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parent.parent
# Documentos delicados que se prueban siempre, además de los de la política
SENSIBLES = ["User", "Role", "Company", "Employee", "Salary Slip", "Salary Structure", "Leave Application", "Attendance",
             "Bank Account", "Journal Entry", "GL Entry", "Payment Entry", "Account", "Sales Invoice", "Purchase Invoice",
             "Supplier", "Customer", "Item", "Bin", "Stock Entry", "Purchase Order", "Sales Order", "Quotation",
             "Project", "Task", "Lead", "Opportunity", "Campaign", "Contract",
             "CRM Lead", "CRM Deal", "CRM Organization", "CRM Task", "FCRM Note", "CRM Call Log"]


def leer_env(ruta: Path) -> dict[str, str]:
    d = {}
    if ruta.exists():
        for l in ruta.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^([A-Z][A-Z0-9_]*)=(.*)$", l)
            if m:
                d[m.group(1)] = re.split(r"\s+#", m.group(2), maxsplit=1)[0].strip()
    return d


def agentes_con_erp() -> dict[str, list[str]]:
    por: dict[str, list[str]] = defaultdict(list)
    for f in sorted(glob.glob(str(RAIZ / "config" / "agentes" / "*.yaml"))):
        d = yaml.safe_load(open(f, encoding="utf-8"))
        for a in (d if isinstance(d, list) else d.get("agentes", [])):
            if "erpnext" in a.get("herramientas", []):
                por[a["departamento"]].append(a["id"])
    return por


def probar(url: str, token: str, doctype: str) -> str:
    req = urllib.request.Request(f"{url.rstrip('/')}/api/resource/{urllib.parse.quote(doctype, safe='')}?limit_page_length=1",
                                 headers={"Authorization": f"token {token}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return "lee" if r.status == 200 else f"?{r.status}"
    except urllib.error.HTTPError as e:
        return {403: "no", 404: "inexistente", 401: "clave-no-valida"}.get(e.code, f"?{e.code}")
    except Exception as e:  # noqa: BLE001
        return f"error:{type(e).__name__}"


def filas(url: str, token: str, doctype: str) -> int:
    req = urllib.request.Request(f"{url.rstrip('/')}/api/resource/{urllib.parse.quote(doctype, safe='')}?limit_page_length=50",
                                 headers={"Authorization": f"token {token}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return len(json.load(r).get("data", []))
    except Exception:  # noqa: BLE001
        return -1


def doctypes_existentes(url: str, clave_admin: str) -> set[str] | None:
    """Nombres de DocType que existen en este ERP (para distinguir «no tiene permiso» de «ese documento no existe aquí»)."""
    try:
        op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        op.open(urllib.request.Request(url.rstrip("/") + "/api/method/login", data=urllib.parse.urlencode({"usr": "Administrator", "pwd": clave_admin}).encode()), timeout=30)
        with op.open(url.rstrip("/") + "/api/resource/DocType?limit_page_length=5000&fields=%5B%22name%22%5D", timeout=60) as r:
            return {x["name"] for x in json.load(r)["data"]}
    except Exception:  # noqa: BLE001
        return None


# Frappe da lectura de Contact y Address enlazados a documentos que el usuario sí puede leer: no es una fuga de la política
VINCULADOS = {"Contact", "Address"}


def roles_de_usuarios(url: str, clave_admin: str) -> dict[str, list[str]]:
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def llamar(ruta, datos=None):
        req = urllib.request.Request(url.rstrip("/") + ruta, data=datos, headers={"Accept": "application/json"})
        with op.open(req, timeout=30) as r:
            return json.load(r)
    llamar("/api/method/login", urllib.parse.urlencode({"usr": "Administrator", "pwd": clave_admin}).encode())
    filtro = urllib.parse.quote(json.dumps([["name", "like", "cerebro.%"]]))
    usuarios = [u["name"] for u in llamar(f"/api/resource/User?filters={filtro}&limit_page_length=100")["data"]]
    return {u: sorted(r["role"] for r in llamar(f"/api/resource/User/{urllib.parse.quote(u, safe='@.')}")["data"].get("roles", [])
                      if r["role"] not in ("All", "Guest", "Desk User")) for u in usuarios}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", default="http://localhost:8081")
    p.add_argument("--env", default=str(RAIZ / ".env"))
    p.add_argument("--roles", action="store_true")
    p.add_argument("--json", action="store_true")
    a = p.parse_args()
    env = leer_env(Path(a.env))
    usan = agentes_con_erp()
    ruta_pol = RAIZ / "config" / "erp_acceso.yaml"
    politica = yaml.safe_load(ruta_pol.read_text(encoding="utf-8")) if ruta_pol.exists() else {}
    pol_deps = (politica or {}).get("departamentos", {})
    general = bool(env.get("ERPNEXT_TOKEN"))
    incidencias: list[str] = []
    informe: dict = {"departamentos": {}}

    print(f"== Departamentos con agentes que usan el ERP ({sum(len(v) for v in usan.values())} agentes) ==")
    print(f"{'departamento':14}{'agentes':>8}  {'clave propia':13}{'política':10}")
    for dep in sorted(usan):
        tiene = bool(env.get(f"ERPNEXT_TOKEN_{dep.upper()}"))
        con_pol = dep in pol_deps
        print(f"{dep:14}{len(usan[dep]):>8}  {'sí' if tiene else ('general' if general else 'NO'):13}{'sí' if con_pol else 'NO':10}")
        informe["departamentos"][dep] = {"agentes": len(usan[dep]), "clave_propia": tiene, "politica": con_pol}
        if not tiene and general:
            incidencias.append(f"{dep}: no tiene clave propia y usa la general (ERPNEXT_TOKEN): ve lo que vea esa clave, no solo su área")
        if con_pol is False:
            incidencias.append(f"{dep}: sin política en config/erp_acceso.yaml -> el código le bloquea todo el ERP")
    for dep in sorted(set(pol_deps) - set(usan)):
        print(f"(política de «{dep}» sin agentes que usen el ERP)")

    probados = sorted(set(SENSIBLES) | {d for v in pol_deps.values() for d in (v.get("leer", []) + v.get("borrador", []))})
    claves = {dep: env.get(f"ERPNEXT_TOKEN_{dep.upper()}") for dep in sorted(usan) if env.get(f"ERPNEXT_TOKEN_{dep.upper()}")}
    if claves:
        print(f"\n== Lo que puede LEER cada usuario técnico en {a.url} (L = puede; · = no; ? = no se pudo comprobar) ==")
        res: dict[str, dict[str, str]] = {d: {dep: probar(a.url, t, d) for dep, t in claves.items()} for d in probados}
        print(f"{'documento':22}" + "".join(f"{dep[:11]:>12}" for dep in claves))
        for d in probados:
            print(f"{d:22}" + "".join(f"{('L' if res[d][dep] == 'lee' else ('·' if res[d][dep] in ('no', 'inexistente') else '?')):>12}" for dep in claves))
        existentes = doctypes_existentes(a.url, env["ERPNEXT_ADMIN_PASSWORD"]) if env.get("ERPNEXT_ADMIN_PASSWORD") else None
        notas: list[str] = []
        for dep in claves:
            if any(res[d][dep] == "clave-no-valida" for d in probados):
                incidencias.append(f"{dep}: el ERP no reconoce su clave (ERPNEXT_TOKEN_{dep.upper()}): hay que regenerarla")
                continue
            leer_dep = set(pol_deps.get(dep, {}).get("leer", []))
            permitidos = leer_dep | set((politica or {}).get("referencias", []) or [])      # referencias: solo devuelven el nombre
            de_mas = [d for d in probados if res[d][dep] == "lee" and d not in permitidos]
            if "User" in de_mas and filas(a.url, claves[dep], "User") <= 1:                  # solo su propia ficha
                de_mas.remove("User")
            vinc = [d for d in de_mas if d in VINCULADOS and leer_dep]
            de_mas = [d for d in de_mas if d not in vinc]
            sin_erp = [d for d in sorted(leer_dep) if existentes is not None and d not in existentes]
            faltan = [d for d in sorted(leer_dep) if res.get(d, {}).get(dep) == "no" and d not in sin_erp]
            informe["departamentos"].setdefault(dep, {}).update({"lee_fuera_de_politica": de_mas, "politica_sin_permiso_en_erp": faltan,
                                                                  "politica_sin_documento_en_erp": sin_erp, "visibles_por_enlace": vinc})
            if de_mas:
                incidencias.append(f"{dep}: su usuario del ERP puede leer FUERA de su política: {', '.join(de_mas)}  -> revisar los roles del usuario cerebro.{dep} (¿tiene solo el rol «Cerebro {dep.capitalize()}»? scripts/erpnext_roles_cerebro.py)")
            if faltan:
                incidencias.append(f"{dep}: la política le permite {', '.join(faltan)} pero el ERP se lo niega -> sus agentes fallarán; falta algún permiso en el rol")
            if vinc:
                notas.append(f"{dep}: ve {', '.join(vinc)} enlazados a los documentos que sí puede leer (regla interna de ERPNext; el código no deja a sus agentes pedirlos si no están en su política)")
            if sin_erp:
                notas.append(f"{dep}: su política incluye documentos que NO existen en este ERP: {', '.join(sin_erp)} (¿falta instalar la aplicación que los trae, p. ej. HRMS?)")
        if notas:
            print("\n== Notas (no son incidencias) ==")
            for n in notas:
                print(" - " + n)
    else:
        print("\n(No hay ninguna clave ERPNEXT_TOKEN_<DEPARTAMENTO> en el .env: no se puede comprobar el ERP)")

    if a.roles:
        clave_admin = env.get("ERPNEXT_ADMIN_PASSWORD")
        if not clave_admin:
            print("\n--roles necesita ERPNEXT_ADMIN_PASSWORD en el .env")
        else:
            print("\n== Roles de cada usuario técnico (cerebro.*) ==")
            try:
                informe["roles"] = roles_de_usuarios(a.url, clave_admin)
                for u, r in informe["roles"].items():
                    print(f"{u:40} {', '.join(r) or '(sin roles)'}")
            except Exception as e:  # noqa: BLE001
                print(f"No se pudieron leer los roles: {type(e).__name__}: {e}")

    print("\n== Incidencias ==")
    for i in incidencias:
        print(" - " + i)
    if not incidencias:
        print(" ninguna")
    if a.json:
        informe["incidencias"] = incidencias
        print(json.dumps(informe, ensure_ascii=False, indent=2))
    return 1 if incidencias else 0


if __name__ == "__main__":
    sys.exit(main())
