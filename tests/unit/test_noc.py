"""Piezas del NOC que no cubren los escenarios: grupos, avisos, rechazos y la verdad del Centinela."""

from __future__ import annotations

from core.control import HUMAN
from ops.human import after_rejection, close_page
from simulator.models import FaultType
from tests.conftest import Stack


async def test_averia_nueva_tras_cerrar_abre_otro_ticket(noc: Stack) -> None:
    await noc.core.set_blast_radius(100_000)
    f1 = noc.sim.inject(FaultType.CAIDA_ENLACE, with_backup=True)
    await noc.pump()
    noc.sim.repair(f1.id)
    noc.sim.inject(FaultType.TARJETA_DEGRADADA, node=f1.node)
    await noc.pump()
    tickets = await noc.mcp.store.tickets()
    assert len(tickets) == 2 and all(t.status == "cerrado" for t in tickets)


async def test_cerrar_aviso_repara_y_activa_al_forense(noc: Stack) -> None:
    fault = noc.sim.inject(FaultType.CAIDA_ENLACE, with_backup=False)
    await noc.pump()
    pages = await noc.mcp.store.pages(status="abierto")
    assert len(pages) == 1
    await close_page(noc.mcp, noc.core, pages[0].id, by=HUMAN, resolution="Fibra empalmada.")
    await noc.pump()
    assert noc.sim.state.node_has_service(fault.node or "")
    assert (await noc.mcp.store.tickets())[0].status == "cerrado"
    assert await noc.core.audit.list(agent="05_forense", step="salida")


async def test_rechazo_escala_el_ticket(noc: Stack) -> None:
    await noc.core.set_blast_radius(0)
    noc.sim.inject(FaultType.CAIDA_ENLACE, with_backup=True)
    await noc.pump()
    pending = await noc.core.approvals(status="pendiente")
    assert len(pending) == 1
    done = await noc.core.decide(pending[0].id, approve=False, comment="ahora no")
    await after_rejection(noc.mcp, done)
    await noc.pump()
    assert (await noc.mcp.store.tickets())[0].status == "escalado"
    assert len(await noc.mcp.store.pages(status="abierto")) == 1


async def test_aprobar_cierra_el_ticket(noc: Stack) -> None:
    await noc.core.set_blast_radius(0)
    noc.sim.inject(FaultType.CAIDA_ENLACE, with_backup=True)
    await noc.pump()
    pending = await noc.core.approvals(status="pendiente")
    await noc.core.decide(pending[0].id, approve=True, comment="adelante")
    await noc.pump()
    assert (await noc.mcp.store.tickets())[0].status == "cerrado"
    assert await noc.core.audit.list(agent="05_forense", step="salida")


async def test_centinela_filtra_mas_del_80_por_ciento_de_falsas(noc: Stack) -> None:
    await noc.core.set_blast_radius(100_000)
    await noc.tick(6 * 60)
    noc.sim.inject(FaultType.CAIDA_ENLACE, with_backup=True)
    noc.sim.inject(FaultType.TORMENTA, zone="TRI")
    await noc.pump()
    await noc.tick(6 * 60)
    stats = noc.sim.centinela_stats()
    assert stats.false_total > 20
    assert stats.false_filtered_pct >= 80
    assert stats.real_discarded == 0
