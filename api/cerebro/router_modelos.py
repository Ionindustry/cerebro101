"""Router de modelos: decide qué modelo local atiende cada tarea y con qué prioridad."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from .ajustes import ajustes
from .registro import Ficha


@lru_cache(maxsize=1)
def _modelos(dir_config: str) -> dict:
    with open(Path(dir_config) / "modelos.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@dataclass(frozen=True)
class Asignacion:
    clase: str           # rapido | principal | vision | juez
    modelo: str          # etiqueta de Ollama
    prioridad: int
    mantener_cargado: str  # valor keep_alive para Ollama


def asignar(ficha: Ficha, origen: str = "peticion", con_imagenes: bool = False,
            dificil: bool = False, perfil: str | None = None,
            dir_config: Path | None = None) -> Asignacion:
    """Elige el modelo para una tarea.

    - Si la tarea trae imágenes o PDF escaneados, va al modelo de visión.
    - Un agente «rápido» sube al principal si la tarea se marca como difícil
      (por ejemplo, cuando el modelo rápido no ha dado una respuesta válida).
    """
    cfg = _modelos(str(dir_config or ajustes.dir_config))
    perfil = perfil or ajustes.perfil_hardware or cfg["perfil_por_defecto"]
    clases = cfg["perfiles"][perfil]
    clase = ficha.modelo
    if con_imagenes:
        clase = "vision"
    elif dificil and clase == "rapido":
        clase = "principal"
    datos = clases[clase]
    keep = "-1" if datos.get("siempre_cargado") else f"{cfg['mantener_cargado_segundos']}s"
    return Asignacion(clase=clase, modelo=datos["modelo"],
                      prioridad=cfg["prioridades"].get(origen, 2), mantener_cargado=keep)


def modelos_necesarios(perfil: str | None = None, dir_config: Path | None = None) -> list[str]:
    """Etiquetas de Ollama que usa el perfil activo (más el modelo de embeddings): sirven para avisar de las que falten."""
    cfg = _modelos(str(dir_config or ajustes.dir_config))
    perfil = perfil or ajustes.perfil_hardware or cfg["perfil_por_defecto"]
    return sorted({d["modelo"] for d in cfg["perfiles"][perfil].values()} | {cfg["embeddings"]["modelo"]})
