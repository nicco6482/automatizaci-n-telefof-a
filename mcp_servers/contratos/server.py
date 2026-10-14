"""Servidor MCP «contratos»: SLA de los clientes empresa."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from mcp_servers.context import McpContext, dumps


def build_contratos_server(ctx: McpContext) -> MCPServer:
    server = MCPServer("contratos", instructions="Contratos y SLA de clientes empresa (ficticios).")

    @server.tool(name="sla", description="SLA de una lista de clientes empresa: disponibilidad y plazo de respuesta.")
    async def sla(clientes: list[str]) -> str:
        wanted = set(clientes)
        out = [
            {"id": e.id, "nombre": e.name, "servicio": e.service, "sla": e.sla_pct, "respuesta_horas": e.response_hours}
            for e in await ctx.sim.enterprises()
            if e.id in wanted
        ]
        return dumps(out)

    return server
