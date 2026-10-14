"""Guiones de los agentes 26–40 (empresas, planificación, seguridad y gestión)."""

from __future__ import annotations

import json
from typing import Any

from core.agent import ScriptContext, script
from core.schemas import AgentOutput


def parse(text: str) -> Any:
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return {}


def out(
    resumen: str,
    evidencias: list[str] | None = None,
    accion: str | None = None,
    conf: float = 0.85,
    persona: bool = False,
) -> AgentOutput:
    return AgentOutput(
        resumen=resumen,
        evidencias=[str(e) for e in evidencias or []],
        accion_propuesta=accion,
        confianza=conf,
        requiere_persona=persona,
    )


def outcome(verdict: str, text: str) -> str:
    if verdict == "ejecutada":
        return "hecho"
    if verdict == "en cola de aprobación":
        return "en cola de aprobación"
    return f"{verdict}: {text[:120]}"


# ---------------------------------------------------------------- empresas
@script("26_preventa")
async def preventa(ctx: ScriptContext) -> AgentOutput:
    p = ctx.event.payload
    _, text = await ctx.call("catalogo.precios", {"servicio": p["servicio"]}, reasoning="Precio de catálogo.")
    price = parse(text)
    if "error" in price:
        return out(f"{p['servicio']} no está en el catálogo: lo estudia una persona.", [p["cliente"]], conf=0.6)
    _, text = await ctx.call("red.capacidad.zona", {"zona": p["zona"]}, reasoning="¿Hay capacidad en la zona?")
    cap = parse(text)
    total = int(price["eur_mes_por_sede"]) * int(p["sedes"])
    verdict, msg = await ctx.call(
        "catalogo.enviar_oferta",
        {"cliente": p["cliente"], "servicio": p["servicio"], "sedes": int(p["sedes"]), "importe_mensual": total},
        reasoning=f"Catálogo {price['eur_mes_por_sede']} €/sede; carga pico de la zona "
        f"{cap.get('carga_pico_normal_pct')} %.",
        evidence=[f"{p['sedes']} sedes de {p['servicio']}", f"{total} €/mes", f"Zona {p['zona']}"],
    )
    return out(
        f"Solución para {p['cliente']}: {p['servicio']} en {p['sedes']} sedes por {total} €/mes; "
        f"oferta {outcome(verdict, msg)}.",
        [p["cliente"]],
        "catalogo.enviar_oferta",
        0.88,
    )


@script("27_aprovisionador")
async def aprovisionador(ctx: ScriptContext) -> AgentOutput:
    p = ctx.event.payload
    _, text = await ctx.call("inventario.puertos", {"nodo": p["nodo"]}, reasoning="Puertos y VLAN libres.")
    ports = parse(text)
    if "error" in ports or not ports.get("vlans_libres_sugeridas"):
        return out(f"Sin puertos libres en {p['nodo']}: lo resuelve ingeniería.", [p["nodo"]], conf=0.6)
    vlan = int(p.get("vlan") or ports["vlans_libres_sugeridas"][0])
    verdict, msg = await ctx.call(
        "red.config.alta_servicio",
        {"cliente": p["cliente"], "servicio": p["servicio"], "nodo": p["nodo"], "vlan": vlan},
        reasoning="Alta con plantilla de servicio; VLAN libre según inventario.",
        evidence=[f"{p['nodo']} con {ports.get('puertos_10g_libres')} puertos libres", f"VLAN {vlan}"],
    )
    return out(
        f"Alta de {p['servicio']} para {p['cliente']} en {p['nodo']} (VLAN {vlan}): {outcome(verdict, msg)}.",
        [p["nodo"], str(vlan)],
        "red.config.alta_servicio",
        0.87,
    )


@script("28_soporte_2_nivel")
async def soporte(ctx: ScriptContext) -> AgentOutput:
    ticket = str(ctx.event.payload["ticket"])
    _, text = await ctx.call("tickets.obtener", {"ticket": ticket}, reasoning="Qué le pasa al cliente empresa.")
    tk = parse(text)
    if "error" in tk:
        return out(f"{ticket} no existe.", [ticket], conf=0.5)
    state = "sin datos de nodo"
    if tk.get("node"):
        _, s = await ctx.call("red.estado.nodo", {"nodo": tk["node"]}, reasoning="Estado actual del servicio.")
        state = "servicio restablecido" if parse(s).get("con_servicio") else "afectación en curso"
    note = f"Informadas {len(tk['enterprises'])} empresas ({state}); próxima actualización en 30 min."
    verdict, _ = await ctx.call(
        "tickets.actualizar",
        {"ticket": ticket, "nota": note},
        reasoning="El cliente empresa necesita estado y estimación.",
    )
    return out(f"{ticket}: {note} ({verdict}).", [ticket, *tk["enterprises"][:3]], "tickets.actualizar", 0.9)


@script("29_redactor_informes")
async def redactor(ctx: ScriptContext) -> AgentOutput:
    _, text = await ctx.call("contratos.disponibilidad", {}, reasoning="Disponibilidad del mes por cliente.")
    rows = parse(text) or []
    await ctx.call("red.kpis.zona", {"zona": "CEN"}, reasoning="Consumo de referencia de la red.")
    fails = [r for r in rows if not r["cumple"]]
    average = round(sum(r["disponibilidad"] for r in rows) / max(1, len(rows)), 3)
    summary = (
        f"{len(rows)} clientes; disponibilidad media {average} %; "
        f"{len(fails)} por debajo de su SLA."
    )
    verdict, _ = await ctx.call(
        "contratos.enviar_informes",
        {"mes": str(ctx.event.payload.get("mes", "mes anterior")), "resumen": summary},
        reasoning="Informe mensual contractual.",
    )
    return out(
        f"Informes mensuales enviados ({verdict}): {summary}",
        [r["id"] for r in fails[:5]],
        "contratos.enviar_informes",
        0.92,
    )


@script("30_licitador")
async def licitador(ctx: ScriptContext) -> AgentOutput:
    p = ctx.event.payload
    _, text = await ctx.call("documentos.pliego", {"lote": p["lote"]}, reasoning="Extraigo los requisitos técnicos.")
    tender = parse(text)
    reqs = tender.get("requisitos", [])
    ok = [r for r in reqs if r["cumplimos"]]
    gaps = [r["requisito"] for r in reqs if not r["cumplimos"]]
    resumen = (
        f"Oferta técnica para «{p['lote']}»: cumple {len(ok)} de {len(reqs)} requisitos. "
        f"Alternativa para: {'; '.join(gaps) or 'ninguno'}."
    )
    verdict, msg = await ctx.call(
        "documentos.presentar_oferta_tecnica",
        {"lote": p["lote"], "resumen": resumen, "requisitos_cumplidos": len(ok)},
        reasoning=f"Pliego de {tender.get('paginas')} páginas analizado.",
        evidence=[r["id"] for r in reqs[:4]],
    )
    return out(
        f"{resumen} Presentación {outcome(verdict, msg)}.", [p["lote"]], "documentos.presentar_oferta_tecnica", 0.82
    )


# ---------------------------------------------------------------- planificación
@script("31_estratega_5g")
async def estratega(ctx: ScriptContext) -> AgentOutput:
    _, a = await ctx.call("red.trafico.zonas", {}, reasoning="Demanda por zona.")
    _, b = await ctx.call("mercado_sim.comparativa", {}, reasoning="Dónde nos gana la competencia.")
    load, market = parse(a) or [], {m["zone"]: m for m in parse(b) or []}
    scored = sorted(
        load, key=lambda z: -(z["carga_pico_pct"] + 2 * market.get(z["zona"], {}).get("desventaja_cobertura", 0))
    )
    top = scored[:2]
    text = "; ".join(
        f"{z['nombre']} (carga {z['carga_pico_pct']} %, desventaja de cobertura "
        f"{market.get(z['zona'], {}).get('desventaja_cobertura', 0)} puntos)"
        for z in top
    )
    return out(
        f"Propuesta de 3 emplazamientos 5G en {top[0]['nombre']} y 2 en {top[1]['nombre']}: {text}.",
        [z["zona"] for z in top],
        "Publicar plan.proposed para el Analista de inversiones",
        0.78,
    )


@script("32_analista_inversiones")
async def analista(ctx: ScriptContext) -> AgentOutput:
    p = ctx.event.payload
    _, text = await ctx.call(
        "finanzas_sim.modelo",
        {"zona": p["zona"], "emplazamientos": int(p["emplazamientos"])},
        reasoning="Inversión, ingresos y retorno.",
    )
    m = parse(text)
    if "error" in m:
        return out(f"No hay modelo para {p['zona']}.", [p["zona"]], conf=0.5)
    verdict = "rentable" if m["retorno_meses"] and m["retorno_meses"] <= 36 else "retorno largo, revisar"
    return out(
        f"{m['emplazamientos']} emplazamientos en {p['zona']}: {m['capex_eur']} € de inversión, "
        f"{m['ingresos_mensuales_eur']} €/mes, retorno en {m['retorno_meses']} meses ({verdict}).",
        [p["zona"]],
        verdict,
        0.76,
    )


@script("33_negociador_emplazamientos")
async def negociador(ctx: ScriptContext) -> AgentOutput:
    site = str(ctx.event.payload["emplazamiento"])
    _, text = await ctx.call("contratos.alquiler", {"emplazamiento": site}, reasoning="Contrato vigente.")
    c = parse(text)
    if "error" in c:
        return out(f"{site} no existe.", [site], conf=0.5, persona=True)
    proposal = int(c["renta_mercado_eur"])
    resumen = (
        f"{c['owner']}: renta actual {c['rent_eur']} €/mes, vence en {c['dias_para_vencer']} días. "
        f"Propuesta: {proposal} €/mes a 5 años con revisión por IPC."
    )
    verdict, msg = await ctx.call(
        "contratos.entregar_borrador_renovacion",
        {"emplazamiento": site, "propuesta_eur": proposal, "resumen": resumen},
        reasoning="La negociación con la comunidad es de una persona.",
    )
    return out(
        f"Borrador de renovación de {site} a {proposal} €/mes entregado a patrimonio ({verdict}).",
        [site],
        "Negociación y firma por una persona",
        0.82,
        persona=True,
    )


@script("34_proyectista")
async def proyectista(ctx: ScriptContext) -> AgentOutput:
    p = ctx.event.payload
    await ctx.call("documentos.plantilla", {"tipo": "proyecto técnico"}, reasoning="Estructura del proyecto.")
    contenido = (
        f"Proyecto técnico de {p['proyecto']}: red FTTH para {p.get('viviendas')} viviendas en {p['zona']}. "
        "Memoria, cálculos de potencia óptica, planos y pliego de condiciones."
    )
    verdict, _ = await ctx.call(
        "documentos.entregar_borrador",
        {
            "tipo": "proyecto",
            "titulo": f"Proyecto técnico {p['proyecto']}",
            "contenido": contenido,
            "responsable": "Ingeniero colegiado",
        },
        reasoning="La firma del proyecto visado es de un ingeniero colegiado.",
    )
    return out(
        f"Borrador del proyecto {p['proyecto']} entregado para firma ({verdict}).",
        [p["proyecto"]],
        "Firma de un ingeniero colegiado",
        0.84,
        persona=True,
    )


@script("35_espia")
async def espia(ctx: ScriptContext) -> AgentOutput:
    _, text = await ctx.call("mercado_sim.comparativa", {}, reasoning="Cobertura y velocidad frente a la competencia.")
    rows = parse(text) or []
    behind = [r for r in rows if r["desventaja_cobertura"] > 0 or r["desventaja_velocidad"] > 0]
    ahead = [r["zone"] for r in rows if r not in behind]
    worst = behind[0] if behind else None
    lost = ", ".join(r["zone"] for r in behind)
    tail = (
        f" Peor zona: {worst['zone']} ({worst['desventaja_cobertura']:+} puntos de cobertura, "
        f"{worst['desventaja_velocidad']:+} Mbps)."
        if worst
        else ""
    )
    return out(
        f"Ganamos en {', '.join(ahead) or 'ninguna zona'}; perdemos en {lost or 'ninguna'}.{tail}",
        [r["zone"] for r in behind],
        "Priorizar las zonas perdidas en el plan 5G",
        0.8,
    )


# ---------------------------------------------------------------- seguridad
@script("36_escudo")
async def escudo(ctx: ScriptContext) -> AgentOutput:
    target = str(ctx.event.payload["target"])
    _, text = await ctx.call("red.trafico.flujos", {"destino": target}, reasoning="Separo ataque de tráfico legítimo.")
    flows = parse(text)
    if not flows.get("ataque"):
        return out(f"Tráfico hacia {target} normal: no hay ataque.", [target], conf=0.85)
    verdict, msg = await ctx.call(
        "red.filtros.aplicar_filtro_temporal",
        {"destino": target},
        reasoning="Filtro reversible que caduca solo en 2 h.",
        evidence=[f"{flows.get('gbps')} Gbps de {flows.get('tipo')}", f"{flows.get('origenes')} orígenes"],
    )
    return out(
        f"Ataque contra {target} ({flows.get('gbps')} Gbps, {flows.get('tipo')}): filtro {outcome(verdict, msg)}.",
        [target],
        "red.filtros.aplicar_filtro_temporal",
        0.93,
    )


@script("37_cazavulnerabilidades")
async def cazavulnerabilidades(ctx: ScriptContext) -> AgentOutput:
    p = ctx.event.payload
    _, text = await ctx.call(
        "inventario.por_fabricante", {"fabricante": p["fabricante"]}, reasoning="Equipos afectados."
    )
    nodes = parse(text) or []
    cvss = float(p.get("cvss", 7))
    prio = "crítica" if cvss >= 9 else "alta" if cvss >= 7 else "media"
    core = [n["nodo"] for n in nodes if n["tipo"] in ("core", "agg")]
    return out(
        f"{p['cve']} (CVSS {cvss}) afecta a {len(nodes)} equipos de {p['fabricante']}; prioridad {prio}. "
        f"Primero núcleo y agregación: {', '.join(core) or 'ninguno'}.",
        [n["nodo"] for n in nodes[:6]],
        "Pedir el parche al fabricante y planificarlo con el Gestor de actualizaciones",
        0.9,
    )


@script("38_cumplidor")
async def cumplidor(ctx: ScriptContext) -> AgentOutput:
    _, text = await ctx.call("auditoria.resumen", {}, reasoning="Trazabilidad del periodo.")
    a = parse(text)
    contenido = (
        f"Informe regulatorio: {a.get('registros')} registros de auditoría, {a.get('acciones_ejecutadas')} "
        f"acciones ejecutadas, {a.get('bloqueos')} bloqueos del núcleo y {a.get('decisiones_humanas')} "
        "decisiones humanas trazadas."
    )
    verdict, _ = await ctx.call(
        "documentos.entregar_borrador",
        {
            "tipo": "informe_regulatorio",
            "titulo": "Informe regulatorio mensual",
            "contenido": contenido,
            "responsable": "Responsable regulatorio",
        },
        reasoning="El responsable ante el regulador es una persona.",
    )
    return out(
        f"Borrador de informe regulatorio entregado para firma ({verdict}).",
        [],
        "Firma del responsable regulatorio",
        0.88,
        persona=True,
    )


# ---------------------------------------------------------------- gestión
@script("39_bibliotecario")
async def bibliotecario(ctx: ScriptContext) -> AgentOutput:
    ticket = str(ctx.event.payload["ticket"])
    resolution = str(ctx.event.payload.get("resolution", ""))
    low = resolution.lower()
    kind = (
        "caida_enlace"
        if any(k in low for k in ("tráfico de", "respaldo", "enlace"))
        else "tarjeta"
        if "tarjeta" in low
        else "energia"
        if any(k in low for k in ("energía", "agg-"))
        else ""
    )
    if not kind:
        return out(f"{ticket}: nada que añadir a los procedimientos.", [ticket], conf=0.85)
    _, text = await ctx.call("documentos.buscar_procedimiento", {"tipo": kind}, reasoning="Procedimiento vigente.")
    proc = parse(text)
    verdict, _ = await ctx.call(
        "documentos.publicar_procedimiento",
        {
            "titulo": f"{proc.get('procedimiento')} v{proc.get('versiones')}",
            "cambios": f"Lecciones de {ticket}: {resolution[:200]}",
            "tipo": kind,
        },
        reasoning="Incorporar lo aprendido en el incidente.",
    )
    return out(
        f"«{proc.get('procedimiento')}» actualizado con {ticket} ({verdict}).",
        [ticket],
        "documentos.publicar_procedimiento",
        0.9,
    )


@script("40_director_orquesta")
async def director(ctx: ScriptContext) -> AgentOutput:
    _, text = await ctx.call("panel.resumen", {}, reasoning="Estado de los 39 agentes y de las personas.")
    s = parse(text)
    tickets = sorted(s.get("tickets_abiertos", []), key=lambda t: t["prioridad"])
    prios = [f"{t['id']} {t['prioridad']} · {t['diagnostico']}" for t in tickets]
    if s.get("aprobaciones_pendientes"):
        prios.append(f"{s['aprobaciones_pendientes']} aprobaciones esperando a una persona")
    if s.get("avisos_guardia"):
        prios.append(f"{s['avisos_guardia']} avisos de guardia abiertos")
    if s.get("agentes_en_pausa"):
        prios.append(f"Agentes en pausa: {', '.join(s['agentes_en_pausa'])}")
    if not prios:
        prios = ["Sin prioridades abiertas: la red funciona con normalidad."]
    at = str(ctx.event.payload.get("at", ""))
    if at[11:16] == "08:00":
        await ctx.call(
            "panel.entregar_resumen", {"resumen": " · ".join(prios)}, reasoning="Resumen diario a dirección."
        )
    return out(prios[0], [], None, 0.9, persona=True)
