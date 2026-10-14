"""Plantilla común de agente. Los 40 heredan de aquí; cada uno solo aporta su YAML y su prompt.

Dos formas de pensar, un solo camino de control:
- ClaudeRunner: Claude Agent SDK. Sin herramientas integradas; solo MCP; cada llamada pasa por el hook
  PreToolUse (núcleo) y queda auditada en PostToolUse. La salida se pide con esquema JSON (AgentOutput).
- ScriptedRunner: modo guion para pruebas y demo sin clave. Hace las llamadas por `ControlCore.call_tool`,
  que aplica exactamente la misma política y auditoría.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, Protocol, cast

from pydantic import BaseModel, ValidationError

from core.control import ControlCore
from core.registry import AgentDefinition
from core.schemas import AgentOutput, BusEvent
from core.tools import ToolName, in_whitelist

# Herramientas integradas de Claude Code: ningún agente de la teleco las necesita.
BUILTIN_TOOLS = [
    "Bash",
    "Read",
    "Write",
    "Edit",
    "MultiEdit",
    "Glob",
    "Grep",
    "WebFetch",
    "WebSearch",
    "Agent",
    "Task",
    "NotebookEdit",
    "TodoWrite",
    "BashOutput",
    "KillShell",
    "Skill",
    "SlashCommand",
]


class RunResult(BaseModel):
    output: AgentOutput
    tokens: int = 0
    cost_usd: float = 0.0


class Runner(Protocol):
    async def run(self, agent: BaseAgent, event: BusEvent, run_id: str) -> RunResult: ...


class BaseAgent:
    def __init__(self, definition: AgentDefinition, core: ControlCore, runner: Runner) -> None:
        self.definition = definition
        self.config = definition.config
        self.core = core
        self.runner = runner

    def describe_event(self, event: BusEvent) -> str:
        return (
            f"Evento del bus: {event.topic}\nIncidente: {event.incident or 'ninguno'}\n"
            f"Datos: {json.dumps(event.payload, ensure_ascii=False, default=str)}"
        )

    async def handle(self, event: BusEvent) -> AgentOutput | None:
        slug = self.config.slug
        run_id = f"RUN-{uuid.uuid4().hex[:10]}"
        await self.core.audit.write(
            agent=slug,
            step="evento",
            run_id=run_id,
            incident=event.incident,
            input={"topic": event.topic, **event.payload},
            decision="recibido",
            result=f"Activado por {event.topic}",
        )
        if await self.core.is_paused(slug):
            await self.core.audit.write(
                agent=slug,
                step="sistema",
                run_id=run_id,
                incident=event.incident,
                decision="pausa",
                result="No se ejecuta: agente en pausa.",
            )
            return None
        try:
            result = await self.runner.run(self, event, run_id)
            output = AgentOutput.model_validate(result.output.model_dump())
        except (ValidationError, RunnerError) as exc:
            await self.core.audit.write(
                agent=slug,
                step="error",
                run_id=run_id,
                incident=event.incident,
                decision="salida inválida",
                result=str(exc)[:2000],
            )
            return None
        if self.config.persona:
            output.requiere_persona = True
        await self.core.audit.write(
            agent=slug,
            step="salida",
            run_id=run_id,
            incident=event.incident,
            input={"topic": event.topic},
            result=output.resumen,
            decision="salida válida",
            reasoning=output.accion_propuesta or "",
            tokens=result.tokens,
            cost_usd=result.cost_usd,
        )
        await self.core.record_run(slug, output.model_dump())
        return output


class RunnerError(RuntimeError):
    pass


# ---------- modo guion ----------
class ScriptContext:
    """Lo único que un guion puede hacer: llamar herramientas a través del núcleo."""

    def __init__(self, agent: BaseAgent, event: BusEvent, run_id: str) -> None:
        self.agent, self.event, self.run_id = agent, event, run_id
        self.steps = 0
        self.tokens = 0

    async def call(
        self, canonical: str, args: dict[str, Any], reasoning: str = "", evidence: list[str] | None = None
    ) -> tuple[str, str]:
        """Devuelve (veredicto, texto) igual que lo vería el modelo."""
        self.steps += 1
        self.tokens += 900
        if self.steps > self.agent.config.limites.pasos:
            raise RunnerError(f"superado el máximo de {self.agent.config.limites.pasos} pasos")
        auth, result = await self.agent.core.call_tool(
            self.agent.config,
            canonical,
            args,
            run_id=self.run_id,
            incident=self.event.incident,
            reasoning=reasoning,
            evidence=evidence,
        )
        if result is None:
            return auth.decision.verdict.value, auth.message
        return ("ejecutada" if result.ok else "fallida"), result.text


Script = Callable[[ScriptContext], Awaitable[AgentOutput]]
SCRIPTS: dict[str, Script] = {}


def script(slug: str) -> Callable[[Script], Script]:
    def register(fn: Script) -> Script:
        SCRIPTS[slug] = fn
        return fn

    return register


class ScriptedRunner:
    async def run(self, agent: BaseAgent, event: BusEvent, run_id: str) -> RunResult:
        fn = SCRIPTS.get(agent.config.slug)
        if fn is None:
            return RunResult(
                output=AgentOutput(
                    resumen=f"{agent.config.slug} no tiene guion: no actúa.",
                    confianza=1.0,
                    requiere_persona=agent.config.persona,
                )
            )
        ctx = ScriptContext(agent, event, run_id)
        output = await fn(ctx)
        # Coste estimado como si lo hubiera pensado el modelo (Claude Opus 5.5: 4 $ / 20 $ por millón).
        tokens = ctx.tokens + 1200
        return RunResult(output=output, tokens=tokens, cost_usd=round(ctx.tokens * 4e-6 + 1200 * 20e-6, 5))


# ---------- Claude Agent SDK ----------
class ClaudeRunner:
    def __init__(self, model: str, mcp_urls: dict[str, str], tools_by_server: dict[str, list[str]]) -> None:
        self.model = model
        self.mcp_urls = mcp_urls
        self.tools_by_server = tools_by_server  # nombres canónicos que expone cada servidor MCP

    def whitelisted_tools(self, agent: BaseAgent) -> list[ToolName]:
        names = [ToolName.from_canonical(c) for tools in self.tools_by_server.values() for c in tools]
        return [n for n in names if in_whitelist(n.canonical, agent.config.herramientas)]

    def options(self, agent: BaseAgent, event: BusEvent, run_id: str) -> Any:
        from claude_agent_sdk import ClaudeAgentOptions, HookCallback, HookMatcher

        allowed = self.whitelisted_tools(agent)
        servers = sorted({n.server for n in allowed})
        cfg = agent.config

        async def pre_tool_use(input_data: dict[str, Any], tool_use_id: str | None, context: Any) -> dict[str, Any]:
            name = str(input_data.get("tool_name", ""))
            deny = {"hookEventName": "PreToolUse", "permissionDecision": "deny"}
            try:
                canonical = ToolName.from_sdk(name).canonical
            except ValueError:
                await agent.core.audit.write(
                    agent=cfg.slug,
                    step="bloqueo",
                    run_id=run_id,
                    incident=event.incident,
                    tool=name,
                    decision="bloqueada",
                    result="Herramienta no MCP.",
                )
                return {
                    "hookSpecificOutput": {**deny, "permissionDecisionReason": "Solo se permiten herramientas MCP."}
                }
            try:
                auth = await agent.core.authorize(
                    cfg, canonical, dict(input_data.get("tool_input") or {}), run_id=run_id, incident=event.incident
                )
            except Exception as exc:  # si no se puede auditar, no se ejecuta
                return {"hookSpecificOutput": {**deny, "permissionDecisionReason": f"Núcleo no disponible: {exc}"}}
            if auth.allowed:
                return {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "allow",
                        "permissionDecisionReason": auth.message,
                    }
                }
            return {"hookSpecificOutput": {**deny, "permissionDecisionReason": auth.message}}

        async def post_tool_use(input_data: dict[str, Any], tool_use_id: str | None, context: Any) -> dict[str, Any]:
            from core.gateway import ToolResult

            name = str(input_data.get("tool_name", ""))
            if not name.startswith("mcp__"):
                return {}
            response = input_data.get("tool_response")
            text = response if isinstance(response, str) else json.dumps(response, ensure_ascii=False, default=str)
            await agent.core.record_result(
                cfg,
                ToolName.from_sdk(name).canonical,
                dict(input_data.get("tool_input") or {}),
                ToolResult(ok=True, text=text),
                run_id=run_id,
                incident=event.incident,
            )
            return {}

        return ClaudeAgentOptions(
            model=self.model,
            system_prompt=agent.definition.prompt,
            tools=[],
            disallowed_tools=BUILTIN_TOOLS,
            allowed_tools=[n.sdk for n in allowed],
            mcp_servers={s: {"type": "http", "url": self.mcp_urls[s]} for s in servers},
            strict_mcp_config=True,
            permission_mode="dontAsk",
            setting_sources=[],
            max_turns=cfg.limites.pasos,
            output_format={"type": "json_schema", "schema": AgentOutput.model_json_schema()},
            hooks={
                "PreToolUse": [HookMatcher(hooks=[cast(HookCallback, pre_tool_use)])],
                "PostToolUse": [HookMatcher(hooks=[cast(HookCallback, post_tool_use)])],
            },
        )

    async def run(self, agent: BaseAgent, event: BusEvent, run_id: str) -> RunResult:
        from claude_agent_sdk import ResultMessage, query

        result: ResultMessage | None = None
        async for message in query(prompt=agent.describe_event(event), options=self.options(agent, event, run_id)):
            if isinstance(message, ResultMessage):
                result = message
        if result is None or result.is_error or result.structured_output is None:
            detail = result.errors if result else "sin respuesta"
            raise RunnerError(f"el agente no devolvió una salida estructurada: {detail}")
        usage = result.usage or {}
        tokens = int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0))
        output = AgentOutput.model_validate(result.structured_output)
        return RunResult(output=output, tokens=tokens, cost_usd=float(result.total_cost_usd or 0.0))
