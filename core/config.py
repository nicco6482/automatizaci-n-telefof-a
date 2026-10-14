"""Configuración por variables de entorno. Ningún secreto vive en el código."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="TELECO_", extra="ignore")

    database_url: str = f"sqlite+aiosqlite:///{(ROOT / 'teleco.db').as_posix()}"
    redis_url: str = "redis://localhost:6379/0"
    simulator_url: str = "http://localhost:8100"
    mcp_base_url: str = Field(default="http://localhost:8101", description="cada servidor en <base>/<nombre>/mcp")

    # "guion": agentes con respuestas guionizadas, sin coste. "claude": Claude Agent SDK con ANTHROPIC_API_KEY.
    agent_mode: Literal["guion", "claude"] = "guion"
    model: str = "claude-opus-5-5"

    blast_radius: int = Field(default=500, description="clientes a partir de los cuales se exige aprobación")
    agents_dir: Path = ROOT / "agents"
    extra_agents_dirs: list[Path] = Field(default_factory=list)
    seed: int = 42


@lru_cache
def get_settings() -> Settings:
    return Settings()
