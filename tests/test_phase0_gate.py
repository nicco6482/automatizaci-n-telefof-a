"""Criterio de la Fase 0: un evento simulado llega al panel con auditoría completa.

Recorre el camino real: API -> simulador -> bus (Redis Streams) -> orquestador -> agente -> núcleo -> MCP
-> auditoría -> API, y después la aprobación humana desde la API hasta la red.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from fakeredis import FakeAsyncRedis

from api.main import Services, create_app
from core.agent import ScriptedRunner
from core.bus import EventBus
from core.control import ControlCore
from core.db import Database
from core.gateway import ToolGateway
from core.orchestrator import Orchestrator
from core.registry import load_registry
from mcp_servers.red.server import build_red_server
from simulator.engine import Simulator
from simulator.port import LocalSimulator
from simulator.service import build_router
from tests.conftest import FIXTURE_AGENTS, ROOT


@pytest.fixture
async def panel(tmp_path: Path) -> AsyncIterator[tuple[httpx.AsyncClient, Orchestrator, EventBus, Simulator]]:
    sim = Simulator(42)
    bus = EventBus(FakeAsyncRedis(decode_responses=True))
    await bus.ensure_group()
    db = Database(f"sqlite+aiosqlite:///{(tmp_path / 'gate.db').as_posix()}")
    await db.init()
    port = LocalSimulator(sim)
    core = ControlCore(db, ToolGateway({"red": build_red_server(port)}), port)
    agents = load_registry(ROOT / "agents", FIXTURE_AGENTS)
    sim_http = httpx.AsyncClient(transport=httpx.ASGITransport(app=build_router(sim, bus)), base_url="http://sim")
    app = create_app(Services(core, agents, bus, sim_http, "guion"))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://panel") as client,
    ):
        yield client, Orchestrator(agents, core, ScriptedRunner()), bus, sim
    await sim_http.aclose()
    await db.close()


async def test_evento_simulado_llega_al_panel_con_auditoria_completa(panel) -> None:  # type: ignore[no-untyped-def]
    client, orchestrator, bus, sim = panel

    # 1. Una persona inyecta una caída desde el panel; el simulador la publica en el bus.
    r = await client.post("/api/sim/inject", json={"type": "caida_enlace", "with_backup": True})
    assert r.status_code == 200
    incident, node = r.json()["id"], r.json()["node"]
    assert node in (await client.get("/api/sim/summary")).json()["nodes_without_service"]

    # 2. El orquestador consume el bus y activa al agente.
    assert await orchestrator.process_once(bus, block_ms=10) > 0
    assert any(e["topic"] == "alarm.raised" for e in (await client.get("/api/events")).json())

    # 3. El panel ve la auditoría completa del incidente.
    rows = (await client.get("/api/audit", params={"incident": incident})).json()
    steps = {(r["agent"], r["step"], r["decision"]) for r in rows}
    assert ("OPERADOR", "evento", "avería inyectada") in steps
    assert ("00_sonda", "evento", "recibido") in steps
    assert ("00_sonda", "lectura", "autorizada") in steps
    assert ("00_sonda", "lectura", "leída") in steps
    assert ("00_sonda", "gemelo", "gemelo ok") in steps
    assert ("00_sonda", "accion", "en cola de aprobación") in steps
    assert ("00_sonda", "salida", "salida válida") in steps
    salida = next(r for r in rows if r["step"] == "salida")
    assert salida["tokens"] > 0 and salida["cost_usd"] > 0
    for r in rows:
        assert r["at"] and r["agent"] and r["step"]

    # 4. La acción espera en la cola con su evidencia y el resultado del gemelo.
    pending = (await client.get("/api/approvals", params={"status": "pendiente"})).json()
    assert len(pending) == 1
    ap = pending[0]
    assert ap["tool"] == "red.runbooks.conmutar_respaldo" and ap["twin_ok"] is True and ap["evidence"]
    assert node in (await client.get("/api/sim/summary")).json()["nodes_without_service"]

    # 5. Una persona aprueba; el núcleo ejecuta y deja constancia de quién aprobó.
    r = await client.post(f"/api/approvals/{ap['id']}/approve", json={"comment": "Conmuta, hay respaldo."})
    assert r.status_code == 200 and r.json()["status"] == "aprobada"
    assert node not in (await client.get("/api/sim/summary")).json()["nodes_without_service"]
    rows = (await client.get("/api/audit", params={"incident": incident})).json()
    executed = [r for r in rows if r["decision"] == "ejecutada tras aprobación"]
    assert executed and executed[0]["approved_by"] == "Operador NOC"

    # 6. Métricas del panel: coste medido y ninguna aprobación colgando.
    control = (await client.get("/api/control")).json()
    assert control["cost_today_usd"] > 0 and control["pending_approvals"] == 0
    assert (await client.post(f"/api/approvals/{ap['id']}/approve", json={})).status_code == 409


async def test_interruptor_desde_el_panel(panel) -> None:  # type: ignore[no-untyped-def]
    client, orchestrator, bus, _ = panel
    assert (await client.post("/api/control/kill-switch", json={"on": True})).json()["kill_switch"] is True
    assert all(a["nivel_efectivo"] == 0 for a in (await client.get("/api/agents")).json())
    await client.post("/api/sim/inject", json={"type": "caida_enlace", "with_backup": True})
    await orchestrator.process_once(bus, block_ms=10)
    assert (await client.get("/api/approvals", params={"status": "pendiente"})).json() == []
