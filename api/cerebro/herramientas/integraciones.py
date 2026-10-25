"""Lectura de config/integraciones.yaml y credenciales por departamento."""
from __future__ import annotations

import os
from functools import lru_cache

import yaml

from ..ajustes import ajustes


@lru_cache(maxsize=1)
def config() -> dict:
    with open(ajustes.dir_config / "integraciones.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def credenciales(servicio: str, departamento: str) -> tuple[str, str]:
    """CORREO_COMERCIAL_USUARIO / CORREO_COMERCIAL_CLAVE, con CORREO_USUARIO / CORREO_CLAVE de reserva."""
    dep = departamento.upper()
    usuario = os.environ.get(f"{servicio}_{dep}_USUARIO") or os.environ.get(f"{servicio}_USUARIO", "")
    clave = os.environ.get(f"{servicio}_{dep}_CLAVE") or os.environ.get(f"{servicio}_CLAVE", "")
    if not usuario:
        raise PermissionError(f"No hay cuenta de {servicio.lower()} configurada para {departamento}")
    return usuario, clave
