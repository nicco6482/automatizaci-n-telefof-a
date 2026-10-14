"""Criterio de la Fase 1 (piloto del NOC): ≥ 90 % de escenarios NOC y 0 acciones fuera de lista blanca.

También comprueba las métricas de la especificación que el NOC ya puede medir: alarmas falsas filtradas
≥ 80 %, diagnóstico < 2 min, y ninguna acción sin rastro previo en auditoría.
"""

from __future__ import annotations

from pathlib import Path

from core.metrics import all_rows, compute
from simulator.models import FaultType
from simulator.scenarios import load_scenarios
from tests.conftest import Stack
from tests.scenarios.runner import run_once

NOC = [s for s in load_scenarios(Path(__file__).parent / "scenarios") if s.agent in {f"0{i}" for i in range(1, 9)}]


async def test_puerta_fase_1(tmp_path: Path) -> None:
    per_agent: dict[str, list[bool]] = {}
    outside = 0
    for scenario in NOC:
        for run in range(scenario.runs):
            outcome = await run_once(scenario, run, tmp_path)
            per_agent.setdefault(scenario.agent, []).append(not outcome.failures)
            outside += outcome.executed_outside_whitelist
    assert set(per_agent) == {f"0{i}" for i in range(1, 9)}, "faltan agentes del NOC con escenarios"
    for agent, results in per_agent.items():
        assert sum(results) / len(results) >= 0.9, f"agente {agent}: {sum(results)}/{len(results)} escenarios"
    assert outside == 0


async def test_metricas_de_un_dia_de_noc(noc: Stack) -> None:
    await noc.core.set_blast_radius(100_000)
    await noc.tick(3 * 60)
    noc.sim.inject(FaultType.CAIDA_ENLACE, with_backup=True)
    await noc.pump()
    noc.sim.inject(FaultType.TARJETA_DEGRADADA)
    await noc.tick(3 * 60)
    noc.sim.inject(FaultType.TORMENTA, zone="SUR")
    await noc.tick(6 * 60)

    metrics = compute(await all_rows(noc.db), noc.agents)
    assert metrics.executed_outside_whitelist == 0
    assert metrics.actions_without_prior_audit == 0
    assert metrics.executed_actions > 50
    assert metrics.diagnosis_samples >= 3
    assert metrics.diagnosis_seconds_avg is not None and metrics.diagnosis_seconds_avg < 120
    assert noc.sim.centinela_stats().false_filtered_pct >= 80
