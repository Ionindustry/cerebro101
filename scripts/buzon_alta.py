"""Da de alta (o cambia la contraseña de) un buzón de correo de la empresa.

    python3 scripts/buzon_alta.py --id rrhh --direccion rrhh@101.cat --departamentos personas
    python3 scripts/buzon_alta.py --todos        # pide la contraseña de cada buzón ya configurado

Hace dos cosas: añade el buzón a config/buzones.yaml (qué departamentos lo pueden usar) y guarda su contraseña en
secretos/buzones.env, que nunca se sube a git. La contraseña se pide por teclado SIN mostrarla (o con --clave-env NOMBRE
se toma de una variable de entorno); no se escribe en pantalla ni en el historial. La API la lee sin reiniciar.
Con --usuario se indica el usuario de acceso si no es la propia dirección.
"""
from __future__ import annotations

import argparse
import getpass
import os
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
YAML = RAIZ / "config" / "buzones.yaml"
SECRETOS = RAIZ / "secretos" / "buzones.env"


def poner(ruta: Path, clave: str, valor: str) -> None:
    lineas = ruta.read_text(encoding="utf-8").splitlines() if ruta.exists() else []
    nueva = f"{clave}={valor}"
    if any(re.match(rf"^{re.escape(clave)}=", linea) for linea in lineas):
        lineas = [nueva if re.match(rf"^{re.escape(clave)}=", linea) else linea for linea in lineas]
    else:
        lineas.append(nueva)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    os.chmod(ruta, 0o644)         # el usuario del contenedor no es el de la máquina: necesita poder leerlo en el montaje de solo lectura


def añadir_a_yaml(ident: str, direccion: str, departamentos: list[str], descripcion: str) -> bool:
    """Añade el buzón al final del yaml sin reescribirlo (conserva comentarios). Devuelve False si ya existía."""
    texto = YAML.read_text(encoding="utf-8")
    if re.search(rf"^  {re.escape(ident)}:\s*$", texto, re.M):
        return False
    bloque = (f"  {ident}:\n    direccion: {direccion}\n    departamentos: [{', '.join(departamentos)}]\n"
              f"    descripcion: \"{descripcion}\"\n")
    YAML.write_text(texto.rstrip("\n") + "\n" + bloque, encoding="utf-8")
    return True


def main() -> int:
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("--id", help="nombre corto del buzón, p. ej. rrhh")
    a.add_argument("--todos", action="store_true", help="pide la contraseña de cada buzón de config/buzones.yaml (Intro vacío = saltar)")
    a.add_argument("--direccion", help="dirección completa, p. ej. rrhh@101.cat (obligatoria si el buzón es nuevo)")
    a.add_argument("--departamentos", help="departamentos que pueden usarlo, separados por comas (obligatorio si es nuevo)")
    a.add_argument("--descripcion", default="")
    a.add_argument("--usuario", help="usuario de acceso si no es la dirección")
    a.add_argument("--clave-env", help="toma la contraseña de esta variable de entorno en vez de pedirla")
    a.add_argument("--solo-clave", action="store_true", help="no toca config/buzones.yaml: solo guarda la contraseña")
    r = a.parse_args()
    if r.todos:
        import yaml
        for ident, b in (yaml.safe_load(YAML.read_text(encoding="utf-8")).get("buzones") or {}).items():
            clave = getpass.getpass(f"{b['direccion']} — contraseña (Intro para saltar, no se ve al escribir): ")
            if clave:
                poner(SECRETOS, f"CORREO_{ident.upper()}_CLAVE", clave)
                print(f"  guardada: {ident}")
        print("Listo. Comprueba con: docker compose exec api python /app/scripts/probar_buzones.py")
        return 0
    if not r.id:
        print("Indica --id <buzón> o --todos")
        return 2
    ident = r.id.lower()
    if not re.fullmatch(r"[a-z0-9_]+", ident):
        print("--id solo admite letras minúsculas, números y _")
        return 2
    if not r.solo_clave:
        import yaml
        existente = (yaml.safe_load(YAML.read_text(encoding="utf-8")).get("buzones") or {}).get(ident)
        if existente is None:
            if not (r.direccion and r.departamentos) or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", r.direccion):
                print("Buzón nuevo: indica --direccion (válida) y --departamentos")
                return 2
            añadir_a_yaml(ident, r.direccion, [d.strip() for d in r.departamentos.split(",") if d.strip()], r.descripcion)
            print(f"Añadido «{ident}» a config/buzones.yaml")
        else:
            print(f"«{ident}» ya está en config/buzones.yaml (no se cambia; edítalo a mano para cambiar departamentos)")
    clave = os.environ.get(r.clave_env, "") if r.clave_env else getpass.getpass(f"Contraseña del buzón {ident} (no se ve al escribir): ")
    if not clave:
        print("No se ha indicado contraseña; no se guarda nada")
        return 1
    poner(SECRETOS, f"CORREO_{ident.upper()}_CLAVE", clave)
    if r.usuario:
        poner(SECRETOS, f"CORREO_{ident.upper()}_USUARIO", r.usuario)
    print(f"Contraseña guardada en secretos/buzones.env. Comprueba la conexión con: python3 scripts/probar_buzones.py --id {ident}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
