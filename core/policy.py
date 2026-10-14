"""Decisión del núcleo sobre una llamada a herramienta. Lógica pura, sin E/S, para poder probarla a fondo."""

from __future__ import annotations

from pydantic import BaseModel

from core.schemas import AgentConfig, PolicyDecision, Verdict
from core.tools import in_whitelist, spec_for


class PolicyContext(BaseModel):
    kill_switch: bool
    blast_radius: int
    actions_last_hour: int
    impact: int = 0
    agent_paused: bool = False


def evaluate(agent: AgentConfig, canonical: str, ctx: PolicyContext) -> PolicyDecision:
    spec = spec_for(canonical)
    is_action = spec.tipo == "accion"

    if not in_whitelist(canonical, agent.herramientas):
        return PolicyDecision(
            verdict=Verdict.BLOQUEADA,
            is_action=is_action,
            reason=f"«{canonical}» no está en la lista blanca de {agent.slug}.",
        )
    if ctx.agent_paused:
        return PolicyDecision(
            verdict=Verdict.PAUSA, is_action=is_action, reason=f"{agent.slug} está en pausa por límite de ritmo."
        )
    if not is_action:
        return PolicyDecision(verdict=Verdict.PERMITIDA, is_action=False, reason="Lectura en lista blanca.")

    level = 0 if ctx.kill_switch else agent.autonomia
    if level == 0:
        reason = (
            "Interruptor general activo: todos los agentes en nivel 0."
            if ctx.kill_switch
            else "Agente de nivel 0: solo propone."
        )
        return PolicyDecision(verdict=Verdict.PROPUESTA, is_action=True, reason=reason, impact=ctx.impact)

    if agent.limites.acciones_hora and ctx.actions_last_hour >= agent.limites.acciones_hora:
        return PolicyDecision(
            verdict=Verdict.PAUSA,
            is_action=True,
            impact=ctx.impact,
            reason=f"Superado el límite de {agent.limites.acciones_hora} acciones por hora.",
        )

    needs_twin = spec.gemelo is not None
    if level == 1:
        return PolicyDecision(
            verdict=Verdict.APROBACION,
            is_action=True,
            impact=ctx.impact,
            needs_twin=needs_twin,
            reason="Agente de nivel 1: actúa con aprobación.",
        )
    if not spec.nivel2:
        return PolicyDecision(
            verdict=Verdict.APROBACION,
            is_action=True,
            impact=ctx.impact,
            needs_twin=needs_twin,
            reason="Acción fuera del catálogo cerrado de nivel 2.",
        )
    if ctx.impact > ctx.blast_radius:
        return PolicyDecision(
            verdict=Verdict.APROBACION,
            is_action=True,
            impact=ctx.impact,
            needs_twin=needs_twin,
            reason=f"Radio de impacto: {ctx.impact} clientes (umbral {ctx.blast_radius}).",
        )
    return PolicyDecision(
        verdict=Verdict.PERMITIDA,
        is_action=True,
        impact=ctx.impact,
        reason="Nivel 2, acción reversible del catálogo y dentro del radio de impacto.",
    )
