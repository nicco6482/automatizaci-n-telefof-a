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
from core.config import get_settings
from core.control import ControlCore
from core.db import Database
from core.gateway import ToolGateway
from core.orchestrator import Orchestrator
from core.registry import load_registry
from simulator.port import HttpSimulator


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    settings = get_settings()
    db = Database(settings.database_url)
    await db.init()
    gateway = ToolGateway({"red": settings.mcp_red_url})
    core = ControlCore(db, gateway, HttpSimulator(settings.simulator_url), blast_radius=settings.blast_radius)
    agents = load_registry(settings.agents_dir, *settings.extra_agents_dirs)

    runner: Runner
    if settings.agent_mode == "claude":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise SystemExit("TELECO_AGENT_MODE=claude necesita ANTHROPIC_API_KEY (en .env, nunca en el código).")
        runner = ClaudeRunner(settings.model, {"red": settings.mcp_red_url}, {"red": await gateway.list_tools("red")})
    else:
        runner = ScriptedRunner()
    await Orchestrator(agents, core, runner).run_forever(EventBus.from_url(settings.redis_url))


if __name__ == "__main__":
    asyncio.run(main())
