"""Todos los servidores MCP del sistema, construidos sobre el mismo contexto."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from mcp_servers.cambios.server import build_cambios_server, seed_changes
from mcp_servers.context import McpContext
from mcp_servers.contratos.server import build_contratos_server
from mcp_servers.externos.server import build_energia_server, build_meteo_server
from mcp_servers.inventario.server import build_inventario_server
from mcp_servers.notificaciones.server import build_notificaciones_server
from mcp_servers.red.server import build_red_server
from mcp_servers.tickets.server import build_tickets_server

SERVER_NAMES = ["red", "tickets", "inventario", "notificaciones", "contratos", "cambios", "meteo_sim", "energia_sim"]


def build_all(ctx: McpContext) -> dict[str, MCPServer]:
    return {
        "red": build_red_server(ctx.sim, ctx),
        "tickets": build_tickets_server(ctx),
        "inventario": build_inventario_server(ctx),
        "notificaciones": build_notificaciones_server(ctx),
        "contratos": build_contratos_server(ctx),
        "cambios": build_cambios_server(ctx),
        "meteo_sim": build_meteo_server(ctx),
        "energia_sim": build_energia_server(ctx),
    }


async def prepare(ctx: McpContext) -> None:
    await ctx.store.seed_changes(seed_changes())
