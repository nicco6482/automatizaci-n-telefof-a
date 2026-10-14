"""Servidor MCP «red»: alarmas, estado de nodos, histórico y runbooks sobre la red simulada.

Los nombres siguen la convención `<grupo>__<accion>` para que el núcleo los mapee a `red.<grupo>.<accion>`.
"""

from __future__ import annotations

import json
import os

import anyio
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from mcp_servers.context import McpContext, dumps
from simulator.engine import UnknownTarget
from simulator.port import HttpSimulator, SimulatorPort

RUNBOOKS = {
    "LINK_DOWN": (
        "RB-01 Conmutación a respaldo",
        "Si el enlace principal está caído, el nodo tiene energía y el respaldo está en reserva: conmutar con "
        "runbooks__conmutar_respaldo. Si no hay respaldo o no hay energía: escalar a guardia.",
    ),
    "CELL_UNAVAILABLE": ("RB-01 Conmutación a respaldo", "Ver LINK_DOWN del nodo que da servicio a la celda."),
    "CARD_BER_HIGH": (
        "RB-02 Reinicio de tarjeta",
        "BER alta sin causa física aparente: reiniciar con runbooks__reiniciar_tarjeta. Si vuelve en 24 h, sustituir.",
    ),
    "MAINS_FAIL": (
        "PR-07 Fallo de alimentación",
        "Ningún runbook remoto arregla la energía. No reiniciar ni conmutar: escalar a guardia para grupo electrógeno.",
    ),
}
RUNBOOKS["BATTERY_DISCHARGING"] = RUNBOOKS["MAINS_FAIL"]
RUNBOOKS["CRC_ERRORS"] = RUNBOOKS["CARD_BER_HIGH"]


def build_red_server(port: SimulatorPort, ctx: McpContext | None = None) -> MCPServer:
    server = MCPServer("red", instructions="Red simulada de la teleco: alarmas, nodos, histórico y runbooks.")

    def need_ctx() -> McpContext:
        if ctx is None:
            raise RuntimeError("este servidor se arrancó sin datos de operación")
        return ctx

    # ---------- alarmas ----------
    @server.tool(name="alarmas__listar", description="Últimas alarmas de la red, opcionalmente de un nodo o zona.")
    async def alarmas_listar(limite: int = 20, nodo: str | None = None, zona: str | None = None) -> str:
        alarms = await port.list_alarms(limit=max(1, min(limite, 100)), node=nodo, zone=zona)
        return dumps([a.model_dump(mode="json") for a in alarms])

    @server.tool(
        name="alarmas__agrupar",
        description="Añade una alarma real al grupo de su fallo (clave = id de nodo, o ZONA-<zona> si es de "
        "energía). Si el grupo es nuevo, se avisa a Triaje con alarm.grouped.",
    )
    async def alarmas_agrupar(alarma: str, clave: str) -> str:
        c = need_ctx()
        alarm = await port.alarm(alarma)
        if alarm is None:
            return dumps({"ok": False, "detail": f"alarma desconocida: {alarma}"})
        trace = await port.alarm_trace(alarma)
        group, created = await c.store.group_alarm(alarm.id, alarm.code, clave[:60], alarm.zone, alarm.node, trace)
        if created:
            await c.emit(
                "alarm.grouped",
                {"group": group.id, "key": group.key, "zone": group.zone, "node": group.node, "codes": group.codes},
                trace,
            )
        return dumps({"ok": True, "grupo": group.id, "nuevo": created, "alarmas": len(group.alarm_ids)})

    @server.tool(name="alarmas__descartar", description="Descarta una alarma falsa o transitoria, con su motivo.")
    async def alarmas_descartar(alarma: str, motivo: str) -> str:
        if await port.alarm(alarma) is None:
            return dumps({"ok": False, "detail": f"alarma desconocida: {alarma}"})
        await port.mark_discarded(alarma)
        return dumps({"ok": True, "detail": f"{alarma} descartada: {motivo}"})

    @server.tool(name="alarmas__grupo", description="Detalle de un grupo de alarmas con sus alarmas.")
    async def alarmas_grupo(grupo: str) -> str:
        group = await need_ctx().store.group(grupo)
        if group is None:
            return dumps({"error": f"grupo desconocido: {grupo}"})
        alarms = [a for a in [await port.alarm(i) for i in group.alarm_ids] if a is not None]
        return dumps({**group.model_dump(mode="json"), "detalle": [a.model_dump(mode="json") for a in alarms]})

    # ---------- nodos e histórico ----------
    @server.tool(name="estado__nodo", description="Estado de un nodo: enlaces, respaldo, energía, clientes FTTH.")
    async def estado_nodo(nodo: str) -> str:
        try:
            node = await port.node(nodo)
            service = await port.has_service(nodo)
        except UnknownTarget:
            return dumps({"error": f"nodo desconocido: {nodo}"})
        return dumps({**node.model_dump(mode="json"), "con_servicio": service})

    @server.tool(
        name="historico__incidente",
        description="Histórico de red de un nodo o zona: alarmas recientes, estado de enlaces y energía.",
    )
    async def historico_incidente(nodo: str | None = None, zona: str | None = None) -> str:
        alarms = await port.list_alarms(limit=30, node=nodo, zone=None if nodo else zona)
        out: dict[str, object] = {"alarmas": [a.model_dump(mode="json") for a in alarms]}
        if nodo:
            try:
                node = await port.node(nodo)
            except UnknownTarget:
                return dumps({"error": f"nodo desconocido: {nodo}"})
            out["nodo"] = node.model_dump(mode="json")
            out["con_servicio"] = await port.has_service(nodo)
        if zona or nodo:
            z = zona or str(out["nodo"]["zone"])  # type: ignore[index]
            out["energia"] = (await port.power(z)).model_dump()
            out["meteo"] = (await port.weather(z)).model_dump()
        return dumps(out)

    # ---------- runbooks ----------
    @server.tool(
        name="runbooks__consultar",
        description="Runbook para un código de alarma y, si se da el nodo, si se puede aplicar ahora y qué acción.",
    )
    async def runbooks_consultar(codigo_alarma: str, nodo: str | None = None) -> str:
        name, text = RUNBOOKS.get(codigo_alarma, ("Sin runbook", "Sin runbook para este código: escalar a guardia."))
        out: dict[str, object] = {"runbook": name, "procedimiento": text, "aplicable": False, "accion": None}
        if not nodo:
            return dumps(out)
        try:
            node = await port.node(nodo)
        except UnknownTarget:
            return dumps({**out, "motivo": f"nodo desconocido: {nodo}"})
        if not node.powered or codigo_alarma in ("MAINS_FAIL", "BATTERY_DISCHARGING"):
            return dumps({**out, "motivo": f"{nodo} sin energía: no hay runbook remoto."})
        if codigo_alarma in ("LINK_DOWN", "CELL_UNAVAILABLE"):
            if not node.backup_link:
                return dumps({**out, "motivo": f"{nodo} no tiene enlace de respaldo."})
            if node.on_backup:
                return dumps({**out, "motivo": f"{nodo} ya está en respaldo."})
            return dumps(
                {
                    **out,
                    "aplicable": True,
                    "accion": "runbooks__conmutar_respaldo",
                    "motivo": f"Respaldo {node.backup_link} disponible; {node.ftth_clients} clientes FTTH.",
                }
            )
        if codigo_alarma in ("CARD_BER_HIGH", "CRC_ERRORS"):
            return dumps(
                {
                    **out,
                    "aplicable": True,
                    "accion": "runbooks__reiniciar_tarjeta",
                    "motivo": f"Reinicio de tarjeta; {node.ftth_clients} clientes con cortes durante 94 s.",
                }
            )
        return dumps({**out, "motivo": "Código sin acción remota."})

    async def _after_action(nodo: str, ticket: str | None, ok: bool, detail: str) -> None:
        if ctx is None or not ticket:
            return
        tk = await ctx.store.ticket(ticket)
        if tk is None:
            return
        trace = await ctx.store.ticket_trace(ticket)
        if ok and await port.has_service(nodo):
            await ctx.store.update_ticket(
                ticket, note=f"Runbook aplicado: {detail} Servicio verificado.", status="cerrado"
            )
            await ctx.emit(
                "ticket.closed", {"ticket": ticket, "node": nodo, "zone": tk.zone, "resolution": detail}, trace
            )
        else:
            await ctx.store.update_ticket(ticket, note=f"Runbook sin éxito: {detail}")

    @server.tool(
        name="runbooks__conmutar_respaldo",
        description="Pasa el tráfico de un nodo de acceso a su enlace de respaldo. Reversible. Si se indica el "
        "ticket, lo cierra cuando el servicio vuelve.",
    )
    async def runbooks_conmutar_respaldo(nodo: str, ticket: str | None = None) -> str:
        result = await port.act("conmutar_respaldo", {"node": nodo})
        await _after_action(nodo, ticket, result.ok, result.detail)
        return result.model_dump_json()

    @server.tool(
        name="runbooks__reiniciar_tarjeta",
        description="Reinicia la tarjeta de línea de un nodo. Reversible. Si se indica el ticket, lo cierra si "
        "el servicio queda bien.",
    )
    async def runbooks_reiniciar_tarjeta(nodo: str, ticket: str | None = None) -> str:
        result = await port.act("reiniciar_tarjeta", {"node": nodo})
        await _after_action(nodo, ticket, result.ok, result.detail)
        return result.model_dump_json()

    @server.tool(name="runbooks__escalar", description="Escala un ticket a la persona de guardia, con el motivo.")
    async def runbooks_escalar(ticket: str, motivo: str) -> str:
        c = need_ctx()
        tk = await c.store.ticket(ticket)
        if tk is None:
            return dumps({"ok": False, "detail": f"ticket desconocido: {ticket}"})
        await c.store.update_ticket(ticket, note=f"Escalado: {motivo}", status="escalado")
        await c.emit(
            "ticket.escalated",
            {
                "ticket": ticket,
                "reason": motivo,
                "priority": tk.priority,
                "diagnosis": tk.diagnosis,
                "node": tk.node,
                "zone": tk.zone,
            },
            await c.store.ticket_trace(ticket),
        )
        return dumps({"ok": True, "detail": f"{ticket} escalado."})

    @server.tool(name="config__escribir", description="Escritura libre de configuración. No reversible.")
    async def config_escribir(nodo: str, cambio: str) -> str:
        return json.dumps({"ok": False, "detail": "Escritura libre no implementada en el simulador."})

    return server


def main() -> None:
    """Solo el servidor «red», sin datos de operación (Fase 0). El despliegue completo usa mcp_servers.app."""
    server = build_red_server(HttpSimulator(os.environ.get("TELECO_SIMULATOR_URL", "http://localhost:8100")))
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
