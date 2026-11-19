"""Normalización de lo que dan las fuentes: fechas, importes, estados, tipos de instrumento y huellas. Código puro y determinista."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

ESTADOS = ("NEW", "UPDATED", "OPENING_SOON", "OPEN", "CLOSING_SOON", "CLOSED", "CANCELLED", "UNKNOWN")
INSTRUMENTOS = ("subvencion", "prestamo", "prestamo_participativo", "garantia", "aval", "incentivo_fiscal", "bonificacion", "mixta", "premio", "otro")


def sin_acentos(t) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", str(t or "")) if unicodedata.category(c) != "Mn")


def plano(t) -> str:
    """Minúsculas, sin acentos y con los espacios colapsados: para comparar textos."""
    return " ".join(sin_acentos(t).lower().split())


def limpiar(t, maximo: int = 4000) -> str | None:
    t = " ".join(str(t or "").split())
    return t[:maximo] or None


_FECHA_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:[T ].*)?$")
_FECHA_ES = re.compile(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})(?:[T ].*)?$")


def fecha(v) -> date | None:
    """Una fecha de la fuente (ISO «2026-03-01», «2026-03-01T10:00:00», «01/03/2026») o None si no se reconoce o no existe."""
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    t = str(v or "").strip()
    for er, orden in ((_FECHA_ISO, (1, 2, 3)), (_FECHA_ES, (3, 2, 1))):
        m = er.match(t)
        if m:
            try:
                return date(int(m.group(orden[0])), int(m.group(orden[1])), int(m.group(orden[2])))
            except ValueError:
                return None
    return None


def importe(v) -> Decimal | None:
    """Un importe en euros u otra moneda: acepta números y textos («1.234,56», «1234.56», «12 000 €»). None si no se entiende o es negativo."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float, Decimal)):
        d = Decimal(str(v))
        return d if d >= 0 else None
    t = re.sub(r"[^\d,.\-]", "", str(v))
    if not t or t in ("-", ",", "."):
        return None
    if "," in t and "." in t:
        t = t.replace(".", "").replace(",", ".") if t.rfind(",") > t.rfind(".") else t.replace(",", "")
    elif "," in t:
        t = t.replace(",", ".")
    elif t.count(".") > 1:
        t = t.replace(".", "")
    try:
        d = Decimal(t)
    except InvalidOperation:
        return None
    return d if d >= 0 else None


def porcentaje(v) -> Decimal | None:
    d = importe(v)
    return d if d is not None and d <= 100 else None


_INSTRUMENTOS = (
    ("prestamo_participativo", ("prestamo participativo", "prestamos participativos")),
    ("prestamo", ("prestamo", "credito", "financiacion reembolsable", "anticipo reembolsable")),
    ("aval", ("aval", "avales")),
    ("garantia", ("garantia", "garantias")),
    ("incentivo_fiscal", ("incentivo fiscal", "deduccion fiscal", "deducciones fiscales", "credito fiscal")),
    ("bonificacion", ("bonificacion", "bonificaciones")),
    ("premio", ("premio", "premios", "concurso de ideas")),
    ("mixta", ("financiacion mixta", "mixta")),
    ("subvencion", ("subvencion", "subvenciones", "ayuda", "ayudas", "fondo perdido", "grant", "grants", "subsidio")),
)


def instrumento(texto) -> str | None:
    """El tipo de instrumento a partir de lo que la fuente declare (nunca del título de una convocatoria por intuición): None si no se puede saber.
    «préstamo participativo» se distingue de «subvención a fondo perdido» (no son lo mismo)."""
    t = plano(texto)
    if not t:
        return None
    for nombre, claves in _INSTRUMENTOS:
        for c in claves:
            if re.search(rf"\b{re.escape(c)}\b", t):
                return nombre
    return None


def estado(apertura: date | None, limite: date | None, hoy: date, cancelada: bool = False, abierta_declarada: bool | None = None, dias_cierre: int = 15) -> str:
    """El estado del ciclo de vida según las fechas (y lo que la fuente declare). Sin fechas ni declaración: UNKNOWN. NEW y UPDATED no son del ciclo de vida: son novedades y se calculan aparte."""
    if cancelada:
        return "CANCELLED"
    if limite is not None and limite < hoy:
        return "CLOSED"
    if apertura is not None and apertura > hoy:
        return "OPENING_SOON"
    if limite is not None:
        return "CLOSING_SOON" if (limite - hoy) <= timedelta(days=dias_cierre) else "OPEN"
    if abierta_declarada is True:
        return "OPEN"
    if abierta_declarada is False:
        return "CLOSED"
    return "UNKNOWN"


def huella(obj) -> str:
    """SHA-256 estable de un objeto JSON (claves ordenadas): sirve para saber si lo que da la fuente ha cambiado."""
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


# Campos que se comparan para detectar cambios sustanciales y se guardan en el historial
CAMPOS_SEGUIDOS = ("title", "description", "program_name", "issuing_organization", "official_url", "application_url", "country", "region", "province", "municipality",
                   "geographic_scope", "eligible_beneficiaries", "company_sizes", "economic_activities", "sector", "funding_objectives", "funding_type", "total_budget",
                   "minimum_amount", "maximum_amount", "funding_percentage", "currency", "cofinancing_required", "publication_date", "opening_date", "deadline",
                   "legal_basis_url", "eligibility_requirements", "exclusions", "eligible_expenses")
# Cambios que importan al usuario (alertas): el resto se guarda en el historial pero no es una novedad
CAMPOS_SUSTANCIALES = ("deadline", "opening_date", "total_budget", "minimum_amount", "maximum_amount", "funding_percentage", "eligibility_requirements",
                       "eligible_beneficiaries", "region", "province", "country", "exclusions", "eligible_expenses", "legal_basis_url", "funding_type")


def _canon(v):
    if isinstance(v, Decimal):
        return format(v.normalize(), "f")
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, (list, tuple, set)):
        return sorted(_canon(x) for x in v)
    return v


def cambios(antes: dict, despues: dict) -> list[dict]:
    """Los campos seguidos que han cambiado entre dos versiones normalizadas: [{field, old, new}] (valores serializables). Un campo que pasa de conocido a desconocido
    NO cuenta como cambio (la fuente dejó de darlo, no es que haya cambiado: se conserva lo que ya se sabía)."""
    out = []
    for c in CAMPOS_SEGUIDOS:
        a, d = _canon(antes.get(c)), _canon(despues.get(c))
        if d in (None, [], "") or a == d:
            continue
        out.append({"field": c, "old": None if a in ([], "") else a, "new": d})
    return out


def huella_normalizada(opp: dict) -> str:
    return huella({c: _canon(opp.get(c)) for c in CAMPOS_SEGUIDOS})
