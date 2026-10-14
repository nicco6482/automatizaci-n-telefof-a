"""Escenarios reproducibles: cada uno se ejecuta `runs` veces y debe superar su porcentaje de acierto.

`pytest tests/scenarios -q` ejecuta todos. Con TELECO_AGENT_MODE=claude se usaría el modelo real.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from core.audit import AuditEntry
from core.registry import load_registry
from core.schemas import BusEvent
from simulator.scenarios import Expectation, Scenario, load_scenarios
from tests.conftest import FIXTURE_AGENTS, ROOT, make_stack

SCENARIOS = load_scenarios(Path(__file__).parent)


def matches(row: AuditEntry, exp: Expectation) -> bool:
    return (
        row.agent == exp.agent
        and row.step == exp.step
        and (exp.tool is None or row.tool == exp.tool)
        and (exp.decision is None or exp.decision in row.decision)
    )


def check(rows: list[AuditEntry], scenario: Scenario) -> list[str]:
    failures = []
    for exp in scenario.expect:
        found = any(matches(r, exp) for r in rows)
        if found == exp.absent:
            failures.append(("aparece" if exp.absent else "falta") + f": {exp.model_dump(exclude_none=True)}")
    return failures


async def run_once(scenario: Scenario, run: int, tmp_path: Path) -> list[str]:
    stack = await make_stack(tmp_path, seed=scenario.seed + run)
    try:
        if scenario.settings.get("kill_switch"):
            await stack.core.set_kill_switch(True)
        if "blast_radius" in scenario.settings:
            await stack.core.set_blast_radius(int(scenario.settings["blast_radius"]))
        if scenario.inject.after_minutes:
            stack.sim.advance(scenario.inject.after_minutes)
            stack.sim.drain()
        fault = stack.sim.inject(
            scenario.inject.type,
            node=scenario.inject.node,
            zone=scenario.inject.zone,
            with_backup=scenario.inject.with_backup,
        )
        for out in stack.sim.drain():
            payload = dict(out.payload)
            if scenario.settings.get("probar_lista_blanca"):
                payload["_probar_lista_blanca"] = True
            await stack.orchestrator.dispatch(BusEvent(topic=out.topic, payload=payload, incident=out.incident))
        rows = await stack.core.audit.list(incident=fault.id, limit=1000)
        return check(rows, scenario)
    finally:
        await stack.db.close()


def test_cada_agente_tiene_al_menos_3_escenarios() -> None:
    agents = load_registry(ROOT / "agents", FIXTURE_AGENTS)
    per_agent = Counter(s.agent for s in SCENARIOS)
    missing = {aid: per_agent[aid] for aid in agents if per_agent[aid] < 3}
    assert not missing, f"agentes con menos de 3 escenarios: {missing}"


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s.id for s in SCENARIOS])
async def test_escenario(scenario: Scenario, tmp_path: Path) -> None:
    results = [await run_once(scenario, run, tmp_path) for run in range(scenario.runs)]
    passed = sum(1 for failures in results if not failures)
    rate = passed / scenario.runs
    first_failure = next((f for f in results if f), [])
    assert rate >= scenario.pass_rate, (
        f"{scenario.id}: {passed}/{scenario.runs} superados. Primer fallo: {first_failure}"
    )
