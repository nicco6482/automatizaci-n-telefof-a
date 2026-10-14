"""Eventos de negocio que en una operadora vendrían de otros sistemas (CRM, calendario, fabricantes, campo).

Se generan con datos ficticios y deterministas a partir de un contador, para que el panel y los escenarios
puedan lanzarlos. Cada uno lleva su propia traza para seguirlo en la auditoría.
"""

from __future__ import annotations

from typing import Any

from mcp_servers.context import McpContext

ZONES = ["CEN", "TRI", "CAR", "MAC", "NER", "EST", "REM", "SUR"]
VENDORS = ["Fabricante A", "Fabricante B", "Fabricante C"]
TOPICS = {
    "measurement.uploaded": "Mediciones de cobertura subidas",
    "project.requested": "Proyecto de despliegue de fibra",
    "design.approved": "Diseño de fibra aprobado",
    "workorder.created": "Orden de trabajo creada",
    "config.requested": "Petición de configuración",
    "firmware.released": "Firmware nuevo de un fabricante",
    "event.scheduled": "Evento especial programado (concierto, feria)",
    "customer.fault": "Cliente FTTH llama por avería",
    "route.changed": "Aviso del colector BGP",
}
_counter = {"n": 0}


class UnknownTopic(ValueError):
    pass


async def publish_business(ctx: McpContext, topic: str, overrides: dict[str, Any] | None = None) -> str:
    """Publica el evento con un payload realista y devuelve su traza."""
    _counter["n"] += 1
    n = _counter["n"]
    o = overrides or {}
    trace = f"NEG-{n:04d}"
    zone = str(o.get("zona") or o.get("zone") or ZONES[n % len(ZONES)])
    now = await ctx.sim.now()
    if topic == "measurement.uploaded":
        payload: dict[str, Any] = {"campana": f"MED-{zone}-{n:03d}", "zona": zone}
    elif topic in ("project.requested", "design.approved"):
        payload = {
            "proyecto": f"PRY-{zone}-{100 + n}",
            "zona": zone,
            "viviendas": int(o.get("viviendas", 1200 + 37 * n)),
        }
    elif topic == "workorder.created":
        wo = await ctx.store.create_workorder(
            kind=str(o.get("kind", "Instalación FTTH")),
            zone=zone,
            node=o.get("node"),
            ont=o.get("ont"),
            detail=str(o.get("detail", "Alta nueva")),
            trace=trace,
        )
        payload = {"ot": wo.id, "kind": wo.kind, "zone": wo.zone, "node": wo.node, "ont": wo.ont}
    elif topic == "config.requested":
        payload = {
            "nodo": str(o.get("nodo", f"ACC-{zone}-1")),
            "plantilla": str(o.get("plantilla", "acceso-estandar-v4")),
            "motivo": str(o.get("motivo", "Volver al estándar tras la auditoría")),
        }
    elif topic == "firmware.released":
        payload = {
            "fabricante": str(o.get("fabricante", VENDORS[n % 3])),
            "version": str(o.get("version", f"{9 + n}.0.0")),
            "criticidad": str(o.get("criticidad", "alta")),
            "at": now.isoformat(),
        }
    elif topic == "customer.fault":
        onts = await ctx.sim.view("onts", {"limit": 60})
        healthy = onts[-1]
        payload = {"ont": healthy["id"], "node": healthy["node"], "power_dbm": healthy["power_dbm"]}
    elif topic == "route.changed":
        route = await ctx.sim.view("route", {"prefix": str(o.get("prefix", "198.51.100.0/24"))})
        payload = {"prefix": route["prefix"], "origin_as": route["origin_as"], "expected_as": route["expected_as"]}
    elif topic == "event.scheduled":
        event = await ctx.sim.schedule_event(
            zone,
            str(o.get("name", f"Concierto en {zone}")),
            int(o.get("hours_ahead", 3)),
            int(o.get("duration", 5)),
            int(o.get("attendance", 45000)),
        )
        return str(event["id"])  # el simulador publica el evento con su propia traza
    else:
        raise UnknownTopic(topic)
    if topic not in ("workorder.created", "customer.fault", "route.changed"):
        payload.update(o)
    await ctx.emit(topic, payload, trace)
    return trace
