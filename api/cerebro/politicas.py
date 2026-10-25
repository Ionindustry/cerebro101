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
    clase: str = "estandar"       # estandar | supervisada | reservada


def clase_de(accion: str, herramienta: str = "", operacion: str = "", externa: bool = False, dir_config: Path | None = None) -> str:
    """Qué necesita una acción: `estandar` (nada), `supervisada` (tu firma) o `reservada` (firma individual, nunca por voz ni cubierta por un objetivo).
    Una acción prohibida lanza AccionProhibida. Lo que no se reconoce como supervisado ni reservado es estándar, salvo que salga de la empresa."""
    pol, _ = _config(str(dir_config or ajustes.dir_config))
    if accion in pol["prohibidas"]:
        raise AccionProhibida(f"La acción «{accion}» no la puede ejecutar ningún agente")
    sup = pol.get("supervision") or {}
    clave = f"{herramienta}.{operacion}" if herramienta and operacion else ""
    nombres = {accion, clave} - {""}
    if nombres & set(sup.get("reservadas") or []):
        return "reservada"
    if externa or accion in pol["impacto_externo"] or nombres & set(sup.get("supervisadas") or []):
        return "supervisada"
    return "estandar"


def nivel_para(ficha: Ficha, accion: str, dir_config: Path | None = None, externa: bool = False,
               herramienta: str = "", operacion: str = "") -> DecisionAprobacion:
    """Decide qué aprobación necesita `accion` hecha por el agente `ficha`.

    La firma depende de la operación (ver `clase_de`), no del agente: las operaciones estándar no la piden aunque el agente sea «simple» o «doble».
    `externa`: la operación de la herramienta tiene impacto externo, sea cual sea el nombre que el agente dé a la acción.
    El nivel de la ficha solo afecta a cómo se firma lo que sí la pide: «doble» (y lo reservado) solo se firma en el panel, no por voz."""
    pol, _ = _config(str(dir_config or ajustes.dir_config))
    clase = clase_de(accion, herramienta, operacion, externa, dir_config)
    if clase == "estandar":
        return DecisionAprobacion(requiere=False, nivel="libre", aprobadores=(), voz_permitida=False, clase=clase)
    nivel = "doble" if clase == "reservada" or ficha.aprobacion == "doble" else "simple"
    datos = pol["niveles"][nivel]
    return DecisionAprobacion(
        requiere=bool(datos["aprobadores"]),
        nivel=nivel,
        aprobadores=tuple(datos["aprobadores"]),
        voz_permitida=bool(datos.get("voz_permitida", False)),
        clase=clase,
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
