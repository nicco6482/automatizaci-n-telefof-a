"""Servidor MCP «red»: alarmas, estado de nodos y runbooks sobre la red simulada.

Los nombres siguen la convención `<grupo>__<accion>` para que el núcleo los mapee a `red.<grupo>.<accion>`.
"""

from __future__ import annotations

import json
import os

import anyio
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from simulator.engine import UnknownTarget
from simulator.port import HttpSimulator, SimulatorPort

RUNBOOKS = {
    "LINK_DOWN": "RB-01 Conmutación a respaldo: si el enlace principal está caído y el respaldo en reserva, "
    "conmutar con runbooks__conmutar_respaldo. Si no hay respaldo, escalar a guardia.",
    "CARD_BER_HIGH": "RB-02 Reinicio de tarjeta: BER alta sin causa física aparente; reiniciar con "
    "runbooks__reiniciar_tarjeta. Si vuelve en 24 h, sustituir la tarjeta.",
}


def build_red_server(port: SimulatorPort) -> MCPServer:
    server = MCPServer("red", instructions="Red simulada de la teleco: alarmas, nodos y runbooks.")

    @server.tool(name="alarmas__listar", description="Últimas alarmas de la red, opcionalmente de un nodo.")
    async def alarmas_listar(limite: int = 20, nodo: str | None = None) -> str:
        alarms = await port.list_alarms(limit=max(1, min(limite, 100)), node=nodo)
        return json.dumps([a.model_dump(mode="json") for a in alarms], ensure_ascii=False)

    @server.tool(name="estado__nodo", description="Estado de un nodo: enlaces, respaldo, clientes FTTH.")
    async def estado_nodo(nodo: str) -> str:
        try:
            node = await port.node(nodo)
        except UnknownTarget:
            return json.dumps({"error": f"nodo desconocido: {nodo}"})
        return node.model_dump_json()

    @server.tool(name="runbooks__consultar", description="Procedimiento recomendado para un código de alarma.")
    async def runbooks_consultar(codigo_alarma: str) -> str:
        return RUNBOOKS.get(codigo_alarma, "Sin runbook para este código: escalar a la persona de guardia.")

    @server.tool(
        name="runbooks__conmutar_respaldo",
        description="Pasa el tráfico de un nodo de acceso a su enlace de respaldo. Reversible.",
    )
    async def runbooks_conmutar_respaldo(nodo: str) -> str:
        return (await port.act("conmutar_respaldo", {"node": nodo})).model_dump_json()

    @server.tool(name="runbooks__reiniciar_tarjeta", description="Reinicia la tarjeta de línea de un nodo. Reversible.")
    async def runbooks_reiniciar_tarjeta(nodo: str) -> str:
        return (await port.act("reiniciar_tarjeta", {"node": nodo})).model_dump_json()

    @server.tool(name="config__escribir", description="Escritura libre de configuración. No reversible.")
    async def config_escribir(nodo: str, cambio: str) -> str:
        return json.dumps({"ok": False, "detail": "Escritura libre no implementada en el simulador."})

    return server


def main() -> None:
    server = build_red_server(HttpSimulator(os.environ.get("TELECO_SIMULATOR_URL", "http://localhost:8100")))
    # Protección contra DNS rebinding: solo los nombres de la red interna de docker compose y localhost.
    hosts = os.environ.get("MCP_ALLOWED_HOSTS", "mcp-red:*,localhost:*,127.0.0.1:*").split(",")
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True, allowed_hosts=hosts, allowed_origins=[f"http://{h}" for h in hosts]
    )
    anyio.run(
        lambda: server.run_streamable_http_async(
            host=os.environ.get("MCP_HOST", "0.0.0.0"),
            port=int(os.environ.get("MCP_PORT", "8101")),
            transport_security=security,
        )
    )


if __name__ == "__main__":
    main()
