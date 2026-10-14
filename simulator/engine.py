"""Motor del simulador: reloj de 15 minutos, tráfico, averías inyectables y acciones sobre la red.

El motor no conoce el bus: deja los eventos en `outbox` y quien lo aloja (el servicio) los publica.
"""

from __future__ import annotations

import math
import random
from datetime import datetime, timedelta
from typing import Any

from pydantic import BaseModel

from simulator.models import (
    Alarm,
    CentinelaStats,
    Fault,
    FaultType,
    KpiSample,
    LinkStatus,
    NetworkState,
    NodeType,
    Power,
    Severity,
    Weather,
)
from simulator.network import build_network

TICK = timedelta(minutes=15)
KPI_HISTORY = 96  # 24 h
ALARM_HISTORY = 500
NOISE_CODES = ["FLAP_1S", "TEMP_TRANSITORIA", "PUERTA_ABIERTA", "LOS_TRANSITORIO"]


class OutEvent(BaseModel):
    topic: str
    payload: dict[str, Any]
    incident: str | None = None


class ActionResult(BaseModel):
    ok: bool
    detail: str
    clients_affected: int = 0


class UnknownTarget(ValueError):
    pass


def diurnal_factor(now: datetime) -> float:
    hour = now.hour + now.minute / 60
    weekend = now.weekday() >= 5
    s = max(0.0, math.sin(math.pi * (hour - 6) / 18.5)) if hour >= 6 else 0.0
    return float((0.08 + 0.92 * s ** (1.1 if weekend else 1.4)) * (0.85 if weekend else 1.0))


class Simulator:
    def __init__(self, seed: int = 42, state: NetworkState | None = None) -> None:
        self.state = state if state is not None else build_network(seed)
        self.rng = random.Random(self.state.seed * 7919 + 13)
        self.outbox: list[OutEvent] = []
        self._alarm_seq = 0
        self._fault_seq = len(self.state.faults)
        self._refresh_traffic()

    # ---------- reloj ----------
    def advance(self, minutes: int) -> None:
        for _ in range(max(0, minutes) // 15):
            self.state.now += TICK
            self._refresh_traffic()
            self._noise()
            self.outbox.append(OutEvent(topic="cron.15min", payload={"at": self.state.now.isoformat()}))

    def drain(self) -> list[OutEvent]:
        events, self.outbox = self.outbox, []
        return events

    def _refresh_traffic(self) -> None:
        f = diurnal_factor(self.state.now)
        total = 0.0
        for cell in self.state.cells.values():
            up = self.state.node_has_service(cell.node)
            cell.users = round(cell.peak_users * f * (0.9 + self.rng.random() * 0.2)) if up else 0
            cell.load = min(1.2, cell.users / (cell.carriers_on * 420))
            total += cell.users * 0.0042
        for link in self.state.links.values():
            active = link.status == LinkStatus.ACTIVO
            link.utilization = round(min(0.99, f * 0.6 * (0.85 + self.rng.random() * 0.3)), 3) if active else 0.0
        alarms_last_tick = sum(1 for a in self.state.alarms if a.raised_at > self.state.now - TICK)
        self.state.kpis.append(KpiSample(at=self.state.now, traffic_gbps=round(total, 1), alarms=alarms_last_tick))
        del self.state.kpis[:-KPI_HISTORY]

    def _noise(self) -> None:
        if self.rng.random() < 0.55:
            for _ in range(self.rng.randint(1, 3)):
                cell = self.rng.choice(list(self.state.cells.values()))
                self._raise(
                    self.rng.choice(NOISE_CODES), Severity.MENOR, cell.zone, node=cell.node, cell=cell.id, real=False
                )

    # ---------- alarmas ----------
    def _raise(
        self,
        code: str,
        severity: Severity,
        zone: str,
        *,
        node: str | None = None,
        cell: str | None = None,
        text: str = "",
        real: bool = True,
        incident: str | None = None,
    ) -> Alarm:
        self._alarm_seq += 1
        alarm = Alarm(
            id=f"ALM-{self._alarm_seq:06d}",
            raised_at=self.state.now,
            code=code,
            severity=severity,
            zone=zone,
            node=node,
            cell=cell,
            text=text,
            real=real,
            incident=incident,
        )
        self.state.alarms.append(alarm)
        del self.state.alarms[:-ALARM_HISTORY]
        self.outbox.append(OutEvent(topic="alarm.raised", payload=alarm.model_dump(mode="json"), incident=incident))
        return alarm

    def alarm_truth(self, alarm_id: str) -> bool | None:
        """Solo para pruebas y métricas: ¿la alarma era real?"""
        return next((a.real for a in self.state.alarms if a.id == alarm_id), None)

    # ---------- averías ----------
    def inject(
        self,
        fault_type: FaultType,
        *,
        node: str | None = None,
        zone: str | None = None,
        with_backup: bool | None = None,
    ) -> Fault:
        self._fault_seq += 1
        fid = f"INC-{self._fault_seq:04d}"
        st = self.state
        access = [n for n in st.nodes.values() if n.type == NodeType.ACC and st.node_has_service(n.id)]

        if fault_type in (FaultType.CAIDA_ENLACE, FaultType.TARJETA_DEGRADADA, FaultType.ONT_DEGRADADA):
            if node is None:
                pool = [n for n in access if with_backup is None or bool(n.backup_link) == with_backup] or access
                node = self.rng.choice(pool).id
            if node not in st.nodes:
                raise UnknownTarget(node)
        target_node = st.nodes[node] if node else None
        fault = Fault(
            id=fid,
            type=fault_type,
            started_at=st.now,
            zone=zone or (target_node.zone if target_node else "CEN"),
            node=node,
        )

        if fault_type == FaultType.CAIDA_ENLACE and target_node is not None and target_node.primary_link:
            st.links[target_node.primary_link].status = LinkStatus.CAIDO
            cells = [c for c in st.cells.values() if c.node == target_node.id]
            fault.detail = (
                f"Caída de {target_node.primary_link} en {target_node.id} "
                f"({'con respaldo ' + target_node.backup_link if target_node.backup_link else 'sin respaldo'})."
            )
            self._raise(
                "LINK_DOWN",
                Severity.CRITICA,
                target_node.zone,
                node=target_node.id,
                incident=fid,
                text=f"{target_node.primary_link} {target_node.id}->AGG-{target_node.zone}",
            )
            for c in cells:
                self._raise("CELL_UNAVAILABLE", Severity.MAYOR, c.zone, node=target_node.id, cell=c.id, incident=fid)
        elif fault_type == FaultType.TARJETA_DEGRADADA and target_node is not None:
            target_node.card_ok = False
            fault.detail = f"Tarjeta de línea degradada en {target_node.id}: BER 3e-6."
            self._raise("CARD_BER_HIGH", Severity.MAYOR, target_node.zone, node=target_node.id, incident=fid)
            self._raise("CRC_ERRORS", Severity.MENOR, target_node.zone, node=target_node.id, incident=fid)
        elif fault_type == FaultType.ONT_DEGRADADA and target_node is not None:
            ont = f"ONT-{target_node.id[4:]}-{self.rng.randint(1, 999):04d}"
            fault.target = ont
            fault.detail = f"{ont} pierde potencia óptica (−26,8 dBm)."
            self.outbox.append(
                OutEvent(
                    topic="customer.fault",
                    incident=fid,
                    payload={"ont": ont, "node": target_node.id, "power_dbm": -26.8},
                )
            )
        elif fault_type == FaultType.INTERFERENCIA:
            z = fault.zone
            affected = [c for c in st.cells.values() if c.zone == z][: self.rng.randint(3, 6)]
            for c in affected:
                c.interference = True
                c.sinr_db = round(c.sinr_db - 8, 1)
            fault.target = ",".join(c.id for c in affected)
            fault.detail = f"Interferencia externa en {len(affected)} celdas de {z}."
        elif fault_type == FaultType.DDOS:
            customer = self.rng.choice(list(st.enterprises.values()))
            fault.zone, fault.target = customer.zone, customer.prefix
            fault.detail = f"Ataque volumétrico contra {customer.name} ({customer.prefix})."
            self.outbox.append(
                OutEvent(
                    topic="traffic.anomaly",
                    incident=fid,
                    payload={"target": customer.prefix, "customer": customer.id, "gbps": self.rng.randint(8, 40)},
                )
            )
        elif fault_type == FaultType.DESVIO_RUTAS:
            origin = self.rng.randint(64497, 64511)
            fault.target = "203.0.113.0/24"
            fault.detail = f"203.0.113.0/24 anunciado por AS{origin} (esperado AS64496)."
            self.outbox.append(
                OutEvent(
                    topic="route.changed",
                    incident=fid,
                    payload={"prefix": "203.0.113.0/24", "origin_as": origin, "expected_as": 64496},
                )
            )
        elif fault_type in (FaultType.TORMENTA, FaultType.CORTE_LUZ):
            z = fault.zone
            if fault_type == FaultType.TORMENTA:
                st.storms.append(z)
            st.power_cuts.append(z)
            for n in [n for n in st.nodes.values() if n.zone == z and n.type == NodeType.ACC][:2]:
                n.powered = False
                self._raise("MAINS_FAIL", Severity.MAYOR, z, node=n.id, incident=fid)
            self._raise("BATTERY_DISCHARGING", Severity.MAYOR, z, node=f"AGG-{z}", incident=fid)
            fault.detail = f"{'Tormenta y corte' if fault_type == FaultType.TORMENTA else 'Corte'} de luz en {z}."

        st.faults[fid] = fault
        self._refresh_traffic()
        return fault

    def repair(self, fault_id: str) -> None:
        fault = self.state.faults[fault_id]
        st = self.state
        if fault.node and fault.node in st.nodes:
            node = st.nodes[fault.node]
            if fault.type == FaultType.CAIDA_ENLACE and node.primary_link:
                st.links[node.primary_link].status = LinkStatus.ACTIVO
                if node.backup_link:
                    st.links[node.backup_link].status = LinkStatus.RESERVA
                node.on_backup = False
            if fault.type == FaultType.TARJETA_DEGRADADA:
                node.card_ok = True
        if fault.type in (FaultType.TORMENTA, FaultType.CORTE_LUZ):
            st.storms = [z for z in st.storms if z != fault.zone]
            st.power_cuts = [z for z in st.power_cuts if z != fault.zone]
            for n in st.nodes.values():
                if n.zone == fault.zone:
                    n.powered = True
        fault.active = False
        fault.resolved_at = st.now
        self._refresh_traffic()

    def repair_node(self, node_id: str) -> list[str]:
        """Un técnico en campo repara todo lo activo en un nodo (o la energía de su zona)."""
        if node_id not in self.state.nodes:
            raise UnknownTarget(node_id)
        zone = self.state.nodes[node_id].zone
        fixed = []
        for fault in list(self.state.faults.values()):
            touches = fault.node == node_id or (
                fault.type in (FaultType.TORMENTA, FaultType.CORTE_LUZ) and fault.zone == zone
            )
            if fault.active and touches:
                self.repair(fault.id)
                fixed.append(fault.id)
        return fixed

    # ---------- consultas ----------
    def alarm(self, alarm_id: str) -> Alarm | None:
        return next((a for a in self.state.alarms if a.id == alarm_id), None)

    def mark_discarded(self, alarm_id: str) -> None:
        if alarm_id not in self.state.discarded_alarms:
            self.state.discarded_alarms.append(alarm_id)

    def centinela_stats(self) -> CentinelaStats:
        discarded = set(self.state.discarded_alarms)
        false = [a for a in self.state.alarms if not a.real]
        real = [a for a in self.state.alarms if a.real]
        return CentinelaStats(
            false_total=len(false),
            false_discarded=sum(1 for a in false if a.id in discarded),
            real_total=len(real),
            real_discarded=sum(1 for a in real if a.id in discarded),
        )

    def weather(self, zone: str) -> Weather:
        storm = zone in self.state.storms
        return Weather(
            zone=zone,
            storm=storm,
            lightning_per_hour=38 if storm else 0,
            detail="Tormenta eléctrica activa" if storm else "Sin avisos meteorológicos",
        )

    def power(self, zone: str) -> Power:
        off = sorted(n.id for n in self.state.nodes.values() if n.zone == zone and not n.powered)
        outage = zone in self.state.power_cuts
        return Power(
            zone=zone,
            outage=outage,
            nodes_without_power=off,
            detail="Corte de suministro declarado por la distribuidora" if outage else "Suministro normal",
        )

    def impact(self, action: str, args: dict[str, Any]) -> int:
        """Clientes afectados por una acción, para el radio de impacto del núcleo."""
        node_id = args.get("node")
        if action in ("conmutar_respaldo", "reiniciar_tarjeta") and isinstance(node_id, str):
            if node_id not in self.state.nodes:
                raise UnknownTarget(node_id)
            return self.state.clients_on_node(node_id)
        if action == "reiniciar_ont":
            return 1
        return 0

    # ---------- acciones (las llama el ejecutor del núcleo) ----------
    def switch_to_backup(self, node_id: str) -> ActionResult:
        node = self.state.nodes.get(node_id)
        if node is None:
            raise UnknownTarget(node_id)
        if not node.backup_link:
            return ActionResult(ok=False, detail=f"{node_id} no tiene enlace de respaldo.")
        backup = self.state.links[node.backup_link]
        if backup.status == LinkStatus.CAIDO:
            return ActionResult(ok=False, detail=f"El respaldo {backup.id} también está caído.")
        backup.status = LinkStatus.ACTIVO
        node.on_backup = True
        for fault in self.state.faults.values():
            if fault.node == node_id and fault.type == FaultType.CAIDA_ENLACE and fault.active:
                fault.mitigated = True
                fault.resolved_at = self.state.now
        self._refresh_traffic()
        return ActionResult(
            ok=True,
            clients_affected=node.ftth_clients,
            detail=f"Tráfico de {node_id} por {backup.id}; {node.ftth_clients} clientes FTTH con servicio.",
        )

    def restart_card(self, node_id: str) -> ActionResult:
        node = self.state.nodes.get(node_id)
        if node is None:
            raise UnknownTarget(node_id)
        node.card_ok = True
        for fault in self.state.faults.values():
            if fault.node == node_id and fault.type == FaultType.TARJETA_DEGRADADA and fault.active:
                fault.active = False
                fault.resolved_at = self.state.now
        return ActionResult(
            ok=True, clients_affected=node.ftth_clients, detail=f"Tarjeta de {node_id} reiniciada en 94 s; BER 1e-12."
        )

    def fault_resolved(self, fault_id: str) -> bool:
        fault = self.state.faults.get(fault_id)
        return fault is not None and (not fault.active or fault.mitigated)
