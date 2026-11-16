"""Productos de referencia que NOMBRA el pliego («cámara Hikvision DS-2CD2143G2-I o equivalente»): marca, modelo, la frase literal y si admite equivalente.

Es determinista, sin modelo de IA: busca en el texto de los pliegos las marcas CONOCIDAS (las de tus tarifas, los fabricantes del ranking y las de `marcas_alias.yaml`) y mira lo que sigue (un
modelo es una palabra con letras y números: «DS-2CD2143G2-I»). Nada se inventa: cada referencia lleva la cita literal y su página. Una marca sin modelo se devuelve igual (el pliego la nombra),
pero sin modelo. Se usa para buscar en las fichas ese producto y los que lo igualan o superan, y para que una persona vea de un vistazo qué producto está pidiendo el pliego.
"""
from __future__ import annotations

import csv
import re
from functools import lru_cache
from pathlib import Path

from ..ajustes import ajustes

MAX_REFERENCIAS = 20
MIN_MARCA = 3
RELLENO = r"(?:modelo|mod\.?|ref\.?|referencia|serie|tipo|de|del|nº|n\.º|num\.?|código|codigo|similar a|tipo)"
RE_MODELO = re.compile(r"(?=[A-Za-z0-9./-]*\d)[A-Za-z0-9][A-Za-z0-9./-]{2,24}")
RE_EQUIVALENTE = re.compile(r"\bo\s+(?:similar|equivalente|equivalentes|superior|de\s+(?:caracter[ií]sticas|prestaciones)\s+\w+)|\b(?:equivalente|similar)(?:es)?\s+o\s+superior|\bor\s+(?:equivalent|similar)|\bo\s+(?:de\s+)?(?:igual|mejor)es?\b", re.I)


@lru_cache(maxsize=1)
def _marcas_de_config(dir_config: str) -> tuple[str, ...]:
    marcas: set[str] = set()
    try:
        import yaml
        cfg = yaml.safe_load((Path(dir_config) / "marcas_alias.yaml").read_text(encoding="utf-8")) or {}
        marcas |= {str(v) for v in (cfg.get("prefijos") or {}).values()} | {str(v) for v in (cfg.get("exactas") or {}).values()}
    except (OSError, ValueError):
        pass
    try:
        with open(Path(dir_config) / "fabricantes_ranking.csv", encoding="utf-8-sig", newline="") as f:
            marcas |= {(r.get("fabricante") or "").strip() for r in csv.DictReader(f)}
    except OSError:
        pass
    return tuple(sorted(m for m in marcas if len(m) >= MIN_MARCA))


def marcas_conocidas(extra: list[str] | None = None) -> list[str]:
    """Las marcas que se buscan: las de la configuración + `extra` (las de tus tarifas), sin repetir ni contar mayúsculas."""
    vistas: dict[str, str] = {}
    for m in list(_marcas_de_config(str(Path(ajustes.dir_config)))) + [str(x) for x in (extra or [])]:
        m = " ".join(m.split())
        if len(m) >= MIN_MARCA and not m.startswith("("):
            vistas.setdefault(m.lower(), m)
    return sorted(vistas.values(), key=lambda m: -len(m))


def _modelo_tras(texto: str, fin: int) -> str:
    resto = texto[fin:fin + 70]
    resto = re.sub(rf"^[\s,:;\-–—(]*(?:{RELLENO}\s+)*", "", resto, flags=re.I)
    m = RE_MODELO.match(resto)
    return m.group(0).rstrip(".-/") if m else ""


def extraer(paginas: list[tuple[int, int, str]], marcas: list[str], maximo: int = MAX_REFERENCIAS) -> list[dict]:
    """`paginas`: [(documento, página, texto)]. Devuelve [{marca, modelo, cita, equivalente, documento, pagina}], sin repetir (marca, modelo), las que traen modelo primero. Pura."""
    patrones = [(m, re.compile(rf"(?<![A-Za-z0-9]){re.escape(m)}(?![A-Za-z0-9])", re.I)) for m in marcas]
    vistas: dict[tuple[str, str], dict] = {}
    for doc, pag, texto in paginas:
        texto = texto or ""
        for marca, rx in patrones:
            for m in rx.finditer(texto):
                modelo = _modelo_tras(texto, m.end())
                ventana = texto[max(0, m.start() - 160): m.end() + 200]
                clave = (marca.lower(), modelo.lower())
                ref = vistas.get(clave)
                eq = bool(RE_EQUIVALENTE.search(ventana))
                if ref is None:
                    cita = " ".join(texto[max(0, m.start() - 80): m.end() + 140].split())
                    vistas[clave] = {"marca": marca, "modelo": modelo, "cita": cita, "equivalente": eq, "documento": doc, "pagina": pag}
                elif eq:
                    ref["equivalente"] = True
    # una marca sin modelo ya cubierta por una con modelo (la del mismo fabricante) sobra
    con_modelo = {k[0] for k in vistas if k[1]}
    salida = [v for k, v in vistas.items() if k[1] or k[0] not in con_modelo]
    salida.sort(key=lambda v: (not v["modelo"], v["documento"], v["pagina"], v["marca"].lower()))
    return salida[:maximo]


def consultas(refs: list[dict]) -> list[str]:
    """Las frases con las que buscar las fichas de lo que el pliego nombra («Hikvision DS-2CD2143G2-I»). Pura."""
    return [f"{r['marca']} {r['modelo']}".strip() for r in refs if r["modelo"]][:8]


def texto_para_modelo(refs: list[dict]) -> str:
    """Para el prompt de la tabla de equivalencias: qué productos nombra el pliego y si admite equivalentes. Vacío si no nombra ninguno con modelo. Pura."""
    con = [r for r in refs if r["modelo"]]
    if not con:
        return ""
    lineas = [f"- {r['marca']} {r['modelo']} ({'admite «o equivalente»' if r['equivalente'] else 'sin cláusula de equivalencia en la frase'}): «{r['cita'][:200]}» (documento {r['documento']}, página {r['pagina']})" for r in con[:10]]
    return ("Productos que el pliego NOMBRA como referencia (úsalos solo si su ficha está en la evidencia: sus datos fijan el mínimo que deben igualar o superar los equivalentes):\n" + "\n".join(lineas))
