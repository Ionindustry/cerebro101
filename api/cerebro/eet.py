"""Consulta de precio y stock a EET Europarts (PA Request / PA Response, XML por HTTPS: ver docs/EET.md).

SOLO LECTURA. No envía pedidos (eso sería otra fase, con firma de Dirección). Lo puro (construir la petición, leer la respuesta) va aparte de lo que sale a la red.
  · Las credenciales (número de cliente y AuthCode) se leen de `secretos/eet.env`; nunca de la configuración, de los registros ni de lo que ve el modelo.
  · La dirección ha de ser https y de un dominio de `hosts`; sin redirecciones; respuesta de tamaño limitado; XML sin DTD ni entidades (sin ataques XML).
  · El precio llega en CÉNTIMOS: aquí se convierte a euros (Decimal). La moneda es la de la cuenta (configuración): el documento de EET no la dice.
"""
from __future__ import annotations

import logging
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlparse
from xml.sax.saxutils import escape

import httpx
import yaml
from defusedxml import ElementTree as ET
from defusedxml.common import DefusedXmlException

from .ajustes import ajustes

log = logging.getLogger("cerebro.eet")

RUTA_SECRETOS = "/run/secretos/eet.env"
MAX_RESPUESTA = 2_000_000
ESTADOS = {"0": "ok", "7": "no existe en EET", "29": "no procesado"}
RE_REF = re.compile(r"^[\w.\-/+ ]{1,30}$")


class ErrorEET(Exception):
    pass


def configuracion() -> dict:
    try:
        c = yaml.safe_load((Path(ajustes.dir_config) / "eet.yaml").read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        c = {}
    return {"url": str(c.get("url") or "").strip(), "hosts": [str(h).lower().strip(".") for h in (c.get("hosts") or []) if h], "cid": str(c.get("cid") or "").strip(),
            "secretos": {"cliente": str((c.get("secretos") or {}).get("cliente") or "EET_CLIENTE"), "clave": str((c.get("secretos") or {}).get("clave") or "EET_CLAVE")},
            "moneda": str(c.get("moneda") or "EUR").upper()[:3], "ampliada": bool(c.get("ampliada", True)), "max_referencias": min(max(int(c.get("max_referencias") or 50), 1), 200)}


def secretos(ruta: str = RUTA_SECRETOS) -> dict[str, str]:
    try:
        lineas = Path(ruta).read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    out = {}
    for l in lineas:
        l = l.strip()
        if l and not l.startswith("#") and "=" in l:
            k, v = l.split("=", 1)
            out[k.strip()] = v.strip().strip("'\"")
    return out


def referencias_validas(refs) -> list[str]:
    """Las referencias de la consulta, limpias y sin repetir. Una con caracteres raros se rechaza (van dentro de un XML). Pura."""
    out: list[str] = []
    for r in refs or []:
        r = str(r).strip()
        if not r:
            continue
        if not RE_REF.match(r):
            raise ErrorEET(f"La referencia «{r[:30]}» no es válida (máximo 30 caracteres: letras, números y . - / +)")
        if r not in out:
            out.append(r)
    if not out:
        raise ErrorEET("Falta al menos una referencia")
    return out


def construir_peticion(cliente: str, clave: str, cid: str, referencias: list[str], ampliada: bool = True) -> bytes:
    """El XML del PA Request. Todo valor va escapado. Pura."""
    def a(v):
        return '"' + escape(str(v), {'"': "&quot;"}) + '"'
    cab = f"CustomerNo={a(cliente)} AuthCode={a(clave)} CId={a(cid)}" + (' Version="Extended"' if ampliada else "")
    items = "".join(f"<Item>{escape(r)}</Item>" for r in referencias)
    return f'<?xml version="1.0" encoding="ISO-8859-1" ?><PARequest {cab}>{items}</PARequest>'.encode("iso-8859-1", "replace")


def _centimos(t) -> str | None:
    try:
        return str((Decimal(str(t).strip()) / 100).quantize(Decimal("0.01")))
    except (InvalidOperation, AttributeError):
        return None


def interpretar_respuesta(datos: bytes, moneda: str = "EUR") -> dict:
    """El PA Response a un dict: por referencia su estado, precio (en la moneda, ya no en céntimos), stock, detalle de stock, EAN y descripción. Pura; lanza ErrorEET si no es un PA Response válido."""
    if len(datos) > MAX_RESPUESTA:
        raise ErrorEET("La respuesta de EET es demasiado grande")
    try:
        raiz = ET.fromstring(datos, forbid_dtd=True)
    except (ET.ParseError, DefusedXmlException, ValueError) as e:
        raise ErrorEET(f"La respuesta de EET no es un XML válido ({type(e).__name__})") from None
    if raiz.tag == "Response":                                       # un error general (p. ej. credenciales)
        raise ErrorEET(f"EET rechaza la consulta: {raiz.get('Text') or 'estado ' + str(raiz.get('Status'))}")
    if raiz.tag != "PAResponse":
        raise ErrorEET("La respuesta de EET no es un PA Response")
    if raiz.get("Status") not in (None, "0"):
        raise ErrorEET(f"EET responde con estado {raiz.get('Status')}: {(raiz.get('Text') or '')[:100]}")
    articulos = []
    for it in raiz.findall("Item"):
        estado = str(it.get("Status") or "")
        a = {"referencia": it.get("ItemNo") or "", "estado": ESTADOS.get(estado, f"estado {estado}"), "encontrado": estado == "0"}
        if estado == "0":
            stock = (it.findtext("Stock") or "").strip()
            a.update(precio=_centimos(it.findtext("Price")), moneda=moneda, stock=int(stock) if stock.lstrip("-").isdigit() else None)
            det = [{"cantidad": int(d.get("Quantity")) if str(d.get("Quantity") or "").isdigit() else None, "tipo": (d.get("Type") or "")[:30], "disponible": (d.get("Available") or "")[:30]}
                   for d in it.findall("./StockDetails/StockDetail")]
            if det:
                a["stock_detalle"] = det
            if (it.findtext("EAN") or "").strip():
                a["ean"] = it.findtext("EAN").strip()[:30]
            if (it.findtext("Description") or "").strip():
                a["descripcion"] = it.findtext("Description").strip()[:50]
        articulos.append(a)
    return {"articulos": articulos}


async def consultar(referencias: list[str], cfg: dict | None = None, transporte=None, resolver=None, claves: dict | None = None) -> dict:
    """Pregunta a EET precio y stock de las referencias. Lanza ErrorEET con un mensaje claro si no está configurado o falla."""
    cfg = cfg or configuracion()
    if not cfg["url"] or not cfg["cid"] or not cfg["hosts"]:
        raise ErrorEET("EET no está configurado todavía: faltan la dirección, el dominio y el identificador de empresa en config/eet.yaml (los da EET)")
    s = claves if claves is not None else secretos()
    cliente, clave = s.get(cfg["secretos"]["cliente"], ""), s.get(cfg["secretos"]["clave"], "")
    if not cliente or not clave:
        raise ErrorEET(f"Faltan los datos de acceso a EET en secretos/eet.env ({cfg['secretos']['cliente']} y {cfg['secretos']['clave']})")
    refs = referencias_validas(referencias)
    if len(refs) > cfg["max_referencias"]:
        raise ErrorEET(f"Máximo {cfg['max_referencias']} referencias por consulta")
    from .herramientas import web
    from .licitaciones import pliegos
    url = cfg["url"]
    if not pliegos.host_permitido(url, cfg["hosts"]):
        raise ErrorEET("La dirección de EET debe ser https y de uno de los dominios de `hosts`")
    try:
        esquema, host, puerto, ips = await (resolver or web._validar_destino)(url)
    except (ValueError, PermissionError) as e:
        raise ErrorEET(str(e)) from None
    u = urlparse(url)
    ip = ips[0]
    anclada = f"{esquema}://{f'[{ip}]' if ':' in ip else ip}:{puerto}{u.path or '/'}" + (f"?{u.query}" if u.query else "")
    cuerpo = construir_peticion(cliente, clave, cfg["cid"], refs, cfg["ampliada"])
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=False, transport=transporte) as c:
            async with c.stream("POST", anclada, content=cuerpo, headers={"Host": host, "Content-Type": "application/xml", "User-Agent": web.AGENTE_HTTP}, extensions={"sni_hostname": host}) as r:
                if r.status_code != 200:
                    raise ErrorEET(f"EET responde con error HTTP {r.status_code}")
                trozos, total = [], 0
                async for t in r.aiter_bytes():
                    total += len(t)
                    if total > MAX_RESPUESTA:
                        raise ErrorEET("La respuesta de EET es demasiado grande")
                    trozos.append(t)
    except httpx.TimeoutException:
        raise ErrorEET("EET tarda demasiado en responder") from None
    except httpx.HTTPError as e:
        raise ErrorEET(f"No se ha podido hablar con EET ({type(e).__name__})") from None
    return interpretar_respuesta(b"".join(trozos), cfg["moneda"])
