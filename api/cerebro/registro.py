"""Registro de agentes: carga y valida las fichas de config/agentes/*.yaml.

Cada agente es un rol definido en configuración; no hay que programar un agente
nuevo, solo añadir su fila en scripts/generar_fichas.py y regenerar.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from .ajustes import ajustes

MODELOS = {"rapido", "principal", "vision", "juez"}
APROBACIONES = {"libre", "simple", "doble"}
SENSIBILIDADES = ("baja", "media", "alta")


@dataclass(frozen=True)
class Ficha:
    id: str
    nombre: str
    departamento: str
    subarea: str
    tareas: str
    modelo: str
    herramientas: tuple[str, ...]
    aprobacion: str
    horario: str | None
    sensibilidad: str
    director: bool


class ErrorFicha(ValueError):
    pass


def _leer(ruta: Path) -> dict:
    with open(ruta, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


@dataclass
class Registro:
    fichas: dict[str, Ficha]
    departamentos: dict[str, dict]

    def del_departamento(self, dep: str) -> list[Ficha]:
        return [f for f in self.fichas.values() if f.departamento == dep]

    def director_de(self, dep: str) -> Ficha:
        return self.fichas[self.departamentos[dep]["director"]]

    def programados(self) -> list[Ficha]:
        return [f for f in self.fichas.values() if f.horario]


def cargar(dir_config: Path | None = None) -> Registro:
    dir_config = dir_config or ajustes.dir_config
    deps = _leer(dir_config / "departamentos.yaml")["departamentos"]
    herramientas = set(_leer(dir_config / "herramientas.yaml")["herramientas"])
    fichas: dict[str, Ficha] = {}
    for ruta in sorted((dir_config / "agentes").glob("*.yaml")):
        for d in _leer(ruta).get("agentes", []):
            f = Ficha(
                id=d["id"], nombre=d["nombre"], departamento=d["departamento"], subarea=d["subarea"],
                tareas=d["tareas"], modelo=d["modelo"], herramientas=tuple(d["herramientas"]),
                aprobacion=d["aprobacion"], horario=d.get("horario"), sensibilidad=d["sensibilidad"],
                director=bool(d.get("director")),
            )
            _validar(f, deps, herramientas)
            if f.id in fichas:
                raise ErrorFicha(f"Agente duplicado: {f.id}")
            fichas[f.id] = f
    for dep_id, dep in deps.items():
        if dep["director"] not in fichas:
            raise ErrorFicha(f"El director de {dep_id} ({dep['director']}) no tiene ficha")
    return Registro(fichas=fichas, departamentos=deps)


def _validar(f: Ficha, deps: dict, herramientas: set[str]) -> None:
    if f.departamento not in deps:
        raise ErrorFicha(f"{f.id}: departamento desconocido {f.departamento}")
    if f.modelo not in MODELOS:
        raise ErrorFicha(f"{f.id}: modelo {f.modelo} no es uno de {sorted(MODELOS)}")
    if f.aprobacion not in APROBACIONES:
        raise ErrorFicha(f"{f.id}: aprobación {f.aprobacion} no válida")
    if f.sensibilidad not in SENSIBILIDADES:
        raise ErrorFicha(f"{f.id}: sensibilidad {f.sensibilidad} no válida")
    desconocidas = set(f.herramientas) - herramientas
    if desconocidas:
        raise ErrorFicha(f"{f.id}: herramientas no declaradas {sorted(desconocidas)}")
    if f.horario and len(f.horario.split()) != 5:
        raise ErrorFicha(f"{f.id}: horario cron no válido «{f.horario}»")


@lru_cache(maxsize=1)
def registro() -> Registro:
    return cargar()
