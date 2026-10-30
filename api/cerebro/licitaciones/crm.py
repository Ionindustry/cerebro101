"""Seguimiento de las licitaciones en el CRM (Frappe CRM, el que ya está instalado en el ERP): cada licitación que se estudia es UN trato (CRM Deal) del organismo comprador
(CRM Organization), y cada hito (estudiar, redactar la oferta, fijar el precio, presentar, ganar o perder) queda como nota (FCRM Note) del trato. Así todo el seguimiento está en el
mismo sitio que el resto de la actividad comercial y los agentes lo leen y lo amplían con la herramienta «erpnext» (notas y tareas), con la política de config/erp_acceso.yaml.

Es COMODIDAD, nunca un requisito: si el CRM no responde o no está configurado, lo que hizo la persona (cambiar de estado, fijar el precio…) ya está guardado y aquí solo se anota en el
registro. El estado del embudo del Cerebro manda; el trato del CRM lo sigue. El trato se identifica por `licitaciones.crm` (columna de db/esquema.sql), así que repetir un aviso no lo duplica.
Los textos de la licitación son datos de terceros: se escapan como texto.
"""
from __future__ import annotations

import asyncio
import html
import logging
from pathlib import Path

import psycopg
import yaml
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ..ajustes import ajustes
from . import embudo

log = logging.getLogger("cerebro.licitaciones.crm")

DEPARTAMENTO = "licitaciones"      # el usuario técnico del ERP con el que se escribe (ERPNEXT_TOKEN_LICITACIONES)
# Etapas de los tratos de Frappe CRM (las de fábrica): se cambian en config/licitaciones.yaml si en tu CRM se llaman de otra manera.
DEFECTO = {
    "activo": True,
    "crear_detectadas": False,       # False: el trato nace cuando una persona decide estudiarla; True: también las que detecta el sistema
    "limite_s": 25,                  # tiempo máximo que se espera al CRM antes de seguir (la acción de la persona no depende de él)
    "url_publica": "http://localhost:8081/crm",
    "etapas": {"detectada": "Qualification", "en_estudio": "Proposal/Quotation", "presentada": "Negotiation",
               "ganada": "Won", "perdida": "Lost", "descartada": "Lost"},
}


def configuracion() -> dict:
    try:
        c = yaml.safe_load((Path(ajustes.dir_config) / "licitaciones.yaml").read_text(encoding="utf-8")).get("crm") or {}
    except OSError:
        c = {}
    cfg = {**DEFECTO, **{k: v for k, v in c.items() if k != "etapas"}}
    cfg["etapas"] = {**DEFECTO["etapas"], **(c.get("etapas") or {})}
    cfg["limite_s"] = min(max(int(cfg["limite_s"]), 5), 120)
    return cfg


def _erp():
    from ..herramientas import erpnext        # al usarlo, no al importar: el ERP también importa módulos de licitaciones
    return erpnext


def _texto(t, n: int) -> str:
    return " ".join(str(t or "").split())[:n]


def url_del_trato(trato: str | None, cfg: dict | None = None) -> str | None:
    if not trato:
        return None
    base = str((cfg or configuracion()).get("url_publica") or "").rstrip("/")
    return f"{base}/deals/{trato}" if base.startswith(("http://", "https://")) else None


def datos_trato(fila: dict, cfg: dict, organizacion: str) -> dict:
    """Los campos del trato del CRM a partir de una fila del embudo. Pura. Los nombres de campo son los de Frappe CRM 1.x (POR VERIFICAR con el CRM real:
    un campo que no exista se ignora, no rompe)."""
    d = {"organization": organizacion, "status": cfg["etapas"][fila["estado"]]}
    if fila.get("importe") is not None:
        d["expected_deal_value"] = float(fila["importe"])
    if fila.get("fecha_limite"):
        d["expected_closure_date"] = str(fila["fecha_limite"])[:10]
        d["next_step"] = f"Presentar la oferta antes del {str(fila['fecha_limite'])[:10]}"
    return d


def cuerpo_nota(contenido: str) -> str:
    """El texto de una nota en el HTML sencillo que guarda el CRM: un párrafo por línea, todo escapado."""
    return "".join(f"<p>{html.escape(l.strip())}</p>" for l in str(contenido or "").splitlines() if l.strip())


def nota_de_alta(fila: dict) -> str:
    return "\n".join(x for x in [
        f"Licitación: {_texto(fila.get('titulo'), 300)}",
        f"Expediente: {fila['expediente']}" if fila.get("expediente") else "",
        f"Organismo: {_texto(fila.get('organismo'), 200)}" if fila.get("organismo") else "",
        f"Importe (sin IVA): {fila['importe']:,.0f} €".replace(",", ".") if fila.get("importe") is not None else "",
        f"Plazo de presentación: {str(fila['fecha_limite'])[:10]}" if fila.get("fecha_limite") else "",
        f"Anuncio: {fila['enlace']}" if str(fila.get("enlace") or "").startswith(("http://", "https://")) else "",
        "Seguimiento creado por el Cerebro de 101.cat desde el embudo de licitaciones."] if x)


async def _organizacion(nombre: str | None) -> str:
    erp = _erp()
    nombre = _texto(nombre, 140) or "(organismo sin nombre)"
    ya = await erp.listar("CRM Organization", DEPARTAMENTO, [["name", "=", nombre]], ["name"], 1)
    if ya:
        return ya[0]["name"]
    return (await erp.crear_maestro("CRM Organization", {"organization_name": nombre}, DEPARTAMENTO))["name"]


async def _guardar(lid: int, conn, crm: dict) -> None:
    await conn.execute("UPDATE licitaciones SET crm = %s WHERE id = %s", [Jsonb(crm), lid])


async def asegurar_trato(lid: int, cfg: dict | None = None) -> str | None:
    """Deja el trato de la licitación creado y en la etapa que le toca según su estado en el embudo. Devuelve el nombre del trato, o None si aún no procede
    (detectada sin `crear_detectadas`, o descartada sin que se llegara a estudiar). Con la fila bloqueada: dos avisos a la vez no crean dos tratos."""
    cfg = cfg or configuracion()
    erp = _erp()
    async with await psycopg.AsyncConnection.connect(ajustes.database_url, row_factory=dict_row) as conn:
        async with conn.transaction():
            cur = await conn.execute(f"SELECT {embudo.COLUMNAS} FROM licitaciones WHERE id = %s FOR UPDATE", [lid])
            fila = await cur.fetchone()
            if not fila:
                return None
            fila = embudo._fila(fila)
            crm = dict(fila.get("crm") or {})
            etapa = cfg["etapas"].get(fila["estado"])
            if not crm.get("trato"):
                if fila["estado"] == "descartada" or (fila["estado"] == "detectada" and not cfg["crear_detectadas"]):
                    return None
                org = await _organizacion(fila.get("organismo"))
                trato = (await erp.crear_maestro("CRM Deal", datos_trato(fila, cfg, org), DEPARTAMENTO))["name"]
                crm = {"trato": trato, "etapa": etapa}
                await _guardar(lid, conn, crm)
                try:
                    await erp.crear_borrador("FCRM Note", {"title": "Licitación en seguimiento", "content": cuerpo_nota(nota_de_alta(fila)),
                                                           "reference_doctype": "CRM Deal", "reference_docname": trato}, DEPARTAMENTO)
                except Exception as e:      # noqa: BLE001 — el trato ya existe; la nota de alta es solo informativa
                    log.warning("crm: trato %s creado, pero no la nota de alta: %s: %s", trato, type(e).__name__, e)
            elif etapa and crm.get("etapa") != etapa:
                await erp.modificar("CRM Deal", crm["trato"], {"status": etapa}, DEPARTAMENTO)
                crm["etapa"] = etapa
                await _guardar(lid, conn, crm)
            return crm["trato"]


async def anotar(lid: int, titulo: str, contenido: str = "", cfg: dict | None = None) -> str | None:
    """Pone al día el trato de la licitación y le añade una nota con lo que ha pasado. NUNCA falla ni espera de más: devuelve el nombre del trato, o None si no se ha podido
    (CRM apagado, sin clave, sin respuesta…); la causa queda en el registro."""
    cfg = cfg or configuracion()
    if not cfg["activo"]:
        return None
    try:
        return await asyncio.wait_for(_anotar(lid, titulo, contenido, cfg), cfg["limite_s"])
    except Exception as e:      # noqa: BLE001 — el seguimiento es comodidad: lo que hizo la persona ya está guardado
        log.warning("crm: no se ha podido anotar «%s» en la licitación %s: %s: %s", _texto(titulo, 60), lid, type(e).__name__, e)
        return None


async def _anotar(lid: int, titulo: str, contenido: str, cfg: dict) -> str | None:
    trato = await asegurar_trato(lid, cfg)
    if trato and titulo:
        await _erp().crear_borrador("FCRM Note", {"title": _texto(titulo, 140), "content": cuerpo_nota(contenido or titulo),
                                                  "reference_doctype": "CRM Deal", "reference_docname": trato}, DEPARTAMENTO)
    return trato


async def anotar_por_oferta(motor_id: str, titulo: str, contenido: str = "") -> str | None:
    """Lo mismo, a partir del identificador del expediente del motor (lo que conocen las ofertas). Si esa licitación no está en el embudo, no hace nada."""
    try:
        filas = await embudo.listar(motor_id=motor_id, limite=1)
    except Exception as e:      # noqa: BLE001
        log.warning("crm: no se ha podido buscar la licitación %s en el embudo: %s: %s", motor_id, type(e).__name__, e)
        return None
    return await anotar(filas[0]["id"], titulo, contenido) if filas else None


# ---- Los textos de cada hito (puros, para poder probarlos) ----

def nota_de_estado(estado: str, motivo_texto: str | None, usuario: str) -> tuple[str, str]:
    titulo = {"en_estudio": "Se decide estudiarla", "presentada": "Oferta presentada", "ganada": "Licitación ganada", "perdida": "Licitación perdida",
              "descartada": "Licitación descartada (no se presenta)", "detectada": "Licitación reabierta"}.get(estado, f"Estado: {estado}")
    detalle = [f"Decidido por: {_texto(usuario, 100)}"] + ([f"Motivo: {motivo_texto}"] if motivo_texto else [])
    return titulo, "\n".join(detalle)


def nota_de_redaccion(ejecucion: dict) -> tuple[str, str]:
    pasos = ejecucion.get("pasos") or []
    etiquetas = {"hecho": "hecho", "parcial": "parcial", "omitido": "omitido", "error": "con error", "pendiente": "pendiente", "en_curso": "en curso"}
    lineas = [f"- {_texto(p.get('titulo') or p.get('id'), 80)}: {etiquetas.get(p.get('estado'), p.get('estado'))}" for p in pasos]
    cabecera = {"completa": "Los agentes han preparado el borrador de la oferta", "parcial": "Los agentes han preparado parte del borrador de la oferta",
                "error": "Los agentes no han podido preparar el borrador de la oferta"}.get(ejecucion.get("estado"), "Los agentes han trabajado en la oferta")
    if ejecucion.get("error"):
        lineas.append(f"Aviso: {_texto(ejecucion['error'], 300)}")
    lineas.append("El borrador necesita revisión y aprobación de una persona antes de presentarse.")
    return cabecera, "\n".join(lineas)


def nota_de_precio(precio, iva_pct, usuario: str) -> tuple[str, str]:
    return "Precio de la oferta fijado", f"Precio sin IVA: {precio} €\nIVA: {iva_pct} %\nFijado por: {_texto(usuario, 100)}"
