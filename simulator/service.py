"""Servicio HTTP del simulador. Avanza el reloj y publica en el bus lo que pasa en la red."""

from __future__ import annotations

import asyncio
import contextlib
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from core.bus import EventBus
from core.schemas import BusEvent
from simulator.engine import ActionResult, Simulator, UnknownTarget
from simulator.models import Alarm, CentinelaStats, EnterpriseCustomer, Fault, FaultType, Node, Power, Weather
from simulator.port import LocalSimulator
from simulator.twin import TwinResult


class InjectRequest(BaseModel):
    type: FaultType
    node: str | None = None
    zone: str | None = None
    with_backup: bool | None = None


class EventRequest(BaseModel):
    zone: str
    name: str
    hours_ahead: int = 3
    duration: int = 5
    attendance: int = 45000


class ChangeRequest(BaseModel):
    action: str
    args: dict[str, Any] = {}


class Summary(BaseModel):
    now: str
    seed: int
    nodes_without_service: list[str]
    active_faults: list[Fault]
    traffic_gbps: float
    alarms_last_tick: int


async def flush(sim: Simulator, bus: EventBus | None) -> int:
    events = sim.drain()
    if bus is not None:
        for out in events:
            await bus.publish(BusEvent(topic=out.topic, payload=out.payload, incident=out.incident, source="simulador"))
    return len(events)


async def clock_loop(sim: Simulator, bus: EventBus | None, seconds_per_tick: float) -> None:
    while True:
        await asyncio.sleep(seconds_per_tick)
        sim.advance(15)
        await flush(sim, bus)


def build_router(sim: Simulator, bus: EventBus | None) -> FastAPI:
    app = FastAPI(title="Simulador teleco-agents")
    port = LocalSimulator(sim)

    @app.get("/summary")
    async def summary() -> Summary:
        st = sim.state
        last = st.kpis[-1] if st.kpis else None
        return Summary(
            now=st.now.isoformat(),
            seed=st.seed,
            nodes_without_service=[n for n in st.nodes if not st.node_has_service(n)],
            active_faults=[f for f in st.faults.values() if f.active and not f.mitigated],
            traffic_gbps=last.traffic_gbps if last else 0.0,
            alarms_last_tick=last.alarms if last else 0,
        )

    @app.get("/alarms")
    async def alarms(limit: int = 20, node: str | None = None, zone: str | None = None) -> list[Alarm]:
        return await port.list_alarms(limit, node, zone)

    @app.get("/alarms/{alarm_id}")
    async def alarm(alarm_id: str) -> Alarm:
        found = await port.alarm(alarm_id)
        if found is None:
            raise HTTPException(404, f"alarma desconocida: {alarm_id}")
        return found

    @app.get("/alarms/{alarm_id}/trace")
    async def alarm_trace(alarm_id: str) -> dict[str, str | None]:
        return {"incident": await port.alarm_trace(alarm_id)}

    @app.post("/alarms/{alarm_id}/discard")
    async def discard(alarm_id: str) -> dict[str, bool]:
        await port.mark_discarded(alarm_id)
        return {"ok": True}

    @app.get("/nodes/{node_id}")
    async def node(node_id: str) -> Node:
        try:
            return await port.node(node_id)
        except UnknownTarget as exc:
            raise HTTPException(404, f"nodo desconocido: {exc}") from exc

    @app.get("/nodes/{node_id}/service")
    async def service(node_id: str) -> dict[str, bool]:
        try:
            return {"service": await port.has_service(node_id)}
        except UnknownTarget as exc:
            raise HTTPException(404, f"nodo desconocido: {exc}") from exc

    @app.post("/nodes/{node_id}/repair")
    async def repair_node(node_id: str) -> dict[str, list[str]]:
        try:
            repaired = await port.repair_node(node_id)
        except UnknownTarget as exc:
            raise HTTPException(404, f"nodo desconocido: {exc}") from exc
        await flush(sim, bus)
        return {"repaired": repaired}

    @app.get("/enterprises")
    async def enterprises(node: str | None = None, zone: str | None = None) -> list[EnterpriseCustomer]:
        return await port.enterprises(node, zone)

    @app.get("/zones/{zone}/weather")
    async def weather(zone: str) -> Weather:
        return await port.weather(zone)

    @app.get("/zones/{zone}/power")
    async def power(zone: str) -> Power:
        return await port.power(zone)

    @app.get("/faults/{fault_id}")
    async def fault(fault_id: str) -> Fault:
        found = await port.fault(fault_id)
        if found is None:
            raise HTTPException(404, f"no existe {fault_id}")
        return found

    @app.post("/view/{name}")
    async def view(name: str, args: dict[str, Any]) -> Any:
        try:
            return await port.view(name, args)
        except UnknownTarget as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/events/schedule")
    async def schedule(req: EventRequest) -> Any:
        try:
            event = await port.schedule_event(req.zone, req.name, req.hours_ahead, req.duration, req.attendance)
        except UnknownTarget as exc:
            raise HTTPException(404, f"zona desconocida: {exc}") from exc
        await flush(sim, bus)
        return event

    @app.get("/truth/centinela")
    async def truth_centinela() -> CentinelaStats:
        return await port.centinela_stats()

    @app.post("/actions/{action}")
    async def act(action: str, args: dict[str, Any]) -> ActionResult:
        try:
            result = await port.act(action, args)
        except UnknownTarget as exc:
            raise HTTPException(404, f"destino desconocido: {exc}") from exc
        await flush(sim, bus)
        return result

    @app.post("/impact")
    async def impact(req: ChangeRequest) -> dict[str, int]:
        try:
            return {"clients": await port.impact(req.action, req.args)}
        except UnknownTarget as exc:
            raise HTTPException(404, f"destino desconocido: {exc}") from exc

    @app.post("/twin")
    async def twin(req: ChangeRequest) -> TwinResult:
        return await port.twin(req.action, req.args)

    @app.post("/inject")
    async def inject(req: InjectRequest) -> Fault:
        try:
            fault = sim.inject(req.type, node=req.node, zone=req.zone, with_backup=req.with_backup)
        except UnknownTarget as exc:
            raise HTTPException(404, f"destino desconocido: {exc}") from exc
        await flush(sim, bus)
        return fault

    @app.post("/advance")
    async def advance(minutes: int = 15) -> dict[str, int]:
        sim.advance(minutes)
        return {"events": await flush(sim, bus)}

    @app.post("/repair/{fault_id}")
    async def repair(fault_id: str) -> Fault:
        if fault_id not in sim.state.faults:
            raise HTTPException(404, f"no existe {fault_id}")
        sim.repair(fault_id)
        return sim.state.faults[fault_id]

    return app


def create_app() -> FastAPI:
    sim = Simulator(int(os.environ.get("TELECO_SEED", "42")))
    bus = EventBus.from_url(os.environ.get("TELECO_REDIS_URL", "redis://localhost:6379/0"))
    tick = float(os.environ.get("TELECO_SIM_SECONDS_PER_TICK", "10"))

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        task = asyncio.create_task(clock_loop(sim, bus, tick))
        yield
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    app = build_router(sim, bus)
    app.router.lifespan_context = lifespan
    return app
