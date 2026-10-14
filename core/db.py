"""Tablas del núcleo. La auditoría es de solo inserción: un trigger impide modificarla o borrarla."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Dialect, Float, Integer, String, Text, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import DateTime as SADateTime
from sqlalchemy.types import TypeDecorator


def utcnow() -> datetime:
    return datetime.now(UTC)


class DateTime(TypeDecorator[datetime]):
    """Siempre en UTC con zona horaria, también en SQLite (que la pierde al guardar)."""

    impl = SADateTime(timezone=True)
    cache_ok = True

    def __init__(self, timezone: bool = True) -> None:
        super().__init__()

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        return value.astimezone(UTC) if value is not None and value.tzinfo else value

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, list[str]: JSON}


class AuditRow(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    agent: Mapped[str] = mapped_column(String(40), index=True)
    run_id: Mapped[str | None] = mapped_column(String(40), index=True)
    incident: Mapped[str | None] = mapped_column(String(40), index=True)
    step: Mapped[str] = mapped_column(String(20))
    tool: Mapped[str | None] = mapped_column(String(120))
    input: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    reasoning: Mapped[str] = mapped_column(Text, default="")
    result: Mapped[str] = mapped_column(Text, default="")
    decision: Mapped[str] = mapped_column(String(60), default="")
    approved_by: Mapped[str | None] = mapped_column(String(80))
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)


class ApprovalRow(Base):
    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    agent: Mapped[str] = mapped_column(String(40), index=True)
    run_id: Mapped[str | None] = mapped_column(String(40))
    incident: Mapped[str | None] = mapped_column(String(40))
    tool: Mapped[str] = mapped_column(String(120))
    args: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    motive: Mapped[str] = mapped_column(Text)
    rationale: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[list[str]] = mapped_column(JSON, default=list)
    impact: Mapped[int] = mapped_column(Integer, default=0)
    twin_ok: Mapped[bool | None] = mapped_column(Boolean)
    twin_detail: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="pendiente", index=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[str | None] = mapped_column(String(80))
    comment: Mapped[str] = mapped_column(Text, default="")
    result: Mapped[str] = mapped_column(Text, default="")


class AgentStateRow(Base):
    __tablename__ = "agent_state"

    agent: Mapped[str] = mapped_column(String(40), primary_key=True)
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    reason: Mapped[str] = mapped_column(Text, default="")
    runs: Mapped[int] = mapped_column(Integer, default=0)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_output: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class FlagRow(Base):
    __tablename__ = "system_flags"

    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


_SQLITE_TRIGGERS = [
    "CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_log "
    "BEGIN SELECT RAISE(ABORT, 'audit_log es de solo inserción'); END",
    "CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_log "
    "BEGIN SELECT RAISE(ABORT, 'audit_log es de solo inserción'); END",
]
_PG_TRIGGERS = [
    "CREATE OR REPLACE FUNCTION audit_append_only() RETURNS trigger AS $$ "
    "BEGIN RAISE EXCEPTION 'audit_log es de solo inserción'; END; $$ LANGUAGE plpgsql",
    "DROP TRIGGER IF EXISTS audit_append_only ON audit_log",
    "CREATE TRIGGER audit_append_only BEFORE UPDATE OR DELETE ON audit_log "
    "FOR EACH ROW EXECUTE FUNCTION audit_append_only()",
]


class Database:
    def __init__(self, url: str) -> None:
        self.engine: AsyncEngine = create_async_engine(url)
        self.session: async_sessionmaker[AsyncSession] = async_sessionmaker(self.engine, expire_on_commit=False)

    async def init(self) -> None:
        import ops.db  # noqa: F401  (registra las tablas de operación en el mismo esquema)

        # En docker compose varios servicios arrancan a la vez y crean el esquema en paralelo: se reintenta.
        for attempt in range(5):
            try:
                async with self.engine.begin() as conn:
                    await conn.run_sync(Base.metadata.create_all)
                    statements = _PG_TRIGGERS if self.engine.dialect.name == "postgresql" else _SQLITE_TRIGGERS
                    for sql in statements:
                        await conn.execute(text(sql))
                return
            except DBAPIError:
                if attempt == 4:
                    raise
                await asyncio.sleep(0.5 * (attempt + 1))

    async def close(self) -> None:
        await self.engine.dispose()
