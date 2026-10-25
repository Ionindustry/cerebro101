"""Activa Jev (la nube de TypeSafe) en el Cerebro: guarda la clave en el .env, enciende USAR_JEV_NUBE y comprueba que responde.

    python3 scripts/jev_activar.py            # pide la clave sin mostrarla
    python3 scripts/jev_activar.py --probar   # solo comprueba la clave que ya hay en el .env

La clave se consigue en console.typesafe.ai. Se escribe SOLO en el .env (que no se sube a git); no se muestra ni se guarda en ningún otro sitio.
Después hay que recrear la API: docker compose up -d --force-recreate --no-deps api worker beat
"""
from __future__ import annotations

import argparse
import getpass
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ENV = Path(__file__).resolve().parent.parent / ".env"
URL = "https://api.typesafe.ai"


def leer(clave: str) -> str:
    m = re.search(rf"^{clave}=(.*)$", ENV.read_text(encoding="utf-8") if ENV.exists() else "", re.M)
    return m.group(1).strip().strip("'\"") if m else ""


def poner(clave: str, valor: str) -> None:
    texto = ENV.read_text(encoding="utf-8") if ENV.exists() else ""
    linea = f"{clave}={valor}"
    texto = re.sub(rf"^{clave}=.*$", lambda _m: linea, texto, flags=re.M) if re.search(rf"^{clave}=", texto, re.M) else texto.rstrip("\n") + f"\n{linea}\n"
    ENV.write_text(texto, encoding="utf-8")
    ENV.chmod(0o600)


def probar(clave: str, url: str) -> tuple[bool, str]:
    cuerpo = json.dumps({"model": "jev-latest", "state": "Prueba de funcionamiento: el sol sale por el este.",
                         "questions": {"q": {"type": "noul", "instructions": "¿Es cierto lo que se afirma en el estado?"}}}).encode()
    req = urllib.request.Request(f"{url.rstrip('/')}/v1/systemone", data=cuerpo, method="POST",
                                 headers={"Authorization": f"Bearer {clave}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            p = json.load(r)["answers"]["q"]["noul"]
        return True, f"Jev responde (probabilidad de «sí»: {p})"
    except urllib.error.HTTPError as e:
        return False, {401: "la clave es incorrecta o ha caducado", 403: "la clave no tiene permiso", 429: "límite de uso superado"}.get(e.code, f"error {e.code}")
    except Exception as e:  # noqa: BLE001
        return False, f"no se ha podido conectar ({type(e).__name__})"


def main() -> int:
    a = argparse.ArgumentParser()
    a.add_argument("--probar", action="store_true", help="solo comprueba la clave del .env")
    r = a.parse_args()
    url = leer("JEV_URL") or URL
    if r.probar:
        clave = leer("JEV_API_KEY")
        if not clave:
            print("No hay JEV_API_KEY en el .env. Ejecuta sin --probar para ponerla.")
            return 1
    else:
        clave = getpass.getpass("Clave de Jev (no se ve al escribir; se guarda solo en el .env): ").strip()
        if not clave:
            print("No se ha indicado ninguna clave; no se cambia nada.")
            return 1
    ok, msg = probar(clave, url)
    print(("OK: " if ok else "FALLA: ") + msg)
    if not r.probar:
        if not ok:
            print("No se guarda una clave que no funciona. Revísala en console.typesafe.ai e inténtalo de nuevo.")
            return 1
        poner("JEV_API_KEY", clave)
        poner("JEV_URL", url)
        poner("USAR_JEV_NUBE", "true")
        print("Guardado en el .env. Falta recrear la API para que lo use:\n  docker compose up -d --force-recreate --no-deps api worker beat")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
