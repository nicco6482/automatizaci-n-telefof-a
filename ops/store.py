"""Acceso a los datos de operación. Lo usan los servidores MCP y el panel; nunca un agente directamente."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.db import Database, utcnow
from ops.db import AlarmGroupRow, ChangeRow, PageRow, TicketRow

GROUP_WINDOW = timedelta(minutes=30)
OPEN_TICKET = ("abierto", "escalado")


class AlarmGroup(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    key: str
    zone: str
    node: str | None
    alarm_ids: list[str]
    codes: list[str]
    status: str
    created_at: datetime


class Ticket(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    created_sim_at: datetime
    priority: str
    diagnosis: str
    zone: str
    node: str | None
    group_id: str | None
    codes: list[str]
    affected_ftth: int
    enterprises: list[str]
    status: str
    notes: list[dict[str, Any]]
    sla_alerted: bool
    closed_at: datetime | None


class Page(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    ticket: str | None
    person: str
    summary: str
    status: str
    closed_at: datetime | None
    closed_by: str | None
    resolution: str


class Change(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    node: str | None
    zone: str
    starts_at: datetime
    ends_at: datetime
    owner: str
    status: str


async def _next_id(s: AsyncSession, model: Any, prefix: str) -> str:
    n = int(await s.scalar(select(func.count()).select_from(model)) or 0)
    return f"{prefix}-{n + 1:04d}"


class OpsStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    # ---------- grupos de alarmas ----------
    async def group_alarm(
        self, alarm_id: str, code: str, key: str, zone: str, node: str | None, trace: str | None
    ) -> tuple[AlarmGroup, bool]:
        """Añade la alarma al grupo abierto con la misma clave o crea uno. Devuelve (grupo, creado)."""
        since = utcnow() - GROUP_WINDOW
        async with self.db.session() as s, s.begin():
            row = await s.scalar(
                select(AlarmGroupRow)
                .where(AlarmGroupRow.key == key, AlarmGroupRow.status != "cerrado", AlarmGroupRow.created_at >= since)
                .order_by(AlarmGroupRow.created_at.desc())
            )
            created = row is None
            if row is None:
                row = AlarmGroupRow(
                    id=await _next_id(s, AlarmGroupRow, "GRP"),
                    key=key,
                    zone=zone,
                    node=node,
                    trace=trace,
                    alarm_ids=[],
                    codes=[],
                )
                s.add(row)
            if alarm_id not in row.alarm_ids:
                row.alarm_ids = [*row.alarm_ids, alarm_id]
            if code not in row.codes:
                row.codes = [*row.codes, code]
            if row.trace is None and trace:
                row.trace = trace
            await s.flush()
            return AlarmGroup.model_validate(row), created

    async def group(self, group_id: str) -> AlarmGroup | None:
        async with self.db.session() as s:
            row = await s.get(AlarmGroupRow, group_id)
            return AlarmGroup.model_validate(row) if row else None

    async def group_trace(self, group_id: str) -> str | None:
        async with self.db.session() as s:
            row = await s.get(AlarmGroupRow, group_id)
            return row.trace if row else None

    # ---------- tickets ----------
    async def create_ticket(
        self,
        *,
        priority: str,
        diagnosis: str,
        zone: str,
        node: str | None,
        group_id: str | None,
        codes: list[str],
        affected_ftth: int,
        enterprises: list[str],
        sim_now: datetime,
        trace: str | None,
    ) -> Ticket:
        async with self.db.session() as s, s.begin():
            row = TicketRow(
                id=await _next_id(s, TicketRow, "TCK"),
                priority=priority,
                diagnosis=diagnosis,
                zone=zone,
                node=node,
                group_id=group_id,
                codes=codes,
                affected_ftth=affected_ftth,
                enterprises=enterprises,
                created_sim_at=sim_now,
                trace=trace,
                notes=[{"at": utcnow().isoformat(), "text": f"Abierto: {priority} · {diagnosis}"}],
            )
            s.add(row)
            await s.flush()
            if group_id:
                group = await s.get(AlarmGroupRow, group_id)
                if group:
                    group.status = "con ticket"
            return Ticket.model_validate(row)

    async def ticket(self, ticket_id: str) -> Ticket | None:
        async with self.db.session() as s:
            row = await s.get(TicketRow, ticket_id)
            return Ticket.model_validate(row) if row else None

    async def ticket_trace(self, ticket_id: str) -> str | None:
        async with self.db.session() as s:
            row = await s.get(TicketRow, ticket_id)
            return row.trace if row else None

    async def find_open_ticket(self, *, node: str | None = None, group_id: str | None = None) -> Ticket | None:
        q = select(TicketRow).where(TicketRow.status.in_(OPEN_TICKET)).order_by(TicketRow.created_at.desc())
        if group_id:
            q = q.where(TicketRow.group_id == group_id)
        elif node:
            q = q.where(TicketRow.node == node)
        else:
            return None
        async with self.db.session() as s:
            row = await s.scalar(q)
            return Ticket.model_validate(row) if row else None

    async def tickets(self, status: str | None = None, limit: int = 100) -> list[Ticket]:
        q = select(TicketRow).order_by(TicketRow.created_at.desc()).limit(limit)
        if status == "abiertos":
            q = q.where(TicketRow.status.in_(OPEN_TICKET))
        elif status:
            q = q.where(TicketRow.status == status)
        async with self.db.session() as s:
            return [Ticket.model_validate(r) for r in (await s.scalars(q)).all()]

    async def update_ticket(
        self, ticket_id: str, *, note: str | None = None, status: str | None = None, sla_alerted: bool | None = None
    ) -> Ticket:
        async with self.db.session() as s, s.begin():
            row = await s.get(TicketRow, ticket_id)
            if row is None:
                raise LookupError(ticket_id)
            if note:
                row.notes = [*row.notes, {"at": utcnow().isoformat(), "text": note}]
            if status:
                row.status = status
                if status == "cerrado":
                    row.closed_at = utcnow()
                    group = await s.get(AlarmGroupRow, row.group_id) if row.group_id else None
                    if group:
                        group.status = "cerrado"
            if sla_alerted is not None:
                row.sla_alerted = sla_alerted
            await s.flush()
            return Ticket.model_validate(row)

    # ---------- avisos a guardia ----------
    async def create_page(self, *, ticket: str | None, person: str, summary: str, trace: str | None) -> Page:
        async with self.db.session() as s, s.begin():
            row = PageRow(
                id=await _next_id(s, PageRow, "AVS"), ticket=ticket, person=person, summary=summary, trace=trace
            )
            s.add(row)
            await s.flush()
            return Page.model_validate(row)

    async def pages(self, status: str | None = None, limit: int = 100) -> list[Page]:
        q = select(PageRow).order_by(PageRow.created_at.desc()).limit(limit)
        if status:
            q = q.where(PageRow.status == status)
        async with self.db.session() as s:
            return [Page.model_validate(r) for r in (await s.scalars(q)).all()]

    async def close_page(self, page_id: str, *, by: str, resolution: str) -> Page:
        async with self.db.session() as s, s.begin():
            row = await s.get(PageRow, page_id)
            if row is None:
                raise LookupError(page_id)
            if row.status != "abierto":
                raise ValueError(f"{page_id} ya está {row.status}")
            row.status, row.closed_at, row.closed_by, row.resolution = "cerrado", utcnow(), by, resolution
            await s.flush()
            return Page.model_validate(row)

    async def page_trace(self, page_id: str) -> str | None:
        async with self.db.session() as s:
            row = await s.get(PageRow, page_id)
            return row.trace if row else None

    # ---------- calendario de cambios ----------
    async def seed_changes(self, changes: list[Change]) -> None:
        async with self.db.session() as s, s.begin():
            if int(await s.scalar(select(func.count()).select_from(ChangeRow)) or 0):
                return
            s.add_all(ChangeRow(**c.model_dump()) for c in changes)

    async def changes(self, start: datetime, end: datetime) -> list[Change]:
        q = select(ChangeRow).where(ChangeRow.starts_at < end, ChangeRow.ends_at > start).order_by(ChangeRow.starts_at)
        async with self.db.session() as s:
            return [Change.model_validate(r) for r in (await s.scalars(q)).all()]
