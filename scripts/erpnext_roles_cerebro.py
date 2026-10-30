"""Un rol de ERPNext por departamento, generado desde config/erp_acceso.yaml, y un usuario técnico que tiene SOLO ese rol.

Por qué: con los roles estándar (Sales User, Accounts User…) el usuario técnico lee mucho más de lo que necesita (Bank Account, Account,
Company, Role, lista de usuarios…), porque ERPNext se lo da por defecto a cualquier usuario de escritorio. Con un rol propio, el usuario
solo ve los documentos de su política (verificado en el ERP real). La política del código sigue siendo la primera barrera; esto es la segunda.

Qué hace, por cada departamento (idempotente: se puede repetir cuando cambie la política):
  1. Crea el rol «Cerebro <Departamento>» (sin acceso a la interfaz de escritorio).
  2. Le da permiso de LEER los documentos de «leer»; de LEER, CREAR y MODIFICAR (nunca validar, cancelar ni borrar) los de «borrador»;
     y de SELECCIÓN (solo poder enlazarlos) los de «referencias»: datos maestros que un borrador necesita (cuentas, monedas…).
     Quita del rol cualquier permiso que ya no esté en la política.
  3. Deja al usuario cerebro.<departamento>@<dominio> con SOLO ese rol (lo crea si no existe, con su clave en el .env; si ya existe,
     conserva la clave: cambiar roles no la cambia).
  4. Verifica con la clave del usuario: lo que debe leer lo lee y lo que no, no.

Uso:  python3 scripts/erpnext_roles_cerebro.py --todos [--simular]
      python3 scripts/erpnext_roles_cerebro.py --departamento comercial
Después: docker compose up -d --force-recreate --no-deps api worker beat   (la API solo lee las claves al arrancar)
Si un agente falla al crear un borrador con «no tiene permiso para seleccionar X», añade X a «referencias» en config/erp_acceso.yaml y repite.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from erpnext_usuario_tecnico import Cliente, poner_en_env  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
PM = "/api/method/frappe.core.page.permission_manager.permission_manager."
TIPOS = ["read", "write", "create", "delete", "submit", "cancel", "amend", "report", "export", "import", "share", "print", "email", "select"]
# Documentos delicados que la verificación comprueba que siguen cerrados si no están en la política del departamento
VIGILADOS = ["User", "Role", "Company", "Account", "Bank Account", "Employee", "Salary Slip", "Journal Entry", "GL Entry", "Payment Entry",
             "Sales Invoice", "Purchase Invoice", "Customer", "Supplier", "Lead", "CRM Deal", "CRM Lead", "Contract"]


def nombre_rol(dep: str) -> str:
    return f"Cerebro {dep.capitalize()}"


def permisos_deseados(politica: dict, dep: str) -> dict[str, dict[str, int]]:
    """{documento: {permiso: 1}} para el rol del departamento. Función pura (se prueba sin ERP)."""
    p = (politica.get("departamentos") or {}).get(dep) or {}
    d: dict[str, dict[str, int]] = {}
    for doc in list(p.get("leer", [])) + list(p.get("sistema", [])):             # «sistema»: el ERP los deja leer; el código solo a procesos del sistema (empresa.py)
        d.setdefault(doc, {})["read"] = 1
    for doc in list(p.get("borrador", [])) + list(p.get("maestros", [])):          # «maestros»: el ERP los deja escribir; el código solo a procesos aprobados
        d.setdefault(doc, {}).update({"read": 1, "write": 1, "create": 1})
    for doc in politica.get("referencias", []) or []:
        if doc not in d:                       # si ya puede leerlo, no hace falta la selección
            d[doc] = {"select": 1}
    return d


def probar(url: str, token: str, doctype: str) -> str:
    req = urllib.request.Request(f"{url.rstrip('/')}/api/resource/{urllib.parse.quote(doctype, safe='')}?limit_page_length=1",
                                 headers={"Authorization": f"token {token}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20):
            return "lee"
    except urllib.error.HTTPError as e:
        return "no" if e.code in (403, 404) else f"?{e.code}"
    except Exception as e:  # noqa: BLE001
        return f"error:{type(e).__name__}"


def aplicar_departamento(c: Cliente, politica: dict, dep: str, dominio: str, ruta_env: Path, simular: bool, regenerar: bool, url: str) -> bool:
    rol, correo = nombre_rol(dep), f"cerebro.{dep}@{dominio}"
    deseados = permisos_deseados(politica, dep)
    print(f"\n== {dep}: rol «{rol}», usuario {correo} ({len(deseados)} documentos) ==")
    ok = True

    # 1) rol
    st, _ = c.llamar("GET", f"/api/resource/Role/{rol}")
    if st != 200:
        print(f"  crear rol {rol}")
        if not simular and c.llamar("POST", "/api/resource/Role", {"role_name": rol, "desk_access": 0})[0] >= 300:
            print("  ERROR: no se pudo crear el rol"); return False

    # 2) permisos: los que hay ahora frente a los que deben haber
    filtro = urllib.parse.quote(json.dumps([["role", "=", rol]]))
    campos = urllib.parse.quote(json.dumps(["parent", "permlevel"] + TIPOS))
    st, r = c.llamar("GET", f"/api/resource/Custom DocPerm?filters={filtro}&fields={campos}&limit_page_length=1000")
    actuales = {x["parent"]: {t: x.get(t, 0) for t in TIPOS} for x in (r.get("data", []) if st == 200 else []) if x.get("permlevel", 0) == 0}
    cambios = 0
    no_existen: set[str] = set()
    for doc, deseo in sorted(deseados.items()):
        quiero = {t: deseo.get(t, 0) for t in TIPOS}
        if actuales.get(doc) == quiero:
            continue
        cambios += 1
        print(f"  {'añadir' if doc not in actuales else 'ajustar'} {doc}: {', '.join(t for t in TIPOS if quiero[t]) }")
        if simular:
            continue
        st, rr = c.llamar("POST", PM + "add", {"parent": doc, "role": rol, "permlevel": 0})
        if st >= 300:
            no_existen.add(doc)
            continue
        for t in TIPOS:
            if quiero[t] != (actuales.get(doc) or {}).get(t, 1 if t == "read" and doc not in actuales else 0):
                c.llamar("POST", PM + "update", {"doctype": doc, "role": rol, "permlevel": 0, "ptype": t, "value": quiero[t]})
    for doc in sorted(set(actuales) - set(deseados)):
        cambios += 1
        print(f"  quitar {doc} (ya no está en la política)")
        if not simular:
            c.llamar("POST", PM + "remove", {"doctype": doc, "role": rol, "permlevel": 0})
    if not cambios:
        print("  permisos del rol: ya estaban al día")

    # 3) usuario con SOLO ese rol
    st, u = c.llamar("GET", f"/api/resource/User/{correo}")
    existe = st == 200
    if not existe:
        print(f"  crear usuario {correo} con el rol {rol}")
        if simular:
            return ok
        st, rr = c.llamar("POST", "/api/resource/User", {"email": correo, "first_name": "Cerebro", "last_name": dep.capitalize(),
                                                          "send_welcome_email": 0, "enabled": 1, "user_type": "System User",
                                                          "roles": [{"role": rol}]})
        if st >= 300:
            print(f"  ERROR: no se pudo crear el usuario: {rr}"); return False
    else:
        roles_ahora = sorted(x["role"] for x in u["data"].get("roles", []))
        if roles_ahora != [rol]:
            print(f"  roles del usuario: {', '.join(roles_ahora) or '(ninguno)'}  ->  solo {rol}")
            if not simular:
                st, rr = c.llamar("PUT", f"/api/resource/User/{correo}", {"roles": [{"role": rol}]})
                if st >= 300:
                    print(f"  ERROR: no se pudieron cambiar los roles: {rr}"); return False
        else:
            print("  usuario: ya tiene solo ese rol")
    if simular:
        return ok

    # 4) clave
    env = ruta_env.read_text(encoding="utf-8") if ruta_env.exists() else ""
    if not existe or regenerar or not re.search(rf"^ERPNEXT_TOKEN_{dep.upper()}=.+", env, re.M):
        st, r = c.llamar("POST", f"/api/method/frappe.core.doctype.user.user.generate_keys?user={correo}")
        secreto = r.get("message", {}).get("api_secret") if st == 200 else None
        st2, uu = c.llamar("GET", f"/api/resource/User/{correo}")
        clave = uu.get("data", {}).get("api_key") if st2 == 200 else None
        if not (secreto and clave):
            print("  ERROR: no se pudieron generar las claves"); return False
        poner_en_env(ruta_env, f"ERPNEXT_TOKEN_{dep.upper()}", f"{clave}:{secreto}")
        print(f"  clave nueva guardada en el .env (ERPNEXT_TOKEN_{dep.upper()})")
        env = ruta_env.read_text(encoding="utf-8")
    token = re.search(rf"^ERPNEXT_TOKEN_{dep.upper()}=(.+)$", env, re.M).group(1).strip()

    # 5) verificación con su propia clave (ERPNext tarda unos segundos en refrescar la caché de roles: se reintenta)
    if no_existen:
        print(f"  AVISO: no existen en este ERP (¿falta instalar la aplicación que los trae, p. ej. HRMS para RR. HH.?): {', '.join(sorted(no_existen))}")
    leer = (set((politica["departamentos"][dep]).get("leer", [])) | set((politica["departamentos"][dep]).get("sistema", []))) - no_existen
    solo_nombre = set(politica.get("referencias", []) or [])           # con «selección» el ERP devuelve únicamente el nombre
    malos_no = malos_si = []
    for intento in range(4):
        malos_no = [d for d in sorted(leer) if probar(url, token, d) != "lee"]
        malos_si = [d for d in VIGILADOS if d not in leer and d not in solo_nombre and d != "User" and probar(url, token, d) == "lee"]
        if not malos_no and not malos_si:
            break
        time.sleep(5)
    if malos_no:
        print(f"  VERIFICACIÓN: no puede leer algo de su política: {', '.join(malos_no)}"); ok = False
    if malos_si:
        print(f"  VERIFICACIÓN: puede leer fuera de su política: {', '.join(malos_si)}"); ok = False
    if ok:
        print(f"  verificado: lee los {len(leer)} documentos de su política y ninguno de los vigilados fuera de ella")
    return ok


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--departamento")
    g.add_argument("--todos", action="store_true")
    p.add_argument("--simular", action="store_true", help="muestra lo que haría sin cambiar nada")
    p.add_argument("--regenerar", action="store_true", help="emite claves nuevas (las anteriores dejan de valer)")
    p.add_argument("--url", default="http://localhost:8081")
    p.add_argument("--env", default=str(RAIZ / ".env"))
    p.add_argument("--politica", default=str(RAIZ / "config" / "erp_acceso.yaml"))
    p.add_argument("--dominio", default="101.cat")
    a = p.parse_args()
    politica = yaml.safe_load(Path(a.politica).read_text(encoding="utf-8")) or {}
    deps = sorted(politica.get("departamentos", {})) if a.todos else [a.departamento]
    if a.departamento and a.departamento not in politica.get("departamentos", {}):
        p.error(f"«{a.departamento}» no está en {a.politica}")
    env = Path(a.env).read_text(encoding="utf-8")
    m = re.search(r"^ERPNEXT_ADMIN_PASSWORD=(.+)$", env, re.M)
    if not m:
        p.error("falta ERPNEXT_ADMIN_PASSWORD en el .env")
    c = Cliente(a.url)
    if c.llamar("POST", "/api/method/login", {"usr": "Administrator", "pwd": m.group(1).strip()})[0] != 200:
        print("No se pudo entrar en ERPNext: ¿está en marcha y es correcta la contraseña?"); return 1
    if a.simular:
        print("SIMULACIÓN: no se cambia nada")
    resultados = {d: aplicar_departamento(c, politica, d, a.dominio, Path(a.env), a.simular, a.regenerar, a.url) for d in deps}
    print("\n== Resumen ==")
    for d, ok in resultados.items():
        print(f"  {d:14} {'correcto' if ok else 'REVISAR'}")
    if not a.simular:
        print("\nAhora reinicia la API para que lea las claves nuevas:  docker compose up -d --force-recreate --no-deps api worker beat")
    return 0 if all(resultados.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
