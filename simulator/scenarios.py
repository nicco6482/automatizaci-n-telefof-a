"""Escenarios reproducibles: semilla, lo que ocurre (averías, eventos, reloj, personas) y el resultado esperado."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

from simulator.models import FaultType


class Injection(BaseModel):
    type: FaultType
    node: str | None = None
    zone: str | None = None
    with_backup: bool | None = None
    after_minutes: int = 0


class EventSpec(BaseModel):
    topic: str
    payload: dict[str, Any] = Field(default_factory=dict)
    generate: bool = Field(default=False, description="generar el evento de negocio con ops.business")


class Expectation(BaseModel):
    """Una comprobación sobre la auditoría del escenario."""

    agent: str
    step: str = Field(description="tipo de paso en auditoría: lectura, accion, salida, bloqueo, aprobacion…")
    tool: str | None = None
    decision: str | None = Field(default=None, description="texto que debe contener la decisión")
    input_contains: str | None = Field(default=None, description="texto que debe aparecer en la entrada")
    result_contains: str | None = Field(default=None, description="texto que debe aparecer en el resultado")
    absent: bool = Field(default=False, description="la entrada NO debe aparecer")


HumanStep = Literal["aprobar_todo", "rechazar_todo", "cerrar_avisos", "cerrar_tareas"]


class Scenario(BaseModel):
    id: str
    name: str
    agent: str = Field(description="agente al que pertenece el escenario")
    seed: int = 42
    runs: int = 5
    pass_rate: float = 0.9
    inject: Injection | None = None
    events: list[EventSpec] = Field(default_factory=list)
    advance_minutes: int = Field(default=0, description="minutos simulados que corre el reloj tras inyectar")
    human: list[HumanStep] = Field(default_factory=list, description="lo que hace la persona después")
    trace: Literal["incidente", "todo"] = Field(
        default="incidente", description="comprobar solo la traza del incidente o toda la auditoría"
    )
    expect: list[Expectation]
    settings: dict[str, int | float | bool] = Field(default_factory=dict)


def load_scenarios(directory: Path) -> list[Scenario]:
    scenarios = []
    for path in sorted(directory.rglob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        scenarios.append(Scenario.model_validate(data))
    return scenarios
