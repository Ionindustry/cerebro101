"""ERPNext: fuente única de datos de negocio.

Cada departamento usa su propio usuario técnico (ERPNEXT_TOKEN_<DEPARTAMENTO>),
con los roles de ERPNext de su área. Los agentes leen y crean documentos en
BORRADOR; este módulo no expone ninguna operación de validar («submit»): eso
lo hace siempre una persona en ERPNext.
"""
from __future__ import annotations

import asyncio
import functools
import json
import logging
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
import yaml

from ..ajustes import ajustes
from .base import Herramienta, registrar

log = logging.getLogger("cerebro.erpnext")
_DOCTYPE = re.compile(r"^[A-Za-z][A-Za-z0-9 _-]{1,80}$")
_NOMBRE_PROHIBIDO = re.compile(r"[/\\?#%]|\.\.|[\x00-\x1f]")      # un nombre de documento no puede ser una ruta ni llevar parámetros


@functools.lru_cache(maxsize=4)
def _politica(dir_config: str) -> dict:
    ruta = Path(dir_config) / "erp_acceso.yaml"
    if not ruta.exists():
        return {"modo": "bloquear", "departamentos": {}}          # sin política, nada: no se abre el ERP por olvido
    return yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}


def comprobar_acceso(departamento: str, doctype: str, accion: str, nombre: str | None = None) -> None:
    """Política de config/erp_acceso.yaml: qué documentos puede tocar cada departamento. `accion`: «leer» o «borrador».
    Además impide que un nombre de documento se use para salirse de /api/resource/ (rutas, parámetros)."""
    if not isinstance(doctype, str) or not _DOCTYPE.match(doctype):
        raise PermissionError(f"«{str(doctype)[:60]}» no es un tipo de documento válido")
    if nombre is not None and (not isinstance(nombre, str) or not nombre or _NOMBRE_PROHIBIDO.search(nombre)):
        raise PermissionError("El nombre del documento no es válido (no puede llevar «/», «..», «?», «#» ni «%»)")
    pol = _politica(str(ajustes.dir_config))
    permitidos = ((pol.get("departamentos") or {}).get(departamento) or {}).get(accion) or []
    if doctype in permitidos:
        return
    verbo = "consultar" if accion == "leer" else "crear en borrador"
    ejemplos = ", ".join(permitidos[:12]) + ("…" if len(permitidos) > 12 else "")
    mensaje = (f"El departamento «{departamento}» no tiene permitido {verbo} «{doctype}» en el ERP/CRM (config/erp_acceso.yaml). "
               + (f"Puede: {ejemplos}." if permitidos else "No tiene ningún documento permitido para esta acción."))
    if (pol.get("modo") or "bloquear") == "avisar":
        log.warning("ACCESO FUERA DE POLÍTICA (solo aviso): %s", mensaje)
        return
    log.warning("Acceso al ERP bloqueado: %s", mensaje)
    raise PermissionError(mensaje)


def _cabeceras(departamento: str) -> dict:
    token = os.environ.get(f"ERPNEXT_TOKEN_{departamento.upper()}") or os.environ.get("ERPNEXT_TOKEN", "")
    if not token:
        # Sin esto el ERP responde 401/403 y la persona solo ve un error HTTP sin pistas
        raise PermissionError(
            f"No hay clave de ERPNext para el departamento «{departamento}» (falta ERPNEXT_TOKEN_{departamento.upper()} en el .env). "
            f"Se crea con: python3 scripts/erpnext_usuario_tecnico.py --departamento {departamento} --roles \"Sales User\" "
            "(los roles según lo que deba leer ese departamento) y después docker compose up -d --force-recreate --no-deps api worker beat")
    return {"Authorization": f"token {token}", "Accept": "application/json"}


async def listar(doctype: str, departamento: str, filtros: list | None = None,
                 campos: list[str] | None = None, limite: int = 50) -> list[dict]:
    comprobar_acceso(departamento, doctype, "leer")
    params = {"limit_page_length": limite, "fields": json.dumps(campos or ["name"])}
    if filtros:
        params["filters"] = json.dumps(filtros)
    async with httpx.AsyncClient(base_url=ajustes.erpnext_url, timeout=30) as c:
        r = await c.get(f"/api/resource/{quote(doctype, safe='')}", params=params, headers=_cabeceras(departamento))
    r.raise_for_status()
    return r.json()["data"]


async def leer(doctype: str, nombre: str, departamento: str) -> dict:
    comprobar_acceso(departamento, doctype, "leer", nombre)
    async with httpx.AsyncClient(base_url=ajustes.erpnext_url, timeout=30) as c:
        r = await c.get(f"/api/resource/{quote(doctype, safe='')}/{quote(nombre, safe='')}", headers=_cabeceras(departamento))
    r.raise_for_status()
    return r.json()["data"]


# Frappe CRM solo deja ver los leads y tratos de los que el usuario es propietario (o se le asignan): sin propietario, quien los crea no los ve
PROPIETARIO = {"CRM Lead": "lead_owner", "CRM Deal": "deal_owner"}
_usuarios: dict[str, str] = {}


async def _usuario_tecnico(departamento: str) -> str:
    token = _cabeceras(departamento)["Authorization"]
    if token not in _usuarios:
        async with httpx.AsyncClient(base_url=ajustes.erpnext_url, timeout=30) as c:
            r = await c.get("/api/method/frappe.auth.get_logged_user", headers=_cabeceras(departamento))
        r.raise_for_status()
        _usuarios[token] = r.json()["message"]
    return _usuarios[token]


async def crear_borrador(doctype: str, datos: dict[str, Any], departamento: str) -> dict:
    comprobar_acceso(departamento, doctype, "borrador")
    datos = {**datos, "docstatus": 0}   # siempre borrador
    campo = PROPIETARIO.get(doctype)
    if campo and not datos.get(campo):
        datos[campo] = await _usuario_tecnico(departamento)
    async with httpx.AsyncClient(base_url=ajustes.erpnext_url, timeout=30) as c:
        r = await c.post(f"/api/resource/{quote(doctype, safe='')}", json=datos, headers=_cabeceras(departamento))
    r.raise_for_status()
    return r.json()["data"]


EXTENSIONES_ADJUNTO = {".pdf", ".docx", ".xlsx", ".csv", ".txt", ".png", ".jpg", ".jpeg", ".doc", ".xls", ".pptx", ".odt", ".ods"}


async def adjuntar_desde_correo(doctype: str, nombre: str, message_id: str, adjunto: int | str, departamento: str,
                                buzon: str | None = None) -> dict:
    """Guarda un adjunto de un correo del buzón del departamento en un documento del ERP/CRM (queda como fichero PRIVADO del documento).
    Solo en documentos que el departamento puede crear en borrador (política), con la clave del departamento y con tipos de fichero
    admitidos: nunca ejecutables ni comprimidos."""
    from . import buzones as B, correo, documentos as D
    comprobar_acceso(departamento, doctype, "borrador", nombre)
    ident, _ = B.resolver(departamento, buzon)
    fichero, tipo, datos = await asyncio.to_thread(correo.obtener_adjunto, ident, message_id, adjunto)
    ext = D.extension(fichero)
    if ext not in EXTENSIONES_ADJUNTO:
        raise PermissionError(f"No se guardan en el ERP ficheros «{ext or 'sin extensión'}». Se admiten: {', '.join(sorted(EXTENSIONES_ADJUNTO))}")
    if (ext == ".pdf" and not datos.lstrip()[:5] == b"%PDF-") or (ext in (".docx", ".xlsx", ".pptx") and datos[:2] != b"PK"):
        raise PermissionError(f"El fichero «{fichero}» no es del tipo que indica su extensión: no se guarda")
    async with httpx.AsyncClient(base_url=ajustes.erpnext_url, timeout=60) as c:
        r = await c.post("/api/method/upload_file", headers=_cabeceras(departamento),
                         data={"doctype": doctype, "docname": nombre, "is_private": "1", "folder": "Home/Attachments"},
                         files={"file": (fichero, datos, tipo)})
    if r.status_code >= 400:
        raise RuntimeError(f"El ERP no ha aceptado el fichero ({r.status_code}): {r.text[:200]}")
    msg = r.json()["message"]
    return {"guardado": msg.get("file_name"), "url": msg.get("file_url"), "documento": f"{doctype} {nombre}", "bytes": len(datos)}


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
    operaciones={"listar": listar, "leer": leer, "crear_borrador": crear_borrador, "adjuntar_desde_correo": adjuntar_desde_correo},
    ayuda={"listar": "lista documentos. filtros = lista de [campo, operador, valor], p. ej. [[\"status\", \"=\", \"Open\"]]. " + AYUDA_DOCUMENTOS,
           "leer": "un documento completo por su nombre (doctype y nombre exactos, p. ej. Customer + «Comunitat Vilanova SL»)",
           "crear_borrador": "crea un documento en BORRADOR; «datos» lleva los campos del documento",
           "adjuntar_desde_correo": "guarda un adjunto de un correo (message_id y adjunto, de correo.leer_bandeja) como fichero privado de un documento "
                                    "que ya existe (doctype y nombre exactos); úsalo después de crear_borrador, con el nombre que este devuelve"},
    ejemplos={"listar": {"doctype": "Customer", "campos": ["customer_name"], "limite": 10},
              "crear_borrador": {"doctype": "Sales Invoice", "datos": {"customer": "Comunitat Vilanova SL", "items": [{"item_code": "ART-001", "qty": 2, "rate": 150}]}}},
))
