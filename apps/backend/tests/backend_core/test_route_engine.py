"""Deterministic in-memory tests for the ADR-0017 route engine."""

import math
from copy import deepcopy

import networkx as nx
import pytest

from backend_core import route_engine
from backend_core.route_engine import (
    LinkRiskGrade,
    RouteEngineConfigurationError,
    RouteGraphValidationError,
    RouteNodeCoordinate,
    RouteStatus,
    ShelterRouteCandidate,
    ValidatedSafeRouteEngine,
    load_raw_sillim_walking_graph,
    prepare_sillim_safe_route_engine,
)


def _graph() -> nx.MultiDiGraph:
    graph = nx.MultiDiGraph()
    graph.add_node("start", x=126.92, y=37.48, metadata={"source": ["osm"]})
    graph.add_node("safe", x=126.93, y=37.49)
    graph.add_node("risky", x=126.94, y=37.50)
    graph.add_node("shelter-a", x=126.95, y=37.51)
    graph.add_node("shelter-b", x=126.96, y=37.52)
    graph.add_edge(
        "start",
        "safe",
        length=30.0,
        risk_grade=LinkRiskGrade.R0,
        metadata={"sources": ["static-table"]},
    )
    graph.add_edge("safe", "shelter-b", length=50.0, risk_grade=LinkRiskGrade.R1)
    graph.add_edge("start", "risky", length=5.0, risk_grade=LinkRiskGrade.R2)
    graph.add_edge("risky", "shelter-a", length=5.0, risk_grade=LinkRiskGrade.R3)
    return graph


def _candidate(shelter_id: str, node_id: str) -> ShelterRouteCandidate:
    return ShelterRouteCandidate(shelter_id=shelter_id, node_id=node_id)


def test_r0_and_r1_return_node_coordinates_distance_and_time() -> None:
    result = ValidatedSafeRouteEngine(_graph()).find_route(
        origin_node="start",
        candidates=[_candidate("b", "shelter-b")],
        walking_speed_mps=2.0,
    )
    assert result.status is RouteStatus.FOUND
    assert result.selected_shelter_id == "b"
    assert result.distance_m == 80.0
    assert result.travel_time_s == 40.0
    assert result.node_coordinates == (
        RouteNodeCoordinate(lat=37.48, lng=126.92),
        RouteNodeCoordinate(lat=37.49, lng=126.93),
        RouteNodeCoordinate(lat=37.52, lng=126.96),
    )


@pytest.mark.parametrize("blocked_grade", [LinkRiskGrade.R2, LinkRiskGrade.R3])
def test_r2_and_r3_are_removed(blocked_grade: LinkRiskGrade) -> None:
    graph = nx.MultiDiGraph()
    graph.add_node("start", x=126.92, y=37.48)
    graph.add_node("shelter", x=126.93, y=37.49)
    graph.add_edge("start", "shelter", length=10.0, risk_grade=blocked_grade)
    result = ValidatedSafeRouteEngine(graph).find_route(
        origin_node="start", candidates=[_candidate("a", "shelter")], walking_speed_mps=1.0
    )
    assert result.status is RouteStatus.NO_ROUTE
    assert result.node_coordinates == ()


def test_raw_osm_graph_without_risk_grades_is_rejected() -> None:
    raw = nx.MultiDiGraph()
    raw.add_node(1, x=126.92, y=37.48)
    raw.add_node(2, x=126.93, y=37.49)
    raw.add_edge(1, 2, length=10.0)
    with pytest.raises(RouteGraphValidationError, match="risk_grade"):
        ValidatedSafeRouteEngine(raw)


def test_loader_annotator_and_validation_are_separate_stages() -> None:
    raw = nx.MultiDiGraph()
    raw.add_node(1, x=126.92, y=37.48)
    raw.add_node(2, x=126.93, y=37.49)
    raw.add_edge(1, 2, length=10.0)
    calls: list[str] = []

    def loader() -> nx.MultiDiGraph:
        calls.append("load")
        return raw

    def annotate(graph: nx.MultiDiGraph) -> nx.MultiDiGraph:
        calls.append("annotate")
        graph.edges[1, 2, 0]["risk_grade"] = LinkRiskGrade.R0
        return graph

    engine = prepare_sillim_safe_route_engine(annotate, graph_loader=loader)
    result = engine.find_route(
        origin_node=1, candidates=[ShelterRouteCandidate("s", 2)], walking_speed_mps=1.0
    )
    assert calls == ["load", "annotate"]
    assert "risk_grade" not in raw.edges[1, 2, 0]
    assert result.status is RouteStatus.FOUND


def test_missing_osmnx_is_a_clear_configuration_error(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = __import__

    def blocked_import(name: str, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name == "osmnx":
            raise ModuleNotFoundError(name="osmnx")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", blocked_import)
    with pytest.raises(
        RouteEngineConfigurationError, match='install the Backend "geo" extra'
    ) as caught:
        load_raw_sillim_walking_graph()
    assert isinstance(caught.value.__cause__, ModuleNotFoundError)
    assert caught.value.__cause__.name == "osmnx"


def test_missing_osmnx_dependency_preserves_cause(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = __import__

    def blocked_import(name: str, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name == "osmnx":
            raise ModuleNotFoundError(name="shapely")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", blocked_import)
    with pytest.raises(RouteEngineConfigurationError, match=r"dependency 'shapely'.*geo") as caught:
        load_raw_sillim_walking_graph()
    assert isinstance(caught.value.__cause__, ModuleNotFoundError)
    assert caught.value.__cause__.name == "shapely"


def test_import_monkeypatch_does_not_leak() -> None:
    assert __import__("math") is math


def test_first_no_route_reselects_second_candidate_in_order() -> None:
    result = ValidatedSafeRouteEngine(_graph()).find_route(
        origin_node="start",
        candidates=[_candidate("a", "shelter-a"), _candidate("b", "shelter-b")],
        walking_speed_mps=1.0,
    )
    assert result.status is RouteStatus.FOUND
    assert result.selected_shelter_id == "b"
    assert result.reselection_count == 1
    assert result.candidates_checked == 2


def test_empty_and_all_unreachable_candidates_are_no_route() -> None:
    engine = ValidatedSafeRouteEngine(_graph())
    empty = engine.find_route(origin_node="start", candidates=[], walking_speed_mps=1.0)
    graph = _graph()
    graph.add_node("isolated", x=126.97, y=37.53)
    unavailable = ValidatedSafeRouteEngine(graph).find_route(
        origin_node="start",
        candidates=[_candidate("a", "shelter-a"), _candidate("c", "isolated")],
        walking_speed_mps=1.0,
    )
    assert empty.status is RouteStatus.NO_ROUTE
    assert empty.candidates_checked == 0
    assert unavailable.status is RouteStatus.NO_ROUTE
    assert unavailable.reselection_count == 1


def test_engine_error_is_not_disguised_as_reselection() -> None:
    result = ValidatedSafeRouteEngine(_graph()).find_route(
        origin_node="missing",
        candidates=[_candidate("a", "shelter-a"), _candidate("b", "shelter-b")],
        walking_speed_mps=1.0,
    )
    assert result.status is RouteStatus.ENGINE_ERROR
    assert result.reselection_count == 0
    assert result.candidates_checked == 1


def test_networkx_no_path_is_no_route(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_path(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise nx.NetworkXNoPath

    monkeypatch.setattr(nx, "shortest_path", no_path)
    result = ValidatedSafeRouteEngine(_graph()).find_route(
        origin_node="start", candidates=[_candidate("a", "shelter-a")], walking_speed_mps=1.0
    )
    assert result.status is RouteStatus.NO_ROUTE


def test_node_not_found_is_engine_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def node_not_found(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise nx.NodeNotFound

    monkeypatch.setattr(nx, "shortest_path", node_not_found)
    result = ValidatedSafeRouteEngine(_graph()).find_route(
        origin_node="start", candidates=[_candidate("a", "shelter-a")], walking_speed_mps=1.0
    )
    assert result.status is RouteStatus.ENGINE_ERROR


def test_engine_error_on_later_candidate_stops_reselection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def fail_after_no_route(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        if calls == 1:
            raise nx.NetworkXNoPath
        raise nx.NodeNotFound

    monkeypatch.setattr(nx, "shortest_path", fail_after_no_route)
    result = ValidatedSafeRouteEngine(_graph()).find_route(
        origin_node="start",
        candidates=[_candidate("a", "shelter-a"), _candidate("b", "shelter-b")],
        walking_speed_mps=1.0,
    )
    assert result.status is RouteStatus.ENGINE_ERROR
    assert result.candidates_checked == 2
    assert calls == 2


@pytest.mark.parametrize("error", [ArithmeticError(), TypeError()])
def test_calculation_errors_are_engine_error(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    def fail(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise error

    monkeypatch.setattr(route_engine, "_route_one", fail)
    result = ValidatedSafeRouteEngine(_graph()).find_route(
        origin_node="start", candidates=[_candidate("a", "shelter-a")], walking_speed_mps=1.0
    )
    assert result.status is RouteStatus.ENGINE_ERROR


@pytest.mark.parametrize("error_type", [MemoryError, KeyboardInterrupt, SystemExit])
def test_non_recoverable_errors_propagate(
    monkeypatch: pytest.MonkeyPatch, error_type: type[BaseException]
) -> None:
    def fail(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise error_type

    monkeypatch.setattr(nx, "shortest_path", fail)
    with pytest.raises(error_type):
        ValidatedSafeRouteEngine(_graph()).find_route(
            origin_node="start",
            candidates=[_candidate("a", "shelter-a")],
            walking_speed_mps=1.0,
        )


@pytest.mark.parametrize("speed", [0.0, -1.0, float("nan"), float("inf"), -float("inf")])
def test_non_positive_or_non_finite_speed_is_engine_error(speed: float) -> None:
    result = ValidatedSafeRouteEngine(_graph()).find_route(
        origin_node="start", candidates=[_candidate("b", "shelter-b")], walking_speed_mps=speed
    )
    assert result.status is RouteStatus.ENGINE_ERROR
    assert result.candidates_checked == 0


def test_parallel_edge_uses_networkx_minimum_weight() -> None:
    graph = nx.MultiDiGraph()
    graph.add_node("start", x=126.92, y=37.48)
    graph.add_node("end", x=126.93, y=37.49)
    graph.add_edge("start", "end", key="slow", length=50.0, risk_grade=LinkRiskGrade.R0)
    graph.add_edge("start", "end", key="fast", length=20.0, risk_grade=LinkRiskGrade.R1)
    result = ValidatedSafeRouteEngine(graph).find_route(
        origin_node="start", candidates=[_candidate("s", "end")], walking_speed_mps=2.0
    )
    assert result.distance_m == 20.0
    assert result.travel_time_s == 10.0


def test_same_origin_and_destination_returns_float_zero_distance() -> None:
    result = ValidatedSafeRouteEngine(_graph()).find_route(
        origin_node="start", candidates=[_candidate("same", "start")], walking_speed_mps=1.5
    )
    assert isinstance(result.distance_m, float)
    assert isinstance(result.travel_time_s, float)
    assert result.distance_m == 0.0
    assert result.travel_time_s == 0.0
    assert result == route_engine.RouteResult(
        selected_shelter_id="same",
        status=RouteStatus.FOUND,
        distance_m=0.0,
        travel_time_s=0.0,
        node_coordinates=(RouteNodeCoordinate(lat=37.48, lng=126.92),),
        reselection_count=0,
        candidates_checked=1,
    )


@pytest.mark.parametrize(
    ("target", "field", "bad_value"),
    [
        ("edge", "length", "10.0"),
        ("node", "x", "127.0"),
        ("node", "y", "37.0"),
        ("edge", "length", True),
        ("node", "x", True),
        ("node", "y", False),
    ],
)
def test_numeric_fields_reject_strings_and_bools(
    target: str, field: str, bad_value: object
) -> None:
    graph = _graph()
    if target == "edge":
        graph.edges["start", "safe", 0][field] = bad_value
    else:
        graph.nodes["safe"][field] = bad_value
    with pytest.raises(RouteGraphValidationError):
        ValidatedSafeRouteEngine(graph)


def test_numeric_fields_accept_ints_and_floats() -> None:
    graph = _graph()
    graph.nodes["start"]["x"] = 126
    graph.nodes["start"]["y"] = 37.0
    graph.edges["start", "safe", 0]["length"] = 30
    result = ValidatedSafeRouteEngine(graph).find_route(
        origin_node="start", candidates=[_candidate("b", "shelter-b")], walking_speed_mps=2
    )
    assert result.status is RouteStatus.FOUND
    assert result.distance_m == 80.0


@pytest.mark.parametrize(
    ("target", "field", "bad_value"),
    [
        ("edge", "risk_grade", "R9"),
        ("edge", "length", -1),
        ("edge", "length", float("nan")),
        ("edge", "length", float("inf")),
        ("node", "x", float("nan")),
        ("node", "y", float("inf")),
    ],
)
def test_whole_graph_validation_rejects_invalid_data(
    target: str, field: str, bad_value: object
) -> None:
    graph = _graph()
    if target == "edge":
        graph.edges["start", "safe", 0][field] = bad_value
    else:
        graph.nodes["safe"][field] = bad_value
    with pytest.raises(RouteGraphValidationError):
        ValidatedSafeRouteEngine(graph)


def test_validation_checks_disconnected_nodes_and_edges_too() -> None:
    graph = _graph()
    graph.add_node("bad-a", x=126.98, y=37.54)
    graph.add_node("bad-b", x=126.99, y=37.55)
    graph.add_edge("bad-a", "bad-b", length=1.0)
    with pytest.raises(RouteGraphValidationError, match="risk_grade"):
        ValidatedSafeRouteEngine(graph)

    graph = _graph()
    graph.add_node("bad", x=126.98)
    with pytest.raises(RouteGraphValidationError, match="numeric x and y"):
        ValidatedSafeRouteEngine(graph)


def test_graph_type_and_missing_length_are_validation_errors() -> None:
    with pytest.raises(RouteGraphValidationError, match="MultiDiGraph"):
        ValidatedSafeRouteEngine(nx.DiGraph())  # type: ignore[arg-type]

    graph = _graph()
    del graph.edges["start", "safe", 0]["length"]
    with pytest.raises(RouteGraphValidationError, match="length"):
        ValidatedSafeRouteEngine(graph)


def test_validation_runs_once_at_engine_preparation(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0
    original = route_engine._validated_safe_copy

    def counted(graph: nx.MultiDiGraph) -> nx.MultiDiGraph:
        nonlocal calls
        calls += 1
        return original(graph)

    monkeypatch.setattr(route_engine, "_validated_safe_copy", counted)
    engine = ValidatedSafeRouteEngine(_graph())
    for _ in range(2):
        engine.find_route(
            origin_node="start",
            candidates=[_candidate("b", "shelter-b")],
            walking_speed_mps=1.0,
        )
    assert calls == 1


def test_original_graph_and_nested_attributes_are_unchanged() -> None:
    graph = _graph()
    before = deepcopy(graph)
    engine = ValidatedSafeRouteEngine(graph)
    engine._safe_graph.nodes["start"]["metadata"]["source"].append("changed")
    engine._safe_graph.edges["start", "safe", 0]["metadata"]["sources"].append("changed")
    assert nx.utils.graphs_equal(graph, before)


def test_same_input_returns_same_unrounded_result() -> None:
    engine = ValidatedSafeRouteEngine(_graph())
    candidates = [_candidate("a", "shelter-a"), _candidate("b", "shelter-b")]
    first = engine.find_route(origin_node="start", candidates=candidates, walking_speed_mps=1.25)
    second = engine.find_route(origin_node="start", candidates=candidates, walking_speed_mps=1.25)
    assert first == second
    assert first.distance_m == 80.0
    assert first.travel_time_s == 64.0
