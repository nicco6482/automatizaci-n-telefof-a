"""Generador determinista de la red: misma semilla, misma ciudad."""

from __future__ import annotations

import random
from datetime import UTC, datetime

from simulator.models import (
    Cell,
    EnterpriseCustomer,
    Link,
    LinkRole,
    LinkStatus,
    NetworkState,
    Node,
    NodeType,
    Ont,
    Route,
    Zone,
    ZoneLand,
)

SIM_START = datetime(2026, 10, 12, 5, 0, tzinfo=UTC)

ZONES: list[Zone] = [
    Zone(id="CEN", name="Centro"),
    Zone(id="TRI", name="Triana"),
    Zone(id="CAR", name="La Cartuja"),
    Zone(id="MAC", name="Macarena"),
    Zone(id="NER", name="Nervión"),
    Zone(id="EST", name="Este"),
    Zone(id="REM", name="Los Remedios"),
    Zone(id="SUR", name="Sur"),
]
# Zona vecina a la que va el enlace de respaldo de cada nodo de acceso.
NEIGHBOUR = {
    "CEN": "TRI",
    "TRI": "REM",
    "CAR": "MAC",
    "MAC": "CEN",
    "NER": "CEN",
    "EST": "NER",
    "REM": "TRI",
    "SUR": "NER",
}
VENDORS = {"Fabricante A": ["7.2.1", "7.3.0"], "Fabricante B": ["21.4", "22.1"], "Fabricante C": ["5.8.2", "6.0.1"]}
TOTAL_FTTH = 20_000
N_CELLS = 300
N_ENTERPRISES = 200
ACCESS_PER_ZONE = 5

_NAME_A = ["Talleres", "Cerámicas", "Logística", "Clínica", "Hotel", "Bodegas", "Consultora", "Imprenta", "Academia"]
_NAME_B = ["del Sur", "Alameda", "Puerta Real", "Altozano", "Guadaíra", "Aljarafe", "San Bernardo", "Arenal"]
_SERVICES = ["Fibra dedicada 1 Gbps", "VPN MPLS", "SD-WAN", "Internet 10 Gbps"]
_SLAS = [(99.9, 8), (99.95, 4), (99.99, 2)]


def build_network(seed: int) -> NetworkState:
    rng = random.Random(seed)
    nodes: dict[str, Node] = {}
    links: dict[str, Link] = {}

    def add_node(node_id: str, node_type: NodeType, zone: str) -> Node:
        vendor = rng.choice(list(VENDORS))
        node = Node(id=node_id, type=node_type, zone=zone, vendor=vendor, firmware=rng.choice(VENDORS[vendor]))
        nodes[node_id] = node
        return node

    def add_link(a: str, b: str, role: LinkRole, capacity: int) -> Link:
        link_id = f"L{len(links) + 1:03d}"
        status = LinkStatus.RESERVA if role == LinkRole.RESPALDO else LinkStatus.ACTIVO
        link = Link(id=link_id, a=a, b=b, role=role, capacity_gbps=capacity, status=status)
        links[link_id] = link
        return link

    add_node("CORE-1", NodeType.CORE, "CEN")
    add_node("CORE-2", NodeType.CORE, "CEN")
    add_link("CORE-1", "CORE-2", LinkRole.TRONCAL, 400)
    for zone in ZONES:
        add_node(f"AGG-{zone.id}", NodeType.AGG, zone.id)
        add_link(f"AGG-{zone.id}", "CORE-1", LinkRole.TRONCAL, 100)
        add_link(f"AGG-{zone.id}", "CORE-2", LinkRole.TRONCAL, 100)

    access: list[Node] = []
    for zone in ZONES:
        for i in range(1, ACCESS_PER_ZONE + 1):
            node = add_node(f"ACC-{zone.id}-{i}", NodeType.ACC, zone.id)
            node.primary_link = add_link(node.id, f"AGG-{zone.id}", LinkRole.PRINCIPAL, 10).id
            if rng.random() < 0.72:
                node.backup_link = add_link(node.id, f"AGG-{NEIGHBOUR[zone.id]}", LinkRole.RESPALDO, 10).id
            access.append(node)

    weights = [0.25 + rng.random() * 1.75 for _ in access]
    total_w = sum(weights)
    left = TOTAL_FTTH
    for i, node in enumerate(access):
        node.ftth_clients = left if i == len(access) - 1 else round(TOTAL_FTTH * weights[i] / total_w)
        left -= node.ftth_clients

    cells: dict[str, Cell] = {}
    per_zone: dict[str, int] = {}
    for i in range(N_CELLS):
        zone = ZONES[i % len(ZONES)]
        per_zone[zone.id] = per_zone.get(zone.id, 0) + 1
        carriers = rng.randint(2, 4)
        cell = Cell(
            id=f"CEL-{zone.id}-{per_zone[zone.id]:03d}",
            zone=zone.id,
            node=rng.choice([n.id for n in access if n.zone == zone.id]),
            tech="5G" if rng.random() < 0.4 else "4G",
            carriers=carriers,
            carriers_on=carriers,
            peak_users=rng.randint(300, 1500),
            sinr_db=round(12 + rng.random() * 8, 1),
            tilt_deg=rng.randint(2, 7),
            power_dbm=rng.randint(40, 45),
        )
        cells[cell.id] = cell

    enterprises: dict[str, EnterpriseCustomer] = {}
    for i in range(N_ENTERPRISES):
        node = rng.choice(access)
        sla, hours = rng.choice(_SLAS)
        customer = EnterpriseCustomer(
            id=f"EMP-{i + 1:03d}",
            name=f"{rng.choice(_NAME_A)} {rng.choice(_NAME_B)} {'S.L.' if rng.random() < 0.7 else 'S.A.'}",
            zone=node.zone,
            node=node.id,
            service=rng.choice(_SERVICES),
            sla_pct=sla,
            response_hours=hours,
            prefix=f"198.51.100.{i}/32",
        )
        enterprises[customer.id] = customer

    state = NetworkState(
        seed=seed, now=SIM_START, zones=ZONES, nodes=nodes, links=links, cells=cells, enterprises=enterprises
    )
    _enrich(state, random.Random(seed + 101))
    return state


TEMPLATES = {NodeType.CORE: "nucleo-v1", NodeType.AGG: "agregacion-v2", NodeType.ACC: "acceso-estandar-v4"}
DRIFTS = ["servidor NTP puesto a mano", "ACL temporal any-any olvidada", "MTU 1500 en vez de 9000"]


def _enrich(st: NetworkState, rng: random.Random) -> None:
    """Datos de las Fases 2+ con su propio generador, para no cambiar la red de las fases anteriores."""
    for node in st.nodes.values():
        node.config_template = TEMPLATES[node.type]
    for node in rng.sample([n for n in st.nodes.values() if n.type != NodeType.CORE], 3):
        node.config_drift = [rng.choice(DRIFTS)]
    for link in st.links.values():
        link.growth_pct_week = round(0.4 + rng.random() * 2.6, 2)
    by_zone: dict[str, list[Cell]] = {}
    for cell in st.cells.values():
        by_zone.setdefault(cell.zone, []).append(cell)
    for cells in by_zone.values():
        for i, cell in enumerate(cells):
            cell.neighbors = [cells[(i + d) % len(cells)].id for d in (-2, -1, 1, 2)]
            cell.handover_fail_pct = round(0.3 + rng.random() * 0.7, 2)
            if rng.random() < 0.06:
                cell.missing_neighbors = [cell.neighbors.pop(rng.randrange(len(cell.neighbors)))]
                cell.handover_fail_pct = round(4 + rng.random() * 4, 2)
    access = [n for n in st.nodes.values() if n.type == NodeType.ACC]
    for i in range(60):
        node = rng.choice(access)
        degrading = i < 5
        ont = Ont(
            id=f"ONT-{node.id[4:]}-{i + 1:04d}",
            node=node.id,
            zone=node.zone,
            customer=f"Cliente FTTH n.º {10000 + i * 137}",
            power_dbm=round(-24.6 + rng.random() * 0.3, 2) if degrading else round(-23 + rng.random() * 5, 2),
            trend_db_day=round(-0.12 - rng.random() * 0.06, 3) if degrading else round(-0.01 + rng.random() * 0.02, 3),
        )
        st.onts[ont.id] = ont
    st.routes = {p: Route(prefix=p, origin_as=64496, expected_as=64496) for p in ("203.0.113.0/24", "198.51.100.0/24")}
    for zone in ZONES:
        homes = rng.randint(6000, 22000)
        st.land[zone.id] = ZoneLand(
            zone=zone.id,
            buildings=homes // rng.randint(18, 40),
            homes=homes,
            homes_passed_pct=round(55 + rng.random() * 40, 1),
            ducts_km=round(20 + rng.random() * 60, 1),
        )
