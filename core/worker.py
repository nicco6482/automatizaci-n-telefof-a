"""Proceso del orquestador en docker compose: lee el bus y ejecuta a los agentes.

python -m core.worker
"""

from __future__ import annotations

import asyncio
import logging
import os

import core.guiones  # noqa: F401  (registra los guiones del modo sin clave)
from core.agent import ClaudeRunner, Runner, ScriptedRunner
from core.bus import EventBus
from core.config import Settings, get_settings
from core.control import ControlCore
from core.db import Database
from core.gateway import ToolGateway
from core.orchestrator import Orchestrator
from core.registry import load_registry
from mcp_servers.app import urls
from mcp_servers.registry import SERVER_NAMES
from simulator.port import HttpSimulator


async def build_runner(settings: Settings, gateway: ToolGateway, mcp_urls: dict[str, str]) -> Runner:
    if settings.agent_mode != "claude":
        return ScriptedRunner()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("TELECO_AGENT_MODE=claude necesita ANTHROPIC_API_KEY (en .env, nunca en el código).")
    tools = {name: await gateway.list_tools(name) for name in mcp_urls}
    return ClaudeRunner(settings.model, mcp_urls, tools)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    settings = get_settings()
    db = Database(settings.database_url)
    await db.init()
    mcp_urls = urls(settings.mcp_base_url, SERVER_NAMES)
    gateway = ToolGateway(dict(mcp_urls))
    core = ControlCore(db, gateway, HttpSimulator(settings.simulator_url), blast_radius=settings.blast_radius)
    agents = load_registry(settings.agents_dir, *settings.extra_agents_dirs)
    runner = await build_runner(settings, gateway, mcp_urls)
    await Orchestrator(agents, core, runner).run_forever(EventBus.from_url(settings.redis_url))


if __name__ == "__main__":
    asyncio.run(main())
