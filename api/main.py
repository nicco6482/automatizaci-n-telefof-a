"""API del panel: agentes, auditoría, aprobaciones, interruptor general, eventos y simulador."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core.audit import AuditEntry
from core.bus import EventBus
from core.config import ROOT, get_settings
from core.control import HUMAN, Approval, ApprovalError, ControlCore
from core.db import Database
from core.gateway import ToolGateway
from core.metrics import Metrics, all_rows, compute
from core.registry import AgentDefinition, load_registry
from core.schemas import BusEvent
from mcp_servers.app import urls
from mcp_servers.context import McpContext
from mcp_servers.registry import SERVER_NAMES
from ops.human import after_rejection, close_page
from ops.store import OpsStore, Page, Ticket
from simulator.port import HttpSimulator

DASHBOARD_DIST = ROOT / "dashboard" / "dist"


@dataclass
class Services:
    core: ControlCore
    agents: dict[str, AgentDefinition]
    bus: EventBus
    sim_http: httpx.AsyncClient
    mode: str
    mcp: McpContext | None = None


class AgentView(BaseModel):
    id: str
    slug: str
    titulo: str
    area: str
    autonomia: int
    nivel_efectivo: int
    persona: bool
    disparadores: list[str]
    herramientas: list[str]
    escalado: str
    limites: dict[str, int]
    prompt: str
    paused: bool
    runs: int
    last_run_at: datetime | None
    last_output: dict[str, Any] | None


class ControlView(BaseModel):
    kill_switch: bool
    blast_radius: int
    tokens_today: int
    cost_today_usd: float
    pending_approvals: int
    agent_mode: str


class Decision(BaseModel):
    comment: str = ""


class KillSwitch(BaseModel):
    on: bool


class BlastRadius(BaseModel):
    value: int


class PageClose(BaseModel):
    resolution: str = "Reparado en campo."


class ChangeRequest(BaseModel):
    title: str
    node: str | None = None
    zone: str
    starts_at: datetime
    ends_at: datetime


class MetricsView(Metrics):
    false_alarms_total: int
    false_alarms_filtered_pct: float
    real_alarms_discarded: int


def create_app(services: Services | None = None) -> FastAPI:
    holder: dict[str, Services] = {}

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if services is not None:
            holder["s"] = services
            yield
            return
        settings = get_settings()
        db = Database(settings.database_url)
        await db.init()
        sim_http = httpx.AsyncClient(base_url=settings.simulator_url, timeout=10)
        port = HttpSimulator(settings.simulator_url)
        bus = EventBus.from_url(settings.redis_url)
        core = ControlCore(
            db, ToolGateway(dict(urls(settings.mcp_base_url, SERVER_NAMES))), port, blast_radius=settings.blast_radius
        )
        agents = load_registry(settings.agents_dir, *settings.extra_agents_dirs)
        mcp = McpContext(port, OpsStore(db), bus.publish)
        holder["s"] = Services(core, agents, bus, sim_http, settings.agent_mode, mcp)
        yield
        await sim_http.aclose()
        await db.close()

    app = FastAPI(title="teleco-agents", lifespan=lifespan)

    def s() -> Services:
        return holder["s"]

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "mode": s().mode}

    @app.get("/api/agents")
    async def agents() -> list[AgentView]:
        states = await s().core.agent_states()
        kill = await s().core.kill_switch()
        views = []
        for d in s().agents.values():
            c, st = d.config, states.get(d.config.slug)
            views.append(
                AgentView(
                    id=c.id,
                    slug=c.slug,
                    titulo=c.titulo,
                    area=c.area,
                    autonomia=c.autonomia,
                    nivel_efectivo=0 if kill else c.autonomia,
                    persona=c.persona,
                    disparadores=c.disparadores,
                    herramientas=c.herramientas,
                    escalado=c.escalado,
                    limites=c.limites.model_dump(),
                    prompt=d.prompt,
                    paused=bool(st and st.paused),
                    runs=st.runs if st else 0,
                    last_run_at=st.last_run_at if st else None,
                    last_output=st.last_output if st else None,
                )
            )
        return views

    @app.post("/api/agents/{slug}/resume")
    async def resume(slug: str) -> dict[str, bool]:
        await s().core.set_paused(slug, False, "Reanudado por una persona.", by=HUMAN)
        return {"paused": False}

    @app.get("/api/audit")
    async def audit(
        agent: str | None = None, incident: str | None = None, step: str | None = None, limit: int = 200
    ) -> list[AuditEntry]:
        return await s().core.audit.list(agent=agent, incident=incident, step=step, limit=min(limit, 1000))

    @app.get("/api/approvals")
    async def approvals(status: str | None = None) -> list[Approval]:
        return await s().core.approvals(status=status)

    async def _decide(approval_id: str, approve: bool, body: Decision) -> Approval:
        try:
            return await s().core.decide(approval_id, approve, by=HUMAN, comment=body.comment)
        except ApprovalError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/approvals/{approval_id}/approve")
    async def approve(approval_id: str, body: Decision) -> Approval:
        return await _decide(approval_id, True, body)

    @app.post("/api/approvals/{approval_id}/reject")
    async def reject(approval_id: str, body: Decision) -> Approval:
        done = await _decide(approval_id, False, body)
        if s().mcp is not None:
            await after_rejection(mcp(), done)
        return done

    def mcp() -> McpContext:
        ctx = s().mcp
        if ctx is None:
            raise HTTPException(503, "datos de operación no disponibles")
        return ctx

    @app.get("/api/tickets")
    async def tickets(status: str | None = None) -> list[Ticket]:
        return await mcp().store.tickets(status=status)

    @app.get("/api/pages")
    async def pages(status: str | None = None) -> list[Page]:
        return await mcp().store.pages(status=status)

    @app.post("/api/pages/{page_id}/close")
    async def close(page_id: str, body: PageClose) -> Page:
        try:
            return await close_page(mcp(), s().core, page_id, by=HUMAN, resolution=body.resolution)
        except LookupError as exc:
            raise HTTPException(404, f"no existe {page_id}") from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/changes/request")
    async def request_change(body: ChangeRequest) -> dict[str, str]:
        if body.ends_at <= body.starts_at:
            raise HTTPException(422, "la ventana debe terminar después de empezar")
        n = len(await s().core.audit.list(agent="OPERADOR", step="evento", limit=1000)) + 1
        trace = f"PET-{n:04d}"
        await s().core.audit.write(
            agent="OPERADOR",
            step="evento",
            incident=trace,
            input=body.model_dump(mode="json"),
            decision="cambio solicitado",
            approved_by=HUMAN,
            result=body.title,
        )
        await s().bus.publish(
            BusEvent(topic="change.requested", payload=body.model_dump(mode="json"), incident=trace, source="operador")
        )
        return {"trace": trace}

    @app.get("/api/metrics")
    async def metrics() -> MetricsView:
        base = compute(await all_rows(s().core.db), s().agents)
        truth = await s().core.simulator.centinela_stats()
        return MetricsView(
            **base.model_dump(),
            false_alarms_total=truth.false_total,
            false_alarms_filtered_pct=round(truth.false_filtered_pct, 1),
            real_alarms_discarded=truth.real_discarded,
        )

    @app.get("/api/control")
    async def control() -> ControlView:
        tokens, cost = await s().core.audit.cost_today()
        return ControlView(
            kill_switch=await s().core.kill_switch(),
            blast_radius=await s().core.blast_radius(),
            tokens_today=tokens,
            cost_today_usd=round(cost, 4),
            pending_approvals=len(await s().core.approvals(status="pendiente")),
            agent_mode=s().mode,
        )

    @app.post("/api/control/kill-switch")
    async def kill_switch(body: KillSwitch) -> ControlView:
        await s().core.set_kill_switch(body.on)
        return await control()

    @app.post("/api/control/blast-radius")
    async def blast_radius(body: BlastRadius) -> ControlView:
        if body.value < 0:
            raise HTTPException(422, "el umbral no puede ser negativo")
        await s().core.set_blast_radius(body.value)
        return await control()

    @app.get("/api/events")
    async def events(count: int = 100) -> list[BusEvent]:
        return await s().bus.recent(min(count, 500))

    @app.get("/api/sim/summary")
    async def sim_summary() -> Any:
        r = await s().sim_http.get("/summary")
        return r.json()

    @app.post("/api/sim/inject")
    async def sim_inject(body: dict[str, Any]) -> Any:
        r = await s().sim_http.post("/inject", json=body)
        if r.status_code >= 400:
            raise HTTPException(r.status_code, r.json().get("detail", "error del simulador"))
        await s().core.audit.write(
            agent="OPERADOR",
            step="evento",
            incident=r.json()["id"],
            input=body,
            decision="avería inyectada",
            approved_by=HUMAN,
            result=r.json()["detail"],
        )
        return r.json()

    if DASHBOARD_DIST.is_dir():
        app.mount("/assets", StaticFiles(directory=DASHBOARD_DIST / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str) -> FileResponse:
            return FileResponse(Path(DASHBOARD_DIST / "index.html"))

    return app
