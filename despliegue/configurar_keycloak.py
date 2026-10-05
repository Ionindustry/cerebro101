"""Ajusta Keycloak a las direcciones públicas y crea el primer usuario de dirección.

  · El cliente «cerebro-panel» acepta solo las direcciones del panel (PANEL_URL) y no admite contraseña directa.
  · El realm bloquea ataques de fuerza bruta y exige contraseñas de 12 caracteres o más.
  · Con --director, crea un usuario con rol y grupo «direccion» y una contraseña temporal (se muestra una sola vez;
    Keycloak obliga a cambiarla en el primer acceso).

Es idempotente. Se ejecuta desde el servidor (Keycloak escucha en localhost:8080).
Uso:  python despliegue/configurar_keycloak.py [--director persona@101.cat --nombre "Nombre Apellido"]
"""
from __future__ import annotations

import argparse
import json
import re
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def payload_cliente(actual: dict, panel_url: str) -> dict:
    """Representación del cliente con las direcciones del panel. Pura, para poder probarla."""
    p = panel_url.rstrip("/")
    return {**actual, "redirectUris": [f"{p}/*"], "webOrigins": [p], "directAccessGrantsEnabled": False,
            "publicClient": True, "standardFlowEnabled": True,
            "attributes": {**actual.get("attributes", {}), "post.logout.redirect.uris": f"{p}/*"}}


AJUSTES_REALM = {"bruteForceProtected": True, "failureFactor": 5, "permanentLockout": False, "maxFailureWaitSeconds": 900,
                 "passwordPolicy": "length(12) and notUsername(undefined)", "loginWithEmailAllowed": True,
                 "registrationAllowed": False}


class Admin:
    def __init__(self, base: str, clave: str):
        self.base = base.rstrip("/")
        self.clave = clave
        self.token = ""

    def _pedir(self, metodo: str, ruta: str, datos=None, formulario: dict | None = None):
        cuerpo = urllib.parse.urlencode(formulario).encode() if formulario else (json.dumps(datos).encode() if datos is not None else None)
        cab = {"Content-Type": "application/x-www-form-urlencoded" if formulario else "application/json"}
        if self.token:
            cab["Authorization"] = f"Bearer {self.token}"
        try:
            with urllib.request.urlopen(urllib.request.Request(self.base + ruta, data=cuerpo, method=metodo, headers=cab), timeout=60) as r:
                texto = r.read().decode()
                return r.status, (json.loads(texto) if texto else {}), r.headers
        except urllib.error.HTTPError as e:
            return e.code, {"error": e.read().decode()[:300]}, e.headers

    def entrar(self, espera: int = 240) -> bool:
        limite = time.time() + espera
        while time.time() < limite:
            try:
                st, r, _ = self._pedir("POST", "/realms/master/protocol/openid-connect/token",
                                       formulario={"client_id": "admin-cli", "username": "admin", "password": self.clave, "grant_type": "password"})
                if st == 200:
                    self.token = r["access_token"]
                    return True
                if st in (400, 401):
                    return False                   # contraseña incorrecta: no tiene sentido seguir esperando
            except (urllib.error.URLError, ConnectionError, TimeoutError):
                pass
            time.sleep(5)
        return False

    def api(self, metodo: str, ruta: str, datos=None):
        return self._pedir(metodo, ruta, datos)


def main() -> int:
    raiz = Path(__file__).resolve().parent.parent
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", default="http://localhost:8080")
    p.add_argument("--env", default=str(raiz / ".env"))
    p.add_argument("--director", help="correo del primer usuario de dirección")
    p.add_argument("--nombre", default="Dirección General")
    a = p.parse_args()
    env = Path(a.env).read_text(encoding="utf-8")
    valor = lambda k, d="": (m.group(1).split(" #")[0].strip() if (m := re.search(rf"^{k}=(.*)$", env, re.M)) else d)
    panel, realm, cliente = valor("PANEL_URL"), valor("KEYCLOAK_REALM", "cerebro"), valor("KEYCLOAK_CLIENTE", "cerebro-panel")
    if not panel.startswith("https://") and "localhost" not in panel:
        print(f"PANEL_URL={panel!r} no es una dirección https; ¿se ejecutó preparar_env.py con --dominio?")
        return 1
    k = Admin(a.url, valor("KEYCLOAK_ADMIN_PASSWORD"))
    if not k.entrar():
        print("No se pudo entrar en Keycloak como administrador (¿arrancado? ¿contraseña correcta?)")
        return 1
    st, lista, _ = k.api("GET", f"/admin/realms/{realm}/clients?clientId={cliente}")
    if st != 200 or not lista:
        print(f"No existe el cliente {cliente} en el realm {realm}: {lista}")
        return 1
    st, _, _ = k.api("PUT", f"/admin/realms/{realm}/clients/{lista[0]['id']}", payload_cliente(lista[0], panel))
    print(f"Cliente {cliente}: direcciones de {panel} ({'ok' if st < 300 else f'ERROR {st}'})")
    st, _, _ = k.api("PUT", f"/admin/realms/{realm}", AJUSTES_REALM)
    print(f"Realm {realm}: fuerza bruta y contraseñas de 12+ caracteres ({'ok' if st < 300 else f'ERROR {st}'})")
    if a.director:
        correo = a.director.strip().lower()
        if k.api("GET", f"/admin/realms/{realm}/users?email={urllib.parse.quote(correo)}&exact=true")[1]:
            print(f"Usuario {correo}: ya existía, no se modifica")
        else:
            temporal = secrets.token_urlsafe(12) + "aA1!"
            nombre, _, apellidos = a.nombre.partition(" ")
            st, r, cab = k.api("POST", f"/admin/realms/{realm}/users", {
                "username": correo, "email": correo, "firstName": nombre, "lastName": apellidos or "-", "enabled": True, "emailVerified": True,
                "credentials": [{"type": "password", "value": temporal, "temporary": True}]})
            if st >= 300:
                print(f"No se pudo crear {correo}: {r}")
                return 1
            uid = cab["Location"].rsplit("/", 1)[1]
            rol = k.api("GET", f"/admin/realms/{realm}/roles/direccion")[1]
            k.api("POST", f"/admin/realms/{realm}/users/{uid}/role-mappings/realm", [rol])
            grupos = k.api("GET", f"/admin/realms/{realm}/groups?search=direccion&exact=true")[1]
            if grupos:
                k.api("PUT", f"/admin/realms/{realm}/users/{uid}/groups/{grupos[0]['id']}")
            print(f"Usuario {correo} creado con rol y grupo «direccion».")
            print(f"  Contraseña temporal (se muestra solo ahora; deberá cambiarla al entrar): {temporal}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
