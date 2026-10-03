"""Políticas de seguridad del Cerebro: aprobaciones humanas y uso de herramientas.

Estas reglas se aplican en código, no en las instrucciones del modelo: aunque un
modelo «decida» saltarse una aprobación, la acción no se ejecuta.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from .ajustes import ajustes
from .registro import SENSIBILIDADES, Ficha

ORDEN = {s: i for i, s in enumerate(SENSIBILIDADES)}


@lru_cache(maxsize=1)
def _config(dir_config: str) -> tuple[dict, dict]:
    d = Path(dir_config)
    with open(d / "politicas_aprobacion.yaml", encoding="utf-8") as fh:
        pol = yaml.safe_load(fh)
    with open(d / "herramientas.yaml", encoding="utf-8") as fh:
        her = yaml.safe_load(fh)
    return pol, her


class AccionProhibida(PermissionError):
    pass


class HerramientaNoPermitida(PermissionError):
    pass


@dataclass(frozen=True)
class DecisionAprobacion:
    requiere: bool
    nivel: str
    aprobadores: tuple[str, ...]
    voz_permitida: bool


def nivel_para(ficha: Ficha, accion: str, dir_config: Path | None = None) -> DecisionAprobacion:
    """Decide qué aprobación necesita `accion` hecha por el agente `ficha`."""
    pol, _ = _config(str(dir_config or ajustes.dir_config))
    if accion in pol["prohibidas"]:
        raise AccionProhibida(f"La acción «{accion}» no la puede ejecutar ningún agente")
    nivel = ficha.aprobacion
    if nivel == "libre" and accion in pol["impacto_externo"]:
        nivel = "simple"          # lo que sale de la empresa siempre pasa por una persona
    datos = pol["niveles"][nivel]
    return DecisionAprobacion(
        requiere=bool(datos["aprobadores"]),
        nivel=nivel,
        aprobadores=tuple(datos["aprobadores"]),
        voz_permitida=bool(datos.get("voz_permitida", False)),
    )


def herramienta_efectiva(ficha: Ficha, herramienta: str, sensibilidad_datos: str | None = None,
                         dir_config: Path | None = None) -> str:
    """Devuelve la herramienta a usar, o la alternativa local si los datos son
    demasiado sensibles para la externa. Lanza HerramientaNoPermitida si no hay opción."""
    _, her = _config(str(dir_config or ajustes.dir_config))
    if herramienta not in ficha.herramientas:
        raise HerramientaNoPermitida(f"{ficha.id} no tiene la herramienta «{herramienta}» en su ficha")
    sens = sensibilidad_datos or ficha.sensibilidad
    maxima = her["herramientas"][herramienta]["sensibilidad_max"]
    if ORDEN[sens] <= ORDEN[maxima]:
        return herramienta
    alternativa = her.get("alternativas_locales", {}).get(herramienta)
    if alternativa:
        return alternativa
    raise HerramientaNoPermitida(
        f"«{herramienta}» admite datos hasta sensibilidad {maxima}; {ficha.id} trabaja con {sens}")
