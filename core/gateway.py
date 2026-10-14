"""Cliente MCP del núcleo: el único que ejecuta acciones aprobadas por una persona."""

from __future__ import annotations

from typing import Any

from mcp.client.client import Client
from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel

from core.tools import ToolName

McpTarget = MCPServer | str  # servidor en memoria (pruebas) o URL streamable-http (docker compose)


class ToolResult(BaseModel):
    ok: bool
    text: str


class UnknownServer(LookupError):
    pass


class ToolGateway:
    def __init__(self, targets: dict[str, McpTarget]) -> None:
        self.targets = targets

    def target(self, server: str) -> McpTarget:
        if server not in self.targets:
            raise UnknownServer(server)
        return self.targets[server]

    async def call(self, canonical: str, args: dict[str, Any]) -> ToolResult:
        name = ToolName.from_canonical(canonical)
        async with Client(self.target(name.server)) as client:
            result = await client.call_tool(name.tool, args)
        text = "\n".join(getattr(block, "text", "") for block in result.content)
        return ToolResult(ok=not result.is_error, text=text)

    async def list_tools(self, server: str) -> list[str]:
        async with Client(self.target(server)) as client:
            listed = await client.list_tools()
        return [ToolName(server=server, tool=t.name).canonical for t in listed.tools]
