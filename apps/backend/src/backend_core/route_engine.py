"""Flood-avoiding walking-route core for the Sillim-dong demo (ADR-0017).

OSMnx returns a raw graph with no SAVERS ``risk_grade``. A separately sourced annotator
must grade every edge before this module builds a validated engine. Missing grades are
never interpreted as R0.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Hashable, Sequence
from copy import deepcopy
from dataclasses import dataclass
from enum import StrEnum
from itertools import pairwise
from numbers import Real

import networkx as nx

SILLIM_PLACE = "신림동, 관악구, 서울특별시, 대한민국"
_BLOCKED_GRADES = frozenset({"R2", "R3"})


class LinkRiskGrade(StrEnum):
    R0 = "R0"
    R1 = "R1"
    R2 = "R2"
    R3 = "R3"


class RouteStatus(StrEnum):
    FOUND = "found"
    NO_ROUTE = "no_route"
    ENGINE_ERROR = "engine_error"


class RouteEngineConfigurationError(RuntimeError):
    """The optional geo stack required to prepare an engine is unavailable."""


class RouteGraphLoadError(RuntimeError):
    """OSMnx could not load the configured demo-area graph."""


class RouteGraphValidationError(ValueError):
    """A graph is not fully annotated and valid for safety routing."""


@dataclass(frozen=True)
class ShelterRouteCandidate:
    shelter_id: str
    node_id: Hashable


@dataclass(frozen=True)
class RouteNodeCoordinate:
    """One OSM node coordinate, not an edge-geometry/polyline vertex."""

    lat: float
    lng: float


@dataclass(frozen=True)
class RouteResult:
    selected_shelter_id: str | None
    status: RouteStatus
    distance_m: float | None
    travel_time_s: float | None
    node_coordinates: tuple[RouteNodeCoordinate, ...]
    reselection_count: int
    candidates_checked: int


RiskAnnotator = Callable[[nx.MultiDiGraph], nx.MultiDiGraph]
GraphLoader = Callable[[], nx.MultiDiGraph]


class _NoSafeRouteError(Exception):
    """A valid graph has no connection between the requested endpoints."""


def load_raw_sillim_walking_graph() -> nx.MultiDiGraph:
    """Load raw OSM walking data; this does not assign SAVERS risk grades."""
    try:
        import osmnx as ox
    except ModuleNotFoundError as exc:
        missing_dependency = exc.name or "unknown"
        if missing_dependency == "osmnx":
            detail = "OSMnx is unavailable"
        else:
            detail = f"OSMnx dependency {missing_dependency!r} is unavailable"
        raise RouteEngineConfigurationError(f'{detail}; install the Backend "geo" extra') from exc

    try:
        graph: nx.MultiDiGraph = ox.graph_from_place(SILLIM_PLACE, network_type="walk")
    except Exception as exc:
        raise RouteGraphLoadError("failed to load the Sillim walking graph") from exc
    return graph


def prepare_sillim_safe_route_engine(
    risk_annotator: RiskAnnotator,
    *,
    graph_loader: GraphLoader = load_raw_sillim_walking_graph,
) -> ValidatedSafeRouteEngine:
    """Run the three explicit stages: raw loader -> annotator -> validated engine."""
    raw_graph = graph_loader()
    annotated_graph = risk_annotator(deepcopy(raw_graph))
    return ValidatedSafeRouteEngine(annotated_graph)


def _validated_safe_copy(graph: nx.MultiDiGraph) -> nx.MultiDiGraph:
    """Deep-copy, validate the whole graph once, then remove R2/R3 edges."""
    if not isinstance(graph, nx.MultiDiGraph):
        raise RouteGraphValidationError("route graph must be a networkx.MultiDiGraph")

    safe = deepcopy(graph)
    for node_id, data in safe.nodes(data=True):
        try:
            x = data["x"]
            y = data["y"]
        except KeyError as exc:
            raise RouteGraphValidationError(
                f"route node {node_id!r} requires numeric x and y"
            ) from exc
        if not _is_finite_real(x) or not _is_finite_real(y):
            raise RouteGraphValidationError(f"route node {node_id!r} requires finite x and y")

    blocked: list[tuple[Hashable, Hashable, Hashable]] = []
    for start, end, key, data in safe.edges(keys=True, data=True):
        try:
            grade = LinkRiskGrade(data["risk_grade"])
            length = data["length"]
        except (KeyError, TypeError, ValueError) as exc:
            raise RouteGraphValidationError(
                f"route edge {(start, end, key)!r} requires a valid risk_grade and length"
            ) from exc
        if not _is_finite_real(length) or length < 0:
            raise RouteGraphValidationError(
                f"route edge {(start, end, key)!r} requires a finite non-negative length"
            )
        if grade in _BLOCKED_GRADES:
            blocked.append((start, end, key))

    for start, end, key in blocked:
        safe.remove_edge(start, end, key)
    return safe


def _is_finite_real(value: object) -> bool:
    return isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(value)


def _node_coordinate(graph: nx.MultiDiGraph, node_id: Hashable) -> RouteNodeCoordinate:
    data = graph.nodes[node_id]
    return RouteNodeCoordinate(lat=float(data["y"]), lng=float(data["x"]))


def _selected_edge_length(graph: nx.MultiDiGraph, start: Hashable, end: Hashable) -> float:
    """Match NetworkX's minimum-weight parallel edge with a deterministic tie-break."""
    edges = graph.get_edge_data(start, end)
    if not edges:
        raise RouteGraphValidationError(f"route step {(start, end)!r} has no edge")
    _key, data = min(
        edges.items(),
        key=lambda item: (float(item[1]["length"]), repr(item[0])),
    )
    return float(data["length"])


def _route_one(
    graph: nx.MultiDiGraph,
    origin_node: Hashable,
    destination_node: Hashable,
) -> tuple[float, tuple[RouteNodeCoordinate, ...]]:
    try:
        nodes = nx.shortest_path(graph, origin_node, destination_node, weight="length")
    except nx.NetworkXNoPath as exc:
        raise _NoSafeRouteError from exc
    distance = sum(
        (_selected_edge_length(graph, start, end) for start, end in pairwise(nodes)),
        start=0.0,
    )
    return distance, tuple(_node_coordinate(graph, node_id) for node_id in nodes)


def _engine_error(*, candidates_checked: int) -> RouteResult:
    return RouteResult(
        None,
        RouteStatus.ENGINE_ERROR,
        None,
        None,
        (),
        max(0, candidates_checked - 1),
        candidates_checked,
    )


class ValidatedSafeRouteEngine:
    """Route only on a graph fully validated and filtered during construction."""

    def __init__(self, annotated_graph: nx.MultiDiGraph) -> None:
        self._safe_graph = _validated_safe_copy(annotated_graph)

    def find_route(
        self,
        *,
        origin_node: Hashable,
        candidates: Sequence[ShelterRouteCandidate],
        walking_speed_mps: float,
    ) -> RouteResult:
        """Return OSM node coordinates; edge geometry is intentionally not represented."""
        if not _is_finite_real(walking_speed_mps) or walking_speed_mps <= 0:
            return _engine_error(candidates_checked=0)
        if origin_node not in self._safe_graph:
            return _engine_error(candidates_checked=0)

        checked = 0
        for candidate in candidates:
            checked += 1
            if candidate.node_id not in self._safe_graph:
                continue
            try:
                distance, node_coordinates = _route_one(
                    self._safe_graph, origin_node, candidate.node_id
                )
            except _NoSafeRouteError:
                continue
            except MemoryError:
                raise
            except Exception:
                return _engine_error(candidates_checked=checked)
            return RouteResult(
                candidate.shelter_id,
                RouteStatus.FOUND,
                distance,
                distance / walking_speed_mps,
                node_coordinates,
                checked - 1,
                checked,
            )

        return RouteResult(
            None,
            RouteStatus.NO_ROUTE,
            None,
            None,
            (),
            max(0, checked - 1),
            checked,
        )
