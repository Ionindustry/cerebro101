"""Constancia en el CRM de los correos que salen hacia clientes potenciales (config/crm.yaml, `constancia_correo`).

Un correo aprobado que sale de Comercial hacia la dirección de un CRM Lead deja una nota (FCRM Note) en el lead y en sus tratos (CRM Deal). Así el CRM guarda todo el seguimiento
sin que cada agente tenga que acordarse de anotarlo. Es COMODIDAD: nunca falla ni retrasa el correo; si el CRM no responde, solo queda en el registro. El texto del correo es propio
(lo escribió el agente y lo aprobó una persona), pero se escapa igual al guardarlo como HTML.
"""
from __future__ import annotations

import asyncio
import functools
import html
import logging
from email.utils import getaddresses
from pathlib import Path

import yaml

from .ajustes import ajustes

log = logging.getLogger("cerebro.crm_comercial")
DEFECTO = {"departamentos": [], "limite_s": 20, "max_caracteres": 3000}


@functools.lru_cache(maxsize=4)
def _config(dir_config: str) -> dict:
    ruta = Path(dir_config) / "crm.yaml"
    try:
        c = (yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}).get("constancia_correo") or {}
    except OSError:
        c = {}
    cfg = {**DEFECTO, **c}
    cfg["limite_s"] = min(max(int(cfg["limite_s"]), 5), 120)
    cfg["max_caracteres"] = min(max(int(cfg["max_caracteres"]), 200), 20000)
    return cfg


def configuracion() -> dict:
    return _config(str(ajustes.dir_config))


def direcciones(para) -> list[str]:
    """Las direcciones de un «Para» (texto con comas o lista), en minúsculas y sin repetir."""
    trozos = [para] if isinstance(para, str) else list(para or [])
    out: list[str] = []
    for _, a in getaddresses([str(t) for t in trozos]):
        a = a.strip().lower()
        if "@" in a and a not in out:
            out.append(a)
    return out[:10]


def cuerpo_nota(asunto: str, texto: str, maximo: int) -> str:
    lineas = [f"Correo enviado: {' '.join(str(asunto or '').split())[:200]}"] + [l.strip() for l in str(texto or "")[:maximo].splitlines() if l.strip()]
    return "".join(f"<p>{html.escape(l)}</p>" for l in lineas)


def _erp():
    from .herramientas import erpnext      # al usarlo, no al importar (el correo y el ERP se importan entre sí en algún orden)
    return erpnext


async def _anotar(departamento: str, para, asunto: str, texto: str, cfg: dict) -> int:
    erp = _erp()
    n = 0
    for a in direcciones(para):
        for lead in await erp.listar("CRM Lead", departamento, [["email", "=", a]], ["name"], 3):
            destinos = [("CRM Lead", lead["name"])]
            try:
                destinos += [("CRM Deal", d["name"]) for d in await erp.listar("CRM Deal", departamento, [["lead", "=", lead["name"]]], ["name"], 5)]
            except Exception as e:      # noqa: BLE001 — sin tratos (o sin permiso) se anota en el lead
                log.info("crm: no se han podido buscar los tratos del lead %s: %s", lead["name"], type(e).__name__)
            for tipo, nombre in destinos:
                await erp.crear_borrador("FCRM Note", {"title": f"Correo: {' '.join(str(asunto or '').split())[:120]}", "content": cuerpo_nota(asunto, texto, cfg["max_caracteres"]),
                                                       "reference_doctype": tipo, "reference_docname": nombre}, departamento)
                n += 1
    return n


async def anotar_correo(departamento: str, para, asunto: str, texto: str) -> int:
    """Anota el correo en los leads y tratos de sus destinatarios. Devuelve cuántas notas ha creado (0 si no procede). NUNCA lanza."""
    try:
        cfg = configuracion()
        if departamento not in (cfg.get("departamentos") or []):
            return 0
        return await asyncio.wait_for(_anotar(departamento, para, asunto, texto, cfg), cfg["limite_s"])
    except Exception as e:      # noqa: BLE001 — el correo ya salió; esto es solo constancia
        log.warning("crm: no se ha podido dejar constancia del correo «%s»: %s: %s", str(asunto)[:60], type(e).__name__, e)
        return 0
