from simulator.engine import Simulator, diurnal_factor
from simulator.models import FaultType, LinkStatus, NodeType
from simulator.network import SIM_START, build_network
from simulator.twin import probar_cambio as run_twin


def test_misma_semilla_misma_red() -> None:
    a, b = build_network(42), build_network(42)
    assert a.model_dump() == b.model_dump()
    assert build_network(7).model_dump() != a.model_dump()


def test_tamano_de_la_ciudad() -> None:
    st = build_network(42)
    assert len(st.cells) == 300
    assert len(st.nodes) == 50
    assert sum(n.ftth_clients for n in st.nodes.values()) == 20_000
    assert len(st.enterprises) == 200


def test_trafico_de_dia_mayor_que_de_noche() -> None:
    noche = diurnal_factor(SIM_START.replace(hour=4))
    dia = diurnal_factor(SIM_START.replace(hour=20))
    assert dia > noche * 4


def test_avance_genera_kpis_cada_15_minutos() -> None:
    sim = Simulator(42)
    sim.advance(60)
    assert len(sim.state.kpis) == 5
    assert [e.topic for e in sim.drain()].count("cron.15min") == 4


def test_caida_de_enlace_corta_servicio_y_lanza_alarmas() -> None:
    sim = Simulator(42)
    fault = sim.inject(FaultType.CAIDA_ENLACE, with_backup=True)
    node = sim.state.nodes[fault.node or ""]
    assert node.type == NodeType.ACC
    assert not sim.state.node_has_service(node.id)
    events = sim.drain()
    codes = [e.payload["code"] for e in events if e.topic == "alarm.raised"]
    assert codes[0] == "LINK_DOWN"
    assert all(e.incident == fault.id for e in events)


def test_conmutar_a_respaldo_recupera_el_nodo() -> None:
    sim = Simulator(42)
    fault = sim.inject(FaultType.CAIDA_ENLACE, with_backup=True)
    result = sim.switch_to_backup(fault.node or "")
    assert result.ok
    assert sim.state.node_has_service(fault.node or "")
    assert sim.fault_resolved(fault.id)


def test_conmutar_sin_respaldo_no_hace_nada() -> None:
    sim = Simulator(42)
    fault = sim.inject(FaultType.CAIDA_ENLACE, with_backup=False)
    result = sim.switch_to_backup(fault.node or "")
    assert not result.ok
    assert not sim.state.node_has_service(fault.node or "")


def test_gemelo_no_toca_la_red_real() -> None:
    sim = Simulator(42)
    fault = sim.inject(FaultType.CAIDA_ENLACE, with_backup=True)
    node = sim.state.nodes[fault.node or ""]
    twin = run_twin(sim.state, "conmutar_respaldo", {"node": node.id})
    assert twin.ok
    assert sim.state.links[node.backup_link or ""].status == LinkStatus.RESERVA


def test_gemelo_rechaza_lo_que_no_sabe_probar() -> None:
    sim = Simulator(42)
    assert not run_twin(sim.state, "borrar_todo", {}).ok


def test_ruido_marca_alarmas_falsas() -> None:
    sim = Simulator(42)
    sim.advance(24 * 60)
    falsas = [a for a in sim.state.alarms if not a.real]
    assert falsas
    assert all(a.code in {"FLAP_1S", "TEMP_TRANSITORIA", "PUERTA_ABIERTA", "LOS_TRANSITORIO"} for a in falsas)
