"""Servidores MCP de la Fase 2: eventos, mediciones, GIS, catastro, documentos, órdenes, fotos, plantillas y gemelo."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from mcp_servers.context import McpContext, dumps
from simulator.engine import UnknownTarget

TEMPLATES = {
    "acceso-estandar-v4": ["hostname {nodo}", "ntp server 10.0.0.1", "mtu 9000", "acl gestion-v3", "qos acceso-v2"],
    "agregacion-v2": ["hostname {nodo}", "ntp server 10.0.0.1", "mtu 9000", "acl gestion-v3", "bfd 50ms"],
    "nucleo-v1": ["hostname {nodo}", "ntp server 10.0.0.1", "mtu 9000", "acl gestion-v3", "bgp as 64496"],
}
CONTRACTORS = {
    "Contrata Norte (ficticia)": ["CAR", "MAC", "EST"],
    "Instalaciones Guadaíra (ficticia)": ["SUR", "NER", "CEN"],
    "Redes Aljarafe (ficticia)": ["TRI", "REM", "CEN"],
}
DOC_TEMPLATES = {
    "licencia de obra": "Solicitud de licencia de obra menor para canalización de telecomunicaciones: memoria, "
    "planos de trazado, plazo, reposición de pavimento y seguro de responsabilidad civil.",
}


async def _view(ctx: McpContext, name: str, args: dict[str, Any]) -> Any:
    return await ctx.sim.view(name, args)


def build_eventos_server(ctx: McpContext) -> MCPServer:
    server = MCPServer("eventos", instructions="Calendario de eventos especiales de la ciudad (simulado).")

    @server.tool(name="calendario", description="Eventos especiales próximos o en curso: zona, horas y asistentes.")
    async def calendario() -> str:
        return dumps(await _view(ctx, "events", {}))

    return server


def build_mediciones_server(ctx: McpContext) -> MCPServer:
    server = MCPServer("mediciones", instructions="Campañas de medición de cobertura (simuladas).")

    @server.tool(name="resultados", description="Resultados de la campaña de medición de una zona.")
    async def resultados(zona: str) -> str:
        try:
            return dumps(await _view(ctx, "coverage", {"zone": zona}))
        except UnknownTarget as exc:
            return dumps({"error": str(exc)})

    @server.tool(
        name="entregar_informe",
        description="Entrega el informe de cobertura a la persona de medidas, "
        "que decide si hay que volver a medir. El agente no cierra esta tarea.",
    )
    async def entregar_informe(campana: str, zona: str, resumen: str) -> str:
        doc = await ctx.store.create_document(
            kind="informe_cobertura",
            title=f"Informe de cobertura {campana}",
            body=resumen,
            agent="mediciones",
            status="borrador",
            trace=None,
        )
        task = await ctx.store.create_task(
            agent="14_analista_mediciones",
            kind="revisar_informe",
            title=f"Revisar informe de cobertura {campana} ({zona})",
            detail=resumen,
            ref=doc.id,
            assignee="Técnico de medidas",
            trace=None,
        )
        return dumps({"ok": True, "documento": doc.id, "tarea": task.id})

    return server


def build_gis_server(ctx: McpContext) -> MCPServer:
    server = MCPServer("gis", instructions="Capas GIS de la red de fibra (sintéticas).")

    @server.tool(name="capa", description="Capa GIS de una zona: canalización disponible y hogares pasados.")
    async def capa(zona: str) -> str:
        try:
            land = await _view(ctx, "land", {"zone": zona})
        except UnknownTarget as exc:
            return dumps({"error": str(exc)})
        return dumps(
            {"zona": zona, "canalizacion_km": land["ducts_km"], "hogares_pasados_pct": land["homes_passed_pct"]}
        )

    @server.tool(name="actualizar_capa", description="Registra en el GIS un tendido o una acometida terminada.")
    async def actualizar_capa(zona: str, detalle: str) -> str:
        doc = await ctx.store.create_document(
            kind="gis", title=f"Actualización GIS {zona}", body=detalle, agent="gis", status="aplicado", trace=None
        )
        return dumps({"ok": True, "registro": doc.id})

    return server


def build_catastro_server(ctx: McpContext) -> MCPServer:
    server = MCPServer("catastro_sim", instructions="Catastro sintético de la ciudad.")

    @server.tool(name="parcelas", description="Edificios y viviendas de una zona según el catastro.")
    async def parcelas(zona: str) -> str:
        try:
            land = await _view(ctx, "land", {"zone": zona})
        except UnknownTarget as exc:
            return dumps({"error": str(exc)})
        return dumps({"zona": zona, "edificios": land["buildings"], "viviendas": land["homes"]})

    return server


def build_documentos_server(ctx: McpContext) -> MCPServer:
    server = MCPServer("documentos", instructions="Gestor documental: plantillas, borradores y presentaciones.")

    @server.tool(name="plantilla", description="Plantilla de un tipo de documento (p. ej. «licencia de obra»).")
    async def plantilla(tipo: str) -> str:
        return dumps(
            {
                "tipo": tipo,
                "plantilla": DOC_TEMPLATES.get(tipo.lower(), "Plantilla genérica: objeto, alcance, plazos y anexos."),
            }
        )

    @server.tool(
        name="presentar_solicitud",
        description="Presenta una solicitud de obra al ayuntamiento. "
        "Sale de la empresa: requiere aprobación de una persona.",
    )
    async def presentar_solicitud(proyecto: str, ayuntamiento: str, resumen: str) -> str:
        doc = await ctx.store.create_document(
            kind="solicitud_obra",
            title=f"Solicitud de obra {proyecto}",
            body=f"{ayuntamiento}: {resumen}",
            agent="documentos",
            status="presentado",
            trace=None,
        )
        return dumps({"ok": True, "documento": doc.id, "detail": f"Solicitud {doc.id} presentada a {ayuntamiento}."})

    return server


def build_ordenes_server(ctx: McpContext) -> MCPServer:
    server = MCPServer("ordenes", instructions="Órdenes de trabajo de campo y contratas.")

    @server.tool(name="obtener", description="Orden de trabajo: tipo, zona, ONT o nodo y estado.")
    async def obtener(ot: str) -> str:
        wo = await ctx.store.workorder(ot)
        return dumps(wo.model_dump(mode="json") if wo else {"error": f"orden desconocida: {ot}"})

    @server.tool(name="contratas", description="Contratas que trabajan en una zona, con su carga y su nota de calidad.")
    async def contratas(zona: str) -> str:
        out = []
        for i, (name, zones) in enumerate(CONTRACTORS.items()):
            if zona in zones:
                out.append({"contrata": name, "ordenes_abiertas": 3 + i * 2, "nota_calidad": round(4.6 - i * 0.3, 1)})
        return dumps(out)

    @server.tool(name="asignar", description="Asigna una orden de trabajo a una contrata. Requiere aprobación.")
    async def asignar(ot: str, contrata: str) -> str:
        if contrata not in CONTRACTORS:
            return dumps({"ok": False, "detail": f"contrata desconocida: {contrata}"})
        try:
            wo = await ctx.store.update_workorder(ot, status="asignada", contractor=contrata)
        except LookupError:
            return dumps({"ok": False, "detail": f"orden desconocida: {ot}"})
        return dumps({"ok": True, "detail": f"{wo.id} asignada a {contrata}."})

    return server


def build_fotos_server(ctx: McpContext) -> MCPServer:
    server = MCPServer("fotos", instructions="Fotos que suben las contratas al terminar una orden.")

    @server.tool(name="listar", description="Fotos de una orden de trabajo y su metadato.")
    async def listar(ot: str) -> str:
        wo = await ctx.store.workorder(ot)
        if wo is None:
            return dumps({"error": f"orden desconocida: {ot}"})
        if wo.status == "creada":
            return dumps([])
        return dumps(
            [
                {"foto": f"{ot}-{i}.jpg", "tipo": t, "geolocalizada": True}
                for i, t in enumerate(["caja terminal", "fusión", "medida de potencia", "roseta"], 1)
            ]
        )

    @server.tool(
        name="solicitar_validacion",
        description="Deja a una persona la validación de las fotos de una "
        "orden. Al validarlas, la orden se cierra. El agente no cierra esta tarea.",
    )
    async def solicitar_validacion(ot: str, resumen: str) -> str:
        wo = await ctx.store.workorder(ot)
        if wo is None:
            return dumps({"ok": False, "detail": f"orden desconocida: {ot}"})
        task = await ctx.store.create_task(
            agent="18_coordinador_contratas",
            kind="validar_fotos",
            title=f"Validar fotos y cerrar {ot}",
            detail=resumen,
            ref=ot,
            assignee="Jefe de obra",
            trace=await ctx.store.workorder_trace(ot),
        )
        return dumps({"ok": True, "tarea": task.id})

    return server


def build_plantillas_server(ctx: McpContext) -> MCPServer:
    server = MCPServer("plantillas", instructions="Plantillas de configuración estándar.")

    @server.tool(name="obtener", description="Líneas de una plantilla de configuración.")
    async def obtener(plantilla: str) -> str:
        lines = TEMPLATES.get(plantilla)
        if lines is None:
            return dumps({"error": f"plantilla desconocida: {plantilla}", "disponibles": sorted(TEMPLATES)})
        return dumps({"plantilla": plantilla, "lineas": lines})

    @server.tool(name="comparar", description="Compara la configuración de un nodo con su plantilla estándar.")
    async def comparar(nodo: str) -> str:
        try:
            cfg = await _view(ctx, "node_config", {"node": nodo})
        except UnknownTarget as exc:
            return dumps({"error": str(exc)})
        return dumps({**cfg, "conforme": not cfg["desviaciones"]})

    return server


def build_gemelo_server(ctx: McpContext) -> MCPServer:
    server = MCPServer("gemelo", instructions="Gemelo digital: prueba configuraciones antes de aplicarlas.")

    @server.tool(name="probar_config", description="Prueba en el gemelo aplicar una plantilla a un nodo.")
    async def probar_config(nodo: str, plantilla: str) -> str:
        return (await ctx.sim.twin("aplicar_config", {"node": nodo, "template": plantilla})).model_dump_json()

    @server.tool(
        name="aplicar_config",
        description="Aplica en la red una plantilla probada en el gemelo. Es un "
        "cambio de configuración: el núcleo lo vuelve a probar y requiere aprobación.",
    )
    async def aplicar_config(nodo: str, plantilla: str) -> str:
        try:
            return (await ctx.sim.act("aplicar_config", {"node": nodo, "template": plantilla})).model_dump_json()
        except UnknownTarget as exc:
            return dumps({"ok": False, "detail": str(exc)})

    return server
