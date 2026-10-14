"""Nombres de herramientas y catálogo de acciones.

Una herramienta tiene tres nombres:
- canónico (YAML, auditoría):    red.runbooks.conmutar_respaldo
- en el servidor MCP «red»:      runbooks__conmutar_respaldo
- en el Claude Agent SDK:        mcp__red__runbooks__conmutar_respaldo
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel

CATALOG_PATH = Path(__file__).with_name("actions_catalog.yaml")
SDK_PREFIX = "mcp__"


class ToolSpec(BaseModel):
    # entrega: deja trabajo a una persona (borrador, validación). No toca la red; se permite en cualquier nivel.
    tipo: Literal["lectura", "accion", "entrega"]
    nivel2: bool = False
    gemelo: str | None = None
    impacto: str | None = None
    cambio: bool = False  # cambio de configuración de red: siempre gemelo + aprobación (puerta de la Fase 2)


class ToolName(BaseModel):
    server: str
    tool: str

    @property
    def canonical(self) -> str:
        return f"{self.server}.{self.tool.replace('__', '.')}"

    @property
    def sdk(self) -> str:
        return f"{SDK_PREFIX}{self.server}__{self.tool}"

    @classmethod
    def from_canonical(cls, name: str) -> ToolName:
        server, _, rest = name.partition(".")
        if not server or not rest:
            raise ValueError(f"nombre canónico no válido: {name!r}")
        return cls(server=server, tool=rest.replace(".", "__"))

    @classmethod
    def from_sdk(cls, name: str) -> ToolName:
        if not name.startswith(SDK_PREFIX):
            raise ValueError(f"no es una herramienta MCP: {name!r}")
        server, sep, tool = name[len(SDK_PREFIX) :].partition("__")
        if not sep or not tool:
            raise ValueError(f"nombre MCP no válido: {name!r}")
        return cls(server=server, tool=tool)


def in_whitelist(canonical: str, whitelist: list[str]) -> bool:
    return any(canonical == entry or canonical.startswith(entry + ".") for entry in whitelist)


@lru_cache
def catalog() -> dict[str, ToolSpec]:
    raw = yaml.safe_load(CATALOG_PATH.read_text(encoding="utf-8"))
    return {name: ToolSpec.model_validate(spec) for name, spec in raw["herramientas"].items()}


def spec_for(canonical: str) -> ToolSpec:
    """Lo desconocido se trata como acción fuera de catálogo: nunca como lectura."""
    return catalog().get(canonical, ToolSpec(tipo="accion", nivel2=False))
