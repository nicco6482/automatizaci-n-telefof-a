"""Tablas de operación. Comparten base de datos con el núcleo, pero solo las tocan los servidores MCP."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from core.db import Base, DateTime, utcnow


class AlarmGroupRow(Base):
    __tablename__ = "alarm_groups"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    key: Mapped[str] = mapped_column(String(60), index=True)
    zone: Mapped[str] = mapped_column(String(10))
    node: Mapped[str | None] = mapped_column(String(30))
    alarm_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    codes: Mapped[list[str]] = mapped_column(JSON, default=list)
    trace: Mapped[str | None] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(20), default="abierto")
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)


class TicketRow(Base):
    __tablename__ = "tickets"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)
    created_sim_at: Mapped[datetime] = mapped_column(DateTime())
    priority: Mapped[str] = mapped_column(String(4))
    diagnosis: Mapped[str] = mapped_column(Text)
    zone: Mapped[str] = mapped_column(String(10))
    node: Mapped[str | None] = mapped_column(String(30), index=True)
    group_id: Mapped[str | None] = mapped_column(String(20), index=True)
    codes: Mapped[list[str]] = mapped_column(JSON, default=list)
    affected_ftth: Mapped[int] = mapped_column(Integer, default=0)
    enterprises: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="abierto", index=True)
    notes: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    sla_alerted: Mapped[bool] = mapped_column(Boolean, default=False)
    trace: Mapped[str | None] = mapped_column(String(40), index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime())


class PageRow(Base):
    """Aviso a la persona de guardia. Lo cierra siempre una persona."""

    __tablename__ = "pages"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)
    ticket: Mapped[str | None] = mapped_column(String(20), index=True)
    person: Mapped[str] = mapped_column(String(80))
    summary: Mapped[str] = mapped_column(Text)
    trace: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="abierto", index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime())
    closed_by: Mapped[str | None] = mapped_column(String(80))
    resolution: Mapped[str] = mapped_column(Text, default="")


class ChangeRow(Base):
    __tablename__ = "changes"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    node: Mapped[str | None] = mapped_column(String(30))
    zone: Mapped[str] = mapped_column(String(10))
    starts_at: Mapped[datetime] = mapped_column(DateTime())
    ends_at: Mapped[datetime] = mapped_column(DateTime())
    owner: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), default="planificado")


class TaskRow(Base):
    """Trabajo que acaba en una persona: borradores de agentes «Persona», validaciones, revisiones."""

    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)
    agent: Mapped[str] = mapped_column(String(40), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(Text)
    detail: Mapped[str] = mapped_column(Text, default="")
    ref: Mapped[str | None] = mapped_column(String(40))
    assignee: Mapped[str] = mapped_column(String(80), default="Persona responsable")
    trace: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="abierta", index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime())
    closed_by: Mapped[str | None] = mapped_column(String(80))
    resolution: Mapped[str] = mapped_column(Text, default="")


class WorkOrderRow(Base):
    __tablename__ = "workorders"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)
    kind: Mapped[str] = mapped_column(String(60))
    zone: Mapped[str] = mapped_column(String(10))
    node: Mapped[str | None] = mapped_column(String(30))
    ont: Mapped[str | None] = mapped_column(String(30))
    detail: Mapped[str] = mapped_column(Text, default="")
    contractor: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), default="creada", index=True)
    trace: Mapped[str | None] = mapped_column(String(40))


class DocumentRow(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    title: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text, default="")
    agent: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="borrador")
    trace: Mapped[str | None] = mapped_column(String(40))
