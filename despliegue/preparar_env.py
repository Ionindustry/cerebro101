"""Prepara el .env de producción: añade lo que falte, genera contraseñas aleatorias donde haya «cambia-esto» y fija las
direcciones públicas a partir del dominio. No pisa ningún valor que ya esté rellenado.

Uso:  python despliegue/preparar_env.py --dominio 101.cat --correo it@101.cat [--tls letsencrypt|interno]
                                        [--env .env] [--ejemplo .env.example]
"""
from __future__ import annotations

import argparse
import re
import secrets
import sys
from pathlib import Path

PLACEHOLDERS = {"", "cambia-esto", "pk-lf-cambia-esto", "sk-lf-cambia-esto"}
SUFIJOS_SECRETOS = ("_PASSWORD", "_SECRET", "_SALT")
LINEA = re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$")


def limpiar(valor: str) -> str:
    """Quita el comentario al final de la línea del ejemplo («valor   # explicación»)."""
    return re.split(r"\s+#", valor, maxsplit=1)[0].strip()


def generar(clave: str) -> str | None:
    """Valor aleatorio para las claves que lo necesitan; None si se deja como esté (claves de servicios externos…)."""
    if clave == "LANGFUSE_ENCRYPTION_KEY":
        return secrets.token_hex(32)                     # exactamente 64 caracteres hexadecimales
    if clave == "LANGFUSE_PUBLIC_KEY":
        return "pk-lf-" + secrets.token_hex(16)
    if clave == "LANGFUSE_SECRET_KEY":
        return "sk-lf-" + secrets.token_hex(16)
    if clave.endswith(SUFIJOS_SECRETOS):
        return secrets.token_hex(16)
    return None


def direcciones(dominio: str, correo: str, tls: str) -> dict[str, str]:
    """Todo lo que depende del dominio. Se fija siempre que se indica --dominio."""
    d = {"DOMINIO": dominio, "CORREO_ADMIN": correo, "TLS_MODO": tls,
         "DOM_PANEL": f"cerebro.{dominio}", "DOM_AUTH": f"auth.{dominio}",
         "DOM_ERP": f"erp.{dominio}", "DOM_TRAZAS": f"trazas.{dominio}"}
    return {**d,
            "CEREBRO_MODO": "produccion", "PANEL_USUARIO_DESARROLLO": "",
            "PANEL_URL": f"https://{d['DOM_PANEL']}", "KEYCLOAK_URL_PUBLICA": f"https://{d['DOM_AUTH']}",
            "LANGFUSE_URL_PUBLICA": f"https://{d['DOM_TRAZAS']}", "ERPNEXT_SITE": d["DOM_ERP"],
            "LANGFUSE_INIT_USER_EMAIL": correo}


def completar(ejemplo: str, actual: str, forzar: dict[str, str]) -> tuple[str, dict[str, str]]:
    """Devuelve (nuevo contenido del .env, {clave: 'añadida'|'generada'|'fijada'}) sin tocar lo ya rellenado."""
    cambios: dict[str, str] = {}
    lineas = actual.splitlines()
    presentes = {m.group(1): i for i, l in enumerate(lineas) if (m := LINEA.match(l))}
    for clave, valor in forzar.items():
        if clave in presentes:
            if limpiar(LINEA.match(lineas[presentes[clave]]).group(2)) != valor:
                lineas[presentes[clave]] = f"{clave}={valor}"
                cambios[clave] = "fijada"
    for l in ejemplo.splitlines():
        m = LINEA.match(l)
        if not m or m.group(1) in forzar:
            continue
        clave, valor = m.group(1), limpiar(m.group(2))
        if clave in presentes:
            actual_valor = limpiar(LINEA.match(lineas[presentes[clave]]).group(2))
            if actual_valor in PLACEHOLDERS and (nuevo := generar(clave)):
                lineas[presentes[clave]] = f"{clave}={nuevo}"
                cambios[clave] = "generada"
        else:
            nuevo = generar(clave) if valor in PLACEHOLDERS else None
            lineas.append(f"{clave}={nuevo if nuevo else valor}")
            presentes[clave] = len(lineas) - 1
            cambios[clave] = "generada" if nuevo else "añadida"
    for clave, valor in forzar.items():
        if clave not in presentes:
            lineas.append(f"{clave}={valor}")
            cambios[clave] = "fijada"
    return "\n".join(lineas) + "\n", cambios


def main() -> int:
    raiz = Path(__file__).resolve().parent.parent
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dominio")
    p.add_argument("--correo")
    p.add_argument("--tls", choices=["letsencrypt", "interno"], default="letsencrypt")
    p.add_argument("--env", default=str(raiz / ".env"))
    p.add_argument("--ejemplo", default=str(raiz / ".env.example"))
    a = p.parse_args()
    forzar: dict[str, str] = {}
    if a.dominio:
        if not a.correo:
            p.error("indica también --correo (avisos de certificados y administrador de Langfuse)")
        if not re.fullmatch(r"[a-z0-9]([a-z0-9.-]*[a-z0-9])?\.[a-z]{2,}", a.dominio):
            p.error(f"dominio no válido: {a.dominio}")
        forzar = direcciones(a.dominio, a.correo, a.tls)
    destino = Path(a.env)
    nuevo, cambios = completar(Path(a.ejemplo).read_text(encoding="utf-8"),
                               destino.read_text(encoding="utf-8") if destino.exists() else "", forzar)
    destino.write_text(nuevo, encoding="utf-8")
    destino.chmod(0o600)
    for clave, que in cambios.items():
        print(f"  {que:9} {clave}")           # nunca se imprimen los valores
    print(f"{destino}: {len(cambios)} cambios (permisos 600)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
