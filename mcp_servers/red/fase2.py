"""Herramientas de red de la Fase 2 (móvil, fibra y núcleo) dentro del servidor «red»."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from mcp_servers.context import McpContext, dumps
from simulator.engine import UnknownTarget
from simulator.port import SimulatorPort


def register_red_fase2(server: MCPServer, port: SimulatorPort, ctx: McpContext | None) -> None:
    async def view(name: str, args: dict[str, Any]) -> str:
        try:
            return dumps(await port.view(name, args))
        except UnknownTarget as exc:
            return dumps({"error": str(exc)})

    async def act(action: str, args: dict[str, Any]) -> str:
        try:
            return (await port.act(action, args)).model_dump_json()
        except UnknownTarget as exc:
            return dumps({"ok": False, "detail": str(exc)})

    # ---------- KPI y configuración de radio ----------
    @server.tool(
        name="kpis__celdas",
        description="KPI de celdas (carga, SINR, interferencia, portadoras). "
        "Con solo_problemas=true, solo las que tienen interferencia, SINR < 5 dB o carga > 95 %.",
    )
    async def kpis_celdas(zona: str | None = None, solo_problemas: bool = False) -> str:
        return await view("cells", {"zone": zona, "only_problems": solo_problemas})

    @server.tool(name="kpis__zona", description="Resumen de KPI de una zona, incluidas las portadoras que sobran.")
    async def kpis_zona(zona: str) -> str:
        return await view("zone_kpis", {"zone": zona})

    @server.tool(name="config__leer", description="Configuración de un nodo: plantilla, firmware y desviaciones.")
    async def config_leer(nodo: str) -> str:
        return await view("node_config", {"node": nodo})

    @server.tool(name="config__desviaciones", description="Nodos cuya configuración se sale de su plantilla estándar.")
    async def config_desviaciones() -> str:
        return await view("deviations", {})

    @server.tool(
        name="config__cambiar_parametros",
        description="Cambia inclinación (grados) y potencia (dB) de "
        "varias celdas. Es un cambio de configuración: se prueba en el gemelo y requiere aprobación.",
    )
    async def config_cambiar_parametros(celdas: list[str], delta_inclinacion: int, delta_potencia: int) -> str:
        return await act(
            "cambiar_parametros", {"cells": celdas, "tilt_delta": delta_inclinacion, "power_delta": delta_potencia}
        )

    @server.tool(
        name="config__apagar_portadoras",
        description="Deja con una sola portadora las celdas de baja carga de una zona. Reversible.",
    )
    async def config_apagar_portadoras(zona: str) -> str:
        return await act("apagar_portadoras", {"zone": zona})

    @server.tool(name="config__encender_portadoras", description="Enciende todas las portadoras de una zona.")
    async def config_encender_portadoras(zona: str) -> str:
        return await act("encender_portadoras", {"zone": zona})

    # ---------- capacidad y vecindades ----------
    @server.tool(name="capacidad__zona", description="Capacidad de una zona: usuarios pico frente a capacidad.")
    async def capacidad_zona(zona: str) -> str:
        return await view("capacity", {"zone": zona})

    @server.tool(
        name="capacidad__ampliar_temporal",
        description="Capacidad extra en una zona hasta una fecha ISO "
        "8601. Es un cambio: se prueba en el gemelo y requiere aprobación.",
    )
    async def capacidad_ampliar_temporal(zona: str, hasta: str) -> str:
        return await act("ampliar_capacidad", {"zone": zona, "until": hasta})

    @server.tool(name="vecinos__listar", description="Celdas con muchos fallos de traspaso y la vecina que les falta.")
    async def vecinos_listar(zona: str | None = None) -> str:
        return await view("neighbors", {"zone": zona})

    @server.tool(
        name="vecinos__corregir",
        description="Añade relaciones de vecindad, en pares «CEL-A>CEL-B». "
        "Es un cambio: se prueba en el gemelo y requiere aprobación.",
    )
    async def vecinos_corregir(pares: list[str]) -> str:
        return await act("corregir_vecinos", {"pairs": pares})

    # ---------- fibra ----------
    @server.tool(name="ont__diagnostico", description="Diagnóstico remoto de una ONT: potencia óptica y estado.")
    async def ont_diagnostico(ont: str) -> str:
        return await view("ont", {"ont": ont})

    @server.tool(name="ont__reiniciar", description="Reinicia en remoto la ONT de un cliente. Reversible.")
    async def ont_reiniciar(ont: str) -> str:
        return await act("reiniciar_ont", {"ont": ont})

    @server.tool(name="ont__potencias", description="Las ONT con peor potencia óptica.")
    async def ont_potencias(limite: int = 20) -> str:
        return await view("onts", {"limit": max(1, min(limite, 60))})

    @server.tool(
        name="ont__solicitar_sustitucion",
        description="Abre una orden de trabajo para sustituir la acometida o la ONT de un cliente.",
    )
    async def ont_solicitar_sustitucion(ont: str, motivo: str) -> str:
        if ctx is None:
            return dumps({"ok": False, "detail": "sin datos de operación"})
        try:
            info = await port.view("ont", {"ont": ont})
        except UnknownTarget as exc:
            return dumps({"ok": False, "detail": str(exc)})
        trace = (await port.view("ont_trace", {"ont": ont})).get("incident")
        wo = await ctx.store.create_workorder(
            kind="Sustitución de acometida óptica",
            zone=info["zone"],
            node=info["node"],
            ont=ont,
            detail=motivo,
            trace=trace,
        )
        await ctx.emit(
            "workorder.created", {"ot": wo.id, "kind": wo.kind, "zone": wo.zone, "ont": ont, "node": wo.node}, trace
        )
        return dumps({"ok": True, "ot": wo.id})

    @server.tool(
        name="historico__tendencias_ont",
        description="Tendencia de potencia de las ONT y días que les quedan hasta −27 dBm.",
    )
    async def historico_tendencias_ont() -> str:
        return await view("ont_trends", {})

    # ---------- núcleo ----------
    @server.tool(name="trafico__enlaces", description="Pico de uso y crecimiento semanal de cada enlace.")
    async def trafico_enlaces() -> str:
        return await view("links", {})

    @server.tool(name="bgp__rib", description="Origen anunciado y esperado de un prefijo propio.")
    async def bgp_rib(prefijo: str) -> str:
        return await view("route", {"prefix": prefijo})

    @server.tool(name="bgp__emitir_alerta", description="Registra y difunde una alerta de desvío de rutas.")
    async def bgp_emitir_alerta(prefijo: str, origen: int) -> str:
        if ctx is not None:
            await ctx.store.create_document(
                kind="alerta_bgp",
                title=f"Desvío de {prefijo} por AS{origen}",
                body=f"{prefijo} anunciado desde AS{origen}.",
                agent="red",
                status="emitida",
                trace=None,
            )
        return dumps({"ok": True, "detail": f"Alerta de desvío de {prefijo} (AS{origen}) emitida."})

    @server.tool(
        name="bgp__revertir_anuncio",
        description="Retira el anuncio desviado de un prefijo propio. Es un "
        "cambio de enrutamiento: se prueba en el gemelo y requiere aprobación.",
    )
    async def bgp_revertir_anuncio(prefijo: str) -> str:
        return await act("revertir_anuncio", {"prefix": prefijo})
