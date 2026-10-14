"""Servidor MCP «inventario»: nodos y clientes afectados."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from mcp_servers.context import McpContext, dumps
from simulator.engine import UnknownTarget


def build_inventario_server(ctx: McpContext) -> MCPServer:
    server = MCPServer("inventario", instructions="Inventario de red y clientes (simulado, datos ficticios).")

    @server.tool(name="nodo", description="Ficha de inventario de un nodo: tipo, zona, fabricante, firmware, respaldo.")
    async def nodo(nodo: str) -> str:
        try:
            node = await ctx.sim.node(nodo)
        except UnknownTarget:
            return dumps({"error": f"nodo desconocido: {nodo}"})
        return node.model_dump_json()

    @server.tool(
        name="clientes_afectados",
        description="Clientes FTTH y empresas de un nodo, o de los nodos sin servicio de una zona.",
    )
    async def clientes_afectados(nodo: str | None = None, zona: str | None = None) -> str:
        if nodo:
            try:
                nodes = [await ctx.sim.node(nodo)]
            except UnknownTarget:
                return dumps({"error": f"nodo desconocido: {nodo}"})
        elif zona:
            summary = [await ctx.sim.node(n) for n in await _zone_nodes(ctx, zona)]
            nodes = [n for n in summary if not await ctx.sim.has_service(n.id)]
        else:
            return dumps({"error": "indica nodo o zona"})
        enterprises = []
        for n in nodes:
            enterprises += [
                {"id": e.id, "nombre": e.name, "sla": e.sla_pct, "respuesta_horas": e.response_hours}
                for e in await ctx.sim.enterprises(node=n.id)
            ]
        return dumps(
            {"nodos": [n.id for n in nodes], "ftth": sum(n.ftth_clients for n in nodes), "empresas": enterprises}
        )

    return server


async def _zone_nodes(ctx: McpContext, zone: str) -> list[str]:
    ids = [f"ACC-{zone}-{i}" for i in range(1, 6)]
    found = []
    for node_id in ids:
        try:
            await ctx.sim.node(node_id)
            found.append(node_id)
        except UnknownTarget:
            continue
    return found
