from __future__ import annotations

import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import core.guiones  # noqa: E402,F401  (registra los guiones)
from core.agent import ScriptedRunner  # noqa: E402
from core.control import ControlCore  # noqa: E402
from core.db import Database  # noqa: E402
from core.gateway import ToolGateway  # noqa: E402
from core.orchestrator import Orchestrator  # noqa: E402
from core.registry import AgentDefinition, load_registry  # noqa: E402
from core.schemas import BusEvent  # noqa: E402
from mcp_servers.red.server import build_red_server  # noqa: E402
from simulator.engine import Simulator  # noqa: E402
from simulator.port import LocalSimulator  # noqa: E402

FIXTURE_AGENTS = ROOT / "tests" / "fixtures" / "agents"


@dataclass
class Stack:
    sim: Simulator
    db: Database
    core: ControlCore
    agents: dict[str, AgentDefinition]
    orchestrator: Orchestrator

    async def pump(self) -> int:
        """Lleva al orquestador lo que el simulador ha dejado en su bandeja de salida."""
        n = 0
        for out in self.sim.drain():
            await self.orchestrator.dispatch(BusEvent(topic=out.topic, payload=out.payload, incident=out.incident))
            n += 1
        return n


async def make_stack(tmp_path: Path, seed: int = 42, blast_radius: int = 500) -> Stack:
    sim = Simulator(seed)
    db = Database(f"sqlite+aiosqlite:///{(tmp_path / f'teleco-{seed}.db').as_posix()}")
    await db.init()
    gateway = ToolGateway({"red": build_red_server(LocalSimulator(sim))})
    core = ControlCore(db, gateway, LocalSimulator(sim), blast_radius=blast_radius)
    agents = load_registry(ROOT / "agents", FIXTURE_AGENTS)
    return Stack(sim, db, core, agents, Orchestrator(agents, core, ScriptedRunner()))


@pytest.fixture
async def stack(tmp_path: Path) -> AsyncIterator[Stack]:
    s = await make_stack(tmp_path)
    yield s
    await s.db.close()
