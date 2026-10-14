"""Registro de auditoría: cada paso de cada agente, antes y después de actuar."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select

from core.db import AuditRow, Database, utcnow

# Nunca se guardan secretos en la auditoría aunque un agente o una herramienta los devuelva.
_SECRET = re.compile(r"(sk-ant-[A-Za-z0-9_\-]{8,}|(?i:api[_-]?key|token|password)\s*[:=]\s*\S+)")


def redact(value: str) -> str:
    return _SECRET.sub("[OCULTO]", value)


class AuditEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    at: datetime
    agent: str
    run_id: str | None
    incident: str | None
    step: str
    tool: str | None
    input: dict[str, Any]
    reasoning: str
    result: str
    decision: str
    approved_by: str | None
    tokens: int
    cost_usd: float


class AuditLog:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def write(
        self,
        *,
        agent: str,
        step: str,
        run_id: str | None = None,
        incident: str | None = None,
        tool: str | None = None,
        input: dict[str, Any] | None = None,
        reasoning: str = "",
        result: str = "",
        decision: str = "",
        approved_by: str | None = None,
        tokens: int = 0,
        cost_usd: float = 0.0,
    ) -> int:
        safe_input = json.loads(redact(json.dumps(input or {}, ensure_ascii=False, default=str)))
        row = AuditRow(
            agent=agent,
            step=step,
            run_id=run_id,
            incident=incident,
            tool=tool,
            input=safe_input,
            reasoning=redact(reasoning)[:4000],
            result=redact(result)[:8000],
            decision=decision,
            approved_by=approved_by,
            tokens=tokens,
            cost_usd=cost_usd,
        )
        async with self.db.session() as s, s.begin():
            s.add(row)
        return row.id

    async def list(
        self, *, agent: str | None = None, incident: str | None = None, step: str | None = None, limit: int = 200
    ) -> list[AuditEntry]:
        q = select(AuditRow).order_by(AuditRow.id.desc()).limit(limit)
        if agent:
            q = q.where(AuditRow.agent == agent)
        if incident:
            q = q.where(AuditRow.incident == incident)
        if step:
            q = q.where(AuditRow.step == step)
        async with self.db.session() as s:
            return [AuditEntry.model_validate(r) for r in (await s.scalars(q)).all()]

    async def actions_last_hour(self, agent: str) -> int:
        since = utcnow() - timedelta(hours=1)
        q = (
            select(func.count())
            .select_from(AuditRow)
            .where(
                AuditRow.agent == agent,
                AuditRow.step == "accion",
                AuditRow.decision.like("ejecutada%"),
                AuditRow.at >= since,
            )
        )
        async with self.db.session() as s:
            return int((await s.scalar(q)) or 0)

    async def cost_today(self) -> tuple[int, float]:
        start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        q = select(func.coalesce(func.sum(AuditRow.tokens), 0), func.coalesce(func.sum(AuditRow.cost_usd), 0.0)).where(
            AuditRow.at >= start
        )
        async with self.db.session() as s:
            tokens, cost = (await s.execute(q)).one()
        return int(tokens), float(cost)
