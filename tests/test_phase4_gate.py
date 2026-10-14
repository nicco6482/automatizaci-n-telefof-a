"""Criterio de la Fase 4 (cierre): un día simulado completo, con los 40 agentes, y todo auditado."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from core.control import HUMAN
from core.metrics import all_rows, compute
from core.registry import load_registry
from core.schemas import BusEvent
from ops.business import TOPICS, publish_business
from ops.human import close_page, close_task
from simulator.models import FaultType
from simulator.scenarios import load_scenarios
from tests.conftest import NOC_AGENTS, Stack
from tests.scenarios.runner import cached_run

PHASE4 = {f"{i}" for i in range(36, 41)}
SCENARIOS = [s for s in load_scenarios(Path(__file__).parent / "scenarios") if s.agent in PHASE4]


def test_estan_los_40_agentes() -> None:
    agents = load_registry(NOC_AGENTS)
    assert sorted(agents) == [f"{i:02d}" for i in range(1, 41)]
    personas = {a.config.id for a in agents.values() if a.config.persona}
    assert personas == {"14", "18", "33", "34", "38", "40"}


async def test_puerta_fase_4_escenarios(tmp_path: Path) -> None:
    per_agent: dict[str, list[bool]] = {}
    for scenario in SCENARIOS:
        for run in range(scenario.runs):
            o = await cached_run(scenario, run, tmp_path)
            per_agent.setdefault(scenario.agent, []).append(not o.failures)
            assert o.executed_outside_whitelist == 0 and o.changes_without_twin_and_approval == 0
    assert set(per_agent) == PHASE4
    for agent, results in per_agent.items():
        assert sum(results) / len(results) >= 0.9, f"agente {agent}: {sum(results)}/{len(results)} escenarios"


async def _approve_all(stack: Stack) -> None:
    for ap in await stack.core.approvals(status="pendiente"):
        await stack.core.decide(ap.id, approve=True, by=HUMAN, comment="Revisado en el turno")
    await stack.pump()


async def test_un_dia_simulado_completo_todo_auditado(noc: Stack) -> None:
    sim = noc.sim
    plan = {
        2: lambda: sim.inject(FaultType.CAIDA_ENLACE, with_backup=True),
        5: lambda: sim.inject(FaultType.TARJETA_DEGRADADA),
        8: lambda: sim.inject(FaultType.CAIDA_ENLACE, with_backup=False),
        11: lambda: sim.inject(FaultType.INTERFERENCIA, zone="MAC"),
        14: lambda: sim.inject(FaultType.DDOS),
        16: lambda: sim.inject(FaultType.DESVIO_RUTAS),
        18: lambda: sim.inject(FaultType.ONT_DEGRADADA),
        20: lambda: sim.inject(FaultType.TORMENTA, zone="SUR"),
    }
    topics = sorted(TOPICS)
    for hour in range(24):
        if hour in plan:
            plan[hour]()
        if hour < len(topics):
            await publish_business(noc.mcp, topics[hour], {"zona": "TRI"})
        await noc.tick(60)
        await _approve_all(noc)
    # Un solo día no contiene los relojes semanal, mensual y trimestral: se disparan al cierre del día.
    for topic in ("cron.semanal", "cron.mensual", "cron.trimestral"):
        await noc.bus.publish(BusEvent(topic=topic, payload={"at": sim.state.now.isoformat()}))
    # Un operador pide una ventana de cambio desde el panel.
    await noc.bus.publish(
        BusEvent(
            topic="change.requested",
            incident="PET-0001",
            payload={
                "title": "Sustitución de tarjeta",
                "node": "ACC-CEN-1",
                "zone": "CEN",
                "starts_at": "2026-10-13T02:00:00+00:00",
                "ends_at": "2026-10-13T04:00:00+00:00",
            },
        )
    )
    await noc.pump()
    await _approve_all(noc)
    for page in await noc.mcp.store.pages(status="abierto"):
        await close_page(noc.mcp, noc.core, page.id, by=HUMAN, resolution="Reparado en campo.")
    for task in await noc.mcp.store.tasks(status="abierta"):
        await close_task(noc.mcp, noc.core, task.id, by=HUMAN, resolution="Revisado.")
    await noc.pump()

    rows = await all_rows(noc.db)
    m = compute(rows, noc.agents)
    # Todo auditado: ninguna acción sin su autorización previa, nada fuera de lista, ningún cambio sin gemelo.
    assert m.executed_outside_whitelist == 0
    assert m.actions_without_prior_audit == 0
    assert m.changes_without_twin_and_approval == 0
    assert m.executed_actions > 100 and m.changes_executed >= 3
    assert m.diagnosis_seconds_avg is not None and m.diagnosis_seconds_avg < 120
    assert sim.centinela_stats().false_filtered_pct >= 80
    assert not [r for r in rows if r.step == "error"], "hubo errores de agente"

    # Cada ejecución de agente empieza con su evento y termina con su salida (o con su pausa).
    runs: dict[str, list[str]] = defaultdict(list)
    for r in rows:
        if r.run_id:
            runs[r.run_id].append(r.step)
    for run_id, steps in runs.items():
        if run_id.startswith("RUN-"):
            assert steps[0] == "evento", run_id
            assert steps[-1] in ("salida", "sistema"), (run_id, steps)

    # Los 40 agentes han trabajado y han dejado salida validada.
    with_output = {r.agent for r in rows if r.step == "salida"}
    assert {a.config.slug for a in noc.agents.values()} <= with_output

    # El coste del día queda medido.
    assert sum(r.cost_usd for r in rows) > 0
