from __future__ import annotations

import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from fakeredis import FakeAsyncRedis

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import core.guiones  # noqa: E402,F401  (registra los guiones)
from core.agent import ScriptedRunner  # noqa: E402
from core.bus import EventBus  # noqa: E402
from core.control import ControlCore  # noqa: E402
from core.db import Database  # noqa: E402
from core.gateway import ToolGateway  # noqa: E402
from core.orchestrator import Orchestrator  # noqa: E402
from core.registry import AgentDefinition, load_registry  # noqa: E402
from core.schemas import BusEvent  # noqa: E402
from mcp_servers.context import McpContext  # noqa: E402
from mcp_servers.registry import build_all, prepare  # noqa: E402
from ops.store import OpsStore  # noqa: E402
from simulator.engine import Simulator  # noqa: E402
from simulator.port import LocalSimulator  # noqa: E402

FIXTURE_AGENTS = ROOT / "tests" / "fixtures" / "agents"
NOC_AGENTS = ROOT / "agents"


@dataclass
class Stack:
    sim: Simulator
    db: Database
    core: ControlCore
    agents: dict[str, AgentDefinition]
    orchestrator: Orchestrator
    bus: EventBus
    mcp: McpContext

    async def pump(self, max_rounds: int = 200) -> int:
        """Lleva al bus lo que deja el simulador y despacha hasta que no quede nada pendiente."""
        processed = 0
        for _ in range(max_rounds):
            for out in self.sim.drain():
                await self.bus.publish(BusEvent(topic=out.topic, payload=out.payload, incident=out.incident))
            n = await self.orchestrator.process_once(self.bus, block_ms=1)
            processed += n
            if n == 0 and not self.sim.outbox:
                return processed
        raise RuntimeError("el sistema no se estabiliza: posible bucle de eventos")

    async def tick(self, minutes: int) -> None:
        """Avanza el reloj simulado de 15 en 15 minutos, despachando lo que ocurre en cada tick."""
        for _ in range(minutes // 15):
            self.sim.advance(15)
            await self.pump()


async def make_stack(
    tmp_path: Path, seed: int = 42, blast_radius: int = 500, agent_dirs: tuple[Path, ...] = (FIXTURE_AGENTS,)
) -> Stack:
    sim = Simulator(seed)
    db = Database(f"sqlite+aiosqlite:///{(tmp_path / f'teleco-{seed}-{len(agent_dirs)}.db').as_posix()}")
    await db.init()
    bus = EventBus(FakeAsyncRedis(decode_responses=True))
    await bus.ensure_group()
    port = LocalSimulator(sim)
    mcp = McpContext(port, OpsStore(db), bus.publish)
    await prepare(mcp)
    core = ControlCore(db, ToolGateway(dict(build_all(mcp))), port, blast_radius=blast_radius)
    agents = load_registry(*agent_dirs)
    return Stack(sim, db, core, agents, Orchestrator(agents, core, ScriptedRunner()), bus, mcp)


@pytest.fixture
async def stack(tmp_path: Path) -> AsyncIterator[Stack]:
    s = await make_stack(tmp_path)
    yield s
    await s.db.close()


@pytest.fixture
async def noc(tmp_path: Path) -> AsyncIterator[Stack]:
    s = await make_stack(tmp_path, agent_dirs=(NOC_AGENTS,))
    yield s
    await s.db.close()
