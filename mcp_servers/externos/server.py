"""Servidores MCP «meteo_sim» y «energia_sim»: factores externos por zona (simulados)."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from mcp_servers.context import McpContext


def build_meteo_server(ctx: McpContext) -> MCPServer:
    server = MCPServer("meteo_sim", instructions="Avisos meteorológicos por zona (simulados).")

    @server.tool(name="zona__consultar", description="Tiempo en una zona: tormenta y rayos por hora.")
    async def zona_consultar(zona: str) -> str:
        return (await ctx.sim.weather(zona)).model_dump_json()

    return server


def build_energia_server(ctx: McpContext) -> MCPServer:
    server = MCPServer("energia_sim", instructions="Estado del suministro eléctrico por zona (simulado).")

    @server.tool(name="zona__consultar", description="Cortes de luz en una zona y nodos sin red eléctrica.")
    async def zona_consultar(zona: str) -> str:
        return (await ctx.sim.power(zona)).model_dump_json()

    return server
