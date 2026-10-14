"""Servidor MCP «notificaciones»: quién está de guardia y avisarle. El aviso lo cierra siempre una persona."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from mcp_servers.context import McpContext, dumps

# Personas ficticias. En una operadora real vendría del cuadrante de guardias.
NIGHT = "Guardia nocturna de transporte (Lucía Marín, ficticia)"
DAY = "Turno de día del NOC (Andrés Vega, ficticio)"


def build_notificaciones_server(ctx: McpContext) -> MCPServer:
    server = MCPServer("notificaciones", instructions="Avisos a la persona de guardia (simulado).")

    @server.tool(name="guardia", description="Quién está de guardia ahora según el cuadrante (reloj simulado).")
    async def guardia() -> str:
        hour = (await ctx.sim.now()).hour
        return dumps({"persona": NIGHT if hour < 8 or hour >= 22 else DAY, "hora_simulada": hour})

    @server.tool(name="avisar", description="Envía un aviso a la persona de guardia con un resumen de 3 líneas.")
    async def avisar(ticket: str, persona: str, resumen: str) -> str:
        if not resumen.strip():
            return dumps({"ok": False, "detail": "el resumen no puede estar vacío"})
        trace = await ctx.store.ticket_trace(ticket)
        page = await ctx.store.create_page(ticket=ticket, person=persona, summary=resumen[:1200], trace=trace)
        await ctx.emit("page.created", {"page": page.id, "ticket": ticket, "person": persona}, trace)
        return dumps({"ok": True, "aviso": page.id, "detail": f"Aviso {page.id} enviado a {persona} (simulado)."})

    return server
