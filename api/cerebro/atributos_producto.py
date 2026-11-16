"""Atributos normalizados de un producto (resolución, focal, IP, IK, canales…) leídos del texto de su línea de tarifa o ficha, y comprobados contra lo que pide el pliego.

Todo lo hace el código, con reglas fijas: es reproducible, no cuesta nada y no inventa. Un valor que no se puede leer queda como «sin dato», nunca como cumple ni como no cumple.
Sirve para ordenar los candidatos que proponen los vectores ANTES de que el modelo los vea: los que incumplen un mínimo por un dato leído pasan al final y llevan una nota «comprobado por el código».
La decisión de equivalencia sigue siendo de equivalencia.py; esto solo ordena y avisa.
"""
from __future__ import annotations

import re
import unicodedata

# atributo → (etiqueta, unidad, cómo se compara lo exigido con lo ofrecido)
ATRIBUTOS = {
    "resolucion_mp": ("resolución", "MP", "min"),
    "focal_min_mm": ("focal mínima", "mm", "foco"),
    "focal_max_mm": ("focal máxima", "mm", "foco"),
    "ip": ("protección IP", "", "min"),
    "ik": ("protección IK", "", "min"),
    "luz_min_lux": ("sensibilidad mínima", "lux", "max"),
    "alcance_ir_m": ("alcance IR", "m", "min"),
    "canales": ("canales", "", "min"),
    "almacenamiento_gb": ("almacenamiento", "GB", "min"),
    "bateria_ah": ("batería", "Ah", "min"),
    "poe": ("PoE", "", "dato"),
}

_NUM = r"(\d+(?:[.,]\d+)*)"


def _norm(t) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", str(t or "").lower()) if unicodedata.category(c) != "Mn")


def numero(s: str) -> float | None:
    """«0,0005» → 0.0005; «1.000» → 1000; «2.8» → 2.8; «1.234,5» → 1234.5."""
    s = s.strip()
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


def _todos(patron: str, t: str) -> list[float]:
    return [v for v in (numero(m) for m in re.findall(patron, t)) if v is not None]


def _tiene_lente(t: str) -> bool:
    return bool(re.search(r"\b(lente|lentes|lens|focal|objetivo|varifocal|zoom|motorizad\w*)\b", t))


def extraer(texto: str, para_exigencia: bool = False) -> dict[str, float]:
    """Atributos que se leen del texto. Con `para_exigencia` (el texto es un requisito del pliego) de varios valores se toma el más bajo aceptable en IP/IK (p. ej. «IP66/IP67» exige IP66). Pura."""
    t = _norm(texto)
    r: dict[str, float] = {}
    mp = _todos(rf"{_NUM}\s*(?:mp|mpx|megapixel\w*)\b", t)
    if not mp:
        for w, h in re.findall(r"\b(\d{3,4})\s*[x×*]\s*(\d{3,4})\b", t):
            if int(w) >= 640 and int(h) >= 480:
                mp.append(int(w) * int(h) / 1e6)
    if mp:
        r["resolucion_mp"] = round(max(mp), 2)
    ips = [float(x) for x in re.findall(r"\bip\s?-?(\d{2})\b", t)]
    if ips:
        r["ip"] = min(ips) if para_exigencia else max(ips)
    iks = [float(x) for x in re.findall(r"\bik\s?-?(\d{2})\b", t)]
    if iks:
        r["ik"] = min(iks) if para_exigencia else max(iks)
    if _tiene_lente(t):
        rango = re.findall(rf"{_NUM}\s*(?:-|–|—|~|a|to)\s*{_NUM}\s*mm\b", t)
        if rango:
            a, b = numero(rango[0][0]), numero(rango[0][1])
            if a is not None and b is not None:
                r["focal_min_mm"], r["focal_max_mm"] = min(a, b), max(a, b)
        else:
            f = _todos(rf"{_NUM}\s*mm\b", re.sub(r"\d+\s*[x×]\s*\d+(?:\s*[x×]\s*\d+)?\s*mm", " ", t))
            if f:
                r["focal_min_mm"] = r["focal_max_mm"] = f[0]
    lux = _todos(rf"{_NUM}\s*lux\b", t)
    if lux:
        r["luz_min_lux"] = min(lux)
    ir = _todos(rf"(?:\bir\b|infrarroj\w*|infrared|luz suplementaria|iluminacion|alcance|distance|range)\D{{0,25}}?{_NUM}\s*m\b(?!m)", t)
    if ir:
        r["alcance_ir_m"] = max(ir)
    ch = _todos(rf"{_NUM}\s*(?:canales|channels|ch)\b", t)
    if ch:
        r["canales"] = max(ch)
    gb = []
    for m in re.finditer(rf"{_NUM}\s*(tb|gb)\b", t):
        cerca = t[max(0, m.start() - 30):m.end() + 30]
        if re.search(r"micro\s?sd|\bsd\b|almacenamiento|storage|disco|hdd|ssd|memoria|tarjeta", cerca):
            v = numero(m.group(1))
            if v is not None:
                gb.append(v * (1000 if m.group(2) == "tb" else 1))
    if gb:
        r["almacenamiento_gb"] = max(gb)
    ah = _todos(rf"{_NUM}\s*ah\b", t)
    if ah:
        r["bateria_ah"] = max(ah)
    if re.search(r"\bpoe\b", t):
        r["poe"] = 1.0
    return r


def atributos_de_linea(l: dict) -> dict[str, float]:
    """Atributos de una línea de tarifa: lo que dicen su descripción y sus características. Pura."""
    esp = l.get("especificaciones") if isinstance(l.get("especificaciones"), dict) else {}
    texto = f"{l.get('desc') or ''} " + " ".join(f"{k}: {v}" for k, v in esp.items())
    return extraer(texto)


def restricciones(texto: str) -> list[dict]:
    """Lo que pide un requisito del pliego, como comparaciones que el código puede hacer: [{atributo, op, valor}]. «iguala o supera»: mínimos, salvo la sensibilidad (máximo en lux) y la focal (debe cubrir el rango). Pura."""
    a = extraer(texto, para_exigencia=True)
    out: list[dict] = []
    for k, v in a.items():
        _, _, modo = ATRIBUTOS[k]
        if modo == "min":
            out.append({"atributo": k, "op": ">=", "valor": v})
        elif modo == "max":
            out.append({"atributo": k, "op": "<=", "valor": v})
    if "focal_min_mm" in a:
        out.append({"atributo": "focal_min_mm", "op": "<=", "valor": a["focal_min_mm"]})
        out.append({"atributo": "focal_max_mm", "op": ">=", "valor": a["focal_max_mm"]})
    return out


def evaluar(rest: list[dict], atributos: dict) -> dict[str, list]:
    """Compara lo exigido con lo ofrecido: {cumple, no_cumple, sin_dato}, cada elemento (atributo, exigido, ofrecido). Un atributo que no se ha podido leer es «sin dato», no un incumplimiento. Pura."""
    res = {"cumple": [], "no_cumple": [], "sin_dato": []}
    for c in rest:
        ofrecido = atributos.get(c["atributo"])
        if ofrecido is None:
            res["sin_dato"].append((c["atributo"], c["valor"], None))
            continue
        ok = ofrecido >= c["valor"] - 1e-9 if c["op"] == ">=" else ofrecido <= c["valor"] + 1e-9
        res["cumple" if ok else "no_cumple"].append((c["atributo"], c["valor"], ofrecido, c["op"]))
    return res


def _fmt(v) -> str:
    return f"{v:g}".replace(".", ",")


def texto_de_comprobacion(res: dict[str, list]) -> str:
    """La nota que se enseña al modelo junto a la evidencia. Vacía si no había nada que comprobar. Pura."""
    if not (res["cumple"] or res["no_cumple"]):
        return ""
    def parte(x):
        etiqueta, unidad, _ = ATRIBUTOS[x[0]]
        u = f" {unidad}" if unidad else ""
        return f"{etiqueta} {x[3]} {_fmt(x[1])}{u} (ofrece {_fmt(x[2])}{u})"
    partes = [f"cumple {parte(x)}" for x in res["cumple"]] + [f"NO cumple {parte(x)}" for x in res["no_cumple"]]
    return "[Comprobado por el código frente al requisito: " + "; ".join(partes) + ". Lo que no aparece, sin dato.]"


def orden(res: dict[str, list]) -> tuple[int, int]:
    """Clave de ordenación (menor = antes): primero los que no incumplen nada leído, después los que cumplen más. Pura."""
    return (len(res["no_cumple"]) > 0, -len(res["cumple"]))
