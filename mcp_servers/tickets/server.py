"""Servidor MCP «tickets»: abrir, buscar, actualizar y alertar sobre tickets del NOC."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from mcp_servers.context import McpContext, dumps

PRIORITIES = ("P1", "P2", "P3", "P4")


def build_tickets_server(ctx: McpContext) -> MCPServer:
    server = MCPServer("tickets", instructions="Sistema de tickets del NOC (simulado).")

    @server.tool(
        name="crear",
        description="Abre un ticket a partir de un grupo de alarmas. Avisa al Bombero con ticket.created.",
    )
    async def crear(
        prioridad: str,
        diagnostico: str,
        zona: str,
        grupo: str,
        codigos: list[str],
        clientes_ftth: int,
        empresas: list[str],
        nodo: str | None = None,
    ) -> str:
        if prioridad not in PRIORITIES:
            return dumps({"ok": False, "detail": f"prioridad no válida: {prioridad} (usa {', '.join(PRIORITIES)})"})
        existing = await ctx.store.find_open_ticket(group_id=grupo)
        if existing:
            return dumps({"ok": False, "detail": f"ya existe {existing.id} para {grupo}", "ticket": existing.id})
        trace = await ctx.store.group_trace(grupo)
        tk = await ctx.store.create_ticket(
            priority=prioridad,
            diagnosis=diagnostico,
            zone=zona,
            node=nodo,
            group_id=grupo,
            codes=codigos,
            affected_ftth=max(0, clientes_ftth),
            enterprises=empresas,
            sim_now=await ctx.sim.now(),
            trace=trace,
        )
        await ctx.emit(
            "ticket.created",
            {
                "ticket": tk.id,
                "priority": tk.priority,
                "diagnosis": tk.diagnosis,
                "node": tk.node,
                "zone": tk.zone,
                "codes": tk.codes,
            },
            trace,
        )
        return dumps({"ok": True, "ticket": tk.id})

    @server.tool(name="grupo_alarmas", description="Grupo de alarmas del que nace un ticket: códigos, nodo, zona.")
    async def grupo_alarmas(grupo: str) -> str:
        group = await ctx.store.group(grupo)
        if group is None:
            return dumps({"error": f"grupo desconocido: {grupo}"})
        return dumps({**group.model_dump(mode="json"), "num_alarmas": len(group.alarm_ids)})

    @server.tool(name="buscar", description="Busca un ticket abierto o escalado de un nodo o de un grupo de alarmas.")
    async def buscar(nodo: str | None = None, grupo: str | None = None) -> str:
        tk = await ctx.store.find_open_ticket(node=nodo, group_id=grupo)
        return dumps(tk.model_dump(mode="json") if tk else {"ticket": None})

    @server.tool(name="obtener", description="Ticket completo con sus notas.")
    async def obtener(ticket: str) -> str:
        tk = await ctx.store.ticket(ticket)
        return dumps(tk.model_dump(mode="json") if tk else {"error": f"ticket desconocido: {ticket}"})

    @server.tool(
        name="abiertos",
        description="Tickets abiertos o escalados con clientes empresa y minutos abiertos (reloj simulado).",
    )
    async def abiertos() -> str:
        now = await ctx.sim.now()
        out = []
        for tk in await ctx.store.tickets(status="abiertos"):
            if tk.enterprises:
                minutes = int((now - tk.created_sim_at).total_seconds() // 60)
                out.append(
                    {
                        "ticket": tk.id,
                        "prioridad": tk.priority,
                        "diagnostico": tk.diagnosis,
                        "empresas": tk.enterprises,
                        "minutos_abierto": minutes,
                        "alerta_sla_enviada": tk.sla_alerted,
                    }
                )
        return dumps(out)

    @server.tool(name="actualizar", description="Añade una nota a un ticket.")
    async def actualizar(ticket: str, nota: str) -> str:
        try:
            tk = await ctx.store.update_ticket(ticket, note=nota)
        except LookupError:
            return dumps({"ok": False, "detail": f"ticket desconocido: {ticket}"})
        return dumps({"ok": True, "ticket": tk.id})

    @server.tool(name="alerta_sla", description="Marca un ticket en riesgo de incumplir el SLA de un cliente empresa.")
    async def alerta_sla(ticket: str, cliente: str, porcentaje: int) -> str:
        try:
            tk = await ctx.store.update_ticket(
                ticket,
                note=f"Riesgo de SLA: {cliente} lleva el {porcentaje} % de su plazo de respuesta.",
                sla_alerted=True,
            )
        except LookupError:
            return dumps({"ok": False, "detail": f"ticket desconocido: {ticket}"})
        await ctx.emit(
            "sla.risk", {"ticket": tk.id, "customer": cliente, "pct": porcentaje}, await ctx.store.ticket_trace(ticket)
        )
        return dumps({"ok": True, "ticket": tk.id})

    return server
