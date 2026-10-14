"""Lo que comparten los servidores MCP: acceso al simulador, a los datos de operación y al bus."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from core.schemas import BusEvent
from ops.store import OpsStore
from simulator.port import SimulatorPort

Publish = Callable[[BusEvent], Awaitable[Any]]


@dataclass
class McpContext:
    sim: SimulatorPort
    store: OpsStore
    publish: Publish

    async def emit(self, topic: str, payload: dict[str, Any], trace: str | None) -> None:
        # `trace` es la traza interna del incidente para la auditoría; no se devuelve nunca a los agentes.
        await self.publish(BusEvent(topic=topic, payload=payload, incident=trace, source="mcp"))


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)
