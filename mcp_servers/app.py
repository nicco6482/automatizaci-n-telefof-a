"""Todos los servidores MCP en un solo servicio HTTP: http://<host>:8101/<servidor>/mcp

python -m mcp_servers.app
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from collections.abc import AsyncIterator

import uvicorn
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.routing import Mount

from core.bus import EventBus
from core.config import get_settings
from core.db import Database
from mcp_servers.context import McpContext
from mcp_servers.registry import build_all, prepare
from ops.store import OpsStore
from simulator.port import HttpSimulator


def security(hosts: list[str]) -> TransportSecuritySettings:
    # Protección contra DNS rebinding: solo los nombres de la red interna y localhost.
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True, allowed_hosts=hosts, allowed_origins=[f"http://{h}" for h in hosts]
    )


def build_app(servers: dict[str, MCPServer], hosts: list[str]) -> Starlette:
    sec = security(hosts)
    mounts = [
        Mount(f"/{name}", app=srv.streamable_http_app(streamable_http_path="/mcp", transport_security=sec))
        for name, srv in servers.items()
    ]

    @contextlib.asynccontextmanager
    async def lifespan(_: Starlette) -> AsyncIterator[None]:
        async with contextlib.AsyncExitStack() as stack:
            for srv in servers.values():
                await stack.enter_async_context(srv.session_manager.run())
            yield

    return Starlette(routes=mounts, lifespan=lifespan)


def urls(base: str, names: list[str]) -> dict[str, str]:
    return {name: f"{base.rstrip('/')}/{name}/mcp" for name in names}


async def main() -> None:
    settings = get_settings()
    db = Database(settings.database_url)
    await db.init()
    ctx = McpContext(HttpSimulator(settings.simulator_url), OpsStore(db), EventBus.from_url(settings.redis_url).publish)
    await prepare(ctx)
    hosts = os.environ.get("MCP_ALLOWED_HOSTS", "mcp:*,localhost:*,127.0.0.1:*").split(",")
    app = build_app(build_all(ctx), hosts)
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host=os.environ.get("MCP_HOST", "0.0.0.0"),
            port=int(os.environ.get("MCP_PORT", "8101")),
            log_level="warning",
        )
    )
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
