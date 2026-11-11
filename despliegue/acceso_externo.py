"""Activa o desactiva el acceso desde fuera (HTTPS) para una instalación LOCAL: el panel en https://brain.101.cat y el inicio de sesión en https://auth.101.cat.

  python3 despliegue/acceso_externo.py estado
  python3 despliegue/acceso_externo.py activar --panel brain.101.cat --auth auth.101.cat --correo tu@correo [--simular] [--sin-puerto-80] [--puerto-https 18443]
  python3 despliegue/acceso_externo.py puerto 18443          (en un acceso ya activado: cambia el puerto del equipo donde escucha el reenviador HTTPS)
  python3 despliegue/acceso_externo.py desactivar

Qué hace «activar» (en este orden, y se detiene si algo falla antes de tocar nada):
  1. Comprueba que Keycloak conserva sus datos (scripts/keycloak_conservar.sh), que Docker responde y que los dos nombres ya apuntan a algún sitio (DNS).
  2. Fija en el .env las direcciones (PANEL_URL, KEYCLOAK_URL_PUBLICA, DOM_PANEL, DOM_AUTH, CORREO_ADMIN, TLS_MODO) y añade el proxy a COMPOSE_FILE. Los valores anteriores se guardan en
     .acceso-externo.json para poder volver atrás SIN tocar el resto del .env (p. ej. la contraseña de administrador de Keycloak).
  3. Recrea Keycloak, el panel, la API y el proxy, y ajusta el cliente de Keycloak a las nuevas direcciones (despliegue/configurar_keycloak.py).
Lo que NO hace: abrir el router ni el cortafuegos de Windows (hay que hacerlo a mano; al terminar se explica) ni exponer el ERP, Langfuse o la API.
«desactivar» devuelve el .env a como estaba, quita el proxy y vuelve a poner el cliente de Keycloak con las direcciones de localhost.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ESTADO = ".acceso-externo.json"
SUPERPUESTO = "despliegue/docker-compose.externo.yml"
RE_DOMINIO = re.compile(r"^(?=.{4,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}$")
RE_CORREO = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DOMINIOS_DE_EJEMPLO = {"miempresa.com", "tudominio.es", "tudominio.com", "example.com", "example.org", "ejemplo.com", "ejemplo.es", "dominio.com", "empresa.com", "correo.com"}
SERVICIOS = ["keycloak", "panel", "api", "worker", "beat", "proxy", "reenvio"]
LINEA = re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$")


class ErrorAcceso(ValueError):
    """Lo que impide activar o desactivar; el mensaje es para la persona."""


def validar(panel: str, auth: str, correo: str) -> tuple[str, str, str]:
    panel, auth, correo = panel.strip().lower(), auth.strip().lower(), correo.strip()
    for nombre, v in (("panel", panel), ("auth", auth)):
        if not RE_DOMINIO.match(v):
            raise ErrorAcceso(f"«{v}» no parece un nombre de dominio válido (--{nombre}), p. ej. brain.101.cat")
    if panel == auth:
        raise ErrorAcceso("El panel y el inicio de sesión necesitan nombres distintos")
    if not RE_CORREO.match(correo):
        raise ErrorAcceso("Falta un correo válido (--correo): Let's Encrypt lo usa para avisar si el certificado va a caducar")
    if correo.split("@", 1)[1].lower() in DOMINIOS_DE_EJEMPLO:
        raise ErrorAcceso("Ese correo es un ejemplo, no uno real: escribe el tuyo (Let's Encrypt lo usa para avisarte si el certificado va a caducar)")
    return panel, auth, correo


def valores_nuevos(panel: str, auth: str, correo: str, compose_actual: str, sin_puerto_80: bool = False, puerto_https: int = 443) -> dict[str, str]:
    """Lo que se fija en el .env. COMPOSE_FILE conserva lo que ya hubiera (p. ej. docker-compose.sin-gpu.yml) y añade el proxy."""
    partes = [p for p in (compose_actual or "").split(":") if p]
    if not partes:
        partes = ["docker-compose.yml"]
    if SUPERPUESTO not in partes:
        partes.append(SUPERPUESTO)
    v = {"DOM_PANEL": panel, "DOM_AUTH": auth, "CORREO_ADMIN": correo, "TLS_MODO": "letsencrypt", "PANEL_URL": f"https://{panel}", "KEYCLOAK_URL_PUBLICA": f"https://{auth}",
         "COMPOSE_FILE": ":".join(partes)}
    if sin_puerto_80:
        v["PROXY_HTTP_BIND"] = "127.0.0.1:8088"          # el 80 de este equipo lo usa otro programa: el del proxy queda solo en local y el certificado se valida por el 443
    if puerto_https != 443:
        v["PROXY_HTTPS_PUERTO"] = str(puerto_https)      # el puerto del equipo donde escucha el reenviador (en Docker Desktop, 18443; Windows redirige su 443 a él)
    return v


def leer_env(texto: str) -> dict[str, str]:
    return {m.group(1): re.split(r"\s+#", m.group(2), maxsplit=1)[0].strip() for l in texto.splitlines() if (m := LINEA.match(l))}


def poner(texto: str, valores: dict[str, str | None]) -> str:
    """Fija (o quita, con None) esas claves en el texto del .env sin tocar las demás líneas."""
    lineas = texto.splitlines()
    pos = {m.group(1): i for i, l in enumerate(lineas) if (m := LINEA.match(l))}
    quitar = set()
    for k, v in valores.items():
        if v is None:
            if k in pos:
                quitar.add(pos[k])
        elif k in pos:
            lineas[pos[k]] = f"{k}={v}"
        else:
            lineas.append(f"{k}={v}")
    return "\n".join(l for i, l in enumerate(lineas) if i not in quitar) + "\n"


def escribir_env(ruta: Path, texto: str) -> None:
    tmp = ruta.with_name(ruta.name + ".tmp")
    tmp.write_text(texto, encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(ruta)


def compose(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", "compose", *args], cwd=RAIZ, check=check, text=True)


def keycloak_conserva_datos() -> bool:
    r = subprocess.run(["docker", "compose", "ps", "-aq", "keycloak"], cwd=RAIZ, capture_output=True, text=True)
    ctr = (r.stdout.split() or [""])[0]
    if not ctr:
        return False
    m = subprocess.run(["docker", "inspect", ctr, "--format", "{{range .Mounts}}{{.Destination}}{{\"\\n\"}}{{end}}"], capture_output=True, text=True)
    return "/opt/keycloak/data/h2" in m.stdout.split()


def resuelve(nombre: str) -> bool:
    try:
        socket.gethostbyname(nombre)
        return True
    except OSError:
        return False


def pasos_siguientes(panel: str, auth: str, puerto_https: int = 443, sin_puerto_80: bool = False) -> str:
    puertos = "443" if sin_puerto_80 else "80,443"
    redir = ""
    if puerto_https != 443:
        redir = f"""  2. Redirigir el 443 de Windows al puerto {puerto_https} del reenviador (PowerShell COMO ADMINISTRADOR; sustituye DIRECCION_DEL_PC por la dirección interna fija de este PC, p. ej. 192.168.1.102):
       netsh interface portproxy add v4tov4 listenaddress=DIRECCION_DEL_PC listenport=443 connectaddress=127.0.0.1 connectport={puerto_https}
       netsh interface portproxy show all
"""
    hosts_ip = "DIRECCION_DEL_PC" if puerto_https != 443 else "127.0.0.1"
    return f"""
Falta lo que está fuera del sistema (hazlo ahora; sin esto, desde internet no se llega):
  1. Cortafuegos de Windows (PowerShell COMO ADMINISTRADOR):
       New-NetFirewallRule -DisplayName "Cerebro HTTPS" -Direction Inbound -Protocol TCP -LocalPort {puertos} -Action Allow
{redir}  3. Router: reenvía los puertos TCP {"443" if sin_puerto_80 else "80 y 443"} a la dirección interna de este PC (y reserva esa dirección para el PC, para que no cambie).
  4. DNS: {panel} y {auth} deben apuntar a tu IP pública fija (los registros A de Hostalia).
  5. Desde ESTE PC, si el router no permite entrar por su propia IP pública, añade al fichero C:\\Windows\\System32\\drivers\\etc\\hosts (como administrador):
       {hosts_ip} {panel} {auth}
     (con Docker Desktop usa la dirección del PC y no 127.0.0.1: en 127.0.0.1:443 puede escuchar otro programa de Windows)
  6. Comprueba:  curl -I https://{panel}        (la primera vez tarda unos segundos en sacar el certificado)
     Si no sale, mira:  docker compose logs proxy reenvio --tail 30
Para volver atrás:  python3 despliegue/acceso_externo.py desactivar
"""


def activar(a: argparse.Namespace) -> int:
    panel, auth, correo = validar(a.panel, a.auth, a.correo)
    if not 1 <= a.puerto_https <= 65535:
        raise ErrorAcceso("--puerto-https debe estar entre 1 y 65535")
    ruta = RAIZ / ".env"
    if not ruta.exists():
        raise ErrorAcceso("Falta el fichero .env")
    if (RAIZ / ESTADO).exists():
        raise ErrorAcceso("El acceso externo ya está activado (hay un .acceso-externo.json). Para cambiarlo, primero «desactivar».")
    texto = ruta.read_text(encoding="utf-8")
    actual = leer_env(texto)
    nuevos = valores_nuevos(panel, auth, correo, actual.get("COMPOSE_FILE", ""), a.sin_puerto_80, a.puerto_https)
    if a.simular:
        print("Se fijaría en el .env:")
        for k, v in nuevos.items():
            print(f"  {k}={v}")
        print("Y se recrearían:", ", ".join(SERVICIOS))
        return 0
    if not keycloak_conserva_datos():
        raise ErrorAcceso("Keycloak todavía no conserva sus datos: sin eso, recrearlo con las direcciones nuevas podría perder los usuarios. Ejecuta antes  ./scripts/keycloak_conservar.sh")
    sin_dns = [d for d in (panel, auth) if not resuelve(d)]
    if sin_dns and not a.sin_dns:
        raise ErrorAcceso(f"Todavía no resuelven en DNS: {', '.join(sin_dns)}. Crea los registros A en Hostalia y espera a que se propaguen (o repite con --sin-dns, sabiendo que el certificado no se podrá sacar hasta entonces).")
    (RAIZ / ESTADO).write_text(json.dumps({k: actual.get(k) for k in nuevos}, indent=2), encoding="utf-8")
    os.chmod(RAIZ / ESTADO, 0o600)
    escribir_env(ruta, poner(texto, nuevos))
    print("→ .env actualizado (los valores anteriores quedan en .acceso-externo.json)")
    try:
        print("→ Recreando Keycloak, panel, API, proxy y reenviador")
        compose("up", "-d", "--no-build", *SERVICIOS)
        print("→ Ajustando el cliente de Keycloak a las nuevas direcciones")
        subprocess.run([sys.executable, str(RAIZ / "despliegue" / "configurar_keycloak.py")], cwd=RAIZ, check=True)
    except (subprocess.CalledProcessError, OSError) as e:
        print(f"\nAlgo ha fallado ({e}). Para dejarlo como estaba:  python3 despliegue/acceso_externo.py desactivar", file=sys.stderr)
        return 1
    print(pasos_siguientes(panel, auth, a.puerto_https, a.sin_puerto_80))
    return 0


def desactivar(_: argparse.Namespace) -> int:
    estado = RAIZ / ESTADO
    if not estado.exists():
        raise ErrorAcceso("El acceso externo no está activado (no hay .acceso-externo.json).")
    antes = json.loads(estado.read_text(encoding="utf-8"))
    ruta = RAIZ / ".env"
    escribir_env(ruta, poner(ruta.read_text(encoding="utf-8"), antes))
    print("→ .env devuelto a sus valores anteriores (el resto no se toca)")
    try:
        compose("up", "-d", "--no-build", "--remove-orphans", "keycloak", "panel", "api", "worker", "beat")
        compose("rm", "-sf", "proxy", "reenvio", check=False)
        subprocess.run([sys.executable, str(RAIZ / "despliegue" / "configurar_keycloak.py")], cwd=RAIZ, check=True)
    except (subprocess.CalledProcessError, OSError) as e:
        print(f"Algo ha fallado al volver atrás ({e}): mira docker compose ps", file=sys.stderr)
        return 1
    estado.unlink()
    print("Hecho: el acceso externo está desactivado. Recuerda quitar el reenvío de puertos del router y la regla del cortafuegos de Windows.")
    return 0


def puerto(a: argparse.Namespace) -> int:
    """Cambia el puerto del equipo donde escucha el reenviador HTTPS de un acceso externo YA activado (p. ej. pasar de una sonda manual a este reenviador)."""
    if not (RAIZ / ESTADO).exists():
        raise ErrorAcceso("El acceso externo no está activado: usa «activar».")
    if not 1 <= a.numero <= 65535:
        raise ErrorAcceso("El puerto debe estar entre 1 y 65535")
    ruta = RAIZ / ".env"
    antes = json.loads((RAIZ / ESTADO).read_text(encoding="utf-8"))
    actual = leer_env(ruta.read_text(encoding="utf-8"))
    antes.setdefault("PROXY_HTTPS_PUERTO", actual.get("PROXY_HTTPS_PUERTO"))        # para que «desactivar» lo quite
    (RAIZ / ESTADO).write_text(json.dumps(antes, indent=2), encoding="utf-8")
    os.chmod(RAIZ / ESTADO, 0o600)
    escribir_env(ruta, poner(ruta.read_text(encoding="utf-8"), {"PROXY_HTTPS_PUERTO": None if a.numero == 443 else str(a.numero)}))
    try:
        compose("up", "-d", "--no-build", "proxy", "reenvio")
    except (subprocess.CalledProcessError, OSError) as e:
        print(f"Algo ha fallado ({e}). Si el puerto {a.numero} ya lo usa otro contenedor (p. ej. una sonda manual «sonda-443»), quítalo con  docker rm -f sonda-443  y repite.", file=sys.stderr)
        return 1
    print(f"Reenviador HTTPS escuchando en el puerto {a.numero} de este equipo.")
    if a.numero != 443:
        print(f"Recuerda la redirección de Windows (PowerShell como administrador):  netsh interface portproxy add v4tov4 listenaddress=DIRECCION_DEL_PC listenport=443 connectaddress=127.0.0.1 connectport={a.numero}")
    return 0


def estado_(_: argparse.Namespace) -> int:
    e = RAIZ / ESTADO
    if not e.exists():
        print("Acceso externo: NO activado")
        return 0
    env = leer_env((RAIZ / ".env").read_text(encoding="utf-8"))
    print(f"Acceso externo: ACTIVADO · panel {env.get('PANEL_URL')} · inicio de sesión {env.get('KEYCLOAK_URL_PUBLICA')}")
    compose("ps", "proxy", check=False)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    s = p.add_subparsers(dest="orden", required=True)
    act = s.add_parser("activar")
    act.add_argument("--panel", required=True)
    act.add_argument("--auth", required=True)
    act.add_argument("--correo", required=True)
    act.add_argument("--simular", action="store_true")
    act.add_argument("--sin-dns", action="store_true")
    act.add_argument("--puerto-https", type=int, default=443, help="puerto de este equipo donde escucha el reenviador HTTPS (con Docker Desktop en Windows, 18443 y se redirige el 443 con netsh)")
    act.add_argument("--sin-puerto-80", action="store_true", help="el puerto 80 de este equipo lo usa otro programa: el proxy solo publica el 443")
    s.add_parser("desactivar")
    pu = s.add_parser("puerto", help="cambia el puerto del reenviador HTTPS en un acceso ya activado")
    pu.add_argument("numero", type=int)
    s.add_parser("estado")
    a = p.parse_args(argv)
    try:
        return {"activar": activar, "desactivar": desactivar, "estado": estado_, "puerto": puerto}[a.orden](a)
    except ErrorAcceso as e:
        print(f"No se puede: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
