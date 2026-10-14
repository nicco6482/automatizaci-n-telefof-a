"""Lo que hacen las personas desde el panel y no hace ningún agente: cerrar avisos y responder a rechazos."""

from __future__ import annotations

from core.control import Approval, ControlCore
from mcp_servers.context import McpContext
from ops.store import Page


async def close_page(ctx: McpContext, core: ControlCore, page_id: str, *, by: str, resolution: str) -> Page:
    """La persona de guardia confirma que la avería está reparada en campo."""
    page = await ctx.store.close_page(page_id, by=by, resolution=resolution)
    trace = await ctx.store.page_trace(page_id)
    await core.audit.write(
        agent="PERSONA",
        step="aprobacion",
        incident=trace,
        tool="aviso",
        input={"aviso": page_id},
        decision="aviso cerrado",
        approved_by=by,
        result=resolution or "Reparado en campo.",
    )
    if page.ticket:
        ticket = await ctx.store.ticket(page.ticket)
        if ticket and ticket.status != "cerrado":
            repaired = await ctx.sim.repair_node(ticket.node or f"AGG-{ticket.zone}")
            detail = f"Reparado en campo por {by}: {resolution.rstrip('.')}" + (
                f" ({', '.join(repaired)})." if repaired else "."
            )
            await ctx.store.update_ticket(ticket.id, note=detail, status="cerrado")
            await ctx.emit(
                "ticket.closed",
                {"ticket": ticket.id, "node": ticket.node, "zone": ticket.zone, "resolution": detail},
                trace,
            )
    return page


async def after_rejection(ctx: McpContext, approval: Approval) -> None:
    """Si una persona rechaza la acción de un ticket, el ticket se escala a guardia."""
    ticket_id = approval.args.get("ticket")
    if not isinstance(ticket_id, str):
        return
    ticket = await ctx.store.ticket(ticket_id)
    if ticket is None or ticket.status == "cerrado":
        return
    reason = f"Acción {approval.tool} rechazada por {approval.decided_by}" + (
        f": {approval.comment}" if approval.comment else ""
    )
    await ctx.store.update_ticket(ticket_id, note=reason, status="escalado")
    await ctx.emit(
        "ticket.escalated",
        {
            "ticket": ticket_id,
            "reason": reason,
            "priority": ticket.priority,
            "diagnosis": ticket.diagnosis,
            "node": ticket.node,
            "zone": ticket.zone,
        },
        await ctx.store.ticket_trace(ticket_id),
    )
