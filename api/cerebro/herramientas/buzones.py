"""Buzones de correo de la empresa (config/buzones.yaml): qué departamento puede usar cada uno, con qué servidor y con qué credenciales.

Las credenciales (CORREO_<BUZON>_CLAVE, y CORREO_<BUZON>_USUARIO si el usuario no es la dirección) viven en el fichero
secretos/buzones.env, montado solo en la API y el worker; se relee si cambia, así que dar de alta un buzón no obliga a reiniciar.
También valen como variables de entorno. Nunca están en la configuración ni se devuelven al modelo.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml

from ..ajustes import ajustes

SEGURIDADES = ("ssl", "starttls", "ninguna")
RUTA_CONFIG: str | None = None                      # solo para pruebas y scripts; por defecto config/buzones.yaml
RUTA_SECRETOS = "/run/secretos/buzones.env"          # idem: en producción lo monta docker-compose
_LEIDO: dict = {"ruta": None, "mtime": None, "valores": {}}


def _secreto(nombre: str) -> str:
    if nombre in os.environ:
        return os.environ[nombre]
    ruta = Path(RUTA_SECRETOS)
    try:
        mtime = ruta.stat().st_mtime_ns
    except OSError:
        return ""
    if _LEIDO["ruta"] != str(ruta) or _LEIDO["mtime"] != mtime:
        valores = {}
        for linea in ruta.read_text(encoding="utf-8").splitlines():
            linea = linea.strip()
            if linea and not linea.startswith("#") and "=" in linea:
                k, v = linea.split("=", 1)
                valores[k.strip()] = v.strip().strip("'\"")
        _LEIDO.update(ruta=str(ruta), mtime=mtime, valores=valores)
    return _LEIDO["valores"].get(nombre, "")


@lru_cache(maxsize=4)
def _cargar(ruta: str) -> dict:
    return yaml.safe_load(Path(ruta).read_text(encoding="utf-8")) or {}


def cargar() -> dict:
    return _cargar(RUTA_CONFIG or str(Path(ajustes.dir_config) / "buzones.yaml"))


def limpiar_cache() -> None:
    _cargar.cache_clear()


def direcciones_propias() -> set[str]:
    return {b["direccion"].lower() for b in (cargar().get("buzones") or {}).values()}


def buzones_de(departamento: str) -> list[str]:
    return [i for i, b in (cargar().get("buzones") or {}).items() if departamento in (b.get("departamentos") or [])]


def resolver(departamento: str, buzon: str | None) -> tuple[str, dict]:
    """El buzón que va a usar el agente de `departamento`: el que pide (si le corresponde) o el único que tiene."""
    permitidos = buzones_de(departamento)
    todos = cargar().get("buzones") or {}
    if not permitidos:
        raise PermissionError(f"El departamento «{departamento}» no tiene ningún buzón de correo asignado (config/buzones.yaml)")
    if buzon is None or buzon == "":
        if len(permitidos) == 1:
            buzon = permitidos[0]
        else:
            raise PermissionError(f"Indica en qué buzón: {', '.join(permitidos)}")
    if buzon not in permitidos:
        raise PermissionError(f"El departamento «{departamento}» no puede usar el buzón «{buzon}». Puede usar: {', '.join(permitidos)}")
    return buzon, todos[buzon]


def servidor(buzon: str, protocolo: str) -> dict:
    """Servidor `imap` o `smtp` del buzón (el suyo propio si lo define, y si no el de `servidor`)."""
    cfg = cargar()
    propio = ((cfg.get("buzones") or {}).get(buzon) or {}).get(protocolo) or {}
    s = {**(cfg.get("servidor") or {}).get(protocolo, {}), **propio}
    if s.get("seguridad", "ssl") not in SEGURIDADES:
        raise ValueError(f"seguridad «{s.get('seguridad')}» no válida en el buzón {buzon}: use {', '.join(SEGURIDADES)}")
    s.setdefault("seguridad", "ssl")
    return s


def credenciales(buzon: str) -> tuple[str, str]:
    """(usuario, clave). El usuario es la dirección si no se indica otro. Sin clave, el buzón no está dado de alta."""
    ident = buzon.upper()
    clave = _secreto(f"CORREO_{ident}_CLAVE")
    if not clave:
        raise PermissionError(f"El buzón «{buzon}» no está configurado: falta su contraseña. Se da de alta con "
                              f"scripts/buzon_alta.py --id {buzon} (la guarda en .env.buzones) y se reinicia la API")
    direccion = ((cargar().get("buzones") or {}).get(buzon) or {}).get("direccion", "")
    return _secreto(f"CORREO_{ident}_USUARIO") or direccion, clave


def activo(buzon: str) -> bool:
    return bool(_secreto(f"CORREO_{buzon.upper()}_CLAVE"))
