"""Busca secretos que no deberían estar en git: claves privadas, tokens, contraseñas asignadas en claro y direcciones con usuario y contraseña.

    python3 scripts/comprobar_secretos.py               # ficheros del repositorio (lo que hay ahora)
    python3 scripts/comprobar_secretos.py --historial   # además, todo lo que se haya añadido alguna vez en cualquier commit

Sale con código 1 si encuentra algo. No imprime el secreto entero: solo fichero, línea y el tipo de hallazgo con el valor tapado.
Los valores de prueba evidentes (vacíos, «x», «clave», «changeme», «${VARIABLE}»…) no cuentan. Se ejecuta también en la integración continua.
"""
from __future__ import annotations

import re
import subprocess
import sys

PATRONES = [
    ("clave privada", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----")),
    ("token de GitHub", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{20,}")),
    ("clave de AWS", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("token de Slack", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("clave tipo sk-", re.compile(r"\bsk-[A-Za-z0-9]{24,}")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    ("dirección con usuario y contraseña", re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s/:@'\"]+:(?![\s$<{*]|\$\{|%s|%\()[^\s/@'\"]{4,}@[^\s/'\"]+")),
    ("asignación de secreto en claro", re.compile(
        r"""(?i)\b[A-Z0-9_]*(?:PASSWORD|PASSWD|SECRET|API_?KEY|TOKEN|CLAVE)[A-Z0-9_]*\s*[:=]\s*['"]?([A-Za-z0-9+/_\-.=!#$%^&*]{16,})['"]?\s*$""")),
]
# valores que son marcadores o de prueba
FALSOS = re.compile(r"(?i)^(x+|clave[-_a-z0-9]*|changeme.*|password|contrasena|ejemplo.*|test.*|prueba.*|dummy.*|\$\{.*\}|<.*>|\*+|none|null|false|true|sin[-_ ]clave|vacio|secreto|clave-de-prueba|.*cambia.*|.*prueba.*)$")
# Un valor que es el NOMBRE de una variable de entorno (LIC_NATS_PASSWORD, en mayúsculas y con guiones bajos) no es un secreto: es a qué variable se llama.
NOMBRE_ENTORNO = re.compile(r"^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+$")
OMITIR = re.compile(r"(^|/)(package-lock\.json|.*\.(png|jpg|jpeg|pdf|onnx|ico|woff2?))$|^api/tests/|^panel/test/")


def hallazgos(texto: str, nombre: str, base_linea: int = 0):
    for n, linea in enumerate(texto.splitlines(), 1):
        if len(linea) > 600:
            continue
        for tipo, rx in PATRONES:
            m = rx.search(linea)
            if not m:
                continue
            valor = m.group(1) if m.groups() else m.group(0)
            if tipo.startswith("dirección"):
                u = re.search(r"://([^:@/]+):([^@/]+)@", valor)
                # usuario:usuario@ es la contraseña de desarrollo, y una contraseña que es un marcador evidente («clave», «prueba…», «changeme»…)
                # no cuenta, igual que en las asignaciones: así lo dice la cabecera de este fichero.
                if u and (u.group(1) == u.group(2) or FALSOS.match(u.group(2))):
                    continue
            limpio = valor.strip("'\" ")
            if FALSOS.match(limpio) or NOMBRE_ENTORNO.match(limpio) or valor.startswith(("os.environ", "_env", "ajustes.")):
                continue
            tapado = valor[:3] + "…" + f"({len(valor)} caracteres)"
            yield f"{nombre}:{base_linea + n}: {tipo} [{tapado}]"


def ficheros() -> list[str]:
    return subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True).stdout.split("\n")


def principal() -> int:
    encontrados: list[str] = []
    for f in filter(None, ficheros()):
        if OMITIR.search(f):
            continue
        try:
            texto = open(f, encoding="utf-8").read()
        except (UnicodeDecodeError, OSError):
            continue
        encontrados += list(hallazgos(texto, f))
    if "--historial" in sys.argv:
        log = subprocess.run(["git", "log", "--all", "-p", "--no-color", "--format=commit %h", "-U0"], capture_output=True, text=True, errors="replace", check=True).stdout
        commit, fichero = "", ""
        for linea in log.splitlines():
            if linea.startswith("commit "):
                commit = linea[7:]
            elif linea.startswith("+++ b/"):
                fichero = linea[6:]
            elif linea.startswith("+") and not linea.startswith("+++") and fichero and not OMITIR.search(fichero):
                encontrados += [f"[historial {commit}] {h}" for h in hallazgos(linea[1:], fichero)]
    unicos = sorted(set(encontrados))
    for h in unicos:
        print(h)
    print(f"\n{len(unicos)} hallazgo(s)" if unicos else "Sin secretos a la vista.")
    return 1 if unicos else 0


if __name__ == "__main__":
    sys.exit(principal())
