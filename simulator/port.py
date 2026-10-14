"""Puerto de acceso al simulador: en proceso (pruebas) o por HTTP (docker compose).

Cuando el sistema se conecte a una red real, este puerto es lo que se sustituye por el adaptador de la
operadora (gestor de red, inventario); los servidores MCP y los agentes no cambian.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

import httpx

from simulator.engine import ActionResult, Simulator, UnknownTarget
from simulator.models import Alarm, Node
from simulator.twin import TwinResult, probar_cambio

_ACTIONS: dict[str, Callable[[Simulator, dict[str, Any]], ActionResult]] = {
    "conmutar_respaldo": lambda sim, a: sim.switch_to_backup(str(a["node"])),
    "reiniciar_tarjeta": lambda sim, a: sim.restart_card(str(a["node"])),
}


class SimulatorPort(Protocol):
    async def list_alarms(self, limit: int = 20, node: str | None = None) -> list[Alarm]: ...
    async def node(self, node_id: str) -> Node: ...
    async def act(self, action: str, args: dict[str, Any]) -> ActionResult: ...
    async def impact(self, action: str, args: dict[str, Any]) -> int: ...
    async def twin(self, action: str, args: dict[str, Any]) -> TwinResult: ...


class LocalSimulator:
    def __init__(self, sim: Simulator) -> None:
        self.sim = sim

    async def list_alarms(self, limit: int = 20, node: str | None = None) -> list[Alarm]:
        alarms = [a for a in self.sim.state.alarms if node is None or a.node == node]
        return alarms[-limit:][::-1]

    async def node(self, node_id: str) -> Node:
        if node_id not in self.sim.state.nodes:
            raise UnknownTarget(node_id)
        return self.sim.state.nodes[node_id]

    async def act(self, action: str, args: dict[str, Any]) -> ActionResult:
        fn = _ACTIONS.get(action)
        if fn is None:
            return ActionResult(ok=False, detail=f"El simulador no implementa «{action}».")
        return fn(self.sim, args)

    async def impact(self, action: str, args: dict[str, Any]) -> int:
        return self.sim.impact(action, args)

    async def twin(self, action: str, args: dict[str, Any]) -> TwinResult:
        return probar_cambio(self.sim.state, action, args)


class HttpSimulator:
    def __init__(self, base_url: str, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.client = httpx.AsyncClient(base_url=base_url, timeout=10, transport=transport)

    async def list_alarms(self, limit: int = 20, node: str | None = None) -> list[Alarm]:
        params: dict[str, Any] = {"limit": limit}
        if node:
            params["node"] = node
        r = await self.client.get("/alarms", params=params)
        r.raise_for_status()
        return [Alarm.model_validate(a) for a in r.json()]

    async def node(self, node_id: str) -> Node:
        r = await self.client.get(f"/nodes/{node_id}")
        if r.status_code == 404:
            raise UnknownTarget(node_id)
        r.raise_for_status()
        return Node.model_validate(r.json())

    async def act(self, action: str, args: dict[str, Any]) -> ActionResult:
        r = await self.client.post(f"/actions/{action}", json=args)
        r.raise_for_status()
        return ActionResult.model_validate(r.json())

    async def impact(self, action: str, args: dict[str, Any]) -> int:
        r = await self.client.post("/impact", json={"action": action, "args": args})
        r.raise_for_status()
        return int(r.json()["clients"])

    async def twin(self, action: str, args: dict[str, Any]) -> TwinResult:
        r = await self.client.post("/twin", json={"action": action, "args": args})
        r.raise_for_status()
        return TwinResult.model_validate(r.json())
