"""Crea (o reutiliza) el usuario técnico de un departamento en ERPNext y guarda su clave en el .env.

Uso:  python scripts/erpnext_usuario_tecnico.py --departamento finanzas --roles "Accounts User,Accounts Manager"
      python scripts/erpnext_usuario_tecnico.py --departamento direccion --roles "Sales User,Purchase User,HR User"

Cada departamento usa su propio usuario (ERPNEXT_TOKEN_<DEPARTAMENTO>) con solo los roles de su área: así el
Cerebro no ve más de lo que ve esa área. Si el usuario ya existe no se toca; con --regenerar se emiten claves nuevas
(las anteriores dejan de valer). Lee ERPNEXT_ADMIN_PASSWORD del .env. La clave nunca se muestra por pantalla.
"""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


class Cliente:
    def __init__(self, base: str):
        self.base = base.rstrip("/")
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def llamar(self, metodo: str, ruta: str, datos: dict | None = None) -> tuple[int, dict]:
        req = urllib.request.Request(self.base + urllib.parse.quote(ruta, safe="/?=&:@"), method=metodo,
                                     data=None if datos is None else json.dumps(datos).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with self.op.open(req, timeout=90) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, {"error": e.read().decode()[:300]}


def poner_en_env(ruta: Path, clave: str, valor: str) -> None:
    texto = ruta.read_text(encoding="utf-8") if ruta.exists() else ""
    linea = f"{clave}={valor}"
    if re.search(rf"^{clave}=", texto, re.M):
        texto = re.sub(rf"^{clave}=.*$", lambda _: linea, texto, flags=re.M)
    else:
        texto += ("" if texto.endswith("\n") or not texto else "\n") + linea + "\n"
    ruta.write_text(texto, encoding="utf-8")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--departamento", required=True, help="finanzas, comercial, operaciones, telecom, direccion…")
    p.add_argument("--roles", required=True, help="roles de ERPNext separados por comas")
    p.add_argument("--url", default="http://localhost:8081")
    p.add_argument("--env", default=str(Path(__file__).resolve().parent.parent / ".env"))
    p.add_argument("--dominio", default="101.cat")
    p.add_argument("--regenerar", action="store_true")
    a = p.parse_args()
    env = Path(a.env).read_text(encoding="utf-8")
    m = re.search(r"^ERPNEXT_ADMIN_PASSWORD=(.+)$", env, re.M)
    if not m:
        p.error("falta ERPNEXT_ADMIN_PASSWORD en el .env")
    c = Cliente(a.url)
    st, _ = c.llamar("POST", "/api/method/login", {"usr": "Administrator", "pwd": m.group(1)})
    if st != 200:
        print(f"No se pudo entrar en ERPNext ({st}). ¿Está en marcha y es correcta la contraseña?")
        return 1
    correo = f"cerebro.{a.departamento}@{a.dominio}"
    roles = [r.strip() for r in a.roles.split(",") if r.strip()]
    st, _ = c.llamar("GET", f"/api/resource/User/{correo}")
    existe = st == 200
    if not existe:
        st, r = c.llamar("POST", "/api/resource/User", {"email": correo, "first_name": "Cerebro", "last_name": a.departamento.capitalize(),
                                                        "send_welcome_email": 0, "enabled": 1, "user_type": "System User",
                                                        "roles": [{"role": x} for x in roles]})
        if st >= 300:
            print(f"No se pudo crear {correo}: {r}")
            return 1
        print(f"Usuario {correo} creado con los roles: {', '.join(roles)}")
    else:
        print(f"Usuario {correo} ya existía: no se modifica")
    if existe and not a.regenerar and re.search(rf"^ERPNEXT_TOKEN_{a.departamento.upper()}=.+", env, re.M):
        print("Ya hay clave en el .env (usa --regenerar para emitir otra)")
        return 0
    st, r = c.llamar("POST", f"/api/method/frappe.core.doctype.user.user.generate_keys?user={correo}")
    secreto = r.get("message", {}).get("api_secret") if st == 200 else None
    st2, u = c.llamar("GET", f"/api/resource/User/{correo}")
    clave = u.get("data", {}).get("api_key") if st2 == 200 else None
    if not (secreto and clave):
        print("No se pudieron generar las claves")
        return 1
    poner_en_env(Path(a.env), f"ERPNEXT_TOKEN_{a.departamento.upper()}", f"{clave}:{secreto}")
    print(f"Clave guardada en {a.env} como ERPNEXT_TOKEN_{a.departamento.upper()}. Reinicia la API para que la lea.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
