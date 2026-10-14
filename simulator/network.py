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
    Zone,
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

    return NetworkState(
        seed=seed, now=SIM_START, zones=ZONES, nodes=nodes, links=links, cells=cells, enterprises=enterprises
    )
