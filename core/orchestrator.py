"""Orquestador: lee el bus y activa a los agentes suscritos a cada evento."""

from __future__ import annotations

import asyncio
import logging

from core.agent import BaseAgent, Runner
from core.bus import EventBus
from core.control import ControlCore
from core.registry import AgentDefinition, subscribers
from core.schemas import AgentOutput, BusEvent

log = logging.getLogger("orquestador")


class Orchestrator:
    def __init__(self, agents: dict[str, AgentDefinition], core: ControlCore, runner: Runner) -> None:
        self.agents = {aid: BaseAgent(d, core, runner) for aid, d in agents.items()}
        self.core = core

    async def dispatch(self, event: BusEvent) -> list[AgentOutput]:
        definitions = {aid: agent.definition for aid, agent in self.agents.items()}
        targets = [self.agents[d.config.id] for d in subscribers(definitions, event.topic)]
        outputs = []
        for agent in targets:
            output = await agent.handle(event)
            if output is not None:
                outputs.append(output)
        return outputs

    async def process_once(self, bus: EventBus, consumer: str = "orq-1", block_ms: int = 1000) -> int:
        events = await bus.read(consumer, block_ms=block_ms)
        for event in events:
            try:
                await self.dispatch(event)
            except Exception:  # un agente que falla no tumba al orquestador
                log.exception("fallo al despachar %s", event.topic)
                await self.core.audit.write(
                    agent="ORQUESTADOR",
                    step="error",
                    incident=event.incident,
                    decision="fallo",
                    result=f"Fallo al despachar {event.topic}",
                )
            finally:
                await bus.ack(event)
        return len(events)

    async def run_forever(self, bus: EventBus, consumer: str = "orq-1") -> None:
        await bus.ensure_group()
        log.info("Orquestador escuchando %s con %d agentes", "teleco:events", len(self.agents))
        while True:
            await self.process_once(bus, consumer)
            await asyncio.sleep(0)
