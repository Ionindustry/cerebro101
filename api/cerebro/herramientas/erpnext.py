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


AYUDA_DOCUMENTOS = (
    "Documentos habituales (doctype: campos; los campos pueden variar con la versión): "
    "Customer(customer_name, customer_type, customer_group, territory, email_id); Supplier(supplier_name, supplier_group); "
    "Item(item_code, item_name, item_group, stock_uom, standard_rate); Bin = existencias(item_code, warehouse, actual_qty); "
    "Quotation(party_name, transaction_date, items); Sales Order(customer, transaction_date, delivery_date, items); "
    "Sales Invoice(customer, posting_date, due_date, items); Purchase Order(supplier, transaction_date, schedule_date, items); "
    "Purchase Invoice(supplier, bill_date, items); Project(project_name, status, expected_start_date, expected_end_date); "
    "Task(subject, status, project); Lead(lead_name, company_name, email_id, status); Employee(employee_name, department, status). "
    "En «items» va una lista de {item_code, qty, rate}.")

registrar(Herramienta(
    nombre="erpnext",
    descripcion="ERP de la empresa: clientes, proyectos, artículos, precios, facturas, compras. Nunca valida documentos: "
                "solo los lee o los deja en borrador para que una persona los valide.",
    operaciones={"listar": listar, "leer": leer, "crear_borrador": crear_borrador},
    ayuda={"listar": "lista documentos. filtros = lista de [campo, operador, valor], p. ej. [[\"status\", \"=\", \"Open\"]]. " + AYUDA_DOCUMENTOS,
           "leer": "un documento completo por su nombre (doctype y nombre exactos, p. ej. Customer + «Comunitat Vilanova SL»)",
           "crear_borrador": "crea un documento en BORRADOR; «datos» lleva los campos del documento"},
    ejemplos={"listar": {"doctype": "Customer", "campos": ["customer_name"], "limite": 10},
              "crear_borrador": {"doctype": "Sales Invoice", "datos": {"customer": "Comunitat Vilanova SL", "items": [{"item_code": "ART-001", "qty": 2, "rate": 150}]}}},
))
