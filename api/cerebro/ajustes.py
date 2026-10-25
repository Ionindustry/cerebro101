"""Ajustes del Cerebro leídos de variables de entorno (ver .env.example)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]


def _env(nombre: str, defecto: str = "") -> str:
    return os.environ.get(nombre, defecto)


@dataclass(frozen=True)
class Ajustes:
    raiz: Path = RAIZ
    dir_config: Path = field(default_factory=lambda: Path(_env("CEREBRO_CONFIG", str(RAIZ / "config"))))
    perfil_hardware: str = field(default_factory=lambda: _env("PERFIL_HARDWARE", "pequena"))
    ollama_url: str = field(default_factory=lambda: _env("OLLAMA_URL", "http://ollama:11434"))
    database_url: str = field(default_factory=lambda: _env("DATABASE_URL", "postgresql://cerebro:cerebro@postgres:5432/cerebro"))
    redis_url: str = field(default_factory=lambda: _env("REDIS_URL", "redis://redis:6379/0"))
    erpnext_url: str = field(default_factory=lambda: _env("ERPNEXT_URL", ""))
    xai_api_key: str = field(default_factory=lambda: _env("XAI_API_KEY", ""))
    jev_url: str = field(default_factory=lambda: _env("JEV_URL", ""))
    jev_api_key: str = field(default_factory=lambda: _env("JEV_API_KEY", ""))
    jeff_url: str = field(default_factory=lambda: _env("JEFF_URL", "http://jeff:8080"))
    usar_jev_nube: bool = field(default_factory=lambda: _env("USAR_JEV_NUBE", "false").lower() == "true")
    agent_reach_url: str = field(default_factory=lambda: _env("AGENT_REACH_URL", "http://agent-reach:8090"))
    zona_horaria: str = field(default_factory=lambda: _env("TZ", "Europe/Madrid"))


ajustes = Ajustes()
