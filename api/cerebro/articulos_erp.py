"""El artículo del ERP con TODA la información de la tarifa: marca, descripción con sus características, categorías, enlaces a la ficha, código de barras válido, imagen y la referencia del proveedor.

Pura (sin red): `listas_precios.aplicar` la usa al cargar una tarifa aprobada. Reglas:
  · Lo que trae la tarifa se escribe tal cual (escapado: es texto de terceros que acaba en un campo HTML del ERP); no se inventa ni se completa nada.
  · El código de barras solo va si es un EAN-13 o un UPC-A con el dígito de control correcto: uno inválido hace que el ERP rechace el artículo entero.
  · La imagen es la DIRECCIÓN https de la tarifa (no se descarga nada); un enlace http o raro no se pone.
"""
from __future__ import annotations

import html
import re

MAX_DESCRIPCION = 6000
MAX_ESPECIFICACIONES = 30
RE_HTTPS = re.compile(r"^https://[^\s<>\"']{4,500}$", re.I)
RE_ENLACE = re.compile(r"^https?://[^\s<>\"']{4,500}$", re.I)


def _digito_de_control(cuerpo: str) -> int:
    """Dígito de control de un EAN/UPC (pesos 3 y 1 empezando por la derecha del cuerpo)."""
    total = sum(int(c) * (3 if i % 2 == 0 else 1) for i, c in enumerate(reversed(cuerpo)))
    return (10 - total % 10) % 10


def codigo_de_barras(ean) -> dict | None:
    """{barcode, barcode_type} si es un EAN-13 o un UPC-A válido; None en otro caso (vacío, longitud rara o dígito de control incorrecto). Pura."""
    d = re.sub(r"\D", "", str(ean or ""))
    if len(d) not in (12, 13) or int(d[-1]) != _digito_de_control(d[:-1]):
        return None
    return {"barcode": d, "barcode_type": "EAN" if len(d) == 13 else "UPC-A"}


def _e(t) -> str:
    return html.escape(" ".join(str(t if t is not None else "").split()), quote=True)


def descripcion_html(l: dict) -> str:
    """Descripción del artículo: el nombre, la marca y la referencia, las categorías, la tabla de características y los enlaces a la ficha. Todo escapado. Pura."""
    partes = [f"<p><b>{_e(l.get('desc') or l.get('ref'))}</b></p>"]
    datos = [f"{etq}: {_e(v)}" for etq, v in (("Marca", l.get("marca")), ("Referencia", l.get("ref")), ("Familia", l.get("familia"))) if v]
    if datos:
        partes.append("<p>" + " · ".join(datos) + "</p>")
    cats = [c for c in (l.get("categorias") or []) if c]
    if cats:
        partes.append("<p>Categorías: " + "; ".join(_e(c) for c in cats[:6]) + "</p>")
    esp = list((l.get("especificaciones") or {}).items())[:MAX_ESPECIFICACIONES]
    if esp:
        partes.append("<table><tbody>" + "".join(f"<tr><td>{_e(k)}</td><td>{_e(v)}</td></tr>" for k, v in esp) + "</tbody></table>")
    enlaces = [(k, v) for k, v in (l.get("enlaces") or {}).items() if RE_ENLACE.match(str(v))]
    if enlaces:
        partes.append("<p>" + " · ".join(f'<a href="{_e(v)}" rel="noopener noreferrer">{_e(k)}</a>' for k, v in enlaces[:5]) + "</p>")
    return "".join(partes)[:MAX_DESCRIPCION]


def documento_articulo(l: dict, proveedor: str, cfg: dict, con_extras: bool = True) -> dict:
    """El documento `Item` de una línea de la tarifa. `con_extras=False` deja solo lo básico (sin marca, código de barras ni imagen): es el que se reintenta si el ERP rechaza el completo. Pura."""
    doc = {"item_code": l["codigo"], "item_name": (l.get("desc") or l["ref"])[:140], "description": descripcion_html(l) if con_extras else (l.get("desc") or l["ref"]),
           "item_group": cfg["item_group"], "stock_uom": l.get("unidad") or cfg["stock_uom"], "is_stock_item": 1, "is_purchase_item": 1,
           "supplier_items": [{"supplier": proveedor, "supplier_part_no": l["ref"]}]}
    if con_extras:
        if l.get("marca"):
            doc["brand"] = str(l["marca"])[:140]
        cb = codigo_de_barras(l.get("ean"))
        if cb:
            doc["barcodes"] = [cb]
        if l.get("imagen") and RE_HTTPS.match(str(l["imagen"])):
            doc["image"] = str(l["imagen"])
    return doc


def sin_codigos_repetidos(docs: list[dict]) -> tuple[list[dict], int]:
    """Quita el código de barras a los artículos cuyo código ya lo lleva otro de la misma carga (el ERP no admite el mismo código en dos artículos). Devuelve (documentos, cuántos se quitaron). Pura."""
    vistos: set[str] = set()
    quitados = 0
    out = []
    for d in docs:
        bs = d.get("barcodes") or []
        if bs and bs[0]["barcode"] in vistos:
            d = {k: v for k, v in d.items() if k != "barcodes"}
            quitados += 1
        elif bs:
            vistos.add(bs[0]["barcode"])
        out.append(d)
    return out, quitados
