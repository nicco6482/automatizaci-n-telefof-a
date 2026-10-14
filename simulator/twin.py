"""Gemelo digital: copia del estado donde se prueba un cambio antes de proponerlo."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from simulator.engine import Simulator, UnknownTarget
from simulator.models import NetworkState

# Acciones que el gemelo sabe reproducir. Fuera de esta lista, el cambio no se puede probar.
_APPLY = {
    "conmutar_respaldo": lambda sim, args: sim.switch_to_backup(str(args["node"])),
    "reiniciar_tarjeta": lambda sim, args: sim.restart_card(str(args["node"])),
}


class TwinResult(BaseModel):
    ok: bool
    detail: str
    nodes_losing_service: list[str] = []


def probar_cambio(state: NetworkState, action: str, args: dict[str, Any]) -> TwinResult:
    apply = _APPLY.get(action)
    if apply is None:
        return TwinResult(ok=False, detail=f"El gemelo no sabe probar «{action}»: no puede pasar a aprobación.")
    twin = Simulator(state=state.model_copy(deep=True))
    before = {n for n in twin.state.nodes if twin.state.node_has_service(n)}
    try:
        result = apply(twin, args)
    except UnknownTarget as exc:
        return TwinResult(ok=False, detail=f"Destino desconocido en el gemelo: {exc}.")
    after = {n for n in twin.state.nodes if twin.state.node_has_service(n)}
    lost = sorted(before - after)
    overloaded = [link.id for link in twin.state.links.values() if link.utilization >= 0.95]
    if not result.ok:
        return TwinResult(ok=False, detail=f"En el gemelo la acción falla: {result.detail}")
    if lost:
        return TwinResult(
            ok=False, nodes_losing_service=lost, detail=f"En el gemelo pierden servicio: {', '.join(lost)}."
        )
    if overloaded:
        return TwinResult(ok=False, detail=f"En el gemelo se saturan los enlaces {', '.join(overloaded)}.")
    return TwinResult(ok=True, detail=f"Gemelo: {result.detail} Ningún nodo pierde servicio.")
