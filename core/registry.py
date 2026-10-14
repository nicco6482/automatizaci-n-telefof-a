"""Carga los agentes desde sus YAML. Añadir un agente es añadir un YAML y su prompt."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel

from core.schemas import AgentConfig


class AgentDefinition(BaseModel):
    config: AgentConfig
    prompt: str
    path: Path


class RegistryError(ValueError):
    pass


def load_agent(path: Path) -> AgentDefinition:
    config = AgentConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    if path.stem != config.slug:
        raise RegistryError(f"{path.name}: el fichero debe llamarse {config.slug}.yaml")
    prompt_path = path.parent / config.prompt
    if not prompt_path.is_file():
        raise RegistryError(f"{path.name}: falta el prompt {config.prompt}")
    return AgentDefinition(config=config, prompt=prompt_path.read_text(encoding="utf-8"), path=path)


def load_registry(*dirs: Path) -> dict[str, AgentDefinition]:
    agents: dict[str, AgentDefinition] = {}
    for directory in dirs:
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*.yaml")):
            agent = load_agent(path)
            if agent.config.id in agents:
                raise RegistryError(f"id {agent.config.id} repetido en {path} y {agents[agent.config.id].path}")
            agents[agent.config.id] = agent
    return agents


def subscribers(agents: dict[str, AgentDefinition], topic: str) -> list[AgentDefinition]:
    return [a for a in agents.values() if topic in a.config.disparadores]
