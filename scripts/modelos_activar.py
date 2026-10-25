"""Pone la clave de Claude (Anthropic) o de ChatGPT (OpenAI) en el Cerebro y comprueba que funciona.

    python3 scripts/modelos_activar.py claude            # pide la clave sin mostrarla
    python3 scripts/modelos_activar.py chatgpt
    python3 scripts/modelos_activar.py claude --probar   # solo comprueba la clave que ya hay en el .env

Las claves se consiguen en console.anthropic.com y platform.openai.com. Se escriben SOLO en el .env (que no se sube a git); no se muestran
ni se guardan en ningún otro sitio. Poner la clave NO conecta el modelo: eso se hace con el interruptor del panel (Agentes → Modelos externos).
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
PROVEEDORES = {
    "claude": {"variable": "ANTHROPIC_API_KEY", "prefijo": "sk-ant-", "nombre": "Claude (Anthropic)", "url": "https://api.anthropic.com/v1/models",
               "cabeceras": lambda k: {"x-api-key": k, "anthropic-version": "2023-06-01"}},
    "chatgpt": {"variable": "OPENAI_API_KEY", "prefijo": "sk-", "nombre": "ChatGPT (OpenAI)", "url": "https://api.openai.com/v1/models",
                "cabeceras": lambda k: {"Authorization": f"Bearer {k}"}},
}


def leer(clave: str) -> str:
    m = re.search(rf"^{clave}=(.*)$", ENV.read_text(encoding="utf-8") if ENV.exists() else "", re.M)
    return m.group(1).strip().strip("'\"") if m else ""


def poner(clave: str, valor: str) -> None:
    texto = ENV.read_text(encoding="utf-8") if ENV.exists() else ""
    linea = f"{clave}={valor}"
    texto = re.sub(rf"^{clave}=.*$", lambda _m: linea, texto, flags=re.M) if re.search(rf"^{clave}=", texto, re.M) else texto.rstrip("\n") + f"\n{linea}\n"
    ENV.write_text(texto, encoding="utf-8")
    ENV.chmod(0o600)


def probar(p: dict, clave: str) -> tuple[bool, str]:
    """Pide la lista de modelos: comprueba la clave sin gastar nada ni enviar ningún dato."""
    req = urllib.request.Request(p["url"], headers=p["cabeceras"](clave))
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            n = len(json.load(r).get("data", []))
        return True, f"{p['nombre']} responde (la clave ve {n} modelos)"
    except urllib.error.HTTPError as e:
        return False, {401: "la clave es incorrecta o ha caducado", 403: "la clave no tiene permiso", 429: "límite de uso superado"}.get(e.code, f"error {e.code}")
    except Exception as e:  # noqa: BLE001
        return False, f"no se ha podido conectar ({type(e).__name__})"


def limpiar(clave: str) -> str:
    """Quita lo que se cuela al pegar: marcas invisibles de la terminal, comillas, espacios, saltos de línea y el «Bearer » o «export X=» de algún ejemplo."""
    clave = re.sub(r"\x1b\[[0-9;]*[~A-Za-z]|\[20[01]~", "", clave)      # el «pegado entre corchetes» de algunas terminales añade ESC[200~ … ESC[201~
    clave = "".join(c for c in clave if c.isprintable()).strip().strip("'\"").strip()
    clave = re.sub(r"^(export\s+)?[A-Z_]+=", "", clave).strip().strip("'\"")
    return re.sub(r"^Bearer\s+", "", clave).replace(" ", "").replace("\n", "")


def aviso_formato(p: dict, clave: str) -> str:
    """Pistas sobre la forma de la clave sin mostrarla: solo su longitud y cómo empieza (no sirve para usarla)."""
    pistas = [f"Recibida una clave de {len(clave)} caracteres que empieza por «{clave[:7]}…»."]
    if not clave.startswith(p["prefijo"]):
        pistas.append(f"Las claves de {p['nombre']} empiezan por «{p['prefijo']}»: puede que sea de otro servicio o que no se haya pegado entera.")
    if clave.startswith("sk-ant-oat"):
        pistas.append("Eso es un token de inicio de sesión (de Claude Code), no una clave de API: crea una en console.anthropic.com → API Keys.")
    if len(clave) < 40:
        pistas.append("Es muy corta: las claves de API tienen más de 80 caracteres. Seguramente no se ha pegado entera.")
    return " ".join(pistas)


def main() -> int:
    a = argparse.ArgumentParser()
    a.add_argument("proveedor", choices=sorted(PROVEEDORES))
    a.add_argument("--probar", action="store_true", help="solo comprueba la clave del .env")
    r = a.parse_args()
    p = PROVEEDORES[r.proveedor]
    if r.probar:
        clave = leer(p["variable"])
        if not clave:
            print(f"No hay {p['variable']} en el .env. Ejecuta sin --probar para ponerla.")
            return 1
    else:
        clave = limpiar(getpass.getpass(f"Clave de {p['nombre']} (no se ve al escribir; se guarda solo en el .env): "))
        if not clave:
            print("No se ha indicado ninguna clave; no se cambia nada.")
            return 1
    ok, msg = probar(p, clave)
    print(("OK: " if ok else "FALLA: ") + msg)
    if not ok and "incorrecta" in msg:
        print(aviso_formato(p, clave))
    if not r.probar:
        if not ok:
            print("No se guarda una clave que no funciona. Revísala e inténtalo de nuevo.")
            return 1
        poner(p["variable"], clave)
        print("Guardada en el .env. Falta recrear la API para que la use y conectar el modelo desde el panel (Agentes):\n"
              "  docker compose up -d --force-recreate --no-deps api worker beat")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
