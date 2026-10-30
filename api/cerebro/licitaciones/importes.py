"""Importes de una oferta para los modelos de proposición económica: formato español y cantidad en letra («ciento veinticinco mil euros con cincuenta céntimos»).

Todo es función pura de un Decimal: el precio lo fija una PERSONA (cerebro/licitaciones/ofertas.py) y aquí solo se formatea. En un documento que se firma, «en letra» tiene que ser exacto, por eso
está probado con muchos casos (apócope «un/veintiún» delante de «mil», «millón/millones», «cien/ciento», céntimos…)."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

MAX_IMPORTE = Decimal("999999999999.99")          # hasta casi un billón de euros: de sobra, y acota el texto

_UNI = ["cero", "uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve", "diez", "once", "doce", "trece", "catorce", "quince", "dieciséis", "diecisiete", "dieciocho",
        "diecinueve", "veinte", "veintiuno", "veintidós", "veintitrés", "veinticuatro", "veinticinco", "veintiséis", "veintisiete", "veintiocho", "veintinueve"]
_DEC = ["", "", "", "treinta", "cuarenta", "cincuenta", "sesenta", "setenta", "ochenta", "noventa"]
_CEN = ["", "ciento", "doscientos", "trescientos", "cuatrocientos", "quinientos", "seiscientos", "setecientos", "ochocientos", "novecientos"]


def _hasta_99(r: int, apocope: bool) -> str:
    if r < 30:
        w = _UNI[r]
        if apocope and r == 1:
            return "un"
        if apocope and r == 21:
            return "veintiún"
        return w
    d, u = divmod(r, 10)
    return _DEC[d] + (f" y {'un' if apocope and u == 1 else _UNI[u]}" if u else "")


def _hasta_999(n: int, apocope: bool) -> str:
    c, r = divmod(n, 100)
    partes = []
    if c:
        partes.append("cien" if c == 1 and r == 0 else _CEN[c])
    if r:
        partes.append(_hasta_99(r, apocope))
    return " ".join(partes)


def _hasta_999_999(n: int, apocope: bool) -> str:
    """De 1 a 999.999: «mil» no lleva «un» delante (1000 es «mil», no «un mil») y el apócope va delante de «mil» aunque el número acabe en uno («veintiún mil»)."""
    miles, unidades = divmod(n, 1000)
    partes = []
    if miles:
        partes.append("mil" if miles == 1 else _hasta_999(miles, True) + " mil")
    if unidades:
        partes.append(_hasta_999(unidades, apocope))
    return " ".join(partes)


def a_letras(n: int, apocope: bool = True) -> str:
    """Un entero (0 a 999.999.999.999) en letra. `apocope`: «un» y «veintiún» en lugar de «uno» y «veintiuno» cuando va delante de un sustantivo («un euro», «veintiún euros»)."""
    if isinstance(n, bool) or not isinstance(n, int) or n < 0 or n > 999_999_999_999:
        raise ValueError("número fuera de rango")
    if n == 0:
        return "cero"
    millones, resto = divmod(n, 1_000_000)               # 1.000.000.000 son «mil millones»: los millones se dicen como un número de hasta seis cifras
    partes = []
    if millones:
        partes.append("un millón" if millones == 1 else _hasta_999_999(millones, True) + " millones")
    if resto:
        partes.append(_hasta_999_999(resto, apocope))
    return " ".join(partes)


def euros(valor: Decimal | str | int | float) -> Decimal:
    """El importe a 2 decimales (redondeo comercial). ValueError si no es un importe válido."""
    try:
        d = Decimal(str(valor)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:       # noqa: BLE001 — Decimal lanza varias excepciones según la entrada
        raise ValueError("importe no válido") from None
    if not d.is_finite() or d < 0 or d > MAX_IMPORTE:
        raise ValueError("importe fuera de rango")
    return d


def formato_es(d: Decimal) -> str:
    """125000.5 → «125.000,50»."""
    return f"{euros(d):,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def porcentaje_es(d: Decimal) -> str:
    """21 → «21»; 10.5 → «10,5»."""
    t = format(Decimal(str(d)).normalize(), "f")
    return t.replace(".", ",")


def euros_en_letra(d: Decimal, con_unidad: bool = True) -> str | None:
    """«ciento veinticinco mil euros con cincuenta céntimos». Con `con_unidad=False` solo la parte de euros («ciento veinticinco mil»), que vale si el documento ya trae la palabra «euros» detrás del
    hueco; si hay céntimos eso no se puede decir bien y devuelve None (que lo complete una persona)."""
    d = euros(d)
    ent, cts = int(d), int((d - int(d)) * 100)
    redondo = ent > 0 and ent % 1_000_000 == 0                       # «un millón DE euros», «dos millones DE euros»
    if not con_unidad:
        return a_letras(ent) if cts == 0 and not redondo else None
    t = f"{a_letras(ent)}{' de' if redondo else ''} euro" + ("" if ent == 1 else "s")
    if cts:
        t += f" con {a_letras(cts)} céntimo" + ("" if cts == 1 else "s")
    return t
