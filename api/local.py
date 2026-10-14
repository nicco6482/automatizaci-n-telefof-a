"""Todo en un proceso, sin Docker: simulador, MCP, núcleo, orquestador, API y panel.

    uv run python -m api.local          ->  http://localhost:8000

Usa SQLite y un Redis en memoria. Para el despliegue completo con PostgreSQL y Redis: docker compose up.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os

import httpx
import uvicorn
from fakeredis import FakeAsyncRedis

import core.guiones  # noqa: F401  (registra los guiones del modo sin clave)
from api.main import Services, create_app
from core.agent import ClaudeRunner, Runner, ScriptedRunner
from core.bus import EventBus
from core.config import ROOT, get_settings
from core.control import ControlCore
from core.db import Database
from core.gateway import ToolGateway
from core.orchestrator import Orchestrator
from core.registry import load_registry
from mcp_servers.red.server import build_red_server
from simulator.engine import Simulator
from simulator.port import LocalSimulator
from simulator.service import build_router, clock_loop

log = logging.getLogger("local")


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    settings = get_settings()
    sim = Simulator(settings.seed)
    bus = EventBus(FakeAsyncRedis(decode_responses=True))
    db = Database(settings.database_url)
    await db.init()
    port = LocalSimulator(sim)
    gateway = ToolGateway({"red": build_red_server(port)})
    core = ControlCore(db, gateway, port, blast_radius=settings.blast_radius)
    agents = load_registry(settings.agents_dir, ROOT / "tests" / "fixtures" / "agents", *settings.extra_agents_dirs)

    runner: Runner
    if settings.agent_mode == "claude":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise SystemExit("TELECO_AGENT_MODE=claude necesita ANTHROPIC_API_KEY en el entorno.")
        # El Agent SDK lanza su propio proceso y necesita el MCP por HTTP: arranca `python -m mcp_servers.red.server`.
        runner = ClaudeRunner(settings.model, {"red": settings.mcp_red_url}, {"red": await gateway.list_tools("red")})
    else:
        runner = ScriptedRunner()

    sim_app = build_router(sim, bus)
    sim_http = httpx.AsyncClient(transport=httpx.ASGITransport(app=sim_app), base_url="http://simulador")
    app = create_app(Services(core, agents, bus, sim_http, settings.agent_mode))

    orchestrator = Orchestrator(agents, core, runner)
    tick = float(os.environ.get("TELECO_SIM_SECONDS_PER_TICK", "10"))
    tasks = [asyncio.create_task(orchestrator.run_forever(bus)), asyncio.create_task(clock_loop(sim, bus, tick))]
    log.info("Modo %s con %d agentes. Panel en http://localhost:8000", settings.agent_mode, len(agents))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8000, log_level="warning"))
    try:
        await server.serve()
    finally:
        for t in tasks:
            t.cancel()
        for t in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await t
        await sim_http.aclose()
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
