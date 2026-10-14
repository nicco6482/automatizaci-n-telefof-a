"""Núcleo con base de datos y servidor MCP reales (en memoria): auditoría, aprobaciones, ritmo, interruptor."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from core.audit import redact
from core.control import ApprovalError
from core.schemas import AgentOutput, Verdict
from simulator.models import FaultType
from tests.conftest import Stack


def sonda(stack: Stack, **update: object):  # type: ignore[no-untyped-def]
    return stack.agents["00"].config.model_copy(update=update)


async def test_auditoria_es_de_solo_insercion(stack: Stack) -> None:
    await stack.core.audit.write(agent="00_sonda", step="sistema", result="hola")
    async with stack.db.engine.begin() as conn:
        with pytest.raises(DBAPIError):
            await conn.execute(text("UPDATE audit_log SET result = 'trampa'"))
    async with stack.db.engine.begin() as conn:
        with pytest.raises(DBAPIError):
            await conn.execute(text("DELETE FROM audit_log"))


def test_auditoria_oculta_secretos() -> None:
    assert "sk-ant" not in redact("clave sk-ant-api03-abcdefghijklmnop")
    assert "hunter2" not in redact("password=hunter2")


async def test_lectura_queda_auditada_antes_y_despues(stack: Stack) -> None:
    auth, result = await stack.core.call_tool(
        sonda(stack), "red.alarmas.listar", {"limite": 1}, run_id="R1", incident=None
    )
    assert auth.allowed and result is not None and result.ok
    rows = await stack.core.audit.list(agent="00_sonda")
    assert [r.decision for r in rows][::-1] == ["autorizada", "leída"]


async def test_bloqueo_queda_auditado_y_no_se_ejecuta(stack: Stack) -> None:
    auth, result = await stack.core.call_tool(
        sonda(stack), "red.config.escribir", {"nodo": "CORE-1", "cambio": "x"}, run_id="R1", incident=None
    )
    assert auth.decision.verdict == Verdict.BLOQUEADA and result is None
    rows = await stack.core.audit.list(step="bloqueo")
    assert rows and rows[0].tool == "red.config.escribir"


async def test_aprobacion_con_gemelo_y_ejecucion_por_el_nucleo(stack: Stack) -> None:
    fault = stack.sim.inject(FaultType.CAIDA_ENLACE, with_backup=True)
    node = fault.node or ""
    auth, result = await stack.core.call_tool(
        sonda(stack), "red.runbooks.conmutar_respaldo", {"nodo": node}, run_id="R1", incident=fault.id
    )
    assert auth.decision.verdict == Verdict.APROBACION and result is None
    assert not stack.sim.state.node_has_service(node)  # nada se ejecuta sin aprobación
    pending = await stack.core.approvals(status="pendiente")
    assert len(pending) == 1 and pending[0].twin_ok is True
    done = await stack.core.decide(pending[0].id, approve=True, comment="adelante")
    assert done.status == "aprobada"
    assert stack.sim.state.node_has_service(node)
    rows = await stack.core.audit.list(incident=fault.id)
    executed = [r for r in rows if r.decision == "ejecutada tras aprobación"]
    assert executed and executed[0].approved_by == "Operador NOC"
    with pytest.raises(ApprovalError):
        await stack.core.decide(pending[0].id, approve=True)


async def test_gemelo_frena_lo_que_no_funcionaria(stack: Stack) -> None:
    fault = stack.sim.inject(FaultType.CAIDA_ENLACE, with_backup=False)
    auth, _ = await stack.core.call_tool(
        sonda(stack), "red.runbooks.conmutar_respaldo", {"nodo": fault.node}, run_id="R1", incident=fault.id
    )
    assert auth.approval_id is None
    assert await stack.core.approvals(status="pendiente") == []


async def test_rechazo_no_ejecuta(stack: Stack) -> None:
    fault = stack.sim.inject(FaultType.CAIDA_ENLACE, with_backup=True)
    await stack.core.call_tool(
        sonda(stack), "red.runbooks.conmutar_respaldo", {"nodo": fault.node}, run_id="R1", incident=fault.id
    )
    pending = await stack.core.approvals(status="pendiente")
    await stack.core.decide(pending[0].id, approve=False, comment="no ahora")
    assert not stack.sim.state.node_has_service(fault.node or "")


async def test_nivel_2_ejecuta_y_cuenta_para_el_ritmo(stack: Stack) -> None:
    fault = stack.sim.inject(FaultType.CAIDA_ENLACE, with_backup=True)
    await stack.core.set_blast_radius(100_000)
    bombero = sonda(
        stack, autonomia=2, limites=stack.agents["00"].config.limites.model_copy(update={"acciones_hora": 1})
    )
    auth, result = await stack.core.call_tool(
        bombero, "red.runbooks.conmutar_respaldo", {"nodo": fault.node}, run_id="R1", incident=fault.id
    )
    assert auth.allowed and result is not None and result.ok
    auth2, _ = await stack.core.call_tool(
        bombero, "red.runbooks.conmutar_respaldo", {"nodo": fault.node}, run_id="R2", incident=fault.id
    )
    assert auth2.decision.verdict == Verdict.PAUSA
    assert await stack.core.is_paused("00_sonda")


async def test_interruptor_general(stack: Stack) -> None:
    fault = stack.sim.inject(FaultType.CAIDA_ENLACE, with_backup=True)
    await stack.core.set_kill_switch(True)
    bombero = sonda(stack, autonomia=2)
    auth, result = await stack.core.call_tool(
        bombero, "red.runbooks.conmutar_respaldo", {"nodo": fault.node}, run_id="R1", incident=fault.id
    )
    assert auth.decision.verdict == Verdict.PROPUESTA and result is None
    assert not stack.sim.state.node_has_service(fault.node or "")


def test_salida_de_agente_se_valida() -> None:
    with pytest.raises(ValidationError):
        AgentOutput.model_validate({"resumen": "", "confianza": 2})
    with pytest.raises(ValidationError):
        AgentOutput.model_validate({"resumen": "ok", "confianza": 0.5, "campo_extra": 1})
