"""Pruebas de seguridad: intentar usar herramientas no permitidas o saltarse la aprobación debe fallar siempre.

Se prueban los hooks reales que recibe el Claude Agent SDK, sin llamar a la API.
"""

from __future__ import annotations

from typing import Any

from core.agent import BUILTIN_TOOLS, BaseAgent, ClaudeRunner, ScriptedRunner
from core.schemas import AgentOutput, BusEvent
from simulator.models import FaultType
from tests.conftest import Stack

RED_TOOLS = [
    "red.alarmas.listar",
    "red.estado.nodo",
    "red.runbooks.consultar",
    "red.runbooks.conmutar_respaldo",
    "red.runbooks.reiniciar_tarjeta",
    "red.config.escribir",
]


def runner() -> ClaudeRunner:
    return ClaudeRunner("claude-opus-5-5", {"red": "http://mcp-red:8101/mcp"}, {"red": RED_TOOLS})


def build(stack: Stack, event: BusEvent) -> tuple[Any, BaseAgent]:
    agent = BaseAgent(stack.agents["00"], stack.core, ScriptedRunner())
    return runner().options(agent, event, "RUN-test"), agent


async def call_pre_hook(options: Any, tool_name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
    hook = options.hooks["PreToolUse"][0].hooks[0]
    result: dict[str, Any] = await hook(
        {"hook_event_name": "PreToolUse", "tool_name": tool_name, "tool_input": tool_input}, "tu-1", None
    )
    return result["hookSpecificOutput"]


async def test_sin_herramientas_integradas_y_solo_la_lista_blanca(stack: Stack) -> None:
    options, _ = build(stack, BusEvent(topic="alarm.raised"))
    assert options.tools == []
    assert set(BUILTIN_TOOLS) <= set(options.disallowed_tools)
    assert "mcp__red__config__escribir" not in options.allowed_tools
    assert "mcp__red__runbooks__conmutar_respaldo" in options.allowed_tools
    assert options.permission_mode == "dontAsk"
    assert options.setting_sources == []
    assert options.strict_mcp_config is True
    assert options.output_format["schema"] == AgentOutput.model_json_schema()


async def test_hook_deniega_herramienta_integrada(stack: Stack) -> None:
    options, _ = build(stack, BusEvent(topic="alarm.raised"))
    out = await call_pre_hook(options, "Bash", {"command": "rm -rf /"})
    assert out["permissionDecision"] == "deny"


async def test_hook_deniega_mcp_fuera_de_lista(stack: Stack) -> None:
    options, _ = build(stack, BusEvent(topic="alarm.raised"))
    out = await call_pre_hook(options, "mcp__red__config__escribir", {"nodo": "CORE-1", "cambio": "shutdown"})
    assert out["permissionDecision"] == "deny"
    assert (await stack.core.audit.list(step="bloqueo"))[0].tool == "red.config.escribir"


async def test_hook_manda_a_aprobacion_y_no_ejecuta(stack: Stack) -> None:
    fault = stack.sim.inject(FaultType.CAIDA_ENLACE, with_backup=True)
    options, _ = build(stack, BusEvent(topic="alarm.raised", incident=fault.id))
    out = await call_pre_hook(options, "mcp__red__runbooks__conmutar_respaldo", {"nodo": fault.node})
    assert out["permissionDecision"] == "deny"
    assert "APR-" in out["permissionDecisionReason"]
    assert not stack.sim.state.node_has_service(fault.node or "")


async def test_repetir_la_accion_no_la_ejecuta(stack: Stack) -> None:
    fault = stack.sim.inject(FaultType.CAIDA_ENLACE, with_backup=True)
    options, _ = build(stack, BusEvent(topic="alarm.raised", incident=fault.id))
    for _ in range(3):
        out = await call_pre_hook(options, "mcp__red__runbooks__conmutar_respaldo", {"nodo": fault.node})
        assert out["permissionDecision"] == "deny"
    assert not stack.sim.state.node_has_service(fault.node or "")


async def test_hook_permite_lectura_en_lista(stack: Stack) -> None:
    options, _ = build(stack, BusEvent(topic="alarm.raised"))
    out = await call_pre_hook(options, "mcp__red__alarmas__listar", {"limite": 3})
    assert out["permissionDecision"] == "allow"


async def test_post_hook_audita_el_resultado(stack: Stack) -> None:
    options, _ = build(stack, BusEvent(topic="alarm.raised"))
    hook = options.hooks["PostToolUse"][0].hooks[0]
    await hook(
        {
            "hook_event_name": "PostToolUse",
            "tool_name": "mcp__red__alarmas__listar",
            "tool_input": {"limite": 3},
            "tool_response": "[]",
        },
        "tu-1",
        None,
    )
    rows = await stack.core.audit.list(agent="00_sonda")
    assert rows[0].decision == "leída"


async def test_interruptor_vale_tambien_para_claude(stack: Stack) -> None:
    fault = stack.sim.inject(FaultType.CAIDA_ENLACE, with_backup=True)
    await stack.core.set_kill_switch(True)
    options, _ = build(stack, BusEvent(topic="alarm.raised", incident=fault.id))
    out = await call_pre_hook(options, "mcp__red__runbooks__conmutar_respaldo", {"nodo": fault.node})
    assert out["permissionDecision"] == "deny"
    assert await stack.core.approvals(status="pendiente") == []
