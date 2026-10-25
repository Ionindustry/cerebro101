"""Comprobaciones de una factura leída de un documento (PDF, escaneo o foto) antes de dejarla en el ERP.

El modelo (o el OCR) puede equivocarse al leer cifras: antes de crear nada se comprueba que los datos cuadran entre sí (líneas, IVA y total) y
que el número de factura y el total aparecen realmente en el texto del documento. Si algo no cuadra se rechaza con un mensaje claro y
lo revisa una persona; lo que no es bloqueante (NIF, importes de línea) queda como advertencia en el resultado.
"""
from __future__ import annotations

import difflib
import re
import unicodedata
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal


class DatosFactura(ValueError):
    """Los datos no cuadran o no se pueden verificar: el mensaje dice qué falla."""


def a_decimal(valor) -> Decimal:
    """'1.210,00', '1,210.00', '1210', 1210.5 → Decimal. Rechaza lo que no sea un número claro."""
    if isinstance(valor, bool):
        raise DatosFactura(f"«{valor}» no es un importe")
    if isinstance(valor, (int, float, Decimal)):
        return Decimal(str(valor))
    t = re.sub(r"[€\s ]|EUR", "", str(valor or ""), flags=re.I)
    if not re.fullmatch(r"-?[\d.,]+", t):
        raise DatosFactura(f"«{valor}» no es un importe válido")
    if "," in t and "." in t:                                   # el último separador es el decimal
        decimal = "," if t.rfind(",") > t.rfind(".") else "."
        t = t.replace("." if decimal == "," else ",", "").replace(decimal, ".")
    elif "," in t or "." in t:
        sep = "," if "," in t else "."
        partes = t.split(sep)
        if len(partes) > 2:                                      # 1.234.567 → miles
            t = "".join(partes)
        elif len(partes[1]) == 3 and 0 < len(partes[0].lstrip("-")) <= 3 and partes[0].lstrip("-") != "0":
            raise DatosFactura(f"«{valor}» es ambiguo (¿miles o decimales?): escribe el importe con dos decimales, p. ej. 1210,00")
        else:
            t = f"{partes[0]}.{partes[1]}"
    return Decimal(t)


def centimos(d: Decimal) -> Decimal:
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def a_fecha(valor) -> str:
    """Fecha ISO (yyyy-mm-dd) a partir de formatos habituales en España. Rechaza fechas imposibles o absurdas."""
    t = str(valor or "").strip()
    for formato in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y"):
        try:
            f = datetime.strptime(t, formato).date()
            break
        except ValueError:
            continue
    else:
        raise DatosFactura(f"La fecha «{valor}» no es válida (usa dd/mm/aaaa o aaaa-mm-dd)")
    if not (2000 <= f.year <= date.today().year + 1):
        raise DatosFactura(f"La fecha {f.isoformat()} no es razonable para una factura")
    return f.isoformat()


def variantes_importe(v: Decimal) -> set[str]:
    """Formas en que puede aparecer un importe en un documento: 1210,00 · 1.210,00 · 1,210.00 · 1 210,00 · 1210.00 · 1210."""
    c = centimos(v)
    entero, dec = f"{abs(c):.2f}".split(".")
    miles = f"{int(entero):,}"
    signo = "-" if c < 0 else ""
    salida = {f"{entero},{dec}", f"{entero}.{dec}", f"{miles.replace(',', '.')},{dec}", f"{miles},{dec}",
              f"{miles.replace(',', ' ')},{dec}", f"{miles.replace(',', ' ')}.{dec}"}
    if dec == "00":
        salida |= {entero, miles.replace(",", "."), miles}
    return {signo + x for x in salida}


def aparece_importe(texto: str, v: Decimal) -> bool:
    t = texto.replace(" ", " ")
    return any(re.search(rf"(?<![\d.,]){re.escape(x)}(?![\d]|[.,]\d)", t) for x in variantes_importe(v))


def _alnum(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", s.lower())


def aparece_texto(texto: str, cadena: str) -> bool:
    return bool(_alnum(cadena)) and _alnum(cadena) in _alnum(texto)


def normalizar_nombre(n: str) -> str:
    """Para comparar proveedores: sin acentos, sin puntuación ni forma societaria (SL, S.L., SA…)."""
    s = unicodedata.normalize("NFKD", n or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s.replace(".", ""))
    return " ".join(p for p in s.split() if p not in ("sl", "sa", "slu", "sau", "scp", "cb"))


def buscar_proveedor(proveedores: list[dict], nombre: str, nif: str | None) -> dict:
    """El proveedor del ERP que corresponde: por NIF si lo hay, y si no por nombre. Si no hay uno claro, error con candidatos."""
    if nif:
        n = _alnum(nif)
        por_nif = [p for p in proveedores if _alnum(p.get("tax_id") or "") == n]
        if len(por_nif) == 1:
            return por_nif[0]
    norm = normalizar_nombre(nombre)
    exactos = [p for p in proveedores if normalizar_nombre(p.get("supplier_name") or p["name"]) == norm]
    if len(exactos) == 1:
        return exactos[0]
    if len(exactos) > 1:
        raise DatosFactura(f"Hay varios proveedores que encajan con «{nombre}»: " + ", ".join(p["name"] for p in exactos) + ". Lo decide una persona")
    parecidos = difflib.get_close_matches(norm, [normalizar_nombre(p.get("supplier_name") or p["name"]) for p in proveedores], n=3, cutoff=0.6)
    candidatos = [p["name"] for p in proveedores if normalizar_nombre(p.get("supplier_name") or p["name"]) in parecidos]
    raise DatosFactura(f"El proveedor «{nombre}»{f' (NIF {nif})' if nif else ''} no existe en el ERP; el alta de proveedores la hace una persona. "
                       + (f"Se parecen: {', '.join(candidatos)}." if candidatos else "No hay ninguno parecido."))


NIF = re.compile(r"^(?:[A-HJNPQRSUVW]\d{7}[0-9A-J]|\d{8}[A-Z]|[XYZ]\d{7}[A-Z])$")


def validar_lineas(lineas) -> list[dict]:
    if not isinstance(lineas, list) or not lineas:
        raise DatosFactura("La factura necesita al menos una línea (descripcion, cantidad y precio)")
    if len(lineas) > 60:
        raise DatosFactura("Demasiadas líneas (máximo 60): que la revise una persona")
    salida = []
    for i, l in enumerate(lineas, 1):
        if not isinstance(l, dict):
            raise DatosFactura(f"La línea {i} no es válida")
        desc = str(l.get("descripcion") or "").strip()
        if not desc:
            raise DatosFactura(f"La línea {i} no tiene descripción")
        try:
            cant, precio = a_decimal(l.get("cantidad")), a_decimal(l.get("precio"))
        except DatosFactura as e:
            raise DatosFactura(f"Línea {i}: {e}") from e
        if cant <= 0 or precio < 0:
            raise DatosFactura(f"Línea {i}: cantidad y precio deben ser positivos")
        salida.append({"descripcion": desc[:300], "cantidad": cant, "precio": precio})
    return salida


def comprobar(texto: str, proveedor: str, nif: str | None, numero: str, total: Decimal, lineas: list[dict], iva: int | None,
              tipos_iva: list[int], tolerancia: Decimal) -> tuple[int, Decimal, list[str]]:
    """(tipo de IVA, base imponible, advertencias). Lanza DatosFactura si lo esencial no cuadra o no está en el documento."""
    advertencias: list[str] = []
    base = centimos(sum(centimos(l["cantidad"] * l["precio"]) for l in lineas))
    if iva is not None:
        if int(iva) not in tipos_iva:
            raise DatosFactura(f"IVA del {iva}% no admitido (tipos admitidos: {', '.join(map(str, tipos_iva))}%). Que lo revise una persona")
        candidatos = [int(iva)]
    else:
        candidatos = tipos_iva
    tipo = next((t for t in candidatos if abs(centimos(base * (100 + t) / 100) - total) <= tolerancia), None)
    if tipo is None:
        raise DatosFactura(f"No cuadra: las líneas suman {base} (base imponible) y con IVA "
                           + (f"del {iva}% serían {centimos(base * (100 + int(iva)) / 100)}" if iva is not None else
                              "serían " + " / ".join(f"{centimos(base * (100 + t) / 100)} ({t}%)" for t in tipos_iva))
                           + f", pero el total de la factura es {total}. Revisa las líneas o el total en el documento")
    if not texto.strip():
        raise DatosFactura("No se ha podido leer ningún texto del documento: no se puede comprobar la factura")
    if not aparece_texto(texto, numero):
        raise DatosFactura(f"El número de factura «{numero}» no aparece en el documento: puede estar mal leído. Que lo revise una persona")
    if not aparece_importe(texto, total):
        raise DatosFactura(f"El total {total} no aparece en el documento (formas buscadas: {', '.join(sorted(variantes_importe(total))[:3])}…): "
                           "puede estar mal leído. Que lo revise una persona")
    if nif:
        if not NIF.match(_alnum(nif).upper()):
            advertencias.append(f"El NIF «{nif}» no tiene formato de NIF/CIF español")
        if not aparece_texto(texto, nif):
            advertencias.append(f"El NIF «{nif}» no aparece en el documento")
    if not aparece_texto(texto, proveedor):
        advertencias.append(f"El nombre del proveedor «{proveedor}» no aparece tal cual en el documento")
    for i, l in enumerate(lineas, 1):
        if not (aparece_importe(texto, centimos(l["cantidad"] * l["precio"])) or aparece_importe(texto, l["precio"])):
            advertencias.append(f"El importe de la línea {i} ({centimos(l['cantidad'] * l['precio'])}) no aparece en el documento")
    return tipo, base, advertencias
