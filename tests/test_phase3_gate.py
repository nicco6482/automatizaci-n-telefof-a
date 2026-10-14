"""Criterio de la Fase 3 (empresas y planificación): cada borrador lo cierra una persona."""

from __future__ import annotations

from pathlib import Path

from core.control import HUMAN
from core.tools import catalog
from ops.business import publish_business
from ops.human import close_task
from simulator.scenarios import load_scenarios
from tests.conftest import Stack
from tests.scenarios.runner import cached_run

PHASE3 = {f"{i}" for i in range(26, 36)}
SCENARIOS = [s for s in load_scenarios(Path(__file__).parent / "scenarios") if s.agent in PHASE3]


async def test_puerta_fase_3(tmp_path: Path) -> None:
    per_agent: dict[str, list[bool]] = {}
    outside = without_twin = 0
    for scenario in SCENARIOS:
        for run in range(scenario.runs):
            o = await cached_run(scenario, run, tmp_path)
            per_agent.setdefault(scenario.agent, []).append(not o.failures)
            outside += o.executed_outside_whitelist
            without_twin += o.changes_without_twin_and_approval
    assert set(per_agent) == PHASE3, f"faltan agentes con escenarios: {PHASE3 - set(per_agent)}"
    for agent, results in per_agent.items():
        assert sum(results) / len(results) >= 0.9, f"agente {agent}: {sum(results)}/{len(results)} escenarios"
    assert outside == 0 and without_twin == 0


def test_ningun_agente_tiene_herramienta_para_cerrar_trabajo_de_personas() -> None:
    # Las entregas solo crean borrador y tarea; cerrar es exclusivo del panel (ops.human), fuera del MCP.
    for name, spec in catalog().items():
        assert "cerrar" not in name, f"{name}: un agente no debe poder cerrar nada"
        if spec.tipo == "entrega":
            assert name.split(".")[-1].startswith(("entregar", "solicitar")), name


async def test_cada_borrador_lo_cierra_una_persona(noc: Stack) -> None:
    for topic in ("lease.expiring", "design.approved"):
        await publish_business(noc.mcp, topic, {"zona": "TRI"})
    noc.sim.outbox.clear()
    await noc.pump()
    from core.schemas import BusEvent

    await noc.bus.publish(BusEvent(topic="cron.mensual", payload={}, incident="MES"))
    await noc.pump()

    drafts = [d for d in await noc.mcp.store.documents() if d.kind.startswith("borrador_")]
    kinds = {d.kind for d in drafts}
    assert {"borrador_renovacion", "borrador_proyecto", "borrador_informe_regulatorio"} <= kinds
    # Sin persona, nada se cierra: los agentes solo entregan.
    assert all(d.status == "borrador" for d in drafts)
    open_tasks = await noc.mcp.store.tasks(status="abierta")
    assert {t.ref for t in open_tasks} >= {d.id for d in drafts}

    for t in open_tasks:
        await close_task(noc.mcp, noc.core, t.id, by=HUMAN, resolution="Revisado y firmado.")
    for d in [d for d in await noc.mcp.store.documents() if d.kind.startswith("borrador_")]:
        assert d.status == f"cerrado por {HUMAN}"
    closers = {r.agent for r in await noc.core.audit.list(limit=5000) if r.decision == "tarea cerrada"}
    assert closers == {"PERSONA"}
