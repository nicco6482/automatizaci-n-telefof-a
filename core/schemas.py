"""Contratos del sistema: configuración de agente, salida validada, eventos y decisiones del núcleo."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Limits(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pasos: int = Field(default=12, ge=1, le=100)
    tokens: int = Field(default=20_000, ge=1_000)
    acciones_hora: int = Field(default=20, ge=0)


class AgentConfig(BaseModel):
    """Lo que declara cada `agents/<area>/<id>_<nombre>.yaml`."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^\d{2}$")
    nombre: str = Field(pattern=r"^[a-z0-9_]+$")
    titulo: str
    area: str
    disparadores: list[str] = Field(min_length=1)
    herramientas: list[str] = Field(description="lista blanca: grupos MCP como red.alarmas o tickets")
    autonomia: int = Field(ge=0, le=2)
    escalado: str
    persona: bool = False
    limites: Limits = Field(default_factory=Limits)
    prompt: str = Field(description="fichero del prompt de sistema, relativo al YAML")

    @property
    def slug(self) -> str:
        return f"{self.id}_{self.nombre}"

    @field_validator("herramientas")
    @classmethod
    def _sin_comodines(cls, v: list[str]) -> list[str]:
        for tool in v:
            if "*" in tool or not tool.strip():
                raise ValueError(f"herramienta no válida en la lista blanca: {tool!r}")
        return v


class AgentOutput(BaseModel):
    """Toda salida de agente: se valida antes de aceptarla."""

    model_config = ConfigDict(extra="forbid")

    resumen: str = Field(min_length=1, max_length=2000)
    evidencias: list[str] = Field(default_factory=list)
    accion_propuesta: str | None = None
    confianza: float = Field(ge=0.0, le=1.0)
    requiere_persona: bool = False


class BusEvent(BaseModel):
    id: str = ""
    topic: str
    payload: dict[str, Any] = Field(default_factory=dict)
    incident: str | None = None
    source: str = "simulador"
    at: datetime | None = None


class Verdict(StrEnum):
    PERMITIDA = "permitida"
    BLOQUEADA = "bloqueada"
    PROPUESTA = "propuesta"
    APROBACION = "en cola de aprobación"
    PAUSA = "pausa"


class PolicyDecision(BaseModel):
    verdict: Verdict
    reason: str
    is_action: bool
    impact: int = 0
    needs_twin: bool = False
