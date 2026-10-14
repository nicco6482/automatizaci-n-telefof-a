"""Escenarios reproducibles: semilla, avería inyectada y resultado esperado."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from simulator.models import FaultType


class Injection(BaseModel):
    type: FaultType
    node: str | None = None
    zone: str | None = None
    with_backup: bool | None = None
    after_minutes: int = 0


class Expectation(BaseModel):
    """Una comprobación sobre la auditoría del incidente."""

    agent: str
    step: str = Field(description="tipo de paso en auditoría: lectura, accion, salida, bloqueo, aprobacion…")
    tool: str | None = None
    decision: str | None = Field(default=None, description="texto que debe contener la decisión")
    absent: bool = Field(default=False, description="la entrada NO debe aparecer")


class Scenario(BaseModel):
    id: str
    name: str
    agent: str = Field(description="agente al que pertenece el escenario")
    seed: int = 42
    runs: int = 5
    pass_rate: float = 0.9
    inject: Injection
    expect: list[Expectation]
    settings: dict[str, int | float | bool] = Field(default_factory=dict)


def load_scenarios(directory: Path) -> list[Scenario]:
    scenarios = []
    for path in sorted(directory.rglob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        scenarios.append(Scenario.model_validate(data))
    return scenarios
