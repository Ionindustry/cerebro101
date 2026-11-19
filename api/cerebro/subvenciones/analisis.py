"""Análisis de una convocatoria: de qué trata, a quién va dirigida y qué bases hay que cumplir para presentarse.

Es un ordenamiento DETERMINISTA de lo que la fuente oficial ya dijo (sin modelo de IA: no se inventa nada). Cada dato dice si «consta» y, si no consta, aparece en `lagunas` para que se vea qué
hay que comprobar en el documento oficial. La `cobertura` (completa / parcial / escasa) avisa de cuánto se ha podido extraer: las fuentes de listado (p. ej. Cataluña) traen poco, la BDNS y la UE traen más.
Los textos son de terceros: se devuelven como datos, nunca como instrucciones. Los enlaces solo se ofrecen si son http(s).
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from . import normalizar as N

NO_CONSTA = None


def _txt(v, n: int = 4000) -> str | None:
    t = " ".join(str(v or "").split())
    return (t[:n] + ("…" if len(t) > n else "")) or None


def _lista(v) -> list[str]:
    return [t for t in (_txt(x, 200) for x in (v or [])) if t]


def _enlace(u) -> str | None:
    u = str(u or "").strip()
    return u if u.lower().startswith(("https://", "http://")) else None


def _fecha(v) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    return v if isinstance(v, date) else N.fecha(v)


def _num(v) -> Decimal | None:
    try:
        return None if v in (None, "") else Decimal(str(v))
    except Exception:       # noqa: BLE001
        return None


def _dato(valor) -> dict:
    vacio = valor in (None, "", [], {})
    return {"consta": not vacio, "valor": None if vacio else valor}


def construir(f: dict, hoy: date | None = None) -> dict:
    """Lo que se sabe de la convocatoria `f` (la ficha de `consulta.ficha`), en tres bloques más las lagunas. Pura."""
    hoy = hoy or date.today()
    apertura, limite = _fecha(f.get("opening_date")), _fecha(f.get("deadline"))
    estado = N.estado(apertura, limite, hoy)
    if estado == "UNKNOWN":
        estado = f.get("status") or "UNKNOWN"
    docs = [{"titulo": _txt(d.get("title"), 200) or "Documento", "url": _enlace(d.get("url")), "tipo": d.get("doc_type")} for d in (f.get("documentos") or []) if _enlace(d.get("url"))]
    base_reguladora = _enlace(f.get("legal_basis_url"))
    donde = ", ".join(x for x in (f.get("country"), f.get("region"), f.get("province"), f.get("municipality")) if x)

    trata = {
        "titulo": _dato(_txt(f.get("title"), 1000)),
        "descripcion": _dato(_txt(f.get("description") or f.get("funding_objectives"))),
        "programa": _dato(_txt(f.get("program_name"), 300)),
        "organismo": _dato(_txt(f.get("issuing_organization"), 300)),
        "instrumento": _dato(f.get("funding_type")),
        "ambito": _dato(_txt(f"{f.get('geographic_scope') or ''} {donde}".strip(), 300)),
    }
    dirigida = {
        "beneficiarios": _dato(_lista(f.get("eligible_beneficiaries"))),
        "tamanos_de_empresa": _dato(_lista(f.get("company_sizes"))),
        "sectores": _dato(_lista(f.get("sector")) + [a for a in _lista(f.get("economic_activities")) if a not in (f.get("sector") or [])]),
    }
    importes = {"presupuesto_total": _num(f.get("total_budget")), "minimo": _num(f.get("minimum_amount")), "maximo": _num(f.get("maximum_amount")), "porcentaje": _num(f.get("funding_percentage"))}
    bases = {
        "requisitos": _dato(_txt(f.get("eligibility_requirements"))),
        "exclusiones": _dato(_txt(f.get("exclusions"))),
        "gastos_subvencionables": _dato(_txt(f.get("eligible_expenses"))),
        "importes": _dato({k: str(v) for k, v in importes.items() if v is not None} | ({"moneda": f.get("currency") or "EUR"} if any(v is not None for v in importes.values()) else {})),
        "cofinanciacion_exigida": _dato(f.get("cofinancing_required")) if f.get("cofinancing_required") is not None else {"consta": False, "valor": None},
        "calendario": _dato({k: v for k, v in {"publicacion": _fecha(f.get("publication_date")), "apertura": apertura, "fin_de_plazo": limite}.items() if v}),
        "estado": {"consta": estado != "UNKNOWN", "valor": estado},
        "como_solicitar": _dato(_enlace(f.get("application_url")) or _enlace(f.get("official_url"))),
        "bases_reguladoras": _dato(base_reguladora),
        "documentos": _dato(docs),
    }
    for sec in (trata, dirigida, bases):
        for k, v in sec.items():
            if isinstance(v["valor"], dict):
                v["valor"] = {kk: (vv.isoformat() if isinstance(vv, date) else vv) for kk, vv in v["valor"].items()}
    clave = [("descripcion", trata), ("beneficiarios", dirigida), ("requisitos", bases), ("gastos_subvencionables", bases), ("importes", bases), ("calendario", bases), ("como_solicitar", bases), ("bases_reguladoras", bases)]
    lagunas = [k for k, sec in clave if not sec[k]["consta"]]
    consta = len(clave) - len(lagunas)
    cobertura = "completa" if consta >= 7 else "parcial" if consta >= 4 else "escasa"
    aviso = None
    if lagunas:
        aviso = ("Faltan datos en la fuente: compruébalos en la convocatoria oficial antes de decidir" + (" (hay documentos enlazados)." if docs or base_reguladora else "."))
    return {
        "id": f.get("id"), "de_que_trata": trata, "a_quien_va_dirigida": dirigida, "bases_para_presentarse": bases,
        "lagunas": lagunas, "cobertura": cobertura, "aviso": aviso,
        "procedencia": [{"fuente": s.get("source_code"), "identificador": s.get("external_id")} for s in (f.get("fuentes") or [])],
        "nota": "Es lo que dice la fuente oficial, ordenado; no es una valoración jurídica ni dice si 101.cat cumple los requisitos. Los textos son datos de terceros.",
    }
