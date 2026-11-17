"""El identificador (UUID) de una licitación tal como lo escriben los modelos locales: a veces con comillas, «guillemets», corchetes, un punto final o el título detrás.

`limpiar` devuelve el UUID en minúsculas si el texto contiene EXACTAMENTE uno (el mismo repetido vale), o None. No inventa nada: solo recorta lo que sobra alrededor de un identificador que está escrito.
"""
from __future__ import annotations

import re

RE_UUID_EN_TEXTO = re.compile(r"(?<![0-9a-fA-F])[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}(?![0-9a-fA-F])")
MAX_LARGO = 200


def limpiar(valor) -> str | None:
    if not isinstance(valor, str) or len(valor) > MAX_LARGO:
        return None
    encontrados = {m.lower() for m in RE_UUID_EN_TEXTO.findall(valor)}
    return next(iter(encontrados)) if len(encontrados) == 1 else None
