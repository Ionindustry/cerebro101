"""Esquema exacto de las herramientas: lo que ve el modelo en su prompt y lo que se comprueba antes de ejecutar.

Los modelos pequeños inventan nombres de operaciones y de argumentos si solo leen una frase de descripción. Aquí el
esquema se deriva de las firmas reales de las funciones (no se escribe dos veces) y las llamadas se validan antes de
ejecutarlas, con un mensaje que dice exactamente qué está permitido para que el modelo pueda corregirse.
"""
from __future__ import annotations

import inspect
import json
import re
from dataclasses import dataclass
from typing import Any

# Los pone el sistema, no el modelo: el departamento y la sensibilidad salen de la ficha del agente y de la petición
OCULTOS = frozenset({"departamento", "sensibilidad"})


class ArgumentosNoValidos(ValueError):
    """La llamada a la herramienta no se ajusta a su esquema. El mensaje es para el modelo."""


@dataclass
class Parametro:
    nombre: str
    tipo: str                 # texto, entero, número, sí/no, objeto, lista…
    obligatorio: bool
    defecto: Any = None


_BASE = {"str": "texto", "int": "entero", "float": "número", "bool": "sí/no", "dict": "objeto", "list": "lista"}


def nombre_tipo(anotacion: Any) -> str:
    """'list[str] | None' → 'lista de textos'. Con `from __future__ import annotations` las anotaciones son cadenas."""
    t = str(anotacion).replace("'", "").replace("typing.", "")
    t = re.sub(r"\s*\|\s*None\b", "", t).replace("Optional[", "").strip()
    partes = re.split(r"\s*\|\s*(?![^\[]*\])", t)                  # uniones fuera de corchetes: «list[str] | str»
    if len(partes) > 1:
        return " o ".join(nombre_tipo(x) for x in partes)
    t = re.sub(r"^Any$", "cualquiera", t)
    m = re.match(r"^(list|dict)\[(.*)\]$", t)
    if m:
        base, interior = m.groups()
        if base == "list":
            return "lista de " + {"str": "textos", "int": "enteros", "float": "números", "dict": "objetos"}.get(interior.split(",")[0].strip(), "elementos")
        return "objeto"
    return _BASE.get(t, t)


def parametros(funcion) -> tuple[list[Parametro], bool]:
    """(parámetros que ve el modelo, acepta_campos_libres). Los parámetros de `OCULTOS` no aparecen."""
    salida, libres = [], False
    for p in inspect.signature(funcion).parameters.values():
        if p.kind is inspect.Parameter.VAR_KEYWORD:
            libres = True
        elif p.kind is inspect.Parameter.VAR_POSITIONAL or p.name in OCULTOS:
            continue
        else:
            vacio = p.default is inspect.Parameter.empty
            salida.append(Parametro(p.name, nombre_tipo(p.annotation) if p.annotation is not inspect.Parameter.empty else "cualquiera",
                                    vacio, None if vacio else p.default))
    return salida, libres


def firma(nombre: str, funcion) -> str:
    """erpnext.listar → 'listar(doctype: texto, filtros?: lista, limite?: entero = 50)'."""
    params, libres = parametros(funcion)
    partes = [f"{p.nombre}{'' if p.obligatorio else '?'}: {p.tipo}" + ("" if p.obligatorio or p.defecto in (None, "") else f" = {json.dumps(p.defecto, ensure_ascii=False)}")
              for p in params]
    if libres:
        partes.append("…campos")
    return f"{nombre}({', '.join(partes)})"


def describir(h) -> str:
    """Bloque del prompt para una herramienta: descripción, operaciones con sus argumentos y un ejemplo."""
    lineas = [f"- {h.nombre}: {h.descripcion.strip()}"]
    for op, f in h.operaciones.items():
        marca = "  [necesita aprobación humana: no la llames, propónla en «acciones»]" if op in h.externas else ""
        ayuda = h.ayuda.get(op, "")
        lineas.append(f"    · {firma(op, f)}{' — ' + ayuda if ayuda else ''}{marca}")
        for campo, texto in (h.campos.get(op) or {}).items():
            lineas.append(f"        {campo}: {texto}")
    if h.ejemplos:
        op, args = next(iter(h.ejemplos.items()))
        lineas.append("    ejemplo: " + json.dumps({"tipo": "herramienta", "herramienta": h.nombre, "operacion": op, "argumentos": args}, ensure_ascii=False))
    return "\n".join(lineas)


def _comprueba_tipo(nombre: str, valor: Any, tipo: str) -> str | None:
    if valor is None:
        return None
    if " o " in tipo:
        return None if any(_comprueba_tipo(nombre, valor, t) is None for t in tipo.split(" o ")) else f"«{nombre}» debe ser {tipo}, no {type(valor).__name__}"
    ok = {"texto": isinstance(valor, str), "entero": isinstance(valor, int) and not isinstance(valor, bool),
          "número": isinstance(valor, (int, float)) and not isinstance(valor, bool), "sí/no": isinstance(valor, bool),
          "objeto": isinstance(valor, dict)}.get(tipo, True)
    if tipo.startswith("lista"):
        ok = isinstance(valor, list)
    return None if ok else f"«{nombre}» debe ser {tipo}, no {type(valor).__name__}"


def validar(h, operacion: str, argumentos: dict) -> None:
    """Lanza ArgumentosNoValidos con un mensaje que dice qué está permitido. No ejecuta nada."""
    if operacion not in h.operaciones:
        raise LookupError(f"«{h.nombre}» no tiene la operación «{operacion}». Operaciones: {', '.join(h.operaciones)}")
    params, libres = parametros(h.operaciones[operacion])
    validos = {p.nombre: p for p in params}
    documentados = h.campos.get(operacion) or {}
    propios = {k: v for k, v in argumentos.items() if k not in OCULTOS}      # lo que el modelo pone se ignora si es del sistema
    desconocidos = [k for k in propios if k not in validos and not (libres and (not documentados or k in documentados))]
    ayuda = f"Uso: {firma(operacion, h.operaciones[operacion])}"
    if desconocidos:
        permitidos = list(validos) + (list(documentados) if libres else [])
        raise ArgumentosNoValidos(f"«{operacion}» no admite {', '.join(f'«{d}»' for d in desconocidos)}. Argumentos permitidos: "
                                  f"{', '.join(permitidos) or 'ninguno'}. {ayuda}")
    faltan = [p.nombre for p in params if p.obligatorio and p.nombre not in propios]
    if faltan:
        raise ArgumentosNoValidos(f"Faltan argumentos obligatorios de «{operacion}»: {', '.join(faltan)}. {ayuda}")
    for k, v in propios.items():
        if k in validos and (mal := _comprueba_tipo(k, v, validos[k].tipo)):
            raise ArgumentosNoValidos(f"{mal}. {ayuda}")
