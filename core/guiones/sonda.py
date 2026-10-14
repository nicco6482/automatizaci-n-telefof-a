"""Guion de 00_sonda."""

from __future__ import annotations

import json

from core.agent import ScriptContext, script
from core.schemas import AgentOutput


@script("00_sonda")
async def sonda(ctx: ScriptContext) -> AgentOutput:
    alarm = ctx.event.payload
    if alarm.get("code") != "LINK_DOWN":
        return AgentOutput(
            resumen=f"{alarm.get('code')} en {alarm.get('cell') or alarm.get('node')}: no es "
            "una caída de enlace, no hago nada.",
            evidencias=[str(alarm.get("id"))],
            confianza=0.9,
        )
    node = str(alarm["node"])
    _, alarms = await ctx.call(
        "red.alarmas.listar",
        {"limite": 10, "nodo": node},
        reasoning="Confirmo que la caída sigue activa y veo qué alarmas la acompañan.",
    )
    _, state_text = await ctx.call("red.estado.nodo", {"nodo": node}, reasoning="Necesito saber si hay respaldo.")
    state = json.loads(state_text)

    if ctx.event.payload.get("_probar_lista_blanca"):
        await ctx.call(
            "red.config.escribir",
            {"nodo": node, "cambio": "shutdown"},
            reasoning="Prueba de seguridad: herramienta fuera de la lista blanca.",
        )

    await ctx.call("red.runbooks.consultar", {"codigo_alarma": "LINK_DOWN"}, reasoning="Busco el procedimiento.")
    evidencias = [str(alarm["id"]), node]
    if not state.get("backup_link"):
        return AgentOutput(
            resumen=f"{node} sin enlace de respaldo: hay que escalar a guardia.",
            evidencias=evidencias,
            accion_propuesta="Escalar a guardia",
            confianza=0.85,
            requiere_persona=True,
        )
    verdict, message = await ctx.call(
        "red.runbooks.conmutar_respaldo",
        {"nodo": node},
        reasoning=f"RB-01: principal {state.get('primary_link')} caído y respaldo "
        f"{state.get('backup_link')} disponible.",
        evidence=[
            f"{state.get('primary_link')} caído",
            f"respaldo {state.get('backup_link')}",
            f"{state.get('ftth_clients')} clientes FTTH",
        ],
    )
    return AgentOutput(
        resumen=f"Conmutación de {node} a {state.get('backup_link')}: {verdict}. {message[:200]}",
        evidencias=evidencias + [str(state.get("backup_link"))],
        accion_propuesta="red.runbooks.conmutar_respaldo",
        confianza=0.9,
    )
