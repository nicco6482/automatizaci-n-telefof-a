"""Núcleo de control: el único camino entre un agente y la red.

Toda llamada a herramienta pasa por `authorize`, que decide con `policy.evaluate`, escribe la auditoría
ANTES de que nada se ejecute, prueba los cambios en el gemelo y encola lo que necesita aprobación.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select

from core.audit import AuditLog
from core.db import AgentStateRow, ApprovalRow, Database, FlagRow, utcnow
from core.gateway import ToolGateway, ToolResult
from core.policy import PolicyContext, evaluate
from core.schemas import AgentConfig, PolicyDecision, Verdict
from core.tools import spec_for
from simulator.port import SimulatorPort

HUMAN = "Operador NOC"
# Los servidores MCP hablan en castellano; el simulador, en inglés.
_ARG_MAP = {
    "nodo": "node",
    "celda": "cell",
    "zona": "zone",
    "celdas": "cells",
    "delta_inclinacion": "tilt_delta",
    "delta_potencia": "power_delta",
    "hasta": "until",
    "pares": "pairs",
    "plantilla": "template",
    "fabricante": "vendor",
    "nodos": "nodes",
    "ventana": "window",
    "prefijo": "prefix",
    "cliente": "customer",
    "servicio": "service",
    "destino": "target",
}


def _step(tipo: str) -> str:
    return {"accion": "accion", "entrega": "entrega"}.get(tipo, "lectura")


class Authorization(BaseModel):
    decision: PolicyDecision
    approval_id: str | None = None
    message: str

    @property
    def allowed(self) -> bool:
        return self.decision.verdict == Verdict.PERMITIDA


class Approval(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    agent: str
    incident: str | None
    tool: str
    args: dict[str, Any]
    motive: str
    rationale: str
    evidence: list[str]
    impact: int
    twin_ok: bool | None
    twin_detail: str
    status: str
    decided_at: datetime | None
    decided_by: str | None
    comment: str
    result: str


class ApprovalError(ValueError):
    pass


class ControlCore:
    def __init__(self, db: Database, gateway: ToolGateway, simulator: SimulatorPort, blast_radius: int = 500) -> None:
        self.db = db
        self.audit = AuditLog(db)
        self.gateway = gateway
        self.simulator = simulator
        self.default_blast_radius = blast_radius

    # ---------- banderas ----------
    async def _flag(self, key: str, default: str) -> str:
        async with self.db.session() as s:
            row = await s.get(FlagRow, key)
            return row.value if row else default

    async def _set_flag(self, key: str, value: str) -> None:
        async with self.db.session() as s, s.begin():
            row = await s.get(FlagRow, key)
            if row:
                row.value = value
            else:
                s.add(FlagRow(key=key, value=value))

    async def kill_switch(self) -> bool:
        return await self._flag("kill_switch", "0") == "1"

    async def set_kill_switch(self, on: bool, by: str = HUMAN) -> None:
        await self._set_flag("kill_switch", "1" if on else "0")
        await self.audit.write(
            agent="NUCLEO",
            step="sistema",
            decision="interruptor " + ("activado" if on else "desactivado"),
            approved_by=by,
            result="Todos los agentes en nivel 0." if on else "Cada agente vuelve a su nivel.",
        )

    async def blast_radius(self) -> int:
        return int(await self._flag("blast_radius", str(self.default_blast_radius)))

    async def set_blast_radius(self, value: int, by: str = HUMAN) -> None:
        await self._set_flag("blast_radius", str(value))
        await self.audit.write(
            agent="NUCLEO",
            step="sistema",
            decision="umbral cambiado",
            approved_by=by,
            result=f"Aprobación obligatoria por encima de {value} clientes.",
        )

    async def is_paused(self, agent: str) -> bool:
        async with self.db.session() as s:
            row = await s.get(AgentStateRow, agent)
            return bool(row and row.paused)

    async def set_paused(self, agent: str, paused: bool, reason: str, by: str | None = None) -> None:
        async with self.db.session() as s, s.begin():
            row = await s.get(AgentStateRow, agent)
            if row is None:
                row = AgentStateRow(agent=agent)
                s.add(row)
            row.paused, row.reason = paused, reason
        await self.audit.write(
            agent=agent, step="sistema", decision="pausado" if paused else "reanudado", approved_by=by, result=reason
        )

    # ---------- autorización ----------
    async def authorize(
        self,
        agent: AgentConfig,
        canonical: str,
        args: dict[str, Any],
        *,
        run_id: str | None,
        incident: str | None,
        reasoning: str = "",
        evidence: list[str] | None = None,
    ) -> Authorization:
        spec = spec_for(canonical)
        impact = 0
        if spec.impacto:
            impact = await self.simulator.impact(spec.impacto, {_ARG_MAP.get(k, k): v for k, v in args.items()})
        ctx = PolicyContext(
            kill_switch=await self.kill_switch(),
            blast_radius=await self.blast_radius(),
            actions_last_hour=await self.audit.actions_last_hour(agent.slug),
            impact=impact,
            agent_paused=await self.is_paused(agent.slug),
        )
        decision = evaluate(agent, canonical, ctx)
        common: dict[str, Any] = {
            "agent": agent.slug,
            "run_id": run_id,
            "incident": incident,
            "tool": canonical,
            "input": args,
            "reasoning": reasoning,
        }
        verdict = decision.verdict

        if verdict == Verdict.BLOQUEADA:
            await self.audit.write(step="bloqueo", decision=verdict.value, result=decision.reason, **common)
            return Authorization(decision=decision, message=f"Bloqueada por el núcleo: {decision.reason}")

        if verdict == Verdict.PAUSA:
            await self.audit.write(
                step="accion" if decision.is_action else "lectura",
                decision=verdict.value,
                result=decision.reason,
                **common,
            )
            if not ctx.agent_paused:
                await self.set_paused(agent.slug, True, decision.reason)
            return Authorization(
                decision=decision, message=f"No ejecutada: {decision.reason} Una persona debe reanudarte."
            )

        if verdict == Verdict.PROPUESTA:
            await self.audit.write(step="accion", decision=verdict.value, result=decision.reason, **common)
            return Authorization(decision=decision, message=f"Queda como propuesta, no se ejecuta: {decision.reason}")

        if verdict == Verdict.APROBACION:
            duplicate = await self._pending_duplicate(canonical, args)
            if duplicate:
                await self.audit.write(step="accion", decision="ya en cola", result=f"Igual que {duplicate}.", **common)
                return Authorization(
                    decision=decision,
                    approval_id=duplicate,
                    message=f"Ya hay una aprobación pendiente idéntica ({duplicate}). No la repitas.",
                )
            twin_ok: bool | None = None
            twin_detail = ""
            if decision.needs_twin and spec.gemelo:
                twin = await self.simulator.twin(spec.gemelo, {_ARG_MAP.get(k, k): v for k, v in args.items()})
                twin_ok, twin_detail = twin.ok, twin.detail
                await self.audit.write(
                    step="gemelo", decision="gemelo ok" if twin.ok else "gemelo ko", result=twin.detail, **common
                )
                if not twin.ok:
                    return Authorization(decision=decision, message=f"El gemelo rechaza el cambio: {twin.detail}")
            approval_id = await self._create_approval(
                agent, canonical, args, decision, run_id, incident, reasoning, evidence or [], twin_ok, twin_detail
            )
            await self.audit.write(
                step="accion", decision=verdict.value, result=f"{approval_id}: {decision.reason}", **common
            )
            return Authorization(
                decision=decision,
                approval_id=approval_id,
                message=f"Enviada a aprobación humana como {approval_id}. {decision.reason} "
                "No la repitas: se ejecutará si una persona la aprueba.",
            )

        # PERMITIDA: la entrada de auditoría se escribe antes de ejecutar; si falla, no se ejecuta.
        await self.audit.write(step=_step(spec.tipo), decision="autorizada", result=decision.reason, **common)
        return Authorization(decision=decision, message="Autorizada.")

    async def record_result(
        self,
        agent: AgentConfig,
        canonical: str,
        args: dict[str, Any],
        result: ToolResult,
        *,
        run_id: str | None,
        incident: str | None,
    ) -> None:
        kind = spec_for(canonical).tipo
        is_action = kind == "accion"
        if kind == "entrega":
            decision = "entregada a una persona" if result.ok else "fallida"
        else:
            decision = ("ejecutada" if result.ok else "fallida") if is_action else "leída"
        await self.audit.write(
            agent=agent.slug,
            step=_step(kind),
            run_id=run_id,
            incident=incident,
            tool=canonical,
            input=args,
            result=result.text,
            decision=decision,
        )

    async def call_tool(
        self,
        agent: AgentConfig,
        canonical: str,
        args: dict[str, Any],
        *,
        run_id: str | None,
        incident: str | None,
        reasoning: str = "",
        evidence: list[str] | None = None,
    ) -> tuple[Authorization, ToolResult | None]:
        """Camino completo para quien no es el Agent SDK (modo guion): autorizar, ejecutar, auditar."""
        auth = await self.authorize(
            agent, canonical, args, run_id=run_id, incident=incident, reasoning=reasoning, evidence=evidence
        )
        if not auth.allowed:
            return auth, None
        result = await self.gateway.call(canonical, args)
        await self.record_result(agent, canonical, args, result, run_id=run_id, incident=incident)
        return auth, result

    # ---------- aprobaciones ----------
    async def _create_approval(
        self,
        agent: AgentConfig,
        canonical: str,
        args: dict[str, Any],
        decision: PolicyDecision,
        run_id: str | None,
        incident: str | None,
        rationale: str,
        evidence: list[str],
        twin_ok: bool | None,
        twin_detail: str,
    ) -> str:
        async with self.db.session() as s, s.begin():
            n = int(await s.scalar(select(func.count()).select_from(ApprovalRow)) or 0)
            approval_id = f"APR-{n + 1:04d}"
            s.add(
                ApprovalRow(
                    id=approval_id,
                    agent=agent.slug,
                    run_id=run_id,
                    incident=incident,
                    tool=canonical,
                    args=args,
                    motive=decision.reason,
                    rationale=rationale,
                    evidence=evidence,
                    impact=decision.impact,
                    twin_ok=twin_ok,
                    twin_detail=twin_detail,
                )
            )
        return approval_id

    async def _pending_duplicate(self, canonical: str, args: dict[str, Any]) -> str | None:
        q = select(ApprovalRow).where(ApprovalRow.status == "pendiente", ApprovalRow.tool == canonical)
        async with self.db.session() as s:
            for row in (await s.scalars(q)).all():
                if row.args == args:
                    return row.id
        return None

    async def approvals(self, status: str | None = None, limit: int = 100) -> list[Approval]:
        q = select(ApprovalRow).order_by(ApprovalRow.created_at.desc()).limit(limit)
        if status:
            q = q.where(ApprovalRow.status == status)
        async with self.db.session() as s:
            return [Approval.model_validate(r) for r in (await s.scalars(q)).all()]

    async def decide(self, approval_id: str, approve: bool, by: str = HUMAN, comment: str = "") -> Approval:
        async with self.db.session() as s, s.begin():
            row = await s.get(ApprovalRow, approval_id)
            if row is None:
                raise ApprovalError(f"no existe {approval_id}")
            if row.status != "pendiente":
                raise ApprovalError(f"{approval_id} ya está {row.status}")
            row.status = "ejecutando" if approve else "rechazada"
            row.decided_at, row.decided_by, row.comment = utcnow(), by, comment
            snapshot = Approval.model_validate(row)
        common: dict[str, Any] = {
            "agent": snapshot.agent,
            "incident": snapshot.incident,
            "tool": snapshot.tool,
            "input": snapshot.args,
            "approved_by": by,
            "reasoning": comment,
        }
        if not approve:
            await self.audit.write(
                step="aprobacion", decision="rechazada", result=f"{approval_id} rechazada.", **common
            )
            return snapshot
        await self.audit.write(step="aprobacion", decision="aprobada", result=f"{approval_id} aprobada.", **common)
        result = await self.gateway.call(snapshot.tool, snapshot.args)
        await self.audit.write(
            step="accion",
            decision="ejecutada tras aprobación" if result.ok else "fallida",
            result=result.text,
            **common,
        )
        async with self.db.session() as s, s.begin():
            row = await s.get(ApprovalRow, approval_id)
            assert row is not None
            row.status, row.result = ("aprobada" if result.ok else "fallida"), result.text
            snapshot = Approval.model_validate(row)
        return snapshot

    async def agent_states(self) -> dict[str, AgentStateRow]:
        async with self.db.session() as s:
            return {r.agent: r for r in (await s.scalars(select(AgentStateRow))).all()}

    async def record_run(self, agent: str, output: dict[str, Any]) -> None:
        async with self.db.session() as s, s.begin():
            row = await s.get(AgentStateRow, agent)
            if row is None:
                row = AgentStateRow(agent=agent, runs=0)
                s.add(row)
            row.runs = (row.runs or 0) + 1
            row.last_run_at = utcnow()
            row.last_output = json.loads(json.dumps(output, default=str))
