"""Contrato común de los conectores: cada fuente implementa esto y se añade sin tocar el núcleo.

Un conector solo sabe hablar con SU fuente: traer registros (por páginas, desde una marca de sincronización) y convertir cada uno al modelo unificado.
No guarda nada, no deduplica y no decide estados: eso es del núcleo (sincronizar.py). Si la fuente falla, lanza ErrorConector; si un registro suelto no vale, ErrorRegistro.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, AsyncIterator


class ErrorConector(RuntimeError):
    """La fuente no responde o devuelve algo que no se entiende en conjunto: la ejecución acaba en error (las demás fuentes siguen)."""


class ErrorRegistro(ValueError):
    """Un registro suelto no es válido (falta el identificador o el título): se cuenta y se sigue con el siguiente."""


@dataclass
class Pagina:
    registros: list[dict]                      # registros crudos tal como los da la fuente
    cursor: dict = field(default_factory=dict)  # marca de sincronización a guardar cuando esta página esté guardada (punto de reanudación)


class Conector:
    codigo: str = ""

    def __init__(self, fuente: dict, params: dict, cliente: Any = None):
        self.fuente = fuente
        self.params = params          # sincronizacion: del YAML (páginas máximas, tamaño, pausas, reintentos…)
        self.ajustes = dict(fuente.get("settings") or {})
        self.cliente = cliente        # cliente HTTP inyectable (las pruebas pasan uno falso)

    async def paginas(self, cursor: dict, hoy: date) -> AsyncIterator[Pagina]:   # pragma: no cover - interfaz
        raise NotImplementedError
        yield  # noqa

    def normalizar(self, crudo: dict, hoy: date) -> dict:                        # pragma: no cover - interfaz
        """El registro en el modelo unificado: claves de funding_opportunities más _external_id, _refs, _source_url, _documents y _confidence."""
        raise NotImplementedError
