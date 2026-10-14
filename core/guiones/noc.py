"""Guiones de los agentes 01–08 (NOC). Siguen su prompt; el núcleo los controla igual que a Claude."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from core.agent import ScriptContext, script
from core.schemas import AgentOutput

TRANSIENT = {"FLAP_1S", "TEMP_TRANSITORIA", "PUERTA_ABIERTA", "LOS_TRANSITORIO"}
POWER = {"MAINS_FAIL", "BATTERY_DISCHARGING"}
LINK = {"LINK_DOWN", "CELL_UNAVAILABLE"}
CARD = {"CARD_BER_HIGH", "CRC_ERRORS"}
SIBLING_WINDOW = timedelta(minutes=30)


def parse(text: str) -> Any:
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return {}


@script("01_centinela")
async def centinela(ctx: ScriptContext) -> AgentOutput:
    alarm = ctx.event.payload
    aid, code, node, zone = str(alarm["id"]), str(alarm["code"]), alarm.get("node"), str(alarm["zone"])
    _, text = await ctx.call(
        "red.alarmas.listar",
        {"limite": 15, "nodo": node} if node else {"limite": 15, "zona": zone},
        reasoning="Busco alarmas hermanas en el mismo nodo para distinguir ruido de un fallo real.",
    )
    siblings = [a for a in parse(text) or [] if isinstance(a, dict) and a.get("id") != aid]
    raised = datetime.fromisoformat(str(alarm["raised_at"]))
    serious = [
        a
        for a in siblings
        if a.get("severity") in ("mayor", "critica")
        and abs(datetime.fromisoformat(str(a["raised_at"])) - raised) <= SIBLING_WINDOW
    ]
    if alarm.get("severity") == "menor" and code in TRANSIENT and not serious:
        motive = f"{code} menor y transitoria, sin alarmas mayores en {node or zone}."
        verdict, _ = await ctx.call("red.alarmas.descartar", {"alarma": aid, "motivo": motive}, reasoning=motive)
        return AgentOutput(
            resumen=f"{aid} descartada: {motive}",
            evidencias=[aid],
            accion_propuesta="red.alarmas.descartar",
            confianza=0.88,
        )
    key = f"ZONA-{zone}" if code in POWER or not node else str(node)
    verdict, text = await ctx.call(
        "red.alarmas.agrupar",
        {"alarma": aid, "clave": key},
        reasoning=f"{code} ({alarm.get('severity')}) con {len(serious)} alarmas mayores cerca: fallo real.",
    )
    group = parse(text).get("grupo", "")
    return AgentOutput(
        resumen=f"{aid} {code} agrupada en {group or key} ({verdict}).",
        evidencias=[aid, str(group or key)],
        accion_propuesta="red.alarmas.agrupar",
        confianza=0.9,
    )


@script("02_triaje")
async def triaje(ctx: ScriptContext) -> AgentOutput:
    group_id = str(ctx.event.payload["group"])
    _, text = await ctx.call("tickets.grupo_alarmas", {"grupo": group_id}, reasoning="Leo códigos y alcance del grupo.")
    group = parse(text)
    if not group or "error" in group:
        return AgentOutput(resumen=f"No puedo leer {group_id}: no abro ticket.", evidencias=[group_id], confianza=0.5)
    codes, node, zone = set(group["codes"]), group.get("node"), str(group["zone"])
    power = bool(codes & POWER)
    _, text = await ctx.call(
        "tickets.buscar",
        {"grupo": group_id} if power or not node else {"nodo": node},
        reasoning="Evito tickets duplicados.",
    )
    existing = parse(text)
    if existing.get("id"):
        await ctx.call("tickets.actualizar", {"ticket": existing["id"], "nota": f"Grupo {group_id} añadido."})
        return AgentOutput(
            resumen=f"{group_id} añadido a {existing['id']}: no duplico.",
            evidencias=[group_id, existing["id"]],
            confianza=0.9,
        )
    scope_args = {"zona": zone} if power or not node else {"nodo": node}
    _, text = await ctx.call("inventario.clientes_afectados", scope_args, reasoning="Calculo el alcance.")
    scope = parse(text)
    ftth, enterprises = int(scope.get("ftth", 0)), scope.get("empresas", [])
    if codes & LINK:
        diagnosis = f"Caída del enlace principal de {node}"
    elif codes & CARD:
        diagnosis = f"Tarjeta de línea degradada en {node}"
    elif power:
        diagnosis = f"Fallo de alimentación en la zona {zone}"
    else:
        diagnosis = f"Alarmas {', '.join(sorted(codes))} en {node or zone}"
    if ftth > 1000 or any(e.get("sla") == 99.99 for e in enterprises):
        priority = "P1"
    elif ftth > 300 or enterprises:
        priority = "P2"
    else:
        priority = "P3"
    args: dict[str, Any] = {
        "prioridad": priority,
        "diagnostico": diagnosis,
        "zona": zone,
        "grupo": group_id,
        "codigos": sorted(codes),
        "clientes_ftth": ftth,
        "empresas": [e["id"] for e in enterprises],
    }
    if node and not power:
        args["nodo"] = node
    verdict, text = await ctx.call(
        "tickets.crear", args, reasoning=f"{priority}: {ftth} FTTH, {len(enterprises)} empresas."
    )
    ticket = parse(text).get("ticket", "")
    return AgentOutput(
        resumen=f"{ticket or 'Ticket'} {priority}: {diagnosis} ({ftth} FTTH, {len(enterprises)} empresas). {verdict}.",
        evidencias=[group_id, *sorted(codes)],
        accion_propuesta="tickets.crear",
        confianza=0.9,
    )


@script("03_bombero")
async def bombero(ctx: ScriptContext) -> AgentOutput:
    p = ctx.event.payload
    ticket, node, codes = str(p["ticket"]), p.get("node"), list(p.get("codes") or [])
    main = next((c for c in ("LINK_DOWN", "CARD_BER_HIGH", "MAINS_FAIL") if c in codes), codes[0] if codes else "")
    args: dict[str, Any] = {"codigo_alarma": main}
    if node:
        args["nodo"] = node
    _, text = await ctx.call("red.runbooks.consultar", args, reasoning="Busco una solución conocida y reversible.")
    rb = parse(text)

    async def escalate(reason: str) -> AgentOutput:
        verdict, _ = await ctx.call("red.runbooks.escalar", {"ticket": ticket, "motivo": reason}, reasoning=reason)
        return AgentOutput(
            resumen=f"{ticket} escalado: {reason} ({verdict}).",
            evidencias=[ticket, str(node), rb.get("runbook", "")],
            accion_propuesta="red.runbooks.escalar",
            confianza=0.85,
        )

    if not rb.get("aplicable"):
        return await escalate(str(rb.get("motivo") or rb.get("procedimiento") or "sin runbook aplicable"))
    tool = "red.runbooks." + str(rb["accion"]).split("__", 1)[1]
    verdict, text = await ctx.call(
        tool,
        {"nodo": node, "ticket": ticket},
        reasoning=f"{rb['runbook']}: {rb.get('motivo')}",
        evidence=[f"Ticket {ticket}", f"Runbook {rb['runbook']}", str(rb.get("motivo"))],
    )
    if verdict == "ejecutada":
        result = parse(text)
        if result.get("ok"):
            return AgentOutput(
                resumen=f"{rb['runbook']} aplicado en {node}: {result.get('detail')}",
                evidencias=[ticket, str(node)],
                accion_propuesta=tool,
                confianza=0.92,
            )
        return await escalate(f"el runbook falló: {result.get('detail')}")
    if verdict == "en cola de aprobación":
        return AgentOutput(
            resumen=f"{tool} en {node} espera aprobación humana. {text[:160]}",
            evidencias=[ticket, str(node)],
            accion_propuesta=tool,
            confianza=0.9,
        )
    if verdict == "propuesta":
        return AgentOutput(
            resumen=f"Propongo {tool} en {node}; el interruptor general impide ejecutarlo.",
            evidencias=[ticket, str(node)],
            accion_propuesta=tool,
            confianza=0.8,
        )
    return await escalate(f"la acción quedó «{verdict}»")


@script("04_escalador")
async def escalador(ctx: ScriptContext) -> AgentOutput:
    p = ctx.event.payload
    ticket = str(p["ticket"])
    _, text = await ctx.call("notificaciones.guardia", {}, reasoning="Elijo a quién avisar según la hora.")
    person = str(parse(text).get("persona", "Guardia del NOC"))
    summary = (
        f"{ticket} {p.get('priority')} · {p.get('diagnosis')} ({p.get('node') or p.get('zone')}).\n"
        f"No resuelto en remoto: {str(p.get('reason')).rstrip('.')}.\nHace falta intervención en campo."
    )
    verdict, text = await ctx.call(
        "notificaciones.avisar",
        {"ticket": ticket, "persona": person, "resumen": summary},
        reasoning="Ticket sin solución remota.",
    )
    page = parse(text).get("aviso", "")
    return AgentOutput(
        resumen=f"Aviso {page} a {person} por {ticket} ({verdict}).",
        evidencias=[ticket, str(page)],
        accion_propuesta="notificaciones.avisar",
        confianza=0.93,
        requiere_persona=True,
    )


@script("05_forense")
async def forense(ctx: ScriptContext) -> AgentOutput:
    ticket = str(ctx.event.payload["ticket"])
    _, text = await ctx.call(
        "tickets.obtener", {"ticket": ticket}, reasoning="Reconstruyo qué pasó y cómo se resolvió."
    )
    tk = parse(text)
    if not tk or "error" in tk:
        return AgentOutput(resumen=f"No puedo leer {ticket}: causa no determinada.", evidencias=[ticket], confianza=0.3)
    node, zone = tk.get("node"), tk.get("zone")
    _, text = await ctx.call(
        "red.historico.incidente",
        {"nodo": node} if node else {"zona": zone},
        reasoning="Contrasto con el estado de la red.",
    )
    hist = parse(text)
    notes = " ".join(n.get("text", "") for n in tk.get("notes", []))
    codes = set(tk.get("codes", []))
    links_down = hist.get("nodo", {}).get("on_backup") and "Runbook aplicado" in notes
    power = hist.get("energia", {})
    if codes & POWER or power.get("outage"):
        cause = "causa externa: corte del suministro eléctrico" + (
            " por tormenta" if hist.get("meteo", {}).get("storm") else ""
        )
        fix = "Revisar la autonomía de baterías de los emplazamientos de la zona."
    elif codes & LINK and links_down:
        cause = "corte físico en el tramo del enlace principal (sigue caído tras conmutar al respaldo)"
        fix = "Enviar brigada a localizar el corte con OTDR y volver al principal tras repararlo."
    elif codes & LINK:
        cause = "caída del enlace principal sin respaldo; reparado en campo"
        fix = "Añadir enlace de respaldo a este nodo."
    elif codes & CARD and "Runbook aplicado" in notes:
        cause = "degradación transitoria de la tarjeta de línea, resuelta con reinicio"
        fix = "Vigilar BER 24 h y sustituir la tarjeta si se repite."
    else:
        cause = "causa no determinada con los datos disponibles"
        fix = "Revisión manual del incidente."
    alarm_ids = [a.get("id") for a in hist.get("alarmas", [])[:3] if isinstance(a, dict)]
    return AgentOutput(
        resumen=f"Informe {ticket}: {cause}.",
        evidencias=[ticket, str(node or zone), *map(str, alarm_ids)],
        accion_propuesta=fix,
        confianza=0.75 if "no determinada" not in cause else 0.4,
    )


@script("06_guardian_sla")
async def guardian_sla(ctx: ScriptContext) -> AgentOutput:
    _, text = await ctx.call("tickets.abiertos", {}, reasoning="Reviso tickets abiertos con clientes empresa.")
    tickets = parse(text) or []
    if not tickets:
        return AgentOutput(resumen="Ningún ticket abierto afecta a clientes empresa.", confianza=0.97)
    ids = sorted({e for t in tickets for e in t["empresas"]})
    _, text = await ctx.call("contratos.sla", {"clientes": ids}, reasoning="Necesito los plazos de respuesta.")
    sla = {c["id"]: c for c in parse(text) or []}
    alerts = []
    for t in tickets:
        if t["alerta_sla_enviada"]:
            continue
        customers = [sla[e] for e in t["empresas"] if e in sla]
        if not customers:
            continue
        worst = min(customers, key=lambda c: c["respuesta_horas"])
        pct = round(100 * t["minutos_abierto"] / (worst["respuesta_horas"] * 60))
        if pct >= 50:
            await ctx.call(
                "tickets.alerta_sla",
                {"ticket": t["ticket"], "cliente": worst["nombre"], "porcentaje": pct},
                reasoning=f"SLA {worst['sla']} %: respuesta en {worst['respuesta_horas']} h.",
            )
            alerts.append(t["ticket"])
    return AgentOutput(
        resumen=f"{len(tickets)} tickets con empresas revisados; {len(alerts)} alertas de SLA.",
        evidencias=[t["ticket"] for t in tickets],
        accion_propuesta="tickets.alerta_sla" if alerts else None,
        confianza=0.93,
    )


@script("07_gestor_cambios")
async def gestor_cambios(ctx: ScriptContext) -> AgentOutput:
    p = ctx.event.payload
    start, end = datetime.fromisoformat(str(p["starts_at"])), datetime.fromisoformat(str(p["ends_at"]))
    _, text = await ctx.call(
        "cambios.calendario",
        {"desde": start.isoformat(), "hasta": end.isoformat()},
        reasoning="Busco cambios que se solapen con la ventana pedida.",
    )
    planned = parse(text) or []
    same_node = [c for c in planned if p.get("node") and c.get("node") == p.get("node")]
    same_zone = [c for c in planned if c.get("zone") == p.get("zone") and c not in same_node]
    if same_node or same_zone:
        c = (same_node or same_zone)[0]
        why = "el mismo nodo" if same_node else "la misma zona"
        alt = datetime.fromisoformat(c["ends_at"]) + timedelta(hours=1)
        return AgentOutput(
            resumen=f"Conflicto: {c['id']} «{c['title']}» toca {why} en la misma ventana.",
            evidencias=[c["id"] for c in same_node + same_zone],
            accion_propuesta=f"Mover la ventana a partir de {alt.isoformat()}",
            confianza=0.9,
        )
    return AgentOutput(
        resumen=f"Sin conflictos: la ventana {start:%d/%m %H:%M}–{end:%H:%M} está libre en {p.get('zone')}.",
        accion_propuesta="aprobar",
        confianza=0.9,
    )


@script("08_meteorologo")
async def meteorologo(ctx: ScriptContext) -> AgentOutput:
    p = ctx.event.payload
    group, zone = str(p["group"]), str(p["zone"])
    _, w = await ctx.call("meteo_sim.zona.consultar", {"zona": zone}, reasoning="¿Hay tormenta en la zona?")
    _, e = await ctx.call("energia_sim.zona.consultar", {"zona": zone}, reasoning="¿Hay corte de luz?")
    weather, power = parse(w), parse(e)
    if weather.get("storm") or power.get("outage"):
        cause = (
            "tormenta y corte de luz"
            if weather.get("storm") and power.get("outage")
            else "tormenta"
            if weather.get("storm")
            else "corte de luz"
        )
        return AgentOutput(
            resumen=f"{group} en {zone}: causa externa probable ({cause}).",
            evidencias=[weather.get("detail", ""), power.get("detail", "")],
            accion_propuesta=f"Causa externa probable: {cause}",
            confianza=0.9,
        )
    return AgentOutput(
        resumen=f"{group} en {zone}: sin causa externa (tiempo y suministro normales).",
        evidencias=[weather.get("detail", ""), power.get("detail", "")],
        confianza=0.88,
    )
