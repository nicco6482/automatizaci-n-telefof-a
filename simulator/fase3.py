"""Datos, acciones y consultas de las Fases 3 y 4: emplazamientos, servicios de empresa, mercado, finanzas,
filtros anti-DDoS y flujos de tráfico. Se registran en los catálogos de `simulator.actions`."""

from __future__ import annotations

import math
import random
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from simulator.models import FaultType, MarketZone, NetworkState, NodeType, ServiceOrder, Site

if TYPE_CHECKING:
    from simulator.engine import ActionResult, Simulator

OWNERS = [
    "Comunidad de propietarios Alameda",
    "Comunidad de propietarios Altozano",
    "Inmobiliaria Puerta Real",
    "Comunidad de propietarios San Bernardo",
    "Hotel Arenal (ficticio)",
    "Colegio Guadaíra (ficticio)",
]
PRODUCTS = {
    "Fibra dedicada 1 Gbps": 690,
    "Internet 10 Gbps": 2450,
    "VPN MPLS": 340,
    "SD-WAN": 210,
    "Protección anti-DDoS": 180,
    "Red 5G privada": 3900,
}
SITE_CAPEX_EUR = 85_000
ARPU_EUR = 18.4


def enrich(st: NetworkState, rng: random.Random) -> None:
    for i in range(60):
        zone_id = st.zones[i % len(st.zones)].id
        st.sites[f"EMPL-{i + 1:03d}"] = Site(
            id=f"EMPL-{i + 1:03d}",
            zone=zone_id,
            owner=f"{rng.choice(OWNERS)} {1 + i}",
            rent_eur=600 + rng.randint(0, 1400),
            expires_at=st.now + timedelta(days=10 + rng.randint(0, 700)),
        )
    for node in st.nodes.values():
        if node.type == NodeType.ACC:
            node.vlans = sorted(rng.sample(range(100, 400), 12))
    for z in st.zones:
        ours = round(70 + rng.random() * 25, 1)
        st.market[z.id] = MarketZone(
            zone=z.id,
            our_coverage_pct=ours,
            rival_coverage_pct=round(ours + rng.uniform(-12, 12), 1),
            our_speed_mbps=round(180 + rng.random() * 120),
            rival_speed_mbps=round(170 + rng.random() * 130),
        )


# ---------------------------------------------------------------- acciones
def _result(ok: bool, detail: str, clients: int = 0) -> ActionResult:
    from simulator.engine import ActionResult

    return ActionResult(ok=ok, detail=detail, clients_affected=clients)


def alta_servicio(sim: Simulator, a: dict[str, Any]) -> ActionResult:
    node = sim.state.nodes.get(str(a["node"]))
    if node is None:
        from simulator.engine import UnknownTarget

        raise UnknownTarget(f"nodo desconocido: {a['node']}")
    vlan = int(a["vlan"])
    if vlan in node.vlans:
        return _result(False, f"La VLAN {vlan} ya está en uso en {node.id}.")
    node.vlans.append(vlan)
    order = ServiceOrder(
        id=f"SRV-{len(sim.state.services) + 1:04d}",
        customer=str(a["customer"]),
        service=str(a["service"]),
        node=node.id,
        vlan=vlan,
    )
    sim.state.services[order.id] = order
    return _result(True, f"{order.id}: {order.service} para {order.customer} en {node.id}, VLAN {vlan}.")


def filtro_temporal(sim: Simulator, a: dict[str, Any]) -> ActionResult:
    target = str(a["target"])
    sim.state.filters[target] = sim.state.now + timedelta(hours=2)
    for f in sim.state.faults.values():
        if f.type == FaultType.DDOS and f.target == target and f.active:
            f.active, f.mitigated, f.resolved_at = False, True, sim.state.now
    return _result(True, f"Filtro de limpieza para {target} activo 2 h; tráfico legítimo entregado: 99,2 %.", 1)


APPLY3 = {"alta_servicio": alta_servicio, "filtro_temporal": filtro_temporal}


def twin_check3(before: Simulator, after: Simulator, action: str, a: dict[str, Any]) -> str | None:
    if action == "alta_servicio":
        node = before.state.nodes.get(str(a["node"]))
        if node is not None and int(a["vlan"]) in node.vlans:
            return f"La VLAN {a['vlan']} ya está en uso en {node.id}: el servicio de otro cliente se caería."
        if node is not None and not node.backup_link and str(a.get("service", "")).startswith("Internet 10"):
            return f"{node.id} no tiene respaldo: no cumple el SLA de un acceso de 10 Gbps."
    return None


# ---------------------------------------------------------------- consultas
def v_sites_expiring(sim: Simulator, a: dict[str, Any]) -> Any:
    days = int(a.get("days", 60))
    limit = sim.state.now + timedelta(days=days)
    return [
        s.model_dump(mode="json")
        for s in sorted(sim.state.sites.values(), key=lambda s: s.expires_at)
        if s.expires_at <= limit
    ]


def v_site(sim: Simulator, a: dict[str, Any]) -> Any:
    site = sim.state.sites.get(str(a["site"]))
    if site is None:
        from simulator.engine import UnknownTarget

        raise UnknownTarget(f"emplazamiento desconocido: {a['site']}")
    days = (site.expires_at - sim.state.now).days
    return {**site.model_dump(mode="json"), "dias_para_vencer": days, "renta_mercado_eur": round(site.rent_eur * 0.92)}


def v_ports(sim: Simulator, a: dict[str, Any]) -> Any:
    node = sim.state.nodes.get(str(a["node"]))
    if node is None:
        from simulator.engine import UnknownTarget

        raise UnknownTarget(f"nodo desconocido: {a['node']}")
    free = [v for v in range(100, 400) if v not in node.vlans][:5]
    return {
        "nodo": node.id,
        "puertos_10g_libres": 3,
        "vlans_en_uso": node.vlans,
        "vlans_libres_sugeridas": free,
        "respaldo": bool(node.backup_link),
    }


def v_market(sim: Simulator, a: dict[str, Any]) -> Any:
    zones = [a["zone"]] if a.get("zone") else list(sim.state.market)
    return [sim.state.market[z].model_dump() for z in zones if z in sim.state.market]


def v_zone_traffic(sim: Simulator, a: dict[str, Any]) -> Any:
    out = []
    for z in sim.state.zones:
        cells = [c for c in sim.state.cells.values() if c.zone == z.id]
        peak = sum(c.peak_users for c in cells)
        cap = sum(c.carriers for c in cells) * 420
        out.append(
            {
                "zona": z.id,
                "nombre": z.name,
                "carga_pico_pct": round(100 * peak / cap),
                "celdas_5g": sum(1 for c in cells if c.tech == "5G"),
                "celdas": len(cells),
            }
        )
    return sorted(out, key=lambda x: -x["carga_pico_pct"])


def v_finance(sim: Simulator, a: dict[str, Any]) -> Any:
    zone, sites = str(a["zone"]), max(1, int(a.get("sites", 1)))
    m = sim.state.market.get(zone)
    land = sim.state.land.get(zone)
    if m is None or land is None:
        from simulator.engine import UnknownTarget

        raise UnknownTarget(f"zona desconocida: {zone}")
    capex = sites * SITE_CAPEX_EUR
    new_customers = round(land.homes * max(0.01, (m.rival_coverage_pct - m.our_coverage_pct + 15) / 100) * 0.08)
    monthly = round(new_customers * ARPU_EUR)
    payback = math.ceil(capex / monthly) if monthly else None
    return {
        "zona": zone,
        "emplazamientos": sites,
        "capex_eur": capex,
        "clientes_nuevos_estimados": new_customers,
        "ingresos_mensuales_eur": monthly,
        "retorno_meses": payback,
    }


def v_customers(sim: Simulator, a: dict[str, Any]) -> Any:
    return [
        {"id": e.id, "nombre": e.name, "servicio": e.service, "sla": e.sla_pct, "nodo": e.node}
        for e in sim.state.enterprises.values()
    ]


def v_flows(sim: Simulator, a: dict[str, Any]) -> Any:
    target = str(a["target"])
    attack = next(
        (f for f in sim.state.faults.values() if f.type == FaultType.DDOS and f.target == target and f.active), None
    )
    filt = sim.state.filters.get(target)
    return {
        "destino": target,
        "ataque": attack is not None,
        "gbps": 0 if attack is None else 22,
        "tipo": "UDP reflection (DNS/NTP)" if attack else "normal",
        "origenes": 18000 if attack else 40,
        "filtro_activo_hasta": filt.isoformat() if filt else None,
    }


VIEWS3 = {
    "sites_expiring": v_sites_expiring,
    "site": v_site,
    "ports": v_ports,
    "market": v_market,
    "zone_traffic": v_zone_traffic,
    "finance": v_finance,
    "customers": v_customers,
    "flows": v_flows,
}
