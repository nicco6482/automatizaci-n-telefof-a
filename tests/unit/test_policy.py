import pytest

from core.policy import PolicyContext, evaluate
from core.schemas import AgentConfig, Verdict
from core.tools import ToolName, in_whitelist, spec_for


def agent(level: int = 2, tools: list[str] | None = None, per_hour: int = 10) -> AgentConfig:
    return AgentConfig(
        id="03",
        nombre="bombero",
        titulo="Bombero",
        area="noc",
        disparadores=["ticket.created"],
        herramientas=tools or ["red.runbooks"],
        autonomia=level,
        escalado="04 Escalador",
        limites={"acciones_hora": per_hour},
        prompt="x.md",
    )


def ctx(**kw: object) -> PolicyContext:
    base: dict[str, object] = {"kill_switch": False, "blast_radius": 500, "actions_last_hour": 0, "impact": 100}
    base.update(kw)
    return PolicyContext.model_validate(base)


def test_nombres_de_herramienta_ida_y_vuelta() -> None:
    n = ToolName.from_canonical("red.runbooks.conmutar_respaldo")
    assert n.server == "red" and n.tool == "runbooks__conmutar_respaldo"
    assert n.sdk == "mcp__red__runbooks__conmutar_respaldo"
    assert ToolName.from_sdk(n.sdk).canonical == n.canonical


def test_lista_blanca_por_grupo_sin_prefijos_falsos() -> None:
    assert in_whitelist("red.runbooks.consultar", ["red.runbooks"])
    assert not in_whitelist("red.runbooksx.consultar", ["red.runbooks"])
    assert not in_whitelist("red.config.escribir", ["red.runbooks"])


def test_herramienta_desconocida_nunca_es_lectura() -> None:
    assert spec_for("red.algo.inventado").tipo == "accion"
    assert not spec_for("red.algo.inventado").nivel2


def test_fuera_de_lista_blanca_se_bloquea() -> None:
    d = evaluate(agent(), "red.config.escribir", ctx())
    assert d.verdict == Verdict.BLOQUEADA


def test_lectura_permitida() -> None:
    assert evaluate(agent(), "red.runbooks.consultar", ctx()).verdict == Verdict.PERMITIDA


def test_nivel_2_ejecuta_accion_reversible_del_catalogo() -> None:
    assert evaluate(agent(2), "red.runbooks.conmutar_respaldo", ctx()).verdict == Verdict.PERMITIDA


def test_nivel_1_siempre_pide_aprobacion() -> None:
    d = evaluate(agent(1), "red.runbooks.conmutar_respaldo", ctx(impact=1))
    assert d.verdict == Verdict.APROBACION and d.needs_twin


def test_nivel_0_solo_propone() -> None:
    assert evaluate(agent(0), "red.runbooks.conmutar_respaldo", ctx()).verdict == Verdict.PROPUESTA


@pytest.mark.parametrize("impact,expected", [(500, Verdict.PERMITIDA), (501, Verdict.APROBACION)])
def test_radio_de_impacto(impact: int, expected: Verdict) -> None:
    assert evaluate(agent(2), "red.runbooks.conmutar_respaldo", ctx(impact=impact)).verdict == expected


def test_accion_fuera_de_catalogo_pasa_a_aprobacion_aunque_sea_nivel_2() -> None:
    d = evaluate(agent(2, ["red.config"]), "red.config.escribir", ctx())
    assert d.verdict == Verdict.APROBACION


def test_interruptor_general_baja_a_nivel_0() -> None:
    d = evaluate(agent(2), "red.runbooks.conmutar_respaldo", ctx(kill_switch=True))
    assert d.verdict == Verdict.PROPUESTA


def test_interruptor_no_abre_lo_que_estaba_cerrado() -> None:
    d = evaluate(agent(2), "red.config.escribir", ctx(kill_switch=True))
    assert d.verdict == Verdict.BLOQUEADA


def test_limite_de_ritmo_pausa() -> None:
    d = evaluate(agent(2, per_hour=3), "red.runbooks.conmutar_respaldo", ctx(actions_last_hour=3))
    assert d.verdict == Verdict.PAUSA


def test_agente_en_pausa_no_hace_nada() -> None:
    assert evaluate(agent(), "red.runbooks.consultar", ctx(agent_paused=True)).verdict == Verdict.PAUSA


def test_yaml_rechaza_comodines() -> None:
    with pytest.raises(ValueError):
        agent(tools=["red.*"])
