"""Servidor MCP «cambios»: calendario de cambios planificados en la red."""

from __future__ import annotations

from datetime import datetime, timedelta

from mcp.server.mcpserver import MCPServer

from mcp_servers.context import McpContext, dumps
from ops.store import Change
from simulator.engine import UnknownTarget
from simulator.network import SIM_START

# Calendario inicial fijo, para que los escenarios sean reproducibles (horas desde el arranque del simulador).
SEED: list[tuple[str, str | None, str, int, int, str]] = [
    ("Sustitución de óptica en el enlace principal", "ACC-CEN-1", "CEN", 20, 22, "Ingeniería de transporte"),
    ("Actualización de firmware de la agregación", "AGG-TRI", "TRI", 21, 24, "Ingeniería de núcleo"),
    ("Mantenimiento de baterías del emplazamiento", "ACC-NER-3", "NER", 44, 46, "Energía"),
    ("Migración de VLAN de empresa", "ACC-SUR-2", "SUR", 45, 47, "Clientes empresa"),
    ("Poda de arbolado junto a la torre", None, "MAC", 68, 70, "Contrata de obra civil"),
]


def seed_changes() -> list[Change]:
    return [
        Change(
            id=f"CHG-{i + 1:04d}",
            title=title,
            node=node,
            zone=zone,
            owner=owner,
            starts_at=SIM_START + timedelta(hours=start),
            ends_at=SIM_START + timedelta(hours=end),
            status="planificado",
        )
        for i, (title, node, zone, start, end, owner) in enumerate(SEED)
    ]


def build_cambios_server(ctx: McpContext) -> MCPServer:
    server = MCPServer("cambios", instructions="Calendario de cambios de red (simulado).")

    @server.tool(name="calendario", description="Cambios planificados entre dos fechas ISO 8601 (reloj simulado).")
    async def calendario(desde: str, hasta: str) -> str:
        try:
            start, end = datetime.fromisoformat(desde), datetime.fromisoformat(hasta)
        except ValueError:
            return dumps({"error": "usa fechas ISO 8601, p. ej. 2026-10-13T01:00:00+00:00"})
        return dumps([c.model_dump(mode="json") for c in await ctx.store.changes(start, end)])

    @server.tool(
        name="programar_actualizacion",
        description="Programa y ejecuta la actualización de firmware de "
        "una lista de nodos en una ventana. Es un cambio: se prueba en el gemelo y requiere aprobación.",
    )
    async def programar_actualizacion(fabricante: str, version: str, nodos: list[str], ventana: str) -> str:
        try:
            result = await ctx.sim.act(
                "programar_actualizacion", {"vendor": fabricante, "version": version, "nodes": nodos, "window": ventana}
            )
        except UnknownTarget as exc:
            return dumps({"ok": False, "detail": str(exc)})
        return result.model_dump_json()

    return server
