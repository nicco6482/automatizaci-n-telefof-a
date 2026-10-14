"""Escenarios reproducibles: cada uno se ejecuta `runs` veces y debe superar su porcentaje de acierto.

`pytest tests/scenarios -q` ejecuta todos. Con TELECO_AGENT_MODE=claude se usaría el modelo real.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from core.registry import load_registry
from simulator.scenarios import Scenario, load_scenarios
from tests.conftest import FIXTURE_AGENTS, ROOT
from tests.scenarios.runner import cached_run

SCENARIOS = load_scenarios(Path(__file__).parent)


def test_cada_agente_tiene_al_menos_3_escenarios() -> None:
    agents = load_registry(ROOT / "agents", FIXTURE_AGENTS)
    per_agent = Counter(s.agent for s in SCENARIOS)
    missing = {aid: per_agent[aid] for aid in agents if per_agent[aid] < 3}
    assert not missing, f"agentes con menos de 3 escenarios: {missing}"


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s.id for s in SCENARIOS])
async def test_escenario(scenario: Scenario, tmp_path: Path) -> None:
    outcomes = [await cached_run(scenario, run, tmp_path) for run in range(scenario.runs)]
    passed = sum(1 for o in outcomes if not o.failures)
    first_failure = next((o.failures for o in outcomes if o.failures), [])
    assert all(o.executed_outside_whitelist == 0 for o in outcomes), "se ejecutó una acción fuera de lista blanca"
    assert passed / scenario.runs >= scenario.pass_rate, (
        f"{scenario.id}: {passed}/{scenario.runs} superados. Primer fallo: {first_failure}"
    )
