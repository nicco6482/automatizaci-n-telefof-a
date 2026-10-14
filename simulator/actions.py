"""Acciones y consultas del simulador para las Fases 2+, y las comprobaciones del gemelo para cada cambio."""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from simulator.models import FaultType, LinkStatus, NodeType

if TYPE_CHECKING:
    from simulator.engine import ActionResult, Simulator

CARRIER_CAPACITY = 420  # usuarios por portadora


def _result(ok: bool, detail: str, clients: int = 0) -> ActionResult:
    from simulator.engine import ActionResult

    return ActionResult(ok=ok, detail=detail, clients_affected=clients)


def _unknown(kind: str, value: object) -> ValueError:
    from simulator.engine import UnknownTarget

    return UnknownTarget(f"{kind} desconocido: {value}")


# ---------------------------------------------------------------- acciones
def conmutar_respaldo(sim: Simulator, a: dict[str, Any]) -> ActionResult:
    return sim.switch_to_backup(str(a["node"]))


def reiniciar_tarjeta(sim: Simulator, a: dict[str, Any]) -> ActionResult:
    return sim.restart_card(str(a["node"]))


def cambiar_parametros(sim: Simulator, a: dict[str, Any]) -> ActionResult:
    cells = [_cell(sim, c) for c in a["cells"]]
    tilt, power = int(a.get("tilt_delta", 0)), int(a.get("power_delta", 0))
    fixed = 0
    for c in cells:
        c.tilt_deg += tilt
        c.power_dbm += power
        if c.interference and tilt > 0 and power < 0:
            c.interference = False
            c.sinr_db = round(c.sinr_db + 7, 1)
            fixed += 1
    _clear_interference_faults(sim)
    sim.refresh()
    return _result(
        True,
        f"{len(cells)} celdas con inclinación {tilt:+d}° y potencia {power:+d} dB; {fixed} sin interferencia.",
        sum(c.users for c in cells),
    )


def apagar_portadoras(sim: Simulator, a: dict[str, Any]) -> ActionResult:
    zone = str(a["zone"])
    cells = [c for c in sim.state.cells.values() if c.zone == zone and c.load < 0.15 and c.carriers_on > 1]
    for c in cells:
        c.carriers_on = 1
    sim.refresh()
    return _result(True, f"{len(cells)} celdas de {zone} con una sola portadora.", 0)


def encender_portadoras(sim: Simulator, a: dict[str, Any]) -> ActionResult:
    zone = str(a["zone"])
    cells = [c for c in sim.state.cells.values() if c.zone == zone and c.carriers_on < c.carriers]
    for c in cells:
        c.carriers_on = c.carriers
    sim.refresh()
    return _result(True, f"{len(cells)} celdas de {zone} con todas sus portadoras.", 0)


def ampliar_capacidad(sim: Simulator, a: dict[str, Any]) -> ActionResult:
    zone = str(a["zone"])
    until = datetime.fromisoformat(str(a["until"]))
    sim.state.extra_capacity[zone] = until
    sim.refresh()
    return _result(True, f"Capacidad temporal en {zone} hasta {until:%d/%m %H:%M} (portadora extra y celda portátil).")


def corregir_vecinos(sim: Simulator, a: dict[str, Any]) -> ActionResult:
    done = []
    for pair in a["pairs"]:
        src, _, dst = str(pair).partition(">")
        cell = _cell(sim, src)
        _cell(sim, dst)
        if dst not in cell.neighbors:
            cell.neighbors.append(dst)
        if dst in cell.missing_neighbors:
            cell.missing_neighbors.remove(dst)
        if not cell.missing_neighbors:
            cell.handover_fail_pct = 0.6
        done.append(pair)
    return _result(True, f"{len(done)} relaciones de vecindad añadidas: {', '.join(done)}.")


def reiniciar_ont(sim: Simulator, a: dict[str, Any]) -> ActionResult:
    ont = sim.state.onts.get(str(a["ont"]))
    if ont is None:
        raise _unknown("ONT", a["ont"])
    ont.reboots += 1
    if ont.power_dbm >= -25:
        return _result(True, f"{ont.id} reiniciada; potencia {ont.power_dbm:.1f} dBm, servicio normal.", 1)
    ont.power_dbm = round(ont.power_dbm + 1.0, 2)
    return _result(
        True,
        f"{ont.id} reiniciada; la potencia sigue baja ({ont.power_dbm:.1f} dBm): hace falta revisar la acometida.",
        1,
    )


def aplicar_config(sim: Simulator, a: dict[str, Any]) -> ActionResult:
    node = _node(sim, str(a["node"]))
    node.config_template, removed = str(a["template"]), list(node.config_drift)
    node.config_drift = []
    return _result(
        True,
        f"{node.id} con plantilla {node.config_template}; desviaciones retiradas: {', '.join(removed) or 'ninguna'}.",
        node.ftth_clients,
    )


def programar_actualizacion(sim: Simulator, a: dict[str, Any]) -> ActionResult:
    nodes = [_node(sim, n) for n in a["nodes"]]
    for n in nodes:
        n.firmware = str(a["version"])
    return _result(True, f"{len(nodes)} equipos actualizados a {a['version']} en la ventana {a.get('window', '')}.")


def revertir_anuncio(sim: Simulator, a: dict[str, Any]) -> ActionResult:
    route = sim.state.routes.get(str(a["prefix"]))
    if route is None:
        raise _unknown("prefijo", a["prefix"])
    route.origin_as = route.expected_as
    for f in sim.state.faults.values():
        if f.type == FaultType.DESVIO_RUTAS and f.target == route.prefix and f.active:
            f.active, f.resolved_at = False, sim.state.now
    return _result(True, f"{route.prefix} vuelve a anunciarse desde AS{route.expected_as}.")


APPLY: dict[str, Callable[[Simulator, dict[str, Any]], ActionResult]] = {
    "conmutar_respaldo": conmutar_respaldo,
    "reiniciar_tarjeta": reiniciar_tarjeta,
    "cambiar_parametros": cambiar_parametros,
    "apagar_portadoras": apagar_portadoras,
    "encender_portadoras": encender_portadoras,
    "ampliar_capacidad": ampliar_capacidad,
    "corregir_vecinos": corregir_vecinos,
    "reiniciar_ont": reiniciar_ont,
    "aplicar_config": aplicar_config,
    "programar_actualizacion": programar_actualizacion,
    "revertir_anuncio": revertir_anuncio,
}


# ---------------------------------------------------------------- comprobaciones del gemelo
def twin_checks(before: Simulator, after: Simulator, action: str, a: dict[str, Any]) -> str | None:
    """Devuelve el motivo del fallo o None si el cambio es seguro."""
    if action == "cambiar_parametros":
        for c in [after.state.cells[x] for x in a["cells"]]:
            if c.power_dbm < 38:
                return f"Con {c.power_dbm} dBm la {c.id} deja un hueco de cobertura (RSRP −121 dBm en el borde)."
            if c.tilt_deg > 10:
                return f"Con {c.tilt_deg}° de inclinación la {c.id} deja de cubrir su borde."
    if action == "ampliar_capacidad":
        bad = [c.id for c in after.state.cells.values() if c.zone == a["zone"] and c.interference]
        if bad:
            return f"La portadora extra empeora la interferencia en {', '.join(bad[:3])}."
    if action == "corregir_vecinos":
        for pair in a["pairs"]:
            src, _, dst = str(pair).partition(">")
            if before.state.cells[src].zone != before.state.cells[dst].zone:
                return f"{src} y {dst} no son vecinas físicas: se crearía un bucle de traspasos."
            if len(after.state.cells[src].neighbors) > 8:
                return f"{src} tendría más de 8 vecinas."
    if action == "aplicar_config":
        node = before.state.nodes[str(a["node"])]
        family = {NodeType.ACC: "acceso", NodeType.AGG: "agregacion", NodeType.CORE: "nucleo"}[node.type]
        if not str(a["template"]).startswith(family):
            return f"La plantilla {a['template']} no es de {family}: {node.id} perdería la gestión."
    if action == "programar_actualizacion":
        alone = [
            n
            for n in a["nodes"]
            if before.state.nodes[n].type == NodeType.ACC and not before.state.nodes[n].backup_link
        ]
        if alone:
            clients = sum(before.state.nodes[n].ftth_clients for n in alone)
            return f"Sin respaldo en {', '.join(alone)}: el reinicio cortaría a {clients} clientes."
    if action == "revertir_anuncio":
        route = before.state.routes.get(str(a["prefix"]))
        if route is None or route.origin_as == route.expected_as:
            return "No hay desvío que revertir para ese prefijo."
    return None


# ---------------------------------------------------------------- consultas
def _cell_view(c: Any) -> dict[str, Any]:
    return {
        "id": c.id,
        "zona": c.zone,
        "nodo": c.node,
        "tecnologia": c.tech,
        "usuarios": c.users,
        "carga": round(c.load, 2),
        "sinr_db": c.sinr_db,
        "interferencia": c.interference,
        "portadoras": f"{c.carriers_on}/{c.carriers}",
        "inclinacion": c.tilt_deg,
        "potencia_dbm": c.power_dbm,
    }


def v_cells(sim: Simulator, a: dict[str, Any]) -> Any:
    zone, problems = a.get("zone"), bool(a.get("only_problems"))
    cells = [c for c in sim.state.cells.values() if zone is None or c.zone == zone]
    if problems:
        cells = [c for c in cells if c.interference or c.sinr_db < 5 or c.load > 0.95]
    return [_cell_view(c) for c in cells[:200]]


def v_zone_kpis(sim: Simulator, a: dict[str, Any]) -> Any:
    zone = str(a["zone"])
    cells = [c for c in sim.state.cells.values() if c.zone == zone]
    low = [c for c in cells if c.load < 0.15 and c.carriers_on > 1]
    return {
        "zona": zone,
        "celdas": len(cells),
        "usuarios": sum(c.users for c in cells),
        "carga_media": round(sum(c.load for c in cells) / len(cells), 2),
        "celdas_baja_carga_con_portadoras_extra": len(low),
        "portadoras_encendidas": sum(c.carriers_on for c in cells),
        "portadoras_totales": sum(c.carriers for c in cells),
    }


def v_capacity(sim: Simulator, a: dict[str, Any]) -> Any:
    zone = str(a["zone"])
    cells = [c for c in sim.state.cells.values() if c.zone == zone]
    peak = sum(c.peak_users for c in cells)
    capacity = sum(c.carriers for c in cells) * CARRIER_CAPACITY
    extra = sim.state.extra_capacity.get(zone)
    return {
        "zona": zone,
        "celdas": len(cells),
        "usuarios_pico": peak,
        "capacidad_usuarios": capacity,
        "carga_pico_normal_pct": round(100 * peak / capacity),
        "interferencia": any(c.interference for c in cells),
        "capacidad_extra_hasta": extra.isoformat() if extra else None,
    }


def v_events(sim: Simulator, a: dict[str, Any]) -> Any:
    return [e.model_dump(mode="json") for e in sim.state.events if e.ends_at > sim.state.now]


def v_neighbors(sim: Simulator, a: dict[str, Any]) -> Any:
    zone = a.get("zone")
    cells = [c for c in sim.state.cells.values() if (zone is None or c.zone == zone) and c.handover_fail_pct > 3]
    return [
        {
            "id": c.id,
            "zona": c.zone,
            "vecinas": c.neighbors,
            "fallos_traspaso_pct": c.handover_fail_pct,
            "vecina_ausente_probable": c.missing_neighbors[0] if c.missing_neighbors else None,
        }
        for c in cells
    ]


def v_ont(sim: Simulator, a: dict[str, Any]) -> Any:
    ont = sim.state.onts.get(str(a["ont"]))
    if ont is None:
        raise _unknown("ONT", a["ont"])
    return {
        **ont.model_dump(),
        "estado": "degradada" if ont.power_dbm < -25 else "normal",
        "umbral_dbm": -25,
        "nodo_con_servicio": sim.state.node_has_service(ont.node),
    }


def v_onts(sim: Simulator, a: dict[str, Any]) -> Any:
    return [
        o.model_dump() for o in sorted(sim.state.onts.values(), key=lambda o: o.power_dbm)[: int(a.get("limit", 20))]
    ]


def v_ont_trends(sim: Simulator, a: dict[str, Any]) -> Any:
    out: list[dict[str, Any]] = []
    for o in sim.state.onts.values():
        days = (o.power_dbm + 27) / -o.trend_db_day if o.trend_db_day < 0 else None
        out.append(
            {
                "ont": o.id,
                "cliente": o.customer,
                "potencia_dbm": o.power_dbm,
                "tendencia_db_dia": o.trend_db_day,
                "dias_hasta_-27dBm": round(days) if days is not None and days > 0 else None,
            }
        )
    return sorted(out, key=lambda x: x["dias_hasta_-27dBm"] if x["dias_hasta_-27dBm"] is not None else 10**6)[:20]


def v_links(sim: Simulator, a: dict[str, Any]) -> Any:
    out: list[dict[str, Any]] = []
    for link in sim.state.links.values():
        if link.role.value == "respaldo" and link.status != LinkStatus.ACTIVO:
            continue
        peak = min(0.99, 0.62 * (0.9 + (int(link.id[1:]) * 7 % 20) / 100))
        weeks = None
        if link.growth_pct_week > 0 and peak < 0.8:
            weeks = math.ceil(math.log(0.8 / peak) / math.log(1 + link.growth_pct_week / 100))
        out.append(
            {
                "enlace": link.id,
                "de": link.a,
                "a": link.b,
                "capacidad_gbps": link.capacity_gbps,
                "pico_pct": round(100 * peak),
                "crecimiento_semanal_pct": link.growth_pct_week,
                "semanas_hasta_80pct": weeks,
            }
        )
    return sorted(out, key=lambda x: x["semanas_hasta_80pct"] if x["semanas_hasta_80pct"] is not None else 10**6)


def v_node_config(sim: Simulator, a: dict[str, Any]) -> Any:
    n = _node(sim, str(a["node"]))
    return {
        "nodo": n.id,
        "tipo": n.type.value,
        "fabricante": n.vendor,
        "firmware": n.firmware,
        "plantilla": n.config_template,
        "desviaciones": n.config_drift,
    }


def v_deviations(sim: Simulator, a: dict[str, Any]) -> Any:
    return [v_node_config(sim, {"node": n.id}) for n in sim.state.nodes.values() if n.config_drift]


def v_by_vendor(sim: Simulator, a: dict[str, Any]) -> Any:
    return [
        {
            "nodo": n.id,
            "tipo": n.type.value,
            "zona": n.zone,
            "firmware": n.firmware,
            "respaldo": bool(n.backup_link) or n.type != NodeType.ACC,
            "clientes_ftth": n.ftth_clients,
        }
        for n in sim.state.nodes.values()
        if n.vendor == a["vendor"]
    ]


def v_route(sim: Simulator, a: dict[str, Any]) -> Any:
    route = sim.state.routes.get(str(a["prefix"]))
    if route is None:
        raise _unknown("prefijo", a["prefix"])
    return {**route.model_dump(), "desviado": route.origin_as != route.expected_as}


def v_land(sim: Simulator, a: dict[str, Any]) -> Any:
    land = sim.state.land.get(str(a["zone"]))
    if land is None:
        raise _unknown("zona", a["zone"])
    return land.model_dump()


def v_coverage(sim: Simulator, a: dict[str, Any]) -> Any:
    zone = str(a["zone"])
    cells = [c for c in sim.state.cells.values() if c.zone == zone]
    bad = [c.id for c in cells if c.interference or c.sinr_db < 5 or not sim.state.node_has_service(c.node)]
    ok = round(100 * (1 - len(bad) / max(1, len(cells))), 1)
    return {"zona": zone, "muestras": len(cells) * 40, "rsrp_bueno_pct": ok, "tramos_malos": bad[:10]}


def v_ont_trace(sim: Simulator, a: dict[str, Any]) -> Any:
    fault = next((f for f in sim.state.faults.values() if f.target == a.get("ont") and f.active), None)
    return {"incident": fault.id if fault else None}


VIEWS: dict[str, Callable[[Simulator, dict[str, Any]], Any]] = {
    "ont_trace": v_ont_trace,
    "cells": v_cells,
    "zone_kpis": v_zone_kpis,
    "capacity": v_capacity,
    "events": v_events,
    "neighbors": v_neighbors,
    "ont": v_ont,
    "onts": v_onts,
    "ont_trends": v_ont_trends,
    "links": v_links,
    "node_config": v_node_config,
    "deviations": v_deviations,
    "by_vendor": v_by_vendor,
    "route": v_route,
    "land": v_land,
    "coverage": v_coverage,
}


# ---------------------------------------------------------------- utilidades
def _cell(sim: Simulator, cell_id: str) -> Any:
    cell = sim.state.cells.get(cell_id)
    if cell is None:
        raise _unknown("celda", cell_id)
    return cell


def _node(sim: Simulator, node_id: str) -> Any:
    node = sim.state.nodes.get(node_id)
    if node is None:
        raise _unknown("nodo", node_id)
    return node


def _clear_interference_faults(sim: Simulator) -> None:
    for f in sim.state.faults.values():
        pending = f.type == FaultType.INTERFERENCIA and f.active and f.target
        if pending and not any(sim.state.cells[c].interference for c in (f.target or "").split(",")):
            f.active, f.resolved_at = False, sim.state.now


def event_window(sim: Simulator, hours_ahead: int, duration: int) -> tuple[datetime, datetime]:
    start = sim.state.now + timedelta(hours=hours_ahead)
    return start, start + timedelta(hours=duration)
