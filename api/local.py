"""Todo en un proceso, sin Docker: simulador, servidores MCP, núcleo, orquestador, API y panel.

    uv run python -m api.local          ->  panel en http://localhost:8000

Usa SQLite y un Redis en memoria. Los servidores MCP también se publican por HTTP en :8101, que es como los
usa el Claude Agent SDK en modo `claude`. Para PostgreSQL y Redis reales: docker compose up.
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
from core.bus import EventBus
from core.config import get_settings
from core.control import ControlCore
from core.db import Database
from core.gateway import ToolGateway
from core.orchestrator import Orchestrator
from core.registry import load_registry
from core.worker import build_runner
from mcp_servers.app import build_app, urls
from mcp_servers.context import McpContext
from mcp_servers.registry import SERVER_NAMES, build_all, prepare
from ops.store import OpsStore
from simulator.engine import Simulator
from simulator.port import LocalSimulator
from simulator.service import build_router, clock_loop

log = logging.getLogger("local")
MCP_PORT = 8101


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    for noisy in ("httpx", "mcp", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    settings = get_settings()
    sim = Simulator(settings.seed)
    bus = EventBus(FakeAsyncRedis(decode_responses=True))
    db = Database(settings.database_url)
    await db.init()
    port = LocalSimulator(sim)
    mcp = McpContext(port, OpsStore(db), bus.publish)
    await prepare(mcp)
    servers = build_all(mcp)
    mcp_urls = urls(f"http://127.0.0.1:{MCP_PORT}", SERVER_NAMES)
    # El núcleo usa los servidores en memoria; el Agent SDK, por HTTP. Son los mismos objetos.
    gateway = ToolGateway(dict(servers))
    core = ControlCore(db, gateway, port, blast_radius=settings.blast_radius)
    agents = load_registry(settings.agents_dir, *settings.extra_agents_dirs)
    runner = await build_runner(settings, gateway, mcp_urls)

    sim_http = httpx.AsyncClient(transport=httpx.ASGITransport(app=build_router(sim, bus)), base_url="http://simulador")
    app = create_app(Services(core, agents, bus, sim_http, settings.agent_mode, mcp))
    mcp_server = uvicorn.Server(
        uvicorn.Config(
            build_app(servers, ["localhost:*", "127.0.0.1:*"]), host="127.0.0.1", port=MCP_PORT, log_level="warning"
        )
    )
    tick = float(os.environ.get("TELECO_SIM_SECONDS_PER_TICK", "10"))
    tasks = [
        asyncio.create_task(mcp_server.serve()),
        asyncio.create_task(Orchestrator(agents, core, runner).run_forever(bus)),
        asyncio.create_task(clock_loop(sim, bus, tick)),
    ]
    log.info("Modo %s con %d agentes. Panel en http://localhost:8000", settings.agent_mode, len(agents))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8000, log_level="warning"))
    try:
        await server.serve()
    finally:
        mcp_server.should_exit = True
        for t in tasks[1:]:
            t.cancel()
        for t in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await t
        await sim_http.aclose()
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
