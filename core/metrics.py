"""Métricas de la especificación calculadas a partir de la propia auditoría."""

from __future__ import annotations

from collections import defaultdict

from pydantic import BaseModel
from sqlalchemy import select

from core.audit import AuditEntry
from core.db import AuditRow, Database
from core.registry import AgentDefinition
from core.tools import in_whitelist, spec_for


class Metrics(BaseModel):
    diagnosis_seconds_avg: float | None
    diagnosis_samples: int
    executed_outside_whitelist: int
    actions_without_prior_audit: int
    executed_actions: int
    changes_executed: int = 0
    changes_without_twin_and_approval: int = 0
    audit_rows: int


async def all_rows(db: Database) -> list[AuditEntry]:
    async with db.session() as s:
        return [AuditEntry.model_validate(r) for r in (await s.scalars(select(AuditRow).order_by(AuditRow.id))).all()]


def compute(rows: list[AuditEntry], agents: dict[str, AgentDefinition]) -> Metrics:
    whitelist = {a.config.slug: a.config.herramientas for a in agents.values()}

    # Tiempo de diagnóstico: del primer evento que recibe un agente al ticket abierto por Triaje.
    first_seen: dict[str, float] = {}
    diagnosed: dict[str, float] = {}
    for r in rows:
        if not r.incident:
            continue
        ts = r.at.timestamp()
        if r.step == "evento" and r.decision == "recibido":
            first_seen.setdefault(r.incident, ts)
        if r.tool == "tickets.crear" and r.decision == "ejecutada":
            diagnosed.setdefault(r.incident, ts)
    samples = [diagnosed[i] - first_seen[i] for i in diagnosed if i in first_seen]

    # Toda ejecución debe ir precedida de su autorización (o de una aprobación humana) en la auditoría.
    authorized: dict[tuple[str | None, str | None], int] = defaultdict(int)
    approved: dict[tuple[str | None, str | None], int] = defaultdict(int)
    outside = without_prior = executed = 0
    for r in rows:
        if r.decision == "autorizada":
            authorized[(r.run_id, r.tool)] += 1
        elif r.step == "aprobacion" and r.decision == "aprobada":
            approved[(r.incident, r.tool)] += 1
        elif r.step == "accion" and r.decision.startswith("ejecutada"):
            executed += 1
            if r.agent in whitelist and (r.tool is None or not in_whitelist(r.tool, whitelist[r.agent])):
                outside += 1
            key_auth, key_appr = (r.run_id, r.tool), (r.incident, r.tool)
            if r.decision == "ejecutada tras aprobación" and approved[key_appr] > 0:
                approved[key_appr] -= 1
            elif r.decision == "ejecutada" and authorized[key_auth] > 0:
                authorized[key_auth] -= 1
            else:
                without_prior += 1
    # Puerta de la Fase 2: todo cambio de configuración ejecutado tuvo antes «gemelo ok» y una aprobación humana.
    twin_ok: dict[tuple[str | None, str | None], int] = defaultdict(int)
    approved_change: dict[tuple[str | None, str | None], int] = defaultdict(int)
    changes = changes_bad = 0
    for r in rows:
        if r.tool is None or not spec_for(r.tool).cambio:
            continue
        key = (r.incident, r.tool)
        if r.step == "gemelo" and r.decision == "gemelo ok":
            twin_ok[key] += 1
        elif r.step == "aprobacion" and r.decision == "aprobada":
            approved_change[key] += 1
        elif r.step == "accion" and r.decision.startswith("ejecutada"):
            changes += 1
            if twin_ok[key] > 0 and approved_change[key] > 0:
                twin_ok[key] -= 1
                approved_change[key] -= 1
            else:
                changes_bad += 1
    return Metrics(
        changes_executed=changes,
        changes_without_twin_and_approval=changes_bad,
        diagnosis_seconds_avg=round(sum(samples) / len(samples), 3) if samples else None,
        diagnosis_samples=len(samples),
        executed_outside_whitelist=outside,
        actions_without_prior_audit=without_prior,
        executed_actions=executed,
        audit_rows=len(rows),
    )
