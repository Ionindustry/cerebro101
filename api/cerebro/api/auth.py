"""Identificación de usuarios con Keycloak (tokens JWT).

Roles esperados en Keycloak: «direccion», «responsable» y grupos con el id de cada
departamento (licitaciones, marketing…). En modo desarrollo (CEREBRO_MODO=desarrollo)
se aceptan las cabeceras X-Usuario, X-Roles y X-Departamentos para probar sin Keycloak.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

import httpx
import jwt
from fastapi import Header, HTTPException

MODO = os.environ.get("CEREBRO_MODO", "produccion")
KEYCLOAK_URL = os.environ.get("KEYCLOAK_URL", "http://keycloak:8080")
REALM = os.environ.get("KEYCLOAK_REALM", "cerebro")
CLIENTE = os.environ.get("KEYCLOAK_CLIENTE", "cerebro-panel")


@dataclass
class Usuario:
    id: str
    roles: set[str]
    departamentos: set[str]


@lru_cache(maxsize=1)
def _jwks() -> jwt.PyJWKClient:
    return jwt.PyJWKClient(f"{KEYCLOAK_URL}/realms/{REALM}/protocol/openid-connect/certs")


async def usuario_actual(authorization: str | None = Header(default=None),
                         x_usuario: str | None = Header(default=None),
                         x_roles: str | None = Header(default=None),
                         x_departamentos: str | None = Header(default=None)) -> Usuario:
    if MODO == "desarrollo" and x_usuario:
        return Usuario(x_usuario, set(filter(None, (x_roles or "").split(","))),
                       set(filter(None, (x_departamentos or "").split(","))))
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Inicia sesión para usar el Cerebro")
    token = authorization.removeprefix("Bearer ")
    try:
        clave = _jwks().get_signing_key_from_jwt(token).key
        datos = jwt.decode(token, clave, algorithms=["RS256"], audience=CLIENTE)
    except Exception as e:
        raise HTTPException(401, f"Sesión no válida: {e}") from e
    roles = set(datos.get("realm_access", {}).get("roles", []))
    grupos = {g.strip("/") for g in datos.get("groups", [])}
    return Usuario(datos.get("preferred_username", datos["sub"]), roles, grupos)
