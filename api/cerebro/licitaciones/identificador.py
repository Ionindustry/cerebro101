"""El identificador (UUID) de una licitación tal como lo escriben los modelos locales: a veces con comillas, «guillemets», corchetes, un punto final o el título detrás.

`limpiar` devuelve el UUID en minúsculas si el texto contiene EXACTAMENTE uno (el mismo repetido vale), o None. No inventa nada: solo recorta lo que sobra alrededor de un identificador que está escrito.
Lo que NO se admite, para que nadie cuele rutas o parámetros: un UUID pegado a «/», «?», «#», «&», «%» o «\\» (p. ej. «<uuid>/history», «<uuid>?a=b»): eso es un intento de cambiar la dirección que se consulta.
"""
from __future__ import annotations

import re

RE_UUID_EN_TEXTO = re.compile(r"(?<![0-9a-fA-F])[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}(?![0-9a-fA-F])")
MAX_LARGO = 200
ANTES = " \t\n\"'«»“”([{<=:,;"                  # lo que puede haber justo antes del identificador
DESPUES = " \t\n\"'«»“”)]}>.,;:"                  # y justo después


def limpiar(valor) -> str | None:
    if not isinstance(valor, str) or len(valor) > MAX_LARGO:
        return None
    encontrados = set()
    for m in RE_UUID_EN_TEXTO.finditer(valor):
        antes = valor[m.start() - 1] if m.start() > 0 else " "
        despues = valor[m.end()] if m.end() < len(valor) else " "
        if antes not in ANTES or despues not in DESPUES:
            return None
        encontrados.add(m.group(0).lower())
    return next(iter(encontrados)) if len(encontrados) == 1 else None
