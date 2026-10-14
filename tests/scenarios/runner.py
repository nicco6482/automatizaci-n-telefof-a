"""Ejecuta un escenario sobre el sistema completo (simulador, MCP, bus, orquestador, núcleo) y lo comprueba."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from core.audit import AuditEntry
from core.control import HUMAN
from core.metrics import all_rows, compute
from core.schemas import BusEvent
from ops.business import publish_business
from ops.human import after_rejection, close_page, close_task
from simulator.scenarios import Expectation, Scenario
from tests.conftest import FIXTURE_AGENTS, NOC_AGENTS, make_stack


class RunOutcome(BaseModel):
    failures: list[str]
    executed_outside_whitelist: int
    changes_without_twin_and_approval: int = 0


def matches(row: AuditEntry, exp: Expectation) -> bool:
    return (
        row.agent == exp.agent
        and row.step == exp.step
        and (exp.tool is None or row.tool == exp.tool)
        and (exp.decision is None or exp.decision in row.decision)
        and (exp.input_contains is None or exp.input_contains in str(row.input))
        and (exp.result_contains is None or exp.result_contains in row.result)
    )


def check(rows: list[AuditEntry], scenario: Scenario) -> list[str]:
    failures = []
    for exp in scenario.expect:
        found = any(matches(r, exp) for r in rows)
        if found == exp.absent:
            failures.append(("aparece" if exp.absent else "falta") + f": {exp.model_dump(exclude_none=True)}")
    return failures


async def run_once(scenario: Scenario, run: int, tmp_path: Path) -> RunOutcome:
    dirs = (FIXTURE_AGENTS,) if scenario.agent == "00" else (NOC_AGENTS,)
    workdir = tmp_path / f"{scenario.id}-{run}"
    workdir.mkdir(parents=True, exist_ok=True)
    stack = await make_stack(workdir, seed=scenario.seed + run, agent_dirs=dirs)
    try:
        s = scenario.settings
        if s.get("kill_switch"):
            await stack.core.set_kill_switch(True)
        if "blast_radius" in s:
            await stack.core.set_blast_radius(int(s["blast_radius"]))
        trace = scenario.id
        if scenario.inject is not None:
            if scenario.inject.after_minutes:
                await stack.tick(scenario.inject.after_minutes)
            fault = stack.sim.inject(
                scenario.inject.type,
                node=scenario.inject.node,
                zone=scenario.inject.zone,
                with_backup=scenario.inject.with_backup,
            )
            trace = fault.id
            for out in stack.sim.drain():
                payload = dict(out.payload)
                if s.get("probar_lista_blanca"):
                    payload["_probar_lista_blanca"] = True
                await stack.bus.publish(BusEvent(topic=out.topic, payload=payload, incident=out.incident))
        for ev in scenario.events:
            if ev.generate:
                generated = await publish_business(stack.mcp, ev.topic, ev.payload)
                if scenario.inject is None and trace == scenario.id:
                    trace = generated
            else:
                await stack.bus.publish(
                    BusEvent(topic=ev.topic, payload=ev.payload, incident=trace, source="escenario")
                )
        await stack.pump()
        await stack.tick(scenario.advance_minutes)
        for step in scenario.human:
            if step in ("aprobar_todo", "rechazar_todo"):
                for ap in await stack.core.approvals(status="pendiente"):
                    done = await stack.core.decide(ap.id, step == "aprobar_todo", by=HUMAN, comment="escenario")
                    if step == "rechazar_todo":
                        await after_rejection(stack.mcp, done)
            elif step == "cerrar_avisos":
                for page in await stack.mcp.store.pages(status="abierto"):
                    await close_page(stack.mcp, stack.core, page.id, by=HUMAN, resolution="Reparado en campo.")
            elif step == "cerrar_tareas":
                for task in await stack.mcp.store.tasks(status="abierta"):
                    await close_task(stack.mcp, stack.core, task.id, by=HUMAN, resolution="Revisado.")
            await stack.pump()
        rows = await stack.core.audit.list(incident=None if scenario.trace == "todo" else trace, limit=5000)
        outside = sum(
            1
            for r in await stack.core.audit.list(limit=5000)
            if r.decision.startswith("ejecutada")
            and r.agent in {a.config.slug for a in stack.agents.values()}
            and not _whitelisted(stack, r)
        )
        metrics = compute(await all_rows(stack.db), stack.agents)
        return RunOutcome(
            failures=check(rows, scenario),
            executed_outside_whitelist=outside,
            changes_without_twin_and_approval=metrics.changes_without_twin_and_approval,
        )
    finally:
        await stack.db.close()


def _whitelisted(stack: object, row: AuditEntry) -> bool:
    from core.tools import in_whitelist

    agents = {a.config.slug: a.config for a in stack.agents.values()}  # type: ignore[attr-defined]
    return row.tool is not None and in_whitelist(row.tool, agents[row.agent].herramientas)


_CACHE: dict[tuple[str, int], RunOutcome] = {}


async def cached_run(scenario: Scenario, run: int, tmp_path: Path) -> RunOutcome:
    """Cada (escenario, ejecución) corre una vez por sesión; las puertas de fase reutilizan el resultado."""
    key = (scenario.id, run)
    if key not in _CACHE:
        _CACHE[key] = await run_once(scenario, run, tmp_path)
    return _CACHE[key]
