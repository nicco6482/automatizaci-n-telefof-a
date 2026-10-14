"""Modelos del estado de la red simulada. Todo es sintético."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class NodeType(StrEnum):
    CORE = "core"
    AGG = "agg"
    ACC = "acc"


class LinkRole(StrEnum):
    TRONCAL = "troncal"
    PRINCIPAL = "principal"
    RESPALDO = "respaldo"


class LinkStatus(StrEnum):
    ACTIVO = "activo"
    RESERVA = "reserva"
    CAIDO = "caido"


class Severity(StrEnum):
    CRITICA = "critica"
    MAYOR = "mayor"
    MENOR = "menor"


class FaultType(StrEnum):
    CAIDA_ENLACE = "caida_enlace"
    TARJETA_DEGRADADA = "tarjeta_degradada"
    INTERFERENCIA = "interferencia"
    ONT_DEGRADADA = "ont_degradada"
    DDOS = "ddos"
    DESVIO_RUTAS = "desvio_rutas"
    TORMENTA = "tormenta"
    CORTE_LUZ = "corte_luz"


class Zone(BaseModel):
    id: str
    name: str


class Node(BaseModel):
    id: str
    type: NodeType
    zone: str
    vendor: str
    firmware: str
    ftth_clients: int = 0
    primary_link: str | None = None
    backup_link: str | None = None
    card_ok: bool = True
    on_backup: bool = False
    powered: bool = True


class Link(BaseModel):
    id: str
    a: str
    b: str
    role: LinkRole
    capacity_gbps: int
    status: LinkStatus
    utilization: float = 0.0


class Cell(BaseModel):
    id: str
    zone: str
    node: str
    tech: str
    carriers: int
    carriers_on: int
    peak_users: int
    users: int = 0
    load: float = 0.0
    sinr_db: float
    interference: bool = False
    tilt_deg: int
    power_dbm: int


class EnterpriseCustomer(BaseModel):
    id: str
    name: str
    zone: str
    node: str
    service: str
    sla_pct: float
    response_hours: int
    prefix: str


class Alarm(BaseModel):
    id: str
    raised_at: datetime
    code: str
    severity: Severity
    zone: str
    node: str | None = None
    cell: str | None = None
    text: str = ""
    # Verdad de terreno para medir al Centinela; los agentes no la ven.
    real: bool = Field(default=True, exclude=True)
    incident: str | None = Field(default=None, exclude=True)


class Fault(BaseModel):
    id: str
    type: FaultType
    started_at: datetime
    zone: str
    node: str | None = None
    target: str | None = None
    active: bool = True
    mitigated: bool = False
    detail: str = ""


class KpiSample(BaseModel):
    at: datetime
    traffic_gbps: float
    alarms: int


class NetworkState(BaseModel):
    seed: int
    now: datetime
    zones: list[Zone]
    nodes: dict[str, Node]
    links: dict[str, Link]
    cells: dict[str, Cell]
    enterprises: dict[str, EnterpriseCustomer]
    faults: dict[str, Fault] = Field(default_factory=dict)
    alarms: list[Alarm] = Field(default_factory=list)
    kpis: list[KpiSample] = Field(default_factory=list)
    storms: list[str] = Field(default_factory=list)
    power_cuts: list[str] = Field(default_factory=list)

    def clients_on_node(self, node_id: str) -> int:
        return self.nodes[node_id].ftth_clients

    def node_has_service(self, node_id: str) -> bool:
        node = self.nodes[node_id]
        if not node.powered:
            return False
        if node.type != NodeType.ACC:
            return True
        up = [self.links[lid] for lid in (node.primary_link, node.backup_link) if lid]
        return any(link.status == LinkStatus.ACTIVO for link in up)
