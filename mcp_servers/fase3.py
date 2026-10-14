"""Servidores y herramientas MCP de las Fases 3 y 4: empresas, planificación, seguridad y gestión."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from mcp.server.mcpserver import MCPServer
from sqlalchemy import func, select

from core.audit import AuditLog
from core.db import AgentStateRow, ApprovalRow
from mcp_servers.context import McpContext, dumps
from simulator.engine import UnknownTarget
from simulator.fase3 import PRODUCTS
from simulator.port import SimulatorPort

PROCEDURES = {
    "caida_enlace": "RB-01 Conmutación a respaldo",
    "tarjeta": "RB-02 Reinicio de tarjeta",
    "energia": "PR-07 Fallos de alimentación por zona",
}


async def _view(ctx: McpContext, name: str, args: dict[str, Any]) -> Any:
    return await ctx.sim.view(name, args)


async def _deliver(
    ctx: McpContext, *, agent: str, kind: str, title: str, body: str, assignee: str, trace: str | None = None
) -> dict[str, Any]:
    """Borrador para una persona: documento en estado «borrador» y tarea abierta. Solo una persona lo cierra."""
    doc = await ctx.store.create_document(
        kind=kind, title=title, body=body, agent=agent, status="borrador", trace=trace
    )
    task = await ctx.store.create_task(
        agent=agent,
        kind="revisar_borrador",
        title=f"Revisar: {title}",
        detail=body,
        ref=doc.id,
        assignee=assignee,
        trace=trace,
    )
    return {"ok": True, "documento": doc.id, "tarea": task.id, "para": assignee}


# ================================================================ Fase 3
def build_catalogo_server(ctx: McpContext) -> MCPServer:
    server = MCPServer("catalogo", instructions="Catálogo de productos para empresas (precios ficticios).")

    @server.tool(name="productos", description="Productos de empresa con su precio mensual por sede.")
    async def productos() -> str:
        return dumps([{"producto": k, "eur_mes_por_sede": v} for k, v in PRODUCTS.items()])

    @server.tool(name="precios", description="Precio mensual por sede de un producto.")
    async def precios(servicio: str) -> str:
        if servicio not in PRODUCTS:
            return dumps({"error": f"producto desconocido: {servicio}", "productos": sorted(PRODUCTS)})
        return dumps({"producto": servicio, "eur_mes_por_sede": PRODUCTS[servicio]})

    @server.tool(
        name="enviar_oferta",
        description="Envía la oferta al cliente. Compromete a la empresa: requiere aprobación de una persona.",
    )
    async def enviar_oferta(cliente: str, servicio: str, sedes: int, importe_mensual: int) -> str:
        doc = await ctx.store.create_document(
            kind="oferta",
            title=f"Oferta {servicio} para {cliente}",
            body=f"{sedes} sedes, {importe_mensual} €/mes.",
            agent="catalogo",
            status="enviada",
            trace=None,
        )
        return dumps({"ok": True, "documento": doc.id, "detail": f"Oferta {doc.id} enviada a {cliente} (simulado)."})

    return server


def build_mercado_server(ctx: McpContext) -> MCPServer:
    server = MCPServer(
        "mercado_sim", instructions="Estudio de mercado sintético: cobertura y velocidad de la competencia."
    )

    @server.tool(name="cobertura", description="Cobertura y velocidad propias y de la competencia por zona.")
    async def cobertura(zona: str | None = None) -> str:
        return dumps(await _view(ctx, "market", {"zone": zona}))

    @server.tool(name="comparativa", description="Comparativa de todas las zonas, ordenada por desventaja.")
    async def comparativa() -> str:
        rows = await _view(ctx, "market", {})
        for r in rows:
            r["desventaja_cobertura"] = round(r["rival_coverage_pct"] - r["our_coverage_pct"], 1)
            r["desventaja_velocidad"] = r["rival_speed_mbps"] - r["our_speed_mbps"]
        return dumps(sorted(rows, key=lambda r: -r["desventaja_cobertura"]))

    return server


def build_finanzas_server(ctx: McpContext) -> MCPServer:
    server = MCPServer("finanzas_sim", instructions="Modelo financiero sintético de despliegues.")

    @server.tool(name="modelo", description="Inversión, ingresos y meses de retorno de N emplazamientos en una zona.")
    async def modelo(zona: str, emplazamientos: int) -> str:
        try:
            return dumps(await _view(ctx, "finance", {"zone": zona, "sites": emplazamientos}))
        except UnknownTarget as exc:
            return dumps({"error": str(exc)})

    return server


def register_contratos3(server: MCPServer, ctx: McpContext) -> None:
    @server.tool(name="clientes", description="Clientes empresa con su servicio y SLA.")
    async def clientes() -> str:
        return dumps(await _view(ctx, "customers", {}))

    @server.tool(name="disponibilidad", description="Disponibilidad del mes por cliente empresa, según los tickets.")
    async def disponibilidad() -> str:
        minutes: dict[str, int] = {}
        for t in await ctx.store.tickets(limit=1000):
            end = t.closed_at or t.created_at + timedelta(hours=4)
            for e in t.enterprises:
                minutes[e] = minutes.get(e, 0) + int((end - t.created_at).total_seconds() // 60)
        out = []
        for c in await _view(ctx, "customers", {}):
            down = minutes.get(c["id"], 0)
            avail = round(100 - 100 * down / (30 * 24 * 60), 3)
            out.append(
                {
                    "id": c["id"],
                    "nombre": c["nombre"],
                    "sla": c["sla"],
                    "disponibilidad": avail,
                    "cumple": avail >= c["sla"],
                }
            )
        return dumps(out)

    @server.tool(name="enviar_informes", description="Envía a cada cliente empresa su informe mensual.")
    async def enviar_informes(mes: str, resumen: str) -> str:
        doc = await ctx.store.create_document(
            kind="informe_mensual",
            title=f"Informes mensuales {mes}",
            body=resumen,
            agent="contratos",
            status="enviado",
            trace=None,
        )
        return dumps({"ok": True, "documento": doc.id, "detail": f"Informes de {mes} enviados (simulado)."})

    @server.tool(
        name="alquiler", description="Contrato de alquiler de un emplazamiento: propietario, renta y vencimiento."
    )
    async def alquiler(emplazamiento: str) -> str:
        try:
            return dumps(await _view(ctx, "site", {"site": emplazamiento}))
        except UnknownTarget as exc:
            return dumps({"error": str(exc)})

    @server.tool(
        name="entregar_borrador_renovacion",
        description="Deja a la persona de patrimonio el borrador de "
        "renovación de un alquiler. La negociación y la firma son suyas.",
    )
    async def entregar_borrador_renovacion(emplazamiento: str, propuesta_eur: int, resumen: str) -> str:
        return dumps(
            await _deliver(
                ctx,
                agent="33_negociador_emplazamientos",
                kind="borrador_renovacion",
                title=f"Renovación de {emplazamiento} a {propuesta_eur} €/mes",
                body=resumen,
                assignee="Gestor de patrimonio",
            )
        )


def register_documentos3(server: MCPServer, ctx: McpContext) -> None:
    @server.tool(name="pliego", description="Requisitos técnicos extraídos de un pliego de licitación.")
    async def pliego(lote: str) -> str:
        reqs = [
            {"id": f"RT-{i:02d}", "requisito": r, "cumplimos": ok}
            for i, (r, ok) in enumerate(
                [
                    ("Disponibilidad 99,95 % por sede", True),
                    ("Doble acometida en sedes críticas", True),
                    ("SD-WAN con gestión centralizada", True),
                    ("Tiempo de respuesta 4 h", True),
                    ("Cifrado de extremo a extremo", True),
                    ("Centro de operaciones 24x7", True),
                    ("Fibra hasta 64 sedes en 3 meses", False),
                    ("Certificación de seguridad del proveedor", True),
                ],
                1,
            )
        ]
        return dumps({"lote": lote, "paginas": 312, "requisitos": reqs})

    @server.tool(
        name="presentar_oferta_tecnica",
        description="Presenta la oferta técnica a la licitación. Compromete "
        "a la empresa: requiere aprobación de una persona.",
    )
    async def presentar_oferta_tecnica(lote: str, resumen: str, requisitos_cumplidos: int) -> str:
        doc = await ctx.store.create_document(
            kind="oferta_tecnica",
            title=f"Oferta técnica {lote}",
            body=resumen,
            agent="documentos",
            status="presentada",
            trace=None,
        )
        return dumps(
            {
                "ok": True,
                "documento": doc.id,
                "detail": f"Oferta técnica {doc.id} presentada ({requisitos_cumplidos} requisitos cumplidos).",
            }
        )

    @server.tool(
        name="entregar_borrador",
        description="Deja un borrador (proyecto, informe…) a la persona que debe "
        "revisarlo y firmarlo. El agente no lo cierra.",
    )
    async def entregar_borrador(tipo: str, titulo: str, contenido: str, responsable: str) -> str:
        agent = {"proyecto": "34_proyectista", "informe_regulatorio": "38_cumplidor"}.get(tipo, "documentos")
        return dumps(
            await _deliver(
                ctx, agent=agent, kind=f"borrador_{tipo}", title=titulo, body=contenido, assignee=responsable
            )
        )

    @server.tool(name="buscar_procedimiento", description="Procedimiento vigente para un tipo de incidencia.")
    async def buscar_procedimiento(tipo: str) -> str:
        docs = [d for d in await ctx.store.documents(kind="procedimiento") if tipo in d.body]
        return dumps(
            {"procedimiento": PROCEDURES.get(tipo, "Procedimiento general de incidencias"), "versiones": len(docs) + 1}
        )

    @server.tool(name="publicar_procedimiento", description="Publica una versión revisada de un procedimiento interno.")
    async def publicar_procedimiento(titulo: str, cambios: str, tipo: str) -> str:
        doc = await ctx.store.create_document(
            kind="procedimiento",
            title=titulo,
            body=f"{tipo}: {cambios}",
            agent="documentos",
            status="publicado",
            trace=None,
        )
        return dumps({"ok": True, "documento": doc.id})


def register_inventario3(server: MCPServer, ctx: McpContext) -> None:
    @server.tool(name="puertos", description="Puertos y VLAN libres de un nodo de acceso.")
    async def puertos(nodo: str) -> str:
        try:
            return dumps(await _view(ctx, "ports", {"node": nodo}))
        except UnknownTarget as exc:
            return dumps({"error": str(exc)})


def register_red3(server: MCPServer, port: SimulatorPort) -> None:
    async def act(action: str, args: dict[str, Any]) -> str:
        try:
            return (await port.act(action, args)).model_dump_json()
        except UnknownTarget as exc:
            return dumps({"ok": False, "detail": str(exc)})

    @server.tool(
        name="config__alta_servicio",
        description="Da de alta un circuito de empresa en un nodo y una VLAN. "
        "Es un cambio de configuración: se prueba en el gemelo y requiere aprobación.",
    )
    async def config_alta_servicio(cliente: str, servicio: str, nodo: str, vlan: int) -> str:
        return await act("alta_servicio", {"customer": cliente, "service": servicio, "node": nodo, "vlan": vlan})

    @server.tool(name="trafico__zonas", description="Carga pico y celdas 5G por zona, de más a menos cargada.")
    async def trafico_zonas() -> str:
        return dumps(await port.view("zone_traffic", {}))

    @server.tool(name="trafico__flujos", description="Flujos de tráfico hacia un destino: si hay ataque y de qué tipo.")
    async def trafico_flujos(destino: str) -> str:
        return dumps(await port.view("flows", {"target": destino}))

    @server.tool(
        name="filtros__aplicar_filtro_temporal",
        description="Filtro de limpieza anti-DDoS para un destino; caduca solo en 2 h. Reversible.",
    )
    async def filtros_aplicar(destino: str) -> str:
        return await act("filtro_temporal", {"target": destino})


# ================================================================ Fase 4
def build_auditoria_server(ctx: McpContext) -> MCPServer:
    server = MCPServer("auditoria", instructions="Lectura de la auditoría para informes regulatorios.")

    @server.tool(name="resumen", description="Resumen de la auditoría: registros, acciones, bloqueos y aprobaciones.")
    async def resumen() -> str:
        rows = await AuditLog(ctx.store.db).list(limit=100_000)
        steps: dict[str, int] = {}
        for r in rows:
            steps[r.step] = steps.get(r.step, 0) + 1
        executed = sum(1 for r in rows if r.step == "accion" and r.decision.startswith("ejecutada"))
        return dumps(
            {
                "registros": len(rows),
                "por_paso": steps,
                "acciones_ejecutadas": executed,
                "bloqueos": steps.get("bloqueo", 0),
                "decisiones_humanas": sum(1 for r in rows if r.approved_by),
            }
        )

    return server


def build_panel_server(ctx: McpContext) -> MCPServer:
    server = MCPServer("panel", instructions="Estado del sistema para el Director de orquesta (solo lectura).")

    @server.tool(
        name="resumen", description="Tickets abiertos, aprobaciones pendientes, tareas humanas y agentes en pausa."
    )
    async def resumen() -> str:
        async with ctx.store.db.session() as s:
            pending = int(
                await s.scalar(select(func.count()).select_from(ApprovalRow).where(ApprovalRow.status == "pendiente"))
                or 0
            )
            paused = [r.agent for r in (await s.scalars(select(AgentStateRow).where(AgentStateRow.paused))).all()]
        tickets = await ctx.store.tickets(status="abiertos")
        tasks = await ctx.store.tasks(status="abierta")
        pages = await ctx.store.pages(status="abierto")
        return dumps(
            {
                "tickets_abiertos": [
                    {"id": t.id, "prioridad": t.priority, "diagnostico": t.diagnosis} for t in tickets
                ],
                "aprobaciones_pendientes": pending,
                "tareas_humanas": len(tasks),
                "avisos_guardia": len(pages),
                "agentes_en_pausa": paused,
            }
        )

    @server.tool(name="entregar_resumen", description="Entrega a dirección el resumen y las prioridades del día.")
    async def entregar_resumen(resumen: str) -> str:
        return dumps(
            await _deliver(
                ctx,
                agent="40_director_orquesta",
                kind="resumen_direccion",
                title="Resumen diario a dirección",
                body=resumen,
                assignee="Dirección técnica",
            )
        )

    return server
