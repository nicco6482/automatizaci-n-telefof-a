"""Puerto de acceso al simulador: en proceso (pruebas) o por HTTP (docker compose).

Cuando el sistema se conecte a una red real, este puerto es lo que se sustituye por el adaptador de la
operadora (gestor de red, inventario, meteorología); los servidores MCP y los agentes no cambian.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any, Protocol

import httpx

from simulator.engine import ActionResult, Simulator, UnknownTarget
from simulator.models import Alarm, CentinelaStats, EnterpriseCustomer, Fault, Node, Power, Weather
from simulator.twin import TwinResult, probar_cambio

_ACTIONS: dict[str, Callable[[Simulator, dict[str, Any]], ActionResult]] = {
    "conmutar_respaldo": lambda sim, a: sim.switch_to_backup(str(a["node"])),
    "reiniciar_tarjeta": lambda sim, a: sim.restart_card(str(a["node"])),
}


class SimulatorPort(Protocol):
    async def now(self) -> datetime: ...
    async def list_alarms(self, limit: int = 20, node: str | None = None, zone: str | None = None) -> list[Alarm]: ...
    async def alarm(self, alarm_id: str) -> Alarm | None: ...
    async def alarm_trace(self, alarm_id: str) -> str | None: ...
    async def mark_discarded(self, alarm_id: str) -> None: ...
    async def node(self, node_id: str) -> Node: ...
    async def has_service(self, node_id: str) -> bool: ...
    async def enterprises(self, node: str | None = None, zone: str | None = None) -> list[EnterpriseCustomer]: ...
    async def weather(self, zone: str) -> Weather: ...
    async def power(self, zone: str) -> Power: ...
    async def fault(self, fault_id: str) -> Fault | None: ...
    async def act(self, action: str, args: dict[str, Any]) -> ActionResult: ...
    async def impact(self, action: str, args: dict[str, Any]) -> int: ...
    async def twin(self, action: str, args: dict[str, Any]) -> TwinResult: ...
    async def repair_node(self, node_id: str) -> list[str]: ...
    async def centinela_stats(self) -> CentinelaStats: ...


class LocalSimulator:
    def __init__(self, sim: Simulator) -> None:
        self.sim = sim

    async def now(self) -> datetime:
        return self.sim.state.now

    async def list_alarms(self, limit: int = 20, node: str | None = None, zone: str | None = None) -> list[Alarm]:
        alarms = [
            a for a in self.sim.state.alarms if (node is None or a.node == node) and (zone is None or a.zone == zone)
        ]
        return alarms[-limit:][::-1]

    async def alarm(self, alarm_id: str) -> Alarm | None:
        return self.sim.alarm(alarm_id)

    async def alarm_trace(self, alarm_id: str) -> str | None:
        alarm = self.sim.alarm(alarm_id)
        return alarm.incident if alarm else None

    async def mark_discarded(self, alarm_id: str) -> None:
        self.sim.mark_discarded(alarm_id)

    async def node(self, node_id: str) -> Node:
        if node_id not in self.sim.state.nodes:
            raise UnknownTarget(node_id)
        return self.sim.state.nodes[node_id]

    async def has_service(self, node_id: str) -> bool:
        if node_id not in self.sim.state.nodes:
            raise UnknownTarget(node_id)
        return self.sim.state.node_has_service(node_id)

    async def enterprises(self, node: str | None = None, zone: str | None = None) -> list[EnterpriseCustomer]:
        return [
            e
            for e in self.sim.state.enterprises.values()
            if (node is None or e.node == node) and (zone is None or e.zone == zone)
        ]

    async def weather(self, zone: str) -> Weather:
        return self.sim.weather(zone)

    async def power(self, zone: str) -> Power:
        return self.sim.power(zone)

    async def fault(self, fault_id: str) -> Fault | None:
        return self.sim.state.faults.get(fault_id)

    async def act(self, action: str, args: dict[str, Any]) -> ActionResult:
        fn = _ACTIONS.get(action)
        if fn is None:
            return ActionResult(ok=False, detail=f"El simulador no implementa «{action}».")
        return fn(self.sim, args)

    async def impact(self, action: str, args: dict[str, Any]) -> int:
        return self.sim.impact(action, args)

    async def twin(self, action: str, args: dict[str, Any]) -> TwinResult:
        return probar_cambio(self.sim.state, action, args)

    async def repair_node(self, node_id: str) -> list[str]:
        return self.sim.repair_node(node_id)

    async def centinela_stats(self) -> CentinelaStats:
        return self.sim.centinela_stats()


class HttpSimulator:
    def __init__(self, base_url: str, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.client = httpx.AsyncClient(base_url=base_url, timeout=10, transport=transport)

    async def _get(self, path: str, **params: Any) -> Any:
        r = await self.client.get(path, params={k: v for k, v in params.items() if v is not None})
        if r.status_code == 404:
            raise UnknownTarget(path)
        r.raise_for_status()
        return r.json()

    async def _post(self, path: str, body: Any = None) -> Any:
        r = await self.client.post(path, json=body)
        if r.status_code == 404:
            raise UnknownTarget(path)
        r.raise_for_status()
        return r.json()

    async def now(self) -> datetime:
        return datetime.fromisoformat((await self._get("/summary"))["now"])

    async def list_alarms(self, limit: int = 20, node: str | None = None, zone: str | None = None) -> list[Alarm]:
        return [Alarm.model_validate(a) for a in await self._get("/alarms", limit=limit, node=node, zone=zone)]

    async def alarm(self, alarm_id: str) -> Alarm | None:
        try:
            return Alarm.model_validate(await self._get(f"/alarms/{alarm_id}"))
        except UnknownTarget:
            return None

    async def alarm_trace(self, alarm_id: str) -> str | None:
        try:
            trace = (await self._get(f"/alarms/{alarm_id}/trace"))["incident"]
            return str(trace) if trace else None
        except UnknownTarget:
            return None

    async def mark_discarded(self, alarm_id: str) -> None:
        await self._post(f"/alarms/{alarm_id}/discard")

    async def node(self, node_id: str) -> Node:
        return Node.model_validate(await self._get(f"/nodes/{node_id}"))

    async def has_service(self, node_id: str) -> bool:
        return bool((await self._get(f"/nodes/{node_id}/service"))["service"])

    async def enterprises(self, node: str | None = None, zone: str | None = None) -> list[EnterpriseCustomer]:
        return [EnterpriseCustomer.model_validate(e) for e in await self._get("/enterprises", node=node, zone=zone)]

    async def weather(self, zone: str) -> Weather:
        return Weather.model_validate(await self._get(f"/zones/{zone}/weather"))

    async def power(self, zone: str) -> Power:
        return Power.model_validate(await self._get(f"/zones/{zone}/power"))

    async def fault(self, fault_id: str) -> Fault | None:
        try:
            return Fault.model_validate(await self._get(f"/faults/{fault_id}"))
        except UnknownTarget:
            return None

    async def act(self, action: str, args: dict[str, Any]) -> ActionResult:
        return ActionResult.model_validate(await self._post(f"/actions/{action}", args))

    async def impact(self, action: str, args: dict[str, Any]) -> int:
        return int((await self._post("/impact", {"action": action, "args": args}))["clients"])

    async def twin(self, action: str, args: dict[str, Any]) -> TwinResult:
        return TwinResult.model_validate(await self._post("/twin", {"action": action, "args": args}))

    async def repair_node(self, node_id: str) -> list[str]:
        return [str(f) for f in (await self._post(f"/nodes/{node_id}/repair"))["repaired"]]

    async def centinela_stats(self) -> CentinelaStats:
        return CentinelaStats.model_validate(await self._get("/truth/centinela"))
