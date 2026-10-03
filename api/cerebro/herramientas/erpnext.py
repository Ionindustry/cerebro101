"""ERPNext: fuente única de datos de negocio.

Cada departamento usa su propio usuario técnico (ERPNEXT_TOKEN_<DEPARTAMENTO>),
con los roles de ERPNext de su área. Los agentes leen y crean documentos en
BORRADOR; este módulo no expone ninguna operación de validar («submit»): eso
lo hace siempre una persona en ERPNext.
"""
from __future__ import annotations

import json
import os
from typing import Any

import httpx

from ..ajustes import ajustes
from .base import Herramienta, registrar


def _cabeceras(departamento: str) -> dict:
    token = os.environ.get(f"ERPNEXT_TOKEN_{departamento.upper()}") or os.environ.get("ERPNEXT_TOKEN", "")
    return {"Authorization": f"token {token}", "Accept": "application/json"}


async def listar(doctype: str, departamento: str, filtros: list | None = None,
                 campos: list[str] | None = None, limite: int = 50) -> list[dict]:
    params = {"limit_page_length": limite, "fields": json.dumps(campos or ["name"])}
    if filtros:
        params["filters"] = json.dumps(filtros)
    async with httpx.AsyncClient(base_url=ajustes.erpnext_url, timeout=30) as c:
        r = await c.get(f"/api/resource/{doctype}", params=params, headers=_cabeceras(departamento))
    r.raise_for_status()
    return r.json()["data"]


async def leer(doctype: str, nombre: str, departamento: str) -> dict:
    async with httpx.AsyncClient(base_url=ajustes.erpnext_url, timeout=30) as c:
        r = await c.get(f"/api/resource/{doctype}/{nombre}", headers=_cabeceras(departamento))
    r.raise_for_status()
    return r.json()["data"]


async def crear_borrador(doctype: str, datos: dict[str, Any], departamento: str) -> dict:
    datos = {**datos, "docstatus": 0}   # siempre borrador
    async with httpx.AsyncClient(base_url=ajustes.erpnext_url, timeout=30) as c:
        r = await c.post(f"/api/resource/{doctype}", json=datos, headers=_cabeceras(departamento))
    r.raise_for_status()
    return r.json()["data"]


registrar(Herramienta(
    nombre="erpnext",
    descripcion="ERP de la empresa: clientes, proyectos, artículos, precios, facturas, compras. "
                "Operaciones: listar, leer, crear_borrador (nunca valida documentos).",
    operaciones={"listar": listar, "leer": leer, "crear_borrador": crear_borrador},
))
