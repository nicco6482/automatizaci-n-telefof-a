"""Gemelo digital: copia del estado donde se prueba un cambio antes de proponerlo."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from simulator.actions import APPLY, twin_checks
from simulator.engine import Simulator, UnknownTarget
from simulator.models import NetworkState


class TwinResult(BaseModel):
    ok: bool
    detail: str
    nodes_losing_service: list[str] = []


def probar_cambio(state: NetworkState, action: str, args: dict[str, Any]) -> TwinResult:
    if action not in APPLY:
        return TwinResult(ok=False, detail=f"El gemelo no sabe probar «{action}»: no puede pasar a aprobación.")
    before = Simulator(state=state.model_copy(deep=True))
    twin = Simulator(state=state.model_copy(deep=True))
    served = {n for n in twin.state.nodes if twin.state.node_has_service(n)}
    try:
        result = twin.apply(action, args)
        problem = twin_checks(before, twin, action, args)
    except (UnknownTarget, KeyError) as exc:
        return TwinResult(ok=False, detail=f"Destino desconocido en el gemelo: {exc}.")
    lost = sorted(served - {n for n in twin.state.nodes if twin.state.node_has_service(n)})
    if not result.ok:
        return TwinResult(ok=False, detail=f"En el gemelo la acción falla: {result.detail}")
    if lost:
        return TwinResult(
            ok=False, nodes_losing_service=lost, detail=f"En el gemelo pierden servicio: {', '.join(lost)}."
        )
    if problem:
        return TwinResult(ok=False, detail=f"Gemelo: {problem}")
    return TwinResult(ok=True, detail=f"Gemelo: {result.detail} Sin regresiones: ningún nodo pierde servicio.")
