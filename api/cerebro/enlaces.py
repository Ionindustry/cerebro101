"""Direcciones públicas de los servicios para los enlaces que salen en correos y avisos.

Un enlace con «localhost» solo funciona en el propio equipo: quien abre el correo desde fuera (el móvil, otra oficina) no llega. La dirección real se pone UNA vez en el `.env`
(`PANEL_URL` para el panel, `CRM_URL_PUBLICA` para el CRM) y todos los correos la usan; lo que se ponga en `config/licitaciones.yaml` tiene prioridad si no está vacío.
"""
from __future__ import annotations

import os
import re

PROHIBIDAS = re.compile(r"^https?://[^/\s]*@", re.I)          # nada de usuario:clave@ dentro de un enlace que va por correo


def valida(url) -> str | None:
    """La dirección sin barra final si es http(s) y no lleva credenciales; si no, None."""
    u = str(url or "").strip().rstrip("/")
    if not u.startswith(("http://", "https://")) or PROHIBIDAS.match(u) or len(u) > 300 or re.search(r"\s", u):
        return None
    return u


def desde_entorno(variable: str) -> str | None:
    return valida(os.environ.get(variable))


def es_local(url: str) -> bool:
    return bool(re.match(r"^https?://(localhost|127\.|0\.0\.0\.0|\[::1\])", url or "", re.I))
