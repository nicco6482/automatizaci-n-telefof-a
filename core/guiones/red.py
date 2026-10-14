"""Guiones de los agentes 09–25 (móvil, fibra y núcleo). Siguen su prompt; el núcleo los controla igual que a Claude."""

from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from core.agent import ScriptContext, script
from core.schemas import AgentOutput

ZONES = ["CEN", "TRI", "CAR", "MAC", "NER", "EST", "REM", "SUR"]


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
        return "ejecutado"
    if verdict == "en cola de aprobación":
        return "en cola de aprobación"
    if "gemelo" in text.lower() and "rechaza" in text.lower():
        return f"rechazado por el gemelo ({text[:120]})"
    return f"{verdict}: {text[:120]}"


# ---------------------------------------------------------------- móvil
@script("09_afinador_antenas")
async def afinador(ctx: ScriptContext) -> AgentOutput:
    _, text = await ctx.call("red.kpis.celdas", {"solo_problemas": True}, reasoning="Busco celdas con interferencia.")
    cells = [c for c in parse(text) or [] if c.get("interferencia")]
    if not cells:
        return out("Ninguna celda con interferencia: no cambio parámetros.", conf=0.92)
    by_zone: dict[str, list[str]] = defaultdict(list)
    for c in cells:
        by_zone[c["zona"]].append(c["id"])
    results = []
    for zone, ids in sorted(by_zone.items()):
        verdict, msg = await ctx.call(
            "red.config.cambiar_parametros",
            {"celdas": ids, "delta_inclinacion": 1, "delta_potencia": -1},
            reasoning=f"{len(ids)} celdas de {zone} con interferencia: +1° y −1 dB reducen el solape.",
            evidence=[f"{c['id']}: SINR {c['sinr_db']} dB" for c in cells if c["zona"] == zone],
        )
        results.append(f"{zone}: {outcome(verdict, msg)}")
    return out(
        f"Reajuste propuesto en {len(cells)} celdas. " + "; ".join(results),
        [c["id"] for c in cells],
        "red.config.cambiar_parametros",
        0.85,
    )


@script("10_cazainterferencias")
async def cazainterferencias(ctx: ScriptContext) -> AgentOutput:
    _, text = await ctx.call("red.kpis.celdas", {"solo_problemas": True}, reasoning="Barrido horario de SINR.")
    cells = parse(text) or []
    interf = [c for c in cells if c.get("interferencia") or c.get("sinr_db", 99) < 5]
    if not interf:
        return out("Sin interferencias en la red.", conf=0.93)
    zones = sorted({c["zona"] for c in interf})
    external = [z for z in zones if sum(1 for c in interf if c["zona"] == z) >= 3]
    tail = f" Probable interferencia externa en {', '.join(external)}." if external else ""
    return out(
        f"Interferencia en {len(interf)} celdas de {', '.join(zones)}.{tail}",
        [c["id"] for c in interf],
        "Reajuste de inclinación y potencia (09 Afinador)",
        0.88,
    )


@script("11_planificador_eventos")
async def planificador_eventos(ctx: ScriptContext) -> AgentOutput:
    ev = ctx.event.payload
    _, text = await ctx.call("eventos.calendario", {}, reasoning="Confirmo el evento.")
    _, text = await ctx.call("red.capacidad.zona", {"zona": ev["zone"]}, reasoning="¿Aguanta la zona el pico?")
    cap = parse(text)
    load = cap.get("carga_pico_normal_pct", 0) * float(ev.get("factor", 1))
    if load <= 90:
        return out(f"{ev['name']}: carga prevista {round(load)} %, no hace falta capacidad extra.", [ev["id"]], None)
    until = (datetime.fromisoformat(str(ev["ends_at"])) + timedelta(hours=1)).isoformat()
    verdict, msg = await ctx.call(
        "red.capacidad.ampliar_temporal",
        {"zona": ev["zone"], "hasta": until},
        reasoning=f"Con {ev['attendance']} asistentes la carga llegaría al {round(load)} %.",
        evidence=[f"{ev['name']} en {ev['zone']}", f"Carga prevista {round(load)} %"],
    )
    return out(
        f"Plan de capacidad para {ev['name']} ({round(load)} % sin plan): {outcome(verdict, msg)}.",
        [ev["id"], ev["zone"]],
        "red.capacidad.ampliar_temporal",
        0.86,
    )


@script("12_ahorrador")
async def ahorrador(ctx: ScriptContext) -> AgentOutput:
    off = ctx.event.payload.get("fase") == "apagar"
    done = []
    for zone in ZONES:
        _, text = await ctx.call("red.kpis.zona", {"zona": zone}, reasoning="Miro la carga de la zona.")
        k = parse(text)
        if off and k.get("celdas_baja_carga_con_portadoras_extra", 0) > 0:
            verdict, _ = await ctx.call("red.config.apagar_portadoras", {"zona": zone}, reasoning="Carga mínima.")
            done.append(f"{zone} {verdict}")
        elif not off and k.get("portadoras_encendidas", 0) < k.get("portadoras_totales", 0):
            verdict, _ = await ctx.call(
                "red.config.encender_portadoras", {"zona": zone}, reasoning="Empieza la subida de tráfico."
            )
            done.append(f"{zone} {verdict}")
    action = "red.config.apagar_portadoras" if off else "red.config.encender_portadoras"
    if not done:
        return out(f"Fase {'apagar' if off else 'encender'}: nada que hacer.", conf=0.9)
    return out(
        f"Portadoras {'apagadas' if off else 'encendidas'} en {len(done)} zonas: {', '.join(done)}.", done, action, 0.92
    )


@script("13_auditor_vecindad")
async def auditor_vecindad(ctx: ScriptContext) -> AgentOutput:
    _, text = await ctx.call("red.vecinos.listar", {}, reasoning="Celdas con fallos de traspaso.")
    cells = [c for c in parse(text) or [] if c.get("vecina_ausente_probable")]
    pairs = [
        f"{c['id']}>{c['vecina_ausente_probable']}"
        for c in cells
        if c["vecina_ausente_probable"].split("-")[1] == c["zona"]
    ][:10]
    if not pairs:
        return out("Vecindades completas: sin correcciones.", conf=0.9)
    verdict, msg = await ctx.call(
        "red.vecinos.corregir",
        {"pares": pairs},
        reasoning="Sin esas relaciones las llamadas se cortan al cambiar de celda.",
        evidence=[f"{c['id']}: {c['fallos_traspaso_pct']} % de fallos" for c in cells[:5]],
    )
    return out(
        f"{len(pairs)} relaciones de vecindad propuestas: {outcome(verdict, msg)}.", pairs, "red.vecinos.corregir", 0.87
    )


@script("14_analista_mediciones")
async def analista_mediciones(ctx: ScriptContext) -> AgentOutput:
    p = ctx.event.payload
    _, text = await ctx.call("mediciones.resultados", {"zona": p["zona"]}, reasoning="Leo la campaña.")
    r = parse(text)
    summary = (
        f"Campaña {p['campana']} en {p['zona']}: {r.get('muestras')} muestras, señal buena en el "
        f"{r.get('rsrp_bueno_pct')} %. Tramos malos: {', '.join(r.get('tramos_malos', [])) or 'ninguno'}."
    )
    verdict, _ = await ctx.call(
        "mediciones.entregar_informe",
        {"campana": p["campana"], "zona": p["zona"], "resumen": summary},
        reasoning="Lo revisa una persona.",
    )
    return out(
        f"Informe de cobertura entregado ({verdict}): {summary}",
        [p["campana"]],
        "Revisión por el técnico",
        0.86,
        persona=True,
    )


# ---------------------------------------------------------------- fibra
@script("15_disenador_barrios")
async def disenador_barrios(ctx: ScriptContext) -> AgentOutput:
    p = ctx.event.payload
    _, a = await ctx.call("catastro_sim.parcelas", {"zona": p["zona"]}, reasoning="Edificios y viviendas.")
    _, b = await ctx.call("gis.capa", {"zona": p["zona"]}, reasoning="Canalización disponible.")
    land, gis = parse(a), parse(b)
    homes = int(p.get("viviendas") or land.get("viviendas", 0))
    boxes, km, splitters = math.ceil(homes / 16), round(homes * 0.014, 1), math.ceil(homes / 64)
    reuse = min(100, round(100 * gis.get("canalizacion_km", 0) / max(km, 0.1)))
    return out(
        f"Diseño {p['proyecto']}: {homes} viviendas, {boxes} cajas terminales, {splitters} divisores 1:64 y "
        f"{km} km de fibra; reaprovecha el {reuse} % de canalización existente.",
        [p["proyecto"], p["zona"]],
        "Aprobar diseño (design.approved)",
        0.82,
    )


@script("16_gestor_permisos")
async def gestor_permisos(ctx: ScriptContext) -> AgentOutput:
    p = ctx.event.payload
    await ctx.call("documentos.plantilla", {"tipo": "licencia de obra"}, reasoning="Plantilla municipal.")
    resumen = (
        f"Canalización FTTH en {p['zona']} para {p.get('viviendas')} viviendas: "
        f"{round(int(p.get('viviendas', 0)) * 0.004, 1)} km de zanja, plazo 6 semanas."
    )
    verdict, msg = await ctx.call(
        "documentos.presentar_solicitud",
        {"proyecto": p["proyecto"], "ayuntamiento": "Ayuntamiento (ficticio)", "resumen": resumen},
        reasoning="Borrador completo con memoria y planos.",
        evidence=[p["proyecto"], resumen],
    )
    return out(
        f"Solicitud de obra de {p['proyecto']}: {outcome(verdict, msg)}.",
        [p["proyecto"]],
        "documentos.presentar_solicitud",
        0.88,
    )


@script("17_doctor_remoto")
async def doctor_remoto(ctx: ScriptContext) -> AgentOutput:
    ont = str(ctx.event.payload["ont"])
    _, text = await ctx.call(
        "red.ont.diagnostico", {"ont": ont}, reasoning="Diagnóstico remoto antes de mandar a nadie."
    )
    diag = parse(text)
    if "error" in diag:
        return out(f"{ont} no existe en el inventario.", [ont], conf=0.5)
    verdict, msg = await ctx.call("red.ont.reiniciar", {"ont": ont}, reasoning="Reinicio remoto: un solo cliente.")
    result = parse(msg)
    if verdict == "ejecutada" and "sigue baja" in str(result.get("detail", "")):
        v2, m2 = await ctx.call(
            "red.ont.solicitar_sustitucion",
            {"ont": ont, "motivo": result["detail"]},
            reasoning="La potencia no se recupera: problema físico.",
        )
        ot = parse(m2).get("ot", "")
        return out(
            f"{ont} reiniciada pero sigue por debajo de −25 dBm: orden {ot} para revisar la acometida ({v2}).",
            [ont, ot],
            "red.ont.solicitar_sustitucion",
            0.87,
        )
    return out(f"{ont}: {result.get('detail', msg)} ({verdict}).", [ont], "red.ont.reiniciar", 0.9)


@script("18_coordinador_contratas")
async def coordinador_contratas(ctx: ScriptContext) -> AgentOutput:
    ot = str(ctx.event.payload["ot"])
    _, text = await ctx.call("ordenes.obtener", {"ot": ot}, reasoning="Leo la orden.")
    wo = parse(text)
    if "error" in wo:
        return out(f"{ot} no existe.", [ot], conf=0.5, persona=True)
    _, text = await ctx.call("ordenes.contratas", {"zona": wo["zone"]}, reasoning="Contratas de la zona.")
    options = sorted(parse(text) or [], key=lambda c: (c["ordenes_abiertas"], -c["nota_calidad"]))
    if not options:
        return out(f"No hay contrata para {wo['zone']}: lo decide una persona.", [ot], conf=0.6, persona=True)
    best = options[0]["contrata"]
    verdict, msg = await ctx.call(
        "ordenes.asignar",
        {"ot": ot, "contrata": best},
        reasoning="Menos carga y mejor nota de calidad en la zona.",
        evidence=[f"{c['contrata']}: {c['ordenes_abiertas']} abiertas" for c in options],
    )
    await ctx.call(
        "fotos.solicitar_validacion",
        {"ot": ot, "resumen": f"{wo['kind']} en {wo['zone']}; contrata propuesta {best}."},
        reasoning="La validación de las fotos es de una persona.",
    )
    return out(
        f"{ot}: asignación a {best} {outcome(verdict, msg)}; validación de fotos para el jefe de obra.",
        [ot, best],
        "ordenes.asignar",
        0.86,
        persona=True,
    )


@script("19_cartografo")
async def cartografo(ctx: ScriptContext) -> AgentOutput:
    p = ctx.event.payload
    detail = f"{p['ot']}: {p.get('kind')} en {p.get('zone')} ({p.get('ont') or p.get('node') or 'sin equipo'})."
    v1, _ = await ctx.call(
        "gis.actualizar_capa", {"zona": p["zone"], "detalle": detail}, reasoning="Reflejar en el mapa."
    )
    v2, _ = await ctx.call(
        "inventario.actualizar", {"ot": p["ot"], "detalle": detail}, reasoning="Reflejar en inventario."
    )
    return out(f"GIS ({v1}) e inventario ({v2}) al día tras {p['ot']}.", [p["ot"]], "gis.actualizar_capa", 0.94)


@script("20_adivino")
async def adivino(ctx: ScriptContext) -> AgentOutput:
    _, text = await ctx.call("red.historico.tendencias_ont", {}, reasoning="Tendencia de potencia óptica.")
    risky = [o for o in parse(text) or [] if o.get("dias_hasta_-27dBm") is not None and o["dias_hasta_-27dBm"] < 30]
    await ctx.call("red.ont.potencias", {"limite": 10}, reasoning="Contraste con las peores potencias de hoy.")
    if not risky:
        return out("Ninguna ONT en riesgo en los próximos 30 días.", conf=0.88)
    lst = ", ".join(f"{o['ont']} ({o['dias_hasta_-27dBm']} días)" for o in risky[:5])
    return out(
        f"{len(risky)} ONT llegarán a −27 dBm en menos de 30 días: {lst}.",
        [o["ont"] for o in risky],
        "Sustitución preventiva antes de que el cliente llame",
        0.8,
    )


# ---------------------------------------------------------------- núcleo
@script("21_previsor_capacidad")
async def previsor_capacidad(ctx: ScriptContext) -> AgentOutput:
    _, text = await ctx.call("red.trafico.enlaces", {}, reasoning="Pico y crecimiento semanal.")
    soon = [x for x in parse(text) or [] if x.get("semanas_hasta_80pct") is not None and x["semanas_hasta_80pct"] < 12]
    if not soon:
        return out("Ningún enlace llegará al 80 % en las próximas 12 semanas.", conf=0.85)
    top = ", ".join(f"{x['enlace']} {x['de']}→{x['a']} ({x['semanas_hasta_80pct']} semanas)" for x in soon[:3])
    return out(
        f"{len(soon)} enlaces llegarán al 80 % antes de 12 semanas. Más urgentes: {top}.",
        [x["enlace"] for x in soon],
        "Ampliar capacidad de los tres más urgentes",
        0.78,
    )


@script("22_configurador")
async def configurador(ctx: ScriptContext) -> AgentOutput:
    p = ctx.event.payload
    node, template = str(p["nodo"]), str(p["plantilla"])
    await ctx.call("plantillas.comparar", {"nodo": node}, reasoning="Qué se desvía hoy.")
    _, text = await ctx.call("plantillas.obtener", {"plantilla": template}, reasoning="Configuración de partida.")
    if "error" in parse(text):
        return out(f"La plantilla {template} no existe: no genero configuración.", [node], conf=0.6)
    _, text = await ctx.call("gemelo.probar_config", {"nodo": node, "plantilla": template}, reasoning="Prueba previa.")
    twin = parse(text)
    if not twin.get("ok"):
        return out(
            f"El gemelo rechaza {template} en {node}: {twin.get('detail')}",
            [node, template],
            "Revisar la plantilla pedida",
            0.85,
        )
    verdict, msg = await ctx.call(
        "gemelo.aplicar_config",
        {"nodo": node, "plantilla": template},
        reasoning=f"{template} probada en el gemelo sin regresiones.",
        evidence=[twin.get("detail", ""), str(p.get("motivo", ""))],
    )
    return out(f"{template} para {node}: {outcome(verdict, msg)}.", [node, template], "gemelo.aplicar_config", 0.88)


@script("23_auditor_configuraciones")
async def auditor_configuraciones(ctx: ScriptContext) -> AgentOutput:
    _, text = await ctx.call("red.config.desviaciones", {}, reasoning="Nodos fuera de estándar.")
    devs = parse(text) or []
    for d in devs[:3]:
        await ctx.call("plantillas.comparar", {"nodo": d["nodo"]}, reasoning="Confirmo la desviación.")
    if not devs:
        return out("Todos los equipos cumplen su plantilla.", conf=0.93)
    lst = "; ".join(f"{d['nodo']} ({d['plantilla']}): {', '.join(d['desviaciones'])}" for d in devs)
    return out(
        f"{len(devs)} equipos fuera del estándar: {lst}.",
        [d["nodo"] for d in devs],
        "Pedir al Configurador que los devuelva a su plantilla",
        0.9,
    )


@script("24_gestor_actualizaciones")
async def gestor_actualizaciones(ctx: ScriptContext) -> AgentOutput:
    p = ctx.event.payload
    vendor, version = str(p["fabricante"]), str(p["version"])
    _, text = await ctx.call("inventario.por_fabricante", {"fabricante": vendor}, reasoning="Equipos afectados.")
    nodes = [n for n in parse(text) or [] if n["firmware"] != version]
    safe = [n["nodo"] for n in nodes if n["respaldo"]]
    manual = [n["nodo"] for n in nodes if not n["respaldo"]]
    now = datetime.fromisoformat(str(p.get("at") or "2026-10-12T05:00:00+00:00"))
    start = (now + timedelta(days=1)).replace(hour=2, minute=0, second=0, microsecond=0)
    await ctx.call(
        "cambios.calendario",
        {"desde": start.isoformat(), "hasta": (start + timedelta(hours=3)).isoformat()},
        reasoning="Evito chocar con otros cambios.",
    )
    if not safe:
        return out(
            f"Ningún equipo de {vendor} se puede actualizar sin corte: {len(manual)} necesitan ventana manual.",
            manual,
            "Ventana manual con aviso a clientes",
            0.8,
        )
    window = f"{start:%d/%m} 02:00–05:00"
    verdict, msg = await ctx.call(
        "cambios.programar_actualizacion",
        {"fabricante": vendor, "version": version, "nodos": safe, "ventana": window},
        reasoning="Solo equipos con respaldo: el reinicio no corta el servicio.",
        evidence=[f"{len(safe)} con respaldo", f"{len(manual)} sin respaldo"],
    )
    tail = f" {len(manual)} sin respaldo necesitan ventana manual: {', '.join(manual[:5])}." if manual else ""
    return out(
        f"Plan {vendor} {version} para {len(safe)} equipos el {window}: {outcome(verdict, msg)}.{tail}",
        safe[:5],
        "cambios.programar_actualizacion",
        0.84,
    )


@script("25_vigilante_rutas")
async def vigilante_rutas(ctx: ScriptContext) -> AgentOutput:
    prefix = str(ctx.event.payload["prefix"])
    _, text = await ctx.call("red.bgp.rib", {"prefijo": prefix}, reasoning="Comparo origen anunciado y esperado.")
    route = parse(text)
    if not route.get("desviado"):
        return out(f"{prefix} se anuncia desde su origen esperado: sin desvío.", [prefix], conf=0.9)
    await ctx.call(
        "red.bgp.emitir_alerta",
        {"prefijo": prefix, "origen": route["origin_as"]},
        reasoning="Origen distinto del registrado: posible secuestro o error.",
    )
    verdict, msg = await ctx.call(
        "red.bgp.revertir_anuncio",
        {"prefijo": prefix},
        reasoning="Retirar el anuncio desviado.",
        evidence=[f"{prefix} desde AS{route['origin_as']}", f"esperado AS{route['expected_as']}"],
    )
    return out(
        f"Desvío de {prefix} por AS{route['origin_as']}: alerta emitida y reversión {outcome(verdict, msg)}.",
        [prefix],
        "red.bgp.revertir_anuncio",
        0.9,
    )
