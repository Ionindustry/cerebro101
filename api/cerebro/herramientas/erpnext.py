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
from datetime import date
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
    verbo = {"leer": "consultar", "maestros": "dar de alta o cambiar (datos maestros, solo con un proceso aprobado)",
             "sistema": "consultar (solo un proceso del sistema)"}.get(accion, "crear en borrador")
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


async def crear_maestro(doctype: str, datos: dict[str, Any], departamento: str) -> dict:
    """Da de alta UN dato maestro (p. ej. un proveedor). Como `insertar_varios`, no es una operación de los agentes: solo la usan procesos ya aprobados."""
    comprobar_acceso(departamento, doctype, "maestros")
    datos = {**datos, "docstatus": 0}
    campo = PROPIETARIO.get(doctype)
    if campo and not datos.get(campo):
        datos[campo] = await _usuario_tecnico(departamento)
    async with httpx.AsyncClient(base_url=ajustes.erpnext_url, timeout=30) as c:
        r = await c.post(f"/api/resource/{quote(doctype, safe='')}", json=datos, headers=_cabeceras(departamento))
    r.raise_for_status()
    return r.json()["data"]


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


async def listar_sistema(doctype: str, departamento: str, filtros: list | None = None, campos: list[str] | None = None, limite: int = 20) -> list[dict]:
    """Lee documentos de la categoría «sistema» de config/erp_acceso.yaml (p. ej. Company, Address). NO es una operación de los agentes: solo la usan procesos del sistema
    (cerebro/licitaciones/empresa.py), que piden una lista cerrada de campos."""
    comprobar_acceso(departamento, doctype, "sistema")
    params = {"limit_page_length": limite, "fields": json.dumps(campos or ["name"])}
    if filtros:
        params["filters"] = json.dumps(filtros)
    async with httpx.AsyncClient(base_url=ajustes.erpnext_url, timeout=30) as c:
        r = await c.get(f"/api/resource/{quote(doctype, safe='')}", params=params, headers=_cabeceras(departamento))
    r.raise_for_status()
    return r.json()["data"]


_RUTA_FICHERO = re.compile(r"^/(private/)?files/[^?#\\\x00-\x1f]{1,200}$")


async def descargar_sistema(ruta: str, departamento: str, max_bytes: int = 20 << 20) -> bytes:
    """Descarga un fichero del ERP (p. ej. el DEUC base adjunto a una empresa) con la clave del departamento. NO es una operación de los agentes: solo procesos del sistema, y exige el tipo «File»
    en «sistema». Solo rutas /files/… o /private/files/… (nada de «..» ni de otras direcciones); pasarse del tamaño es un error."""
    comprobar_acceso(departamento, "File", "sistema")
    if not isinstance(ruta, str) or not _RUTA_FICHERO.match(ruta) or ".." in ruta:
        raise PermissionError("La ruta del fichero no es válida")
    async with httpx.AsyncClient(base_url=ajustes.erpnext_url, timeout=60) as c:
        r = await c.get(quote(ruta, safe="/"), headers=_cabeceras(departamento))
    r.raise_for_status()
    if len(r.content) > max_bytes:
        raise ValueError("El fichero es demasiado grande")
    return r.content


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


async def insertar_varios(doctype: str, docs: list[dict], departamento: str, tamano: int = 100) -> list[str]:
    """Crea varios documentos del mismo tipo de una vez (`frappe.client.insert_many`), en tandas. No es una operación de los agentes: la usan procesos del sistema que ya han pasado por
    una aprobación (p. ej. aplicar una lista de precios). Misma política que `crear_borrador`: el departamento necesita el permiso de «borrador» sobre el tipo. POR VERIFICAR con el ERP real."""
    comprobar_acceso(departamento, doctype, "maestros")
    nombres: list[str] = []
    for i in range(0, len(docs), max(1, tamano)):
        lote = [{**d, "doctype": doctype, "docstatus": 0} for d in docs[i:i + tamano]]
        async with httpx.AsyncClient(base_url=ajustes.erpnext_url, timeout=120) as c:
            r = await c.post("/api/method/frappe.client.insert_many", json={"docs": lote}, headers=_cabeceras(departamento))
        r.raise_for_status()
        nombres += [str(n) for n in (r.json().get("message") or [])]
    return nombres


async def modificar(doctype: str, nombre: str, datos: dict[str, Any], departamento: str) -> dict:
    """Cambia campos de un documento que ya existe (nunca su estado de validación). Tampoco es una operación de los agentes; exige el tipo en «maestros»."""
    comprobar_acceso(departamento, doctype, "maestros", nombre)
    datos = {k: v for k, v in datos.items() if k not in ("docstatus", "name", "doctype")}
    async with httpx.AsyncClient(base_url=ajustes.erpnext_url, timeout=30) as c:
        r = await c.put(f"/api/resource/{quote(doctype, safe='')}/{quote(nombre, safe='')}", json=datos, headers=_cabeceras(departamento))
    r.raise_for_status()
    return r.json()["data"]


_METRICAS: dict[str, tuple[float, Any]] = {}          # caché breve: un panel de KPI no debe llamar al ERP en cada refresco
_CAMPO = re.compile(r"^[a-z_][a-z0-9_]{0,60}$")


async def metrica(departamento: str, doctype: str, filtros: list | None = None, agregado: str = "contar", campo: str | None = None,
                  campo_fecha: str | None = None, desde: str | None = None, hasta: str | None = None, ttl: int = 60) -> float:
    """Una cifra del ERP/CRM para un KPI: cuántos documentos hay (contar) o la suma de un campo (sumar), con la clave y la política del departamento.
    `desde`/`hasta` (aaaa-mm-dd, hasta excluido) acotan por `campo_fecha`. Lee en el ERP; no escribe nada."""
    import time as _t
    comprobar_acceso(departamento, doctype, "leer")
    f = [list(x) for x in (filtros or [])]
    if campo_fecha:
        if not _CAMPO.match(campo_fecha):
            raise PermissionError("campo de fecha no válido")
        if desde:
            f.append([campo_fecha, ">=", desde])
        if hasta:
            f.append([campo_fecha, "<", hasta])
    if agregado in ("sumar", "retraso_medio") and not (campo and _CAMPO.match(campo)):
        raise PermissionError("campo no válido")
    clave = json.dumps([departamento, doctype, f, agregado, campo], sort_keys=True, default=str)
    hit = _METRICAS.get(clave)
    if hit and _t.monotonic() - hit[0] < ttl:
        return hit[1]
    async with httpx.AsyncClient(base_url=ajustes.erpnext_url, timeout=30) as c:
        if agregado == "contar":
            r = await c.get("/api/method/frappe.client.get_count", params={"doctype": doctype, "filters": json.dumps(f)}, headers=_cabeceras(departamento))
            r.raise_for_status()
            valor = float(r.json().get("message") or 0)
        elif agregado == "retraso_medio":
            # días de retraso medio: hoy menos la fecha (p. ej. de vencimiento) de cada documento que cumple los filtros
            r = await c.get(f"/api/resource/{quote(doctype, safe='')}", headers=_cabeceras(departamento),
                            params={"fields": json.dumps([campo]), "filters": json.dumps(f), "limit_page_length": 2000})
            r.raise_for_status()
            from datetime import date as _d
            hoy = _d.today()
            dias = [(hoy - _d.fromisoformat(str(x[campo])[:10])).days for x in r.json().get("data", []) if x.get(campo)]
            valor = round(sum(dias) / len(dias), 1) if dias else 0.0
        else:
            r = await c.get(f"/api/resource/{quote(doctype, safe='')}", headers=_cabeceras(departamento),
                            params={"fields": json.dumps([{"SUM": campo, "as": "v"}]), "filters": json.dumps(f), "limit_page_length": 1})
            r.raise_for_status()
            datos = r.json().get("data") or [{}]
            valor = float(datos[0].get("v") or 0)
    _METRICAS[clave] = (_t.monotonic(), valor)
    return valor


EXTENSIONES_ADJUNTO = {".pdf", ".docx", ".xlsx", ".csv", ".txt", ".png", ".jpg", ".jpeg", ".doc", ".xls", ".pptx", ".odt", ".ods"}


async def _subir_fichero(doctype: str, nombre: str, fichero: str, tipo: str, datos: bytes, departamento: str) -> dict:
    """Sube un fichero como PRIVADO de un documento. Solo tipos admitidos y que sean lo que dice su extensión."""
    from . import documentos as D
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


async def adjuntar_desde_correo(doctype: str, nombre: str, message_id: str, adjunto: int | str, departamento: str,
                                buzon: str | None = None) -> dict:
    """Guarda un adjunto de un correo del buzón del departamento en un documento del ERP/CRM (queda como fichero PRIVADO del documento).
    Solo en documentos que el departamento puede crear en borrador (política), con la clave del departamento y con tipos de fichero
    admitidos: nunca ejecutables ni comprimidos."""
    from . import buzones as B, correo
    comprobar_acceso(departamento, doctype, "borrador", nombre)
    ident, _ = B.resolver(departamento, buzon)
    fichero, tipo, datos = await asyncio.to_thread(correo.obtener_adjunto, ident, message_id, adjunto)
    return await _subir_fichero(doctype, nombre, fichero, tipo, datos, departamento)


@functools.lru_cache(maxsize=2)
def _config_facturas(dir_config: str) -> dict:
    ruta = Path(dir_config) / "facturas.yaml"
    return (yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}).get("compra") or {} if ruta.exists() else {}


async def crear_factura_compra(departamento: str, message_id: str, adjunto: int | str, proveedor: str, numero: str, fecha: str,
                               lineas: list[dict], total: float | str, nif: str | None = None, iva_porcentaje: int | None = None,
                               vencimiento: str | None = None, buzon: str | None = None) -> dict:
    """Deja en BORRADOR una factura de proveedor leída de un adjunto del correo (PDF, escaneo o foto, con OCR si hace falta).
    Antes de crear nada comprueba que los datos cuadran entre sí y que el número y el total aparecen de verdad en el documento;
    busca el proveedor en el ERP (no lo da de alta), evita duplicados y adjunta el original a la factura."""
    from decimal import Decimal
    from . import buzones as B, correo, documentos as D, facturas as F
    comprobar_acceso(departamento, "Purchase Invoice", "borrador")
    comprobar_acceso(departamento, "Supplier", "leer")
    cfg = _config_facturas(str(ajustes.dir_config))
    if not cfg.get("cuenta_gasto") or not cfg.get("cuenta_iva"):
        raise RuntimeError("Falta configurar las cuentas en config/facturas.yaml (cuenta_gasto y cuenta_iva)")
    try:
        total_d, lineas_v = F.centimos(F.a_decimal(total)), F.validar_lineas(lineas)
        f_factura = F.a_fecha(fecha)
        f_venc = F.a_fecha(vencimiento) if vencimiento else None
        numero = str(numero or "").strip()
        if not numero or not proveedor.strip():
            raise F.DatosFactura("Faltan el proveedor o el número de factura")
        ident, _ = B.resolver(departamento, buzon)
        fichero, tipo, datos = await asyncio.to_thread(correo.obtener_adjunto, ident, message_id, adjunto)
        texto, info = await asyncio.to_thread(D.extraer_texto, fichero, datos)
        tipo_iva, base, advertencias = F.comprobar(texto, proveedor, nif, numero, total_d, lineas_v, iva_porcentaje,
                                                   [int(x) for x in cfg.get("tipos_iva", [0, 4, 10, 21])], Decimal(str(cfg.get("tolerancia", 0.02))))
        if info.get("ocr"):
            advertencias.insert(0, "Leída por OCR: comprueba las cifras al validar la factura")
        async with httpx.AsyncClient(base_url=ajustes.erpnext_url, timeout=60) as c:
            h = _cabeceras(departamento)
            r = await c.get("/api/resource/Supplier", params={"fields": json.dumps(["name", "supplier_name", "tax_id"]), "limit_page_length": 2000}, headers=h)
            r.raise_for_status()
            prov = F.buscar_proveedor(r.json()["data"], proveedor, nif)
            r = await c.get("/api/resource/Purchase Invoice", params={"fields": json.dumps(["name", "docstatus"]), "limit_page_length": 5,
                            "filters": json.dumps([["supplier", "=", prov["name"]], ["bill_no", "=", numero], ["docstatus", "<", 2]])}, headers=h)
            r.raise_for_status()
            if r.json()["data"]:
                raise F.DatosFactura(f"Ya existe la factura {numero} de {prov['name']} en el ERP ({r.json()['data'][0]['name']}): no se duplica")
    except F.DatosFactura as e:
        raise ValueError(str(e)) from e
    doc = {"supplier": prov["name"], "bill_no": numero, "bill_date": f_factura, "posting_date": date.today().isoformat(),
           "items": [{"item_name": l["descripcion"][:140], "description": l["descripcion"], "qty": float(l["cantidad"]), "rate": float(l["precio"]),
                      "expense_account": cfg["cuenta_gasto"]} for l in lineas_v],
           "remarks": f"Factura leída del correo ({ident}) por el Cerebro. Pendiente de revisión y validación por una persona."}
    if f_venc:
        doc["due_date"] = f_venc
    if tipo_iva:
        doc["taxes"] = [{"charge_type": "On Net Total", "account_head": cfg["cuenta_iva"], "rate": tipo_iva, "description": f"IVA {tipo_iva}%"}]
    creada = await crear_borrador("Purchase Invoice", doc, departamento)
    salida = {"factura": creada["name"], "proveedor": prov["name"], "base": str(base), "iva": f"{tipo_iva}%", "total_en_erp": creada.get("grand_total"),
              "estado": "borrador: una persona debe revisarla y validarla", "advertencias": advertencias}
    if creada.get("grand_total") is not None and abs(Decimal(str(creada["grand_total"])) - total_d) > Decimal("0.02"):
        salida["advertencias"].append(f"¡El ERP calcula un total de {creada['grand_total']} y la factura dice {total_d}! Revisar antes de validar")
    try:
        salida["original"] = (await _subir_fichero("Purchase Invoice", creada["name"], fichero, tipo, datos, departamento))["url"]
    except Exception as e:  # noqa: BLE001 — la factura ya existe: se avisa en vez de perder el resultado
        salida["advertencias"].append(f"No se ha podido adjuntar el original: {e}")
    return salida


AYUDA_DOCUMENTOS = (
    "Documentos habituales (doctype: campos; los campos pueden variar con la versión): "
    "Customer(customer_name, customer_type, customer_group, territory, email_id); Supplier(supplier_name, supplier_group); "
    "Item(item_code, item_name, item_group, stock_uom, standard_rate); Bin = existencias(item_code, warehouse, actual_qty); "
    "Quotation(party_name, transaction_date, items); Sales Order(customer, transaction_date, delivery_date, items); "
    "Sales Invoice(customer, posting_date, due_date, items); Purchase Order(supplier, transaction_date, schedule_date, items); "
    "Purchase Invoice(supplier, bill_date, items); Project(project_name, status, expected_start_date, expected_end_date); "
    "Task(subject, status, project); Lead(lead_name, company_name, email_id, status); Employee(employee_name, department, status). "
    "CRM: CRM Lead(first_name, email, status); CRM Deal(organization, status, lead); FCRM Note(title, content) y CRM Task(title, due_date, status) llevan reference_doctype y reference_docname del lead o trato. "
    "En «items» va una lista de {item_code, qty, rate}.")

registrar(Herramienta(
    nombre="erpnext",
    descripcion="ERP de la empresa: clientes, proyectos, artículos, precios, facturas, compras. Nunca valida documentos: "
                "solo los lee o los deja en borrador para que una persona los valide.",
    operaciones={"listar": listar, "leer": leer, "crear_borrador": crear_borrador, "adjuntar_desde_correo": adjuntar_desde_correo,
                 "crear_factura_compra": crear_factura_compra},
    ayuda={"listar": "lista documentos. filtros = lista de [campo, operador, valor], p. ej. [[\"status\", \"=\", \"Open\"]]. " + AYUDA_DOCUMENTOS,
           "leer": "un documento completo por su nombre (doctype y nombre exactos, p. ej. Customer + «Comunitat Vilanova SL»)",
           "crear_borrador": "crea un documento en BORRADOR; «datos» lleva los campos del documento",
           "adjuntar_desde_correo": "guarda un adjunto de un correo (message_id y adjunto, de correo.leer_bandeja) como fichero privado de un documento "
                                    "que ya existe (doctype y nombre exactos); úsalo después de crear_borrador, con el nombre que este devuelve",
           "crear_factura_compra": "pasa a BORRADOR una factura de proveedor que llegó adjunta a un correo (PDF, escaneo o foto; se lee con OCR si hace falta). "
                                   "Primero lee el documento con correo.leer_adjunto y rellena: proveedor, nif, numero (de factura), fecha (dd/mm/aaaa), "
                                   "lineas = [{descripcion, cantidad, precio (unitario sin IVA)}], total (con IVA, tal como sale en el documento), "
                                   "iva_porcentaje y vencimiento si constan. Se comprueba que cuadra y que número y total están en el documento; "
                                   "si falla, explica el motivo a la persona y no insistas"},
    ejemplos={"listar": {"doctype": "Customer", "campos": ["customer_name"], "limite": 10},
              "crear_borrador": {"doctype": "Sales Invoice", "datos": {"customer": "Comunitat Vilanova SL", "items": [{"item_code": "ART-001", "qty": 2, "rate": 150}]}}},
))
