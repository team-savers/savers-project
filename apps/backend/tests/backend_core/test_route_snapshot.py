"""Deterministic GraphML snapshot loader tests (issue #224).

No network, no OSMnx: the loader reads the committed *synthetic* sample fixture with NetworkX
only. Corruption, absence, oversize, and schema drift each surface as a distinct explicit
error rather than a silent empty graph or a silent Overpass fallback, and the same fixture
always yields the same route. The snapshot-first boundary (in ``route_engine``) judges the
snapshot as a **pair** and falls back to Overpass only when *both* files are absent.
"""

from __future__ import annotations

import builtins
import hashlib
import json
import shutil
import sys
import types
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import ClassVar

import networkx as nx
import pytest

from backend_core import route_engine
from backend_core import route_snapshot as rs
from backend_core.route_engine import (
    LinkRiskGrade,
    LoadedRouteGraph,
    RouteStatus,
    ShelterRouteCandidate,
    load_sillim_walking_graph_snapshot_first,
    prepare_sillim_safe_route_engine,
)


def _copy_sample(tmp_path: Path) -> tuple[Path, Path]:
    """Copy the committed synthetic sample so a test can tamper safely."""
    graph_dst = tmp_path / "s.graphml"
    meta_dst = tmp_path / "s.metadata.json"
    shutil.copyfile(rs.SAMPLE_SNAPSHOT_PATH, graph_dst)
    shutil.copyfile(rs.SAMPLE_SNAPSHOT_METADATA_PATH, meta_dst)
    return graph_dst, meta_dst


def _load_sample() -> rs.LoadedSnapshot:
    return rs.load_sillim_snapshot(
        snapshot_path=rs.SAMPLE_SNAPSHOT_PATH, metadata_path=rs.SAMPLE_SNAPSHOT_METADATA_PATH
    )


def _reseal(graph_path: Path, meta_path: Path, **overrides: object) -> None:
    """Recompute graph_sha256 so checksum passes, then apply metadata overrides."""
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["graph_sha256"] = hashlib.sha256(graph_path.read_bytes()).hexdigest()
    meta.update(overrides)
    meta_path.write_text(json.dumps(meta), encoding="utf-8")


def _write_nx_graph(tmp_path: Path, graph: nx.Graph, **overrides: object) -> tuple[Path, Path]:
    """Write an arbitrary NetworkX graph as GraphML with a matching sealed metadata sidecar.

    Used to build graphs the loader must *reject by type* (a DiGraph, undirected Graph) — the
    checksum and counts are made consistent so the type/structure check is what fails, not a
    stale checksum.
    """
    gpath = tmp_path / "g.graphml"
    mpath = tmp_path / "g.metadata.json"
    nx.write_graphml(graph, gpath, named_key_ids=True)
    meta = json.loads(rs.SAMPLE_SNAPSHOT_METADATA_PATH.read_text(encoding="utf-8"))
    meta["node_count"] = graph.number_of_nodes()
    meta["edge_count"] = graph.number_of_edges()
    meta["graph_sha256"] = hashlib.sha256(gpath.read_bytes()).hexdigest()
    meta.update(overrides)
    mpath.write_text(json.dumps(meta), encoding="utf-8")
    return gpath, mpath


def _grade_all_r0(graph: nx.MultiDiGraph) -> nx.MultiDiGraph:
    for _u, _v, data in graph.edges(data=True):
        data["risk_grade"] = LinkRiskGrade.R0
    return graph


class _SpyLoader:
    def __init__(self, result: nx.MultiDiGraph | None = None, exc: Exception | None = None) -> None:
        self.calls = 0
        self._result = result
        self._exc = exc

    def __call__(self) -> nx.MultiDiGraph:
        self.calls += 1
        if self._exc is not None:
            raise self._exc
        assert self._result is not None
        return self._result


# ── loader focused: happy path, no network, no OSMnx ─────────────────────────────────────────


def test_load_sample_returns_directed_multigraph() -> None:
    loaded = _load_sample()
    assert isinstance(loaded.graph, nx.MultiDiGraph)
    assert loaded.graph.is_directed() and loaded.graph.is_multigraph()
    assert loaded.graph.number_of_nodes() == loaded.identity.node_count == 6
    assert loaded.graph.number_of_edges() == loaded.identity.edge_count == 16


def test_identity_marks_synthetic_for_safety_receipt() -> None:
    identity = _load_sample().identity
    assert identity.source_kind == rs.SOURCE_KIND_SYNTHETIC
    assert identity.is_synthetic is True
    assert (
        identity.snapshot_id
        == f"sillim-walk-v{identity.schema_version}-synthetic-{identity.graph_sha256[:12]}"
    )
    assert identity.schema_version == rs.SNAPSHOT_SCHEMA_VERSION == 2
    assert "OSM 데이터 아님" in identity.attribution  # synthetic never claims OSM
    assert identity.source and identity.place and identity.network_type == "walk"


def test_synthetic_sample_attribution_carries_no_osm_credit() -> None:
    """MINOR: a synthetic fixture must not carry the OSM attribution string at all."""
    payload = json.loads(rs.SAMPLE_SNAPSHOT_METADATA_PATH.read_text(encoding="utf-8"))
    assert "OpenStreetMap" not in payload["attribution"]
    assert payload["source_license"] != rs.OSM_LICENSE
    assert "OSM 데이터 아님" in payload["attribution"]


def test_operational_default_snapshot_is_absent_not_synthetic() -> None:
    """The synthetic sample must not stand in as the operational sillim_walk.graphml."""
    assert not rs.SNAPSHOT_PATH.is_file()
    with pytest.raises(rs.SnapshotFileMissingError):
        rs.load_sillim_snapshot()


def test_round_trip_preserves_types_keys_attrs_and_crs() -> None:
    graph = _load_sample().graph
    assert graph.graph.get("crs") == "EPSG:4326"  # graph attribute preserved
    node_id, data = next(iter(graph.nodes(data=True)))
    assert isinstance(node_id, int)
    assert isinstance(data["x"], float) and isinstance(data["y"], float)
    for _u, _v, edge in graph.edges(data=True):
        assert isinstance(edge["length"], float)
        assert "osmid" in edge  # non-standard edge attribute preserved
    parallel = graph.get_edge_data(1000002, 1000003)
    assert len(parallel) == 2  # parallel edge keys preserved
    assert {round(d["length"]) for d in parallel.values()} == {100, 105}
    assert all(isinstance(key, int) for key in parallel)


def test_load_does_not_import_osmnx(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def blocked(name: str, *args: object, **kwargs: object) -> object:
        if name == "osmnx" or name.startswith("osmnx."):
            raise AssertionError("loader must not import osmnx")
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(builtins, "__import__", blocked)
    assert _load_sample().graph.number_of_nodes() == 6


# ── explicit error classification: absence, size, checksum, schema ───────────────────────────


def test_missing_graphml_is_file_missing_error(tmp_path: Path) -> None:
    _graph, meta = _copy_sample(tmp_path)
    with pytest.raises(rs.SnapshotFileMissingError, match="GraphML is missing"):
        rs.load_sillim_snapshot(snapshot_path=tmp_path / "absent.graphml", metadata_path=meta)


def test_missing_metadata_is_file_missing_error(tmp_path: Path) -> None:
    graph, _meta = _copy_sample(tmp_path)
    with pytest.raises(rs.SnapshotFileMissingError, match="metadata is missing"):
        rs.load_sillim_snapshot(snapshot_path=graph, metadata_path=tmp_path / "absent.json")


def test_oversize_graphml_rejected_before_parse(tmp_path: Path) -> None:
    graph, meta = _copy_sample(tmp_path)
    size = graph.stat().st_size
    # boundary: exactly at the ceiling is allowed, one byte over is rejected. The error names the
    # GraphML so an operator can tell which of the two files blew the limit.
    assert rs.load_sillim_snapshot(snapshot_path=graph, metadata_path=meta, max_bytes=size)
    with pytest.raises(rs.SnapshotTooLargeError, match=r"GraphML exceeds"):
        rs.load_sillim_snapshot(snapshot_path=graph, metadata_path=meta, max_bytes=size - 1)


def test_oversize_metadata_rejected_before_parse(tmp_path: Path) -> None:
    graph, meta = _copy_sample(tmp_path)
    size = meta.stat().st_size
    # Exact boundary allowed; one byte over rejected *before* json.loads reads the file, and the
    # error names the metadata so it is distinguishable from a GraphML oversize.
    assert rs.load_sillim_snapshot(snapshot_path=graph, metadata_path=meta, max_metadata_bytes=size)
    with pytest.raises(rs.SnapshotTooLargeError, match=r"metadata exceeds"):
        rs.load_sillim_snapshot(
            snapshot_path=graph, metadata_path=meta, max_metadata_bytes=size - 1
        )


def test_oversize_metadata_is_rejected_without_parsing(tmp_path: Path) -> None:
    """A metadata file over the ceiling is rejected on size even when its JSON is unparseable —
    proving the bounded read's size gate runs before any decode/parse."""
    graph, meta = _copy_sample(tmp_path)
    meta.write_text("{ this is not valid json at all " + "x" * 200, encoding="utf-8")
    size = meta.stat().st_size
    with pytest.raises(rs.SnapshotTooLargeError, match="metadata exceeds"):
        rs.load_sillim_snapshot(
            snapshot_path=graph, metadata_path=meta, max_metadata_bytes=size - 1
        )


def test_checksum_mismatch_is_its_own_error(tmp_path: Path) -> None:
    graph, meta = _copy_sample(tmp_path)
    graph.write_bytes(graph.read_bytes() + b"<!-- tampered -->")  # metadata sha now stale
    with pytest.raises(rs.SnapshotChecksumMismatchError, match="sha256 does not match"):
        rs.load_sillim_snapshot(snapshot_path=graph, metadata_path=meta)


def test_schema_version_mismatch_is_its_own_error(tmp_path: Path) -> None:
    graph, meta = _copy_sample(tmp_path)
    _reseal(graph, meta, schema_version=rs.SNAPSHOT_SCHEMA_VERSION + 1)
    with pytest.raises(rs.SnapshotSchemaMismatchError, match="schema version"):
        rs.load_sillim_snapshot(snapshot_path=graph, metadata_path=meta)


def test_metadata_top_level_array_is_schema_error(tmp_path: Path) -> None:
    graph, meta = _copy_sample(tmp_path)
    meta.write_text("[]", encoding="utf-8")
    with pytest.raises(rs.SnapshotSchemaMismatchError, match="not a JSON object"):
        rs.load_sillim_snapshot(snapshot_path=graph, metadata_path=meta)


def test_unreadable_metadata_is_schema_error(tmp_path: Path) -> None:
    graph, meta = _copy_sample(tmp_path)
    meta.write_text("{ not json", encoding="utf-8")
    with pytest.raises(rs.SnapshotSchemaMismatchError, match="not readable JSON"):
        rs.load_sillim_snapshot(snapshot_path=graph, metadata_path=meta)


def test_missing_metadata_field_is_schema_error(tmp_path: Path) -> None:
    graph, meta = _copy_sample(tmp_path)
    payload = json.loads(meta.read_text(encoding="utf-8"))
    del payload["source_kind"]
    meta.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(rs.SnapshotSchemaMismatchError, match="missing field 'source_kind'"):
        rs.load_sillim_snapshot(snapshot_path=graph, metadata_path=meta)


def test_wrong_typed_metadata_field_is_schema_error(tmp_path: Path) -> None:
    graph, meta = _copy_sample(tmp_path)
    payload = json.loads(meta.read_text(encoding="utf-8"))
    payload["node_count"] = "six"
    meta.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(rs.SnapshotSchemaMismatchError, match="must be an integer"):
        rs.load_sillim_snapshot(snapshot_path=graph, metadata_path=meta)


def test_arbitrary_source_kind_is_rejected(tmp_path: Path) -> None:
    """MINOR: source_kind must be exactly 'osm' or 'synthetic'; a typo'd/arbitrary value fails."""
    graph, meta = _copy_sample(tmp_path)
    _reseal(graph, meta, source_kind="totally-made-up")
    with pytest.raises(rs.SnapshotSchemaMismatchError, match="source_kind"):
        rs.load_sillim_snapshot(snapshot_path=graph, metadata_path=meta)


def test_malformed_graphml_is_normalized_schema_error(tmp_path: Path) -> None:
    graph, meta = _copy_sample(tmp_path)
    graph.write_bytes(b"<graphml><not-closed>")
    _reseal(graph, meta)  # checksum passes so the parse failure is what surfaces
    with pytest.raises(rs.SnapshotSchemaMismatchError, match="could not be parsed"):
        rs.load_sillim_snapshot(snapshot_path=graph, metadata_path=meta)


def test_all_errors_share_one_base(tmp_path: Path) -> None:
    _graph, meta = _copy_sample(tmp_path)
    with pytest.raises(rs.RouteSnapshotError):
        rs.load_sillim_snapshot(snapshot_path=tmp_path / "absent.graphml", metadata_path=meta)


# ── graph_kind marker contract: writer guards type, loader trusts the marker ──────────────────


def test_writer_rejects_non_multidigraph_input() -> None:
    """The official writer refuses a DiGraph/Graph/MultiGraph so the stored graph_kind marker can
    never lie about the on-disk graph's true type (Codex MAJOR #1)."""
    for bad in (nx.DiGraph(), nx.Graph(), nx.MultiGraph()):
        bad.add_node(1, x=1.0, y=2.0)
        bad.add_node(2, x=1.0, y=2.0)
        bad.add_edge(1, 2, length=5.0)
        with pytest.raises(TypeError, match=r"requires a networkx\.MultiDiGraph"):
            rs.save_snapshot(
                bad,  # type: ignore[arg-type]
                snapshot_path=Path("unused.graphml"),
                metadata_path=Path("unused.json"),
                place="t",
                network_type="walk",
                simplify=True,
                osmnx_version="t",
                source="t",
                source_kind=rs.SOURCE_KIND_SYNTHETIC,
                attribution="t",
                source_license="",
                source_license_url="",
            )


def test_missing_graph_kind_marker_is_rejected(tmp_path: Path) -> None:
    graph, meta = _copy_sample(tmp_path)
    payload = json.loads(meta.read_text(encoding="utf-8"))
    del payload["graph_kind"]
    meta.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(rs.SnapshotSchemaMismatchError, match="missing field 'graph_kind'"):
        rs.load_sillim_snapshot(snapshot_path=graph, metadata_path=meta)


@pytest.mark.parametrize("bad", ["multidigraph", "DiGraph", "MultiGraph", "Graph", ""])
def test_wrong_graph_kind_value_is_rejected(tmp_path: Path, bad: str) -> None:
    graph, meta = _copy_sample(tmp_path)
    _reseal(graph, meta, graph_kind=bad)
    with pytest.raises(rs.SnapshotSchemaMismatchError, match="graph_kind"):
        rs.load_sillim_snapshot(snapshot_path=graph, metadata_path=meta)


def test_wrong_typed_graph_kind_is_rejected(tmp_path: Path) -> None:
    graph, meta = _copy_sample(tmp_path)
    _reseal(graph, meta, graph_kind=123)  # not a string
    with pytest.raises(rs.SnapshotSchemaMismatchError, match="graph_kind"):
        rs.load_sillim_snapshot(snapshot_path=graph, metadata_path=meta)


def test_no_parallel_multidigraph_round_trips_via_marker(tmp_path: Path) -> None:
    """A MultiDiGraph with a single edge (no parallel edges) reads back as a DiGraph in raw GraphML;
    the graph_kind marker lets the loader restore it as a MultiDiGraph with its key preserved."""
    graph = nx.MultiDiGraph(crs="EPSG:4326")
    graph.add_node(1, x=126.9, y=37.4)
    graph.add_node(2, x=126.91, y=37.41)
    graph.add_edge(1, 2, key=7, length=10.0, osmid=101)
    gpath, mpath = _write_graph(tmp_path, graph)
    loaded = rs.load_sillim_snapshot(snapshot_path=gpath, metadata_path=mpath)
    assert isinstance(loaded.graph, nx.MultiDiGraph)
    assert list(loaded.graph.edges(keys=True)) == [(1, 2, 7)]
    assert loaded.graph[1][2][7]["osmid"] == 101


def test_valid_marker_snapshot_restores_multidigraph(tmp_path: Path) -> None:
    """A snapshot whose marker is the valid MultiDiGraph value loads back as a MultiDiGraph."""
    graph, meta = _copy_sample(tmp_path)
    payload = json.loads(meta.read_text(encoding="utf-8"))
    assert payload["graph_kind"] == rs.GRAPH_KIND_MULTIDIGRAPH
    loaded = rs.load_sillim_snapshot(snapshot_path=graph, metadata_path=meta)
    assert isinstance(loaded.graph, nx.MultiDiGraph)
    assert loaded.graph.is_directed() and loaded.graph.is_multigraph()


# ── strict graph-shape validation (undirected / empty rejected despite a marker) ──────────────


def test_undirected_graph_snapshot_is_rejected(tmp_path: Path) -> None:
    graph = nx.Graph(crs="EPSG:4326")
    graph.add_node(1, x=126.9, y=37.4)
    graph.add_node(2, x=126.91, y=37.41)
    graph.add_edge(1, 2, length=10.0)
    gpath, mpath = _write_nx_graph(tmp_path, graph)
    with pytest.raises(rs.SnapshotSchemaMismatchError, match="directed multigraph"):
        rs.load_sillim_snapshot(snapshot_path=gpath, metadata_path=mpath)


def test_undirected_multigraph_snapshot_is_rejected(tmp_path: Path) -> None:
    graph = nx.MultiGraph(crs="EPSG:4326")
    graph.add_node(1, x=126.9, y=37.4)
    graph.add_node(2, x=126.91, y=37.41)
    graph.add_edge(1, 2, length=10.0)
    graph.add_edge(1, 2, length=12.0)  # parallel so it reads back as a MultiGraph, not a Graph
    gpath, mpath = _write_nx_graph(tmp_path, graph)
    with pytest.raises(rs.SnapshotSchemaMismatchError, match="directed multigraph"):
        rs.load_sillim_snapshot(snapshot_path=gpath, metadata_path=mpath)


def test_empty_graphml_is_rejected_on_load(tmp_path: Path) -> None:
    """An empty GraphML (0 nodes) written directly is rejected by the loader's structural check."""
    gpath, mpath = _write_nx_graph(tmp_path, nx.MultiDiGraph(crs="EPSG:4326"))
    with pytest.raises(rs.SnapshotSchemaMismatchError, match="no nodes"):
        rs.load_sillim_snapshot(snapshot_path=gpath, metadata_path=mpath)


def test_missing_crs_graph_attribute_is_rejected(tmp_path: Path) -> None:
    graph = rs.build_sample_graph()
    del graph.graph["crs"]
    gpath, mpath = _write_nx_graph(tmp_path, graph)
    with pytest.raises(rs.SnapshotSchemaMismatchError, match="'crs'"):
        rs.load_sillim_snapshot(snapshot_path=gpath, metadata_path=mpath)


def test_non_integer_edge_key_is_rejected(tmp_path: Path) -> None:
    """read_graphml keeps a non-integer edge id as-is (edge_key_type=int does not enforce it), so
    the loader must reject a non-integer key explicitly."""
    graph, meta = _copy_sample(tmp_path)
    # Turn one parallel edge's key from 1 into a string "x1"; the pair stays parallel (keys 0 &
    # "x1") so the graph still reads back as a MultiDiGraph and the key check is what fails.
    graph.write_bytes(graph.read_bytes().replace(b'id="1"', b'id="x1"', 1))
    _reseal(graph, meta)
    with pytest.raises(rs.SnapshotSchemaMismatchError, match="non-integer key"):
        rs.load_sillim_snapshot(snapshot_path=graph, metadata_path=meta)


def test_non_integer_node_id_is_normalized_schema_error(tmp_path: Path) -> None:
    graph, meta = _copy_sample(tmp_path)
    graph.write_bytes(graph.read_bytes().replace(b'id="1000001"', b'id="nodeA"'))
    _reseal(graph, meta)
    with pytest.raises(rs.SnapshotSchemaMismatchError, match="could not be parsed"):
        rs.load_sillim_snapshot(snapshot_path=graph, metadata_path=meta)


def test_valid_sample_preserves_parallel_edges_and_integer_keys(tmp_path: Path) -> None:
    """The strictness must not cost the valid case: parallel edges, integer keys, edge attrs stay."""
    graph, meta = _copy_sample(tmp_path)
    loaded = rs.load_sillim_snapshot(snapshot_path=graph, metadata_path=meta)
    parallel = loaded.graph.get_edge_data(1000002, 1000003)
    assert set(parallel) == {0, 1}
    assert all(isinstance(k, int) for k in parallel)
    assert {round(d["length"]) for d in parallel.values()} == {100, 105}


# ── graph + metadata count invariants (each direction independently) ──────────────────────────


def test_node_count_mismatch_is_rejected_independently(tmp_path: Path) -> None:
    graph, meta = _copy_sample(tmp_path)
    _reseal(graph, meta, node_count=999)  # edge_count left correct at 16
    with pytest.raises(
        rs.SnapshotSchemaMismatchError, match="node count 6 does not match metadata 999"
    ):
        rs.load_sillim_snapshot(snapshot_path=graph, metadata_path=meta)


def test_edge_count_mismatch_is_rejected_independently(tmp_path: Path) -> None:
    graph, meta = _copy_sample(tmp_path)
    _reseal(graph, meta, edge_count=888)  # node_count left correct at 6
    with pytest.raises(
        rs.SnapshotSchemaMismatchError, match="edge count 16 does not match metadata 888"
    ):
        rs.load_sillim_snapshot(snapshot_path=graph, metadata_path=meta)


def _write_graph(tmp_path: Path, graph: nx.MultiDiGraph) -> tuple[Path, Path]:
    gpath = tmp_path / "g.graphml"
    mpath = tmp_path / "g.metadata.json"
    rs.save_snapshot(
        graph,
        snapshot_path=gpath,
        metadata_path=mpath,
        place="test",
        network_type="walk",
        simplify=True,
        osmnx_version="test",
        source="test",
        source_kind=rs.SOURCE_KIND_SYNTHETIC,
        attribution="test",
        source_license="",
        source_license_url="",
        generated_at="2026-08-29T00:00:00+00:00",
    )
    return gpath, mpath


def test_missing_node_x_is_rejected_on_load(tmp_path: Path) -> None:
    graph = rs.build_sample_graph()
    del graph.nodes[1000001]["x"]
    gpath, mpath = _write_nx_graph(tmp_path, graph)  # raw write bypasses the writer precheck
    with pytest.raises(rs.SnapshotSchemaMismatchError, match="missing x"):
        rs.load_sillim_snapshot(snapshot_path=gpath, metadata_path=mpath)


def test_missing_node_y_is_rejected_on_load(tmp_path: Path) -> None:
    graph = rs.build_sample_graph()
    del graph.nodes[1000001]["y"]
    gpath, mpath = _write_nx_graph(tmp_path, graph)
    with pytest.raises(rs.SnapshotSchemaMismatchError, match="missing y"):
        rs.load_sillim_snapshot(snapshot_path=gpath, metadata_path=mpath)


def test_missing_edge_length_is_rejected_on_load(tmp_path: Path) -> None:
    graph = rs.build_sample_graph()
    first = next(iter(graph.edges(keys=True)))
    del graph.edges[first]["length"]
    gpath, mpath = _write_nx_graph(tmp_path, graph)
    with pytest.raises(rs.SnapshotSchemaMismatchError, match="missing length"):
        rs.load_sillim_snapshot(snapshot_path=gpath, metadata_path=mpath)


# ── writer shares the loader's structural contract (Codex 5th-audit MAJOR #1) ──────────────────


def test_writer_rejects_structurally_invalid_graphs(tmp_path: Path) -> None:
    """The writer refuses, before writing, every graph the loader's structural contract rejects —
    so a save that succeeds always yields an immediately-loadable pair."""
    unused = tmp_path / "unused.graphml"
    unused_meta = tmp_path / "unused.json"

    def _save(g: nx.MultiDiGraph) -> None:
        rs.save_snapshot(
            g,
            snapshot_path=unused,
            metadata_path=unused_meta,
            place="t",
            network_type="walk",
            simplify=True,
            osmnx_version="t",
            source="t",
            source_kind=rs.SOURCE_KIND_SYNTHETIC,
            attribution="t",
            source_license="",
            source_license_url="",
            generated_at="2026-08-29T00:00:00+00:00",
        )

    no_crs = nx.MultiDiGraph()
    no_crs.add_node(1, x=1.0, y=2.0)
    no_crs.add_node(2, x=1.0, y=2.0)
    no_crs.add_edge(1, 2, key=0, length=5.0)

    no_x = nx.MultiDiGraph(crs="EPSG:4326")
    no_x.add_node(1, y=2.0)
    no_x.add_node(2, x=1.0, y=2.0)
    no_x.add_edge(1, 2, key=0, length=5.0)

    no_len = nx.MultiDiGraph(crs="EPSG:4326")
    no_len.add_node(1, x=1.0, y=2.0)
    no_len.add_node(2, x=1.0, y=2.0)
    no_len.add_edge(1, 2, key=0)

    str_id = nx.MultiDiGraph(crs="EPSG:4326")
    str_id.add_node("a", x=1.0, y=2.0)
    str_id.add_node(2, x=1.0, y=2.0)
    str_id.add_edge("a", 2, key=0, length=5.0)

    str_key = nx.MultiDiGraph(crs="EPSG:4326")
    str_key.add_node(1, x=1.0, y=2.0)
    str_key.add_node(2, x=1.0, y=2.0)
    str_key.add_edge(1, 2, key="k", length=5.0)

    for bad in (nx.MultiDiGraph(crs="EPSG:4326"), no_crs, no_x, no_len, str_id, str_key):
        with pytest.raises(rs.SnapshotSerializationError):
            _save(bad)
    assert not unused.exists() and not unused_meta.exists()  # nothing written on rejection


def test_writer_output_reloads_for_boundary_graph(tmp_path: Path) -> None:
    """Round-trip: a no-parallel MultiDiGraph (single edge key 7) saves and then immediately loads
    back through the official loader."""
    minimal = nx.MultiDiGraph(crs="EPSG:4326")
    minimal.add_node(1, x=126.9, y=37.4)
    minimal.add_node(2, x=126.91, y=37.41)
    minimal.add_edge(1, 2, key=7, length=10.0, osmid=101)
    gp, mp = _write_graph(tmp_path, minimal)
    loaded = rs.load_sillim_snapshot(snapshot_path=gp, metadata_path=mp).graph
    assert list(loaded.edges(keys=True)) == [(1, 2, 7)]


@pytest.mark.parametrize("bad", ["NaN", "Infinity"])
def test_non_finite_length_is_rejected(tmp_path: Path, bad: str) -> None:
    graph, meta = _copy_sample(tmp_path)
    graph.write_bytes(graph.read_bytes().replace(b"105.0", bad.encode(), 1))
    _reseal(graph, meta)  # checksum passes; the non-finite value must be what fails
    with pytest.raises(rs.SnapshotSchemaMismatchError, match="not finite"):
        rs.load_sillim_snapshot(snapshot_path=graph, metadata_path=meta)


@pytest.mark.parametrize("bad", ["NaN", "Infinity"])
def test_non_finite_coordinate_is_rejected(tmp_path: Path, bad: str) -> None:
    graph, meta = _copy_sample(tmp_path)
    graph.write_bytes(graph.read_bytes().replace(b"126.929", bad.encode(), 1))
    _reseal(graph, meta)
    with pytest.raises(rs.SnapshotSchemaMismatchError, match="not finite"):
        rs.load_sillim_snapshot(snapshot_path=graph, metadata_path=meta)


# ── committed sample checksum + provenance regression ────────────────────────────────────────


def test_committed_sample_sha256_matches_graphml() -> None:
    recorded = json.loads(rs.SAMPLE_SNAPSHOT_METADATA_PATH.read_text(encoding="utf-8"))[
        "graph_sha256"
    ]
    actual = hashlib.sha256(rs.SAMPLE_SNAPSHOT_PATH.read_bytes()).hexdigest()
    assert recorded == actual


def test_committed_sample_metadata_has_all_required_fields() -> None:
    payload = json.loads(rs.SAMPLE_SNAPSHOT_METADATA_PATH.read_text(encoding="utf-8"))
    for field in rs._REQUIRED_METADATA:
        assert field in payload, f"metadata missing {field!r}"
    assert payload["source_kind"] == rs.SOURCE_KIND_SYNTHETIC
    assert payload["graph_kind"] == rs.GRAPH_KIND_MULTIDIGRAPH
    assert payload["schema_version"] == rs.SNAPSHOT_SCHEMA_VERSION == 2


def test_committed_sample_generated_at_is_not_in_the_future() -> None:
    """Compare against the real current UTC, not a hard-coded future boundary string."""
    payload = json.loads(rs.SAMPLE_SNAPSHOT_METADATA_PATH.read_text(encoding="utf-8"))
    generated_at = datetime.fromisoformat(payload["generated_at"])
    assert generated_at <= datetime.now(UTC)


# ── non-scalar (list) osmid serialization (Codex MAJOR #2) ───────────────────────────────────


def _mdg_with_osmid(osmids: list[object]) -> nx.MultiDiGraph:
    """A minimal MultiDiGraph whose parallel edges 1->2 carry the given osmid values in order."""
    graph = nx.MultiDiGraph(crs="EPSG:4326")
    graph.add_node(1, x=126.9, y=37.4)
    graph.add_node(2, x=126.91, y=37.41)
    for key, osmid in enumerate(osmids):
        graph.add_edge(1, 2, key=key, length=10.0 + key, osmid=osmid)
    return graph


def test_scalar_osmid_round_trips(tmp_path: Path) -> None:
    gpath, mpath = _write_graph(tmp_path, _mdg_with_osmid([101]))
    loaded = rs.load_sillim_snapshot(snapshot_path=gpath, metadata_path=mpath)
    osmid = loaded.graph[1][2][0]["osmid"]
    assert osmid == 101 and isinstance(osmid, int)


def test_list_osmid_round_trips(tmp_path: Path) -> None:
    gpath, mpath = _write_graph(tmp_path, _mdg_with_osmid([[101, 202]]))
    loaded = rs.load_sillim_snapshot(snapshot_path=gpath, metadata_path=mpath)
    osmid = loaded.graph[1][2][0]["osmid"]
    assert osmid == [101, 202] and isinstance(osmid, list)


def test_parallel_edges_preserve_per_key_scalar_and_list_osmid(tmp_path: Path) -> None:
    gpath, mpath = _write_graph(tmp_path, _mdg_with_osmid([101, [303, 404]]))
    loaded = rs.load_sillim_snapshot(snapshot_path=gpath, metadata_path=mpath)
    edges = loaded.graph.get_edge_data(1, 2)
    assert edges[0]["osmid"] == 101 and isinstance(edges[0]["osmid"], int)
    assert edges[1]["osmid"] == [303, 404] and isinstance(edges[1]["osmid"], list)
    # length + crs + x/y also survive the JSON-normalization pass
    assert edges[0]["length"] == 10.0 and edges[1]["length"] == 11.0
    assert loaded.graph.graph["crs"] == "EPSG:4326"
    assert loaded.graph.nodes[1]["x"] == 126.9


def test_malformed_encoded_payload_is_normalized_schema_error(tmp_path: Path) -> None:
    """A corrupt JSON payload in a manifest-listed key is a schema error, never a raw json
    exception — and decoding never runs eval/arbitrary code."""
    gpath, mpath = _write_graph(tmp_path, _mdg_with_osmid([[101, 202]]))
    raw = gpath.read_bytes()
    broken = raw.replace(b"[101, 202]", b"[101,", 1)  # JSON-encoded osmid value, no sentinel
    assert broken != raw  # the encoded value really was present to corrupt
    gpath.write_bytes(broken)
    _reseal(gpath, mpath)  # checksum passes so the decode failure is what surfaces
    with pytest.raises(rs.SnapshotSchemaMismatchError, match="malformed JSON-encoded") as excinfo:
        rs.load_sillim_snapshot(snapshot_path=gpath, metadata_path=mpath)
    assert excinfo.value.__cause__ is not None  # the json error is chained, not swallowed


def test_save_snapshot_from_osm_saves_list_osmid_without_osmnx_on_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The dev-only OSM boundary stores a graph with list osmid (and drops shapely geometry); the
    core-only loader then reads it back with no OSMnx import."""
    geom = object()  # non-serializable shapely stand-in; must be dropped on the copy, not crash
    fake_graph = nx.MultiDiGraph(crs="EPSG:4326")
    fake_graph.add_node(1, x=126.9, y=37.4)
    fake_graph.add_node(2, x=126.91, y=37.41)
    fake_graph.add_edge(
        1,
        2,
        key=0,
        length=10.0,
        osmid=[101, 202],
        highway=["residential", "service"],
        geometry=geom,
    )
    fake_ox = types.SimpleNamespace(
        graph_from_place=lambda *a, **k: fake_graph, __version__="test-osmnx"
    )
    monkeypatch.setitem(sys.modules, "osmnx", fake_ox)

    gpath = tmp_path / "op.graphml"
    mpath = tmp_path / "op.metadata.json"
    identity = rs.save_snapshot_from_osm(
        place="x", network_type="walk", simplify=True, snapshot_path=gpath, metadata_path=mpath
    )
    assert identity.source_kind == rs.SOURCE_KIND_OSM

    # The graph OSMnx returned must be untouched: geometry and everything else stay put.
    original_edge = fake_graph[1][2][0]
    assert "geometry" in original_edge and original_edge["geometry"] is geom
    assert original_edge["osmid"] == [101, 202]
    assert original_edge["highway"] == ["residential", "service"]

    # The stored snapshot drops geometry but keeps the routing-essential attributes.
    loaded = rs.load_sillim_snapshot(snapshot_path=gpath, metadata_path=mpath)
    edge = loaded.graph[1][2][0]
    assert edge["osmid"] == [101, 202]
    assert edge["highway"] == ["residential", "service"]
    assert edge["length"] == 10.0
    assert "geometry" not in edge  # dropped by the OSM boundary (on the copy)
    assert list(loaded.graph.edges(keys=True)) == [(1, 2, 0)]  # edge key preserved
    assert loaded.graph.graph["crs"] == "EPSG:4326"
    assert loaded.graph.nodes[1]["x"] == 126.9 and loaded.graph.nodes[1]["y"] == 37.4


# ── manifest encoding contract: magic-prefix strings never mis-decoded (Codex MAJOR #1) ───────


@pytest.mark.parametrize("magic", ["@@json@@hello", "@@json@@123", "@@json@@[1,2]"])
def test_magic_prefix_string_survives_round_trip_unchanged(tmp_path: Path, magic: str) -> None:
    """A genuine user string that merely *looks* JSON-encoded must round-trip byte-for-byte as a
    string — never decoded to int/list, never a schema error. Its key has only scalar values, so it
    is not in the manifest and the loader leaves it alone."""
    graph = nx.MultiDiGraph(crs="EPSG:4326")
    graph.add_node(1, x=126.9, y=37.4)
    graph.add_node(2, x=126.91, y=37.41)
    graph.add_edge(1, 2, key=0, length=5.0, note=magic)
    gpath, mpath = _write_graph(tmp_path, graph)
    manifest = json.loads(mpath.read_text(encoding="utf-8"))["encoded_attrs"]
    assert "note" not in manifest["edge"]  # scalar-only key: not encoded
    loaded = rs.load_sillim_snapshot(snapshot_path=gpath, metadata_path=mpath)
    value = loaded.graph[1][2][0]["note"]
    assert value == magic and isinstance(value, str)


def test_magic_prefix_string_and_list_coexist_in_one_key(tmp_path: Path) -> None:
    """When a key holds both a magic-prefix string and a real list, the key IS encoded, yet each
    value round-trips to its original type and value (string stays a string)."""
    graph = nx.MultiDiGraph(crs="EPSG:4326")
    graph.add_node(1, x=126.9, y=37.4)
    graph.add_node(2, x=126.91, y=37.41)
    graph.add_edge(1, 2, key=0, length=5.0, tag="@@json@@hello")
    graph.add_edge(1, 2, key=1, length=6.0, tag=["a", "b"])
    gpath, mpath = _write_graph(tmp_path, graph)
    assert "tag" in json.loads(mpath.read_text(encoding="utf-8"))["encoded_attrs"]["edge"]
    edges = rs.load_sillim_snapshot(snapshot_path=gpath, metadata_path=mpath).graph.get_edge_data(
        1, 2
    )
    assert edges[0]["tag"] == "@@json@@hello" and isinstance(edges[0]["tag"], str)
    assert edges[1]["tag"] == ["a", "b"] and isinstance(edges[1]["tag"], list)


# ── input graph is never mutated by the write boundary (Codex MAJOR #2) ────────────────────────


def test_save_snapshot_does_not_mutate_input_graph(tmp_path: Path) -> None:
    graph = nx.MultiDiGraph(crs="EPSG:4326")
    graph.add_node(1, x=126.9, y=37.4, tags=["a", "b"])
    graph.add_node(2, x=126.91, y=37.41)
    graph.add_edge(1, 2, key=0, length=5.0, osmid=[101, 202])
    before_node = dict(graph.nodes[1])
    before_edge = dict(graph[1][2][0])
    _write_graph(tmp_path, graph)
    # values (including the list objects) are unchanged and still their original Python types
    assert graph.nodes[1] == before_node
    assert graph.nodes[1]["tags"] == ["a", "b"] and isinstance(graph.nodes[1]["tags"], list)
    assert graph[1][2][0] == before_edge
    assert graph[1][2][0]["osmid"] == [101, 202] and isinstance(graph[1][2][0]["osmid"], list)


def test_save_snapshot_from_osm_does_not_mutate_input_graph(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    geom = object()
    fake_graph = nx.MultiDiGraph(crs="EPSG:4326")
    fake_graph.add_node(1, x=126.9, y=37.4)
    fake_graph.add_node(2, x=126.91, y=37.41)
    fake_graph.add_edge(1, 2, key=0, length=5.0, osmid=[101, 202], geometry=geom)
    monkeypatch.setitem(
        sys.modules,
        "osmnx",
        types.SimpleNamespace(graph_from_place=lambda *a, **k: fake_graph, __version__="t"),
    )
    rs.save_snapshot_from_osm(
        place="x", snapshot_path=tmp_path / "o.graphml", metadata_path=tmp_path / "o.json"
    )
    edge = fake_graph[1][2][0]
    assert edge["geometry"] is geom  # geometry NOT stripped from the caller's graph
    assert edge["osmid"] == [101, 202] and isinstance(edge["osmid"], list)


# ── unsupported attribute types: one typed error, no raw NetworkXError (Codex MINOR) ───────────


def _mdg_with_edge_attr(value: object) -> nx.MultiDiGraph:
    graph = nx.MultiDiGraph(crs="EPSG:4326")
    graph.add_node(1, x=126.9, y=37.4)
    graph.add_node(2, x=126.91, y=37.41)
    graph.add_edge(1, 2, key=0, length=5.0, bad=value)
    return graph


@pytest.mark.parametrize(
    "value",
    [
        b"raw-bytes",
        {1, 2, 3},
        {"a": 1},
        (1, 2),
        object(),
        [1, {1, 2}],  # list with an unsupported nested element
        [1, (2, 3)],  # list with a nested tuple
    ],
    ids=["bytes", "set", "dict", "tuple", "object", "nested-set", "nested-tuple"],
)
def test_unsupported_attribute_type_raises_serialization_error(
    tmp_path: Path, value: object
) -> None:
    with pytest.raises(rs.SnapshotSerializationError):
        _write_graph(tmp_path, _mdg_with_edge_attr(value))


def test_serialization_error_is_a_route_snapshot_error(tmp_path: Path) -> None:
    assert issubclass(rs.SnapshotSerializationError, rs.RouteSnapshotError)
    with pytest.raises(rs.RouteSnapshotError):
        _write_graph(tmp_path, _mdg_with_edge_attr({"a": 1}))


def test_no_raw_networkx_error_escapes_save_boundary(tmp_path: Path) -> None:
    """An arbitrary object (e.g. a geometry) passed straight to save_snapshot is a typed
    SnapshotSerializationError, never a raw nx.NetworkXError."""
    with pytest.raises(rs.SnapshotSerializationError):
        _write_graph(tmp_path, _mdg_with_edge_attr(object()))
    # and specifically not the raw NetworkX type
    try:
        _write_graph(tmp_path, _mdg_with_edge_attr(object()))
    except nx.NetworkXError:  # pragma: no cover - would fail the test
        raise AssertionError("raw NetworkXError leaked out of save_snapshot") from None
    except rs.SnapshotSerializationError:
        pass


def test_tuple_is_rejected_not_coerced_to_list(tmp_path: Path) -> None:
    """A tuple must NOT be silently turned into a list; it is rejected as unsupported."""
    with pytest.raises(rs.SnapshotSerializationError, match="tuple"):
        _write_graph(tmp_path, _mdg_with_edge_attr((1, 2)))


# ── manifest validation ───────────────────────────────────────────────────────────────────────


def test_missing_manifest_is_rejected(tmp_path: Path) -> None:
    graph, meta = _copy_sample(tmp_path)
    payload = json.loads(meta.read_text(encoding="utf-8"))
    del payload["encoded_attrs"]
    meta.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(rs.SnapshotSchemaMismatchError, match="missing field 'encoded_attrs'"):
        rs.load_sillim_snapshot(snapshot_path=graph, metadata_path=meta)


def test_manifest_wrong_type_is_rejected(tmp_path: Path) -> None:
    graph, meta = _copy_sample(tmp_path)
    _reseal(graph, meta, encoded_attrs=["edge"])  # list, not dict
    with pytest.raises(rs.SnapshotSchemaMismatchError, match="encoded_attrs"):
        rs.load_sillim_snapshot(snapshot_path=graph, metadata_path=meta)


def test_manifest_unknown_or_extra_scope_is_rejected(tmp_path: Path) -> None:
    graph, meta = _copy_sample(tmp_path)
    _reseal(graph, meta, encoded_attrs={"graph": [], "node": [], "edge": [], "bogus": ["x"]})
    with pytest.raises(rs.SnapshotSchemaMismatchError, match="exactly the scopes"):
        rs.load_sillim_snapshot(snapshot_path=graph, metadata_path=meta)


@pytest.mark.parametrize("missing", ["graph", "node", "edge"])
def test_manifest_missing_scope_is_rejected(tmp_path: Path, missing: str) -> None:
    graph, meta = _copy_sample(tmp_path)
    manifest = {"graph": [], "node": [], "edge": []}
    del manifest[missing]
    _reseal(graph, meta, encoded_attrs=manifest)
    with pytest.raises(rs.SnapshotSchemaMismatchError, match="exactly the scopes"):
        rs.load_sillim_snapshot(snapshot_path=graph, metadata_path=meta)


def test_manifest_non_string_keys_are_rejected(tmp_path: Path) -> None:
    graph, meta = _copy_sample(tmp_path)
    _reseal(graph, meta, encoded_attrs={"graph": [], "node": [], "edge": [123]})
    with pytest.raises(rs.SnapshotSchemaMismatchError, match="list of string keys"):
        rs.load_sillim_snapshot(snapshot_path=graph, metadata_path=meta)


def test_manifest_duplicate_keys_are_rejected(tmp_path: Path) -> None:
    graph, meta = _copy_sample(tmp_path)
    _reseal(graph, meta, encoded_attrs={"graph": [], "node": [], "edge": ["osmid", "osmid"]})
    with pytest.raises(rs.SnapshotSchemaMismatchError, match="duplicate keys"):
        rs.load_sillim_snapshot(snapshot_path=graph, metadata_path=meta)


def test_manifest_unsorted_keys_are_rejected(tmp_path: Path) -> None:
    graph, meta = _copy_sample(tmp_path)
    _reseal(graph, meta, encoded_attrs={"graph": [], "node": [], "edge": ["b", "a"]})
    with pytest.raises(rs.SnapshotSchemaMismatchError, match="sorted canonical order"):
        rs.load_sillim_snapshot(snapshot_path=graph, metadata_path=meta)


# ── heterogeneous native-scalar types preserved losslessly (Codex 4th-audit MAJOR #1) ─────────


def _graph_with_edge_vals(values: list[object]) -> nx.MultiDiGraph:
    graph = nx.MultiDiGraph(crs="EPSG:4326")
    graph.add_node(1, x=126.9, y=37.4)
    graph.add_node(2, x=126.91, y=37.41)
    for key, value in enumerate(values):
        graph.add_edge(1, 2, key=key, length=10.0 + key, val=value)
    return graph


@pytest.mark.parametrize(
    "values,types",
    [
        ([7, "7"], [int, str]),
        ([True, 1], [bool, int]),
        ([1, 1.5], [int, float]),
        ([1.5, "1.5"], [float, str]),
        (["x", True], [str, bool]),
        (["x", None], [str, type(None)]),
        ([101, [1, 2]], [int, list]),
        (["@@json@@x", [1, 2]], [str, list]),
    ],
    ids=[
        "int-str",
        "bool-int",
        "int-float",
        "float-str",
        "str-bool",
        "str-none",
        "scalar-list",
        "magic-list",
    ],
)
def test_heterogeneous_edge_values_preserve_value_and_type(
    tmp_path: Path, values: list[object], types: list[type]
) -> None:
    """A key mixing native scalar types must round-trip each value's exact Python type — GraphML's
    lossy type inference (which would collapse int/str or make int/float unloadable) is bypassed."""
    gpath, mpath = _write_graph(tmp_path, _graph_with_edge_vals(values))
    graph = rs.load_sillim_snapshot(snapshot_path=gpath, metadata_path=mpath).graph
    got = [graph[1][2][k]["val"] for k in range(len(values))]
    assert got == values
    assert [type(x) for x in got] == types  # the load-bearing check: no silent coercion
    assert "val" in json.loads(mpath.read_text(encoding="utf-8"))["encoded_attrs"]["edge"]


def test_heterogeneous_node_scope_preserves_types(tmp_path: Path) -> None:
    graph = nx.MultiDiGraph(crs="EPSG:4326")
    graph.add_node(1, x=1.0, y=2.0, ref=7)
    graph.add_node(2, x=1.0, y=2.0, ref="7")
    graph.add_edge(1, 2, key=0, length=5.0)
    gpath, mpath = _write_graph(tmp_path, graph)
    loaded = rs.load_sillim_snapshot(snapshot_path=gpath, metadata_path=mpath).graph
    assert loaded.nodes[1]["ref"] == 7 and isinstance(loaded.nodes[1]["ref"], int)
    assert loaded.nodes[2]["ref"] == "7" and isinstance(loaded.nodes[2]["ref"], str)
    assert json.loads(mpath.read_text(encoding="utf-8"))["encoded_attrs"]["node"] == ["ref"]


def test_graph_scope_list_attr_round_trips(tmp_path: Path) -> None:
    graph = rs.build_sample_graph()
    graph.graph["bbox"] = [1, 2, 3, 4]
    gpath, mpath = _write_graph(tmp_path, graph)
    loaded = rs.load_sillim_snapshot(snapshot_path=gpath, metadata_path=mpath).graph
    assert loaded.graph["bbox"] == [1, 2, 3, 4]
    assert loaded.graph["crs"] == "EPSG:4326"
    assert json.loads(mpath.read_text(encoding="utf-8"))["encoded_attrs"]["graph"] == ["bbox"]


def test_parallel_edges_mixed_types_preserved(tmp_path: Path) -> None:
    gpath, mpath = _write_graph(tmp_path, _graph_with_edge_vals([1, "two", 3.0, [4], True]))
    graph = rs.load_sillim_snapshot(snapshot_path=gpath, metadata_path=mpath).graph
    got = [graph[1][2][k]["val"] for k in range(5)]
    assert got == [1, "two", 3.0, [4], True]
    assert [type(x) for x in got] == [int, str, float, list, bool]


def test_homogeneous_native_key_stays_native_and_unencoded(tmp_path: Path) -> None:
    """A homogeneous native-scalar key is NOT encoded and its exact type round-trips."""
    gpath, mpath = _write_graph(tmp_path, _graph_with_edge_vals([1, 2, 3]))
    assert json.loads(mpath.read_text(encoding="utf-8"))["encoded_attrs"]["edge"] == []
    graph = rs.load_sillim_snapshot(snapshot_path=gpath, metadata_path=mpath).graph
    got = [graph[1][2][k]["val"] for k in range(3)]
    assert got == [1, 2, 3] and all(isinstance(x, int) for x in got)


def test_absent_attribute_is_not_confused_with_none(tmp_path: Path) -> None:
    """An edge missing a key stays missing; it is not materialized as None."""
    graph = nx.MultiDiGraph(crs="EPSG:4326")
    graph.add_node(1, x=1.0, y=2.0)
    graph.add_node(2, x=1.0, y=2.0)
    graph.add_edge(1, 2, key=0, length=5.0, opt=7)  # only this edge has opt
    graph.add_edge(1, 2, key=1, length=6.0)  # opt absent here
    gpath, mpath = _write_graph(tmp_path, graph)
    loaded = rs.load_sillim_snapshot(snapshot_path=gpath, metadata_path=mpath).graph
    assert loaded[1][2][0]["opt"] == 7
    assert "opt" not in loaded[1][2][1]  # absent, not None
    assert json.loads(mpath.read_text(encoding="utf-8"))["encoded_attrs"]["edge"] == []


# ── cross-scope native key-id collision (issue #224, Yopkigom review) ─────────────────────────
# named_key_ids=True writes each <key> id as the attribute name, and the GraphML reader indexes
# <key> by id ALONE (ignoring for="node"/"edge"/"graph"). A name written as a native key of two
# different types in two scopes would collide on load — silently reinterpreting one scope's values
# or failing to parse. _normalize_and_encode force-encodes any such name in every scope it appears
# in. These lock that in end-to-end (save -> load) and confirm the safe cases stay native.


def _cross_scope_ref_graph(node_ref: object, edge_ref: object) -> nx.MultiDiGraph:
    """A graph whose node and edge both carry a ``ref`` attribute (same name, caller-chosen types)."""
    graph = nx.MultiDiGraph(crs="EPSG:4326")
    graph.add_node(1, x=1.0, y=2.0, ref=node_ref)
    graph.add_node(2, x=1.0, y=2.0)
    graph.add_edge(1, 2, key=0, length=5.0, ref=edge_ref)
    return graph


@pytest.mark.parametrize(
    "node_ref,edge_ref,node_type,edge_type",
    [
        (7, "12", int, str),  # node int / edge numeric-looking str
        ("abc", 5, str, int),  # node str / edge int
        (7, "road", int, str),  # node int / edge non-numeric str (previously unparseable)
    ],
    ids=["node-int_edge-numstr", "node-str_edge-int", "node-int_edge-nonnumstr"],
)
def test_cross_scope_same_name_different_native_types_round_trip(
    tmp_path: Path, node_ref: object, edge_ref: object, node_type: type, edge_type: type
) -> None:
    """A name that is a different native type in node vs edge scope must round-trip each value's
    exact type — not collide on a shared ``<key id>`` (issue #224). Before the fix this silently
    changed the value's type or raised 'could not be parsed'."""
    gpath, mpath = _write_graph(tmp_path, _cross_scope_ref_graph(node_ref, edge_ref))
    manifest = json.loads(mpath.read_text(encoding="utf-8"))["encoded_attrs"]
    assert manifest["node"] == ["ref"] and manifest["edge"] == ["ref"]  # encoded in BOTH scopes
    loaded = rs.load_sillim_snapshot(snapshot_path=gpath, metadata_path=mpath).graph
    assert loaded.nodes[1]["ref"] == node_ref and type(loaded.nodes[1]["ref"]) is node_type
    assert loaded[1][2][0]["ref"] == edge_ref and type(loaded[1][2][0]["ref"]) is edge_type


def test_cross_scope_graph_node_edge_same_name_mixed_types(tmp_path: Path) -> None:
    """The same name in all three scopes with three different native types round-trips and is
    encoded in every scope."""
    graph = nx.MultiDiGraph(crs="EPSG:4326")
    graph.graph["ref"] = 1  # graph scope: int
    graph.add_node(1, x=1.0, y=2.0, ref="a")  # node scope: str
    graph.add_node(2, x=1.0, y=2.0)
    graph.add_edge(1, 2, key=0, length=5.0, ref=2.5)  # edge scope: float
    gpath, mpath = _write_graph(tmp_path, graph)
    manifest = json.loads(mpath.read_text(encoding="utf-8"))["encoded_attrs"]
    assert manifest["graph"] == ["ref"]
    assert manifest["node"] == ["ref"]
    assert manifest["edge"] == ["ref"]
    loaded = rs.load_sillim_snapshot(snapshot_path=gpath, metadata_path=mpath).graph
    assert loaded.graph["ref"] == 1 and type(loaded.graph["ref"]) is int
    assert loaded.nodes[1]["ref"] == "a" and type(loaded.nodes[1]["ref"]) is str
    assert loaded[1][2][0]["ref"] == 2.5 and type(loaded[1][2][0]["ref"]) is float


def test_same_name_same_native_type_across_scopes_stays_native(tmp_path: Path) -> None:
    """When a shared name is the SAME single native type in every scope, no collision is possible,
    so it is NOT encoded and its on-disk (native) serialization is unchanged by the fix."""
    graph = nx.MultiDiGraph(crs="EPSG:4326")
    graph.add_node(1, x=1.0, y=2.0, ref=7)
    graph.add_node(2, x=1.0, y=2.0, ref=8)
    graph.add_edge(1, 2, key=0, length=5.0, ref=9)
    gpath, mpath = _write_graph(tmp_path, graph)
    manifest = json.loads(mpath.read_text(encoding="utf-8"))["encoded_attrs"]
    assert manifest["node"] == [] and manifest["edge"] == []  # stays native, unencoded
    assert rs._RESERVED_ATTR_PREFIX not in gpath.read_text(encoding="utf-8")
    loaded = rs.load_sillim_snapshot(snapshot_path=gpath, metadata_path=mpath).graph
    assert loaded.nodes[1]["ref"] == 7 and type(loaded.nodes[1]["ref"]) is int
    assert loaded[1][2][0]["ref"] == 9 and type(loaded[1][2][0]["ref"]) is int


def test_cross_scope_conflict_does_not_mutate_input_graph(tmp_path: Path) -> None:
    """Force-encoding across scopes still happens on the writer's private deepcopy: the caller's
    graph and its nested list references are untouched."""
    tags: list[object] = [1, 2]
    graph = nx.MultiDiGraph(crs="EPSG:4326")
    graph.graph["ref"] = 1
    graph.add_node(1, x=1.0, y=2.0, ref="a", tags=tags)
    graph.add_node(2, x=1.0, y=2.0)
    graph.add_edge(1, 2, key=0, length=5.0, ref=2.5)
    _write_graph(tmp_path, graph)
    assert graph.graph["ref"] == 1 and type(graph.graph["ref"]) is int
    assert graph.nodes[1]["ref"] == "a" and type(graph.nodes[1]["ref"]) is str
    assert graph.nodes[1]["tags"] is tags and graph.nodes[1]["tags"] == [1, 2]  # nested ref intact
    assert graph[1][2][0]["ref"] == 2.5 and type(graph[1][2][0]["ref"]) is float


def test_cross_scope_conflict_writer_output_immediately_loadable(tmp_path: Path) -> None:
    """The writer's own contract holds for a cross-scope conflict: the pair it emits loads with no
    fixup and no reserved marker leaks into the returned graph."""
    gpath, mpath = _write_graph(tmp_path, _cross_scope_ref_graph(7, "road"))
    loaded = rs.load_sillim_snapshot(snapshot_path=gpath, metadata_path=mpath).graph
    for _n, data in loaded.nodes(data=True):
        assert not any(k.startswith(rs._RESERVED_ATTR_PREFIX) for k in data)
    for _u, _v, data in loaded.edges(data=True):
        assert not any(k.startswith(rs._RESERVED_ATTR_PREFIX) for k in data)


def test_cross_scope_conflict_failure_path_leaves_existing_pair_and_no_temp(tmp_path: Path) -> None:
    """If a later save (a cross-scope graph carrying an unserializable value) fails, the earlier
    good pair and the tmp dir are untouched — the fix runs before any file is written."""
    good, meta = tmp_path / "g.graphml", tmp_path / "g.metadata.json"
    _write_graph(tmp_path, _cross_scope_ref_graph(7, "12"))  # a good cross-scope pair first
    before_g, before_m = good.read_bytes(), meta.read_bytes()
    bad = _cross_scope_ref_graph(7, "12")
    bad[1][2][0]["geometry"] = object()  # unsupported -> serialization error before any write
    with pytest.raises(rs.SnapshotSerializationError):
        _write_graph(tmp_path, bad)
    assert good.read_bytes() == before_g and meta.read_bytes() == before_m
    assert not any(p.name.endswith(".tmp") for p in tmp_path.iterdir())


# ── manifest ↔ GraphML cross-check + reserved marker hygiene (Codex 4th-audit MAJOR #2) ───────


def test_reserved_prefix_user_key_rejected_on_write(tmp_path: Path) -> None:
    graph = nx.MultiDiGraph(crs="EPSG:4326")
    graph.add_node(1, x=1.0, y=2.0)
    graph.add_node(2, x=1.0, y=2.0)
    graph.add_edge(1, 2, key=0, length=5.0, **{f"{rs._RESERVED_ATTR_PREFIX}osmid": "x"})
    with pytest.raises(rs.SnapshotSerializationError, match="reserved prefix"):
        _write_graph(tmp_path, graph)


def test_reserved_marker_absent_from_loaded_graph(tmp_path: Path) -> None:
    """The GraphML carries reserved-prefixed keys for encoded values, but the loaded graph must
    only expose the original names."""
    gpath, mpath = _write_graph(tmp_path, _graph_with_edge_vals([1, "x"]))
    assert rs._RESERVED_ATTR_PREFIX in gpath.read_text(encoding="utf-8")  # present on disk
    loaded = rs.load_sillim_snapshot(snapshot_path=gpath, metadata_path=mpath).graph
    for _u, _v, data in loaded.edges(data=True):
        assert not any(k.startswith(rs._RESERVED_ATTR_PREFIX) for k in data)
    assert loaded[1][2][0]["val"] == 1 and loaded[1][2][1]["val"] == "x"


def test_manifest_dropping_real_encoded_key_is_rejected(tmp_path: Path) -> None:
    """MAJOR #2: deleting the real encoded key from the metadata manifest must be detected via the
    GraphML's own reserved keys, not silently returned as a string."""
    gpath, mpath = _write_graph(tmp_path, _graph_with_edge_vals([1, "x"]))
    _reseal(gpath, mpath, encoded_attrs={"graph": [], "node": [], "edge": []})
    with pytest.raises(rs.SnapshotSchemaMismatchError, match="do not match metadata"):
        rs.load_sillim_snapshot(snapshot_path=gpath, metadata_path=mpath)


def test_manifest_ghost_key_absent_from_graphml_is_rejected(tmp_path: Path) -> None:
    graph, meta = _copy_sample(tmp_path)  # sample has no encoded keys
    _reseal(graph, meta, encoded_attrs={"graph": [], "node": [], "edge": ["osmid"]})
    with pytest.raises(rs.SnapshotSchemaMismatchError, match="do not match metadata"):
        rs.load_sillim_snapshot(snapshot_path=graph, metadata_path=meta)


def test_same_key_name_encoded_independently_per_scope(tmp_path: Path) -> None:
    graph = nx.MultiDiGraph(crs="EPSG:4326")
    graph.add_node(1, x=1.0, y=2.0, tag=[1])  # node tag is a list -> node scope encodes it
    graph.add_node(2, x=1.0, y=2.0, tag=[2])
    graph.add_edge(1, 2, key=0, length=5.0, tag="plain")  # edge tag homogeneous str -> not encoded
    gpath, mpath = _write_graph(tmp_path, graph)
    manifest = json.loads(mpath.read_text(encoding="utf-8"))["encoded_attrs"]
    assert manifest["node"] == ["tag"] and manifest["edge"] == []
    loaded = rs.load_sillim_snapshot(snapshot_path=gpath, metadata_path=mpath).graph
    assert loaded.nodes[1]["tag"] == [1] and isinstance(loaded.nodes[1]["tag"], list)
    assert loaded[1][2][0]["tag"] == "plain" and isinstance(loaded[1][2][0]["tag"], str)


# ── serialization exception normalization (Codex 4th-audit MINOR) ─────────────────────────────


def test_cyclic_list_is_serialization_error_no_fake_cause(tmp_path: Path) -> None:
    cyclic: list[object] = [1]
    cyclic.append(cyclic)
    with pytest.raises(rs.SnapshotSerializationError) as excinfo:
        _write_graph(tmp_path, _graph_with_edge_vals([cyclic]))
    assert excinfo.value.__cause__ is None  # a direct preflight rejection, not a wrapped error


def test_nested_cyclic_list_is_serialization_error(tmp_path: Path) -> None:
    inner: list[object] = [1]
    outer: list[object] = [inner]
    inner.append(outer)
    with pytest.raises(rs.SnapshotSerializationError):
        _write_graph(tmp_path, _graph_with_edge_vals([inner]))


def test_nesting_depth_at_limit_ok_over_limit_rejected(tmp_path: Path) -> None:
    at_limit: object = 1
    for _ in range(rs._MAX_ATTR_NESTING_DEPTH):
        at_limit = [at_limit]
    gpath, mpath = _write_graph(tmp_path, _graph_with_edge_vals([at_limit]))
    assert rs.load_sillim_snapshot(snapshot_path=gpath, metadata_path=mpath).graph is not None
    over_limit: object = 1
    for _ in range(rs._MAX_ATTR_NESTING_DEPTH + 1):
        over_limit = [over_limit]
    with pytest.raises(rs.SnapshotSerializationError):
        _write_graph(tmp_path, _graph_with_edge_vals([over_limit]))


@pytest.mark.parametrize(
    "exc",
    [nx.NetworkXError("boom"), ValueError("boom"), TypeError("boom")],
    ids=["NetworkXError", "ValueError", "TypeError"],
)
def test_writer_library_error_is_normalized_with_cause(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, exc: Exception
) -> None:
    def boom(*_a: object, **_k: object) -> None:
        raise exc

    monkeypatch.setattr(rs.nx, "write_graphml", boom)
    with pytest.raises(rs.SnapshotSerializationError) as excinfo:
        _write_graph(tmp_path, rs.build_sample_graph())
    assert excinfo.value.__cause__ is exc  # real cause chained, not swallowed


def test_numpy_scalar_normalized_and_array_rejected(tmp_path: Path) -> None:
    np = pytest.importorskip("numpy")
    gpath, mpath = _write_graph(tmp_path, _graph_with_edge_vals([np.int64(5), np.float64(1.5)]))
    graph = rs.load_sillim_snapshot(snapshot_path=gpath, metadata_path=mpath).graph
    assert graph[1][2][0]["val"] == 5 and isinstance(graph[1][2][0]["val"], int)
    assert graph[1][2][1]["val"] == 1.5 and isinstance(graph[1][2][1]["val"], float)
    with pytest.raises(rs.SnapshotSerializationError):
        _write_graph(tmp_path, _graph_with_edge_vals([np.array([1, 2])]))


# ── finite-value + metadata preflight; writer never emits an unloadable pair (MINOR) ──────────


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_node_x_rejected_on_write(tmp_path: Path, bad: float) -> None:
    graph = rs.build_sample_graph()
    graph.nodes[1000001]["x"] = bad
    with pytest.raises(rs.SnapshotSerializationError, match="not finite"):
        _write_graph(tmp_path, graph)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_edge_length_rejected_on_write(tmp_path: Path, bad: float) -> None:
    graph = rs.build_sample_graph()
    first = next(iter(graph.edges(keys=True)))
    graph.edges[first]["length"] = bad
    with pytest.raises(rs.SnapshotSerializationError, match="not finite"):
        _write_graph(tmp_path, graph)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_general_attr_rejected_on_write(tmp_path: Path, bad: float) -> None:
    with pytest.raises(rs.SnapshotSerializationError, match="non-finite"):
        _write_graph(tmp_path, _graph_with_edge_vals([bad]))


def test_non_finite_inside_list_rejected_on_write(tmp_path: Path) -> None:
    with pytest.raises(rs.SnapshotSerializationError, match="non-finite"):
        _write_graph(tmp_path, _graph_with_edge_vals([[1.0, float("inf")]]))


def test_non_finite_in_nested_list_rejected_on_write(tmp_path: Path) -> None:
    with pytest.raises(rs.SnapshotSerializationError, match="non-finite"):
        _write_graph(tmp_path, _graph_with_edge_vals([[[float("nan")]]]))


def test_non_finite_numpy_float_rejected_on_write(tmp_path: Path) -> None:
    np = pytest.importorskip("numpy")
    with pytest.raises(rs.SnapshotSerializationError, match="non-finite"):
        _write_graph(tmp_path, _graph_with_edge_vals([np.float64("inf")]))


@pytest.mark.parametrize("field", ["source", "source_kind", "attribution"])
def test_non_string_metadata_field_rejected_on_write(tmp_path: Path, field: str) -> None:
    kwargs: dict[str, object] = {
        "place": "t",
        "network_type": "walk",
        "simplify": True,
        "osmnx_version": "t",
        "source": "t",
        "source_kind": rs.SOURCE_KIND_SYNTHETIC,
        "attribution": "t",
        "source_license": "",
        "source_license_url": "",
        "generated_at": "2026-08-29T00:00:00+00:00",
    }
    kwargs[field] = 123  # not a string
    with pytest.raises(rs.SnapshotSerializationError):
        rs.save_snapshot(
            rs.build_sample_graph(),
            snapshot_path=tmp_path / "g.graphml",
            metadata_path=tmp_path / "g.json",
            **kwargs,  # type: ignore[arg-type]
        )


def test_invalid_source_kind_rejected_on_write(tmp_path: Path) -> None:
    with pytest.raises(rs.SnapshotSerializationError, match="source_kind"):
        rs.save_snapshot(
            rs.build_sample_graph(),
            snapshot_path=tmp_path / "g.graphml",
            metadata_path=tmp_path / "g.json",
            place="t",
            network_type="walk",
            simplify=True,
            osmnx_version="t",
            source="t",
            source_kind="bogus",
            attribution="t",
            source_license="",
            source_license_url="",
            generated_at="2026-08-29T00:00:00+00:00",
        )


def test_writer_output_is_immediately_loadable(tmp_path: Path) -> None:
    """The pair a save produces must be readable by the loader with no further fixup."""
    gpath, mpath = _write_graph(tmp_path, _graph_with_edge_vals([1, "x", 2.5, [3]]))
    loaded = rs.load_sillim_snapshot(snapshot_path=gpath, metadata_path=mpath)
    assert loaded.graph.number_of_edges() == 4
    text = (tmp_path / "g.graphml").read_text(encoding="utf-8")
    assert "NaN" not in text and "Infinity" not in text  # no non-standard JSON tokens on disk


def test_failed_save_leaves_existing_pair_intact_and_no_temp(tmp_path: Path) -> None:
    good, meta = tmp_path / "g.graphml", tmp_path / "g.metadata.json"
    rs.save_snapshot(
        rs.build_sample_graph(),
        snapshot_path=good,
        metadata_path=meta,
        place="t",
        network_type="walk",
        simplify=True,
        osmnx_version="t",
        source="t",
        source_kind=rs.SOURCE_KIND_SYNTHETIC,
        attribution="t",
        source_license="",
        source_license_url="",
        generated_at="2026-08-29T00:00:00+00:00",
    )
    before_g, before_m = good.read_bytes(), meta.read_bytes()
    with pytest.raises(rs.SnapshotSerializationError):
        _write_graph(
            tmp_path, _graph_with_edge_vals([object()])
        )  # writes to g.* too, must fail first
    assert good.read_bytes() == before_g and meta.read_bytes() == before_m
    assert not any(p.name.endswith(".tmp") for p in tmp_path.iterdir())


# ── input graph never mutated, including on every error path ──────────────────────────────────


def _graph_with_refs() -> tuple[nx.MultiDiGraph, list[object], list[object], object]:
    tags: list[object] = [1, 2]
    nested: list[object] = [[3, 4]]
    geom = object()
    graph = nx.MultiDiGraph(crs="EPSG:4326")
    graph.add_node(1, x=1.0, y=2.0, tags=tags)
    graph.add_node(2, x=1.0, y=2.0)
    graph.add_edge(1, 2, key=0, length=5.0, nested=nested, geometry=geom)
    return graph, tags, nested, geom


def _assert_refs_intact(
    graph: nx.MultiDiGraph, tags: list[object], nested: list[object], geom: object
) -> None:
    assert graph.nodes[1]["tags"] is tags and graph.nodes[1]["tags"] == [1, 2]
    assert graph[1][2][0]["nested"] is nested and graph[1][2][0]["nested"] == [[3, 4]]
    assert graph[1][2][0]["geometry"] is geom


def test_input_graph_unchanged_on_serialization_error(tmp_path: Path) -> None:
    graph, tags, nested, geom = _graph_with_refs()  # geometry=object() is unsupported -> error
    with pytest.raises(rs.SnapshotSerializationError):
        _write_graph(tmp_path, graph)
    _assert_refs_intact(graph, tags, nested, geom)


def test_input_graph_unchanged_on_finite_error(tmp_path: Path) -> None:
    graph, tags, nested, _geom = _graph_with_refs()
    graph[1][2][0].pop("geometry")  # remove the unsupported one so finite check is the trigger
    graph.nodes[1]["x"] = float("nan")
    with pytest.raises(rs.SnapshotSerializationError, match="not finite"):
        _write_graph(tmp_path, graph)
    assert graph.nodes[1]["tags"] is tags and graph[1][2][0]["nested"] is nested


def test_input_graph_unchanged_on_metadata_error(tmp_path: Path) -> None:
    graph, tags, nested, _geom = _graph_with_refs()
    graph[1][2][0].pop("geometry")
    with pytest.raises(rs.SnapshotSerializationError):
        rs.save_snapshot(
            graph,
            snapshot_path=tmp_path / "g.graphml",
            metadata_path=tmp_path / "g.json",
            place="t",
            network_type="walk",
            simplify=True,
            osmnx_version="t",
            source=123,  # bad metadata field type
            source_kind=rs.SOURCE_KIND_SYNTHETIC,
            attribution="t",
            source_license="",
            source_license_url="",
            generated_at="2026-08-29T00:00:00+00:00",
        )
    assert graph.nodes[1]["tags"] is tags and graph[1][2][0]["nested"] is nested


def test_input_graph_unchanged_on_writer_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    graph, tags, nested, _geom = _graph_with_refs()
    graph[1][2][0].pop("geometry")

    def boom(*_a: object, **_k: object) -> None:
        raise nx.NetworkXError("boom")

    monkeypatch.setattr(rs.nx, "write_graphml", boom)
    with pytest.raises(rs.SnapshotSerializationError):
        _write_graph(tmp_path, graph)
    assert graph.nodes[1]["tags"] is tags and graph[1][2][0]["nested"] is nested


def test_save_snapshot_from_osm_unchanged_on_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Even when the save fails, the OSM-returned graph (geometry included) is untouched."""
    geom = object()
    fake = nx.MultiDiGraph(crs="EPSG:4326")
    fake.add_node(1, x=1.0, y=2.0)
    fake.add_node(2, x=1.0, y=2.0)
    fake.add_edge(
        1, 2, key=0, length=float("inf"), osmid=[1, 2], geometry=geom
    )  # non-finite -> error
    monkeypatch.setitem(
        sys.modules,
        "osmnx",
        types.SimpleNamespace(graph_from_place=lambda *a, **k: fake, __version__="t"),
    )
    with pytest.raises(rs.SnapshotSerializationError):
        rs.save_snapshot_from_osm(
            place="x", snapshot_path=tmp_path / "o.graphml", metadata_path=tmp_path / "o.json"
        )
    assert fake[1][2][0]["geometry"] is geom
    assert fake[1][2][0]["osmid"] == [1, 2]
    assert not (tmp_path / "o.graphml").exists()  # nothing written


# ── determinism: scoped to identical object + insertion order + generated_at ───────────────────


def test_same_object_same_generated_at_is_byte_identical(tmp_path: Path) -> None:
    graph = _graph_with_edge_vals([1, "x", [2, 3]])

    def save_to(sub: str) -> tuple[bytes, bytes, str]:
        d = tmp_path / sub
        d.mkdir()
        identity = rs.save_snapshot(
            graph,
            snapshot_path=d / "g.graphml",
            metadata_path=d / "g.json",
            place="t",
            network_type="walk",
            simplify=True,
            osmnx_version="t",
            source="t",
            source_kind=rs.SOURCE_KIND_SYNTHETIC,
            attribution="t",
            source_license="",
            source_license_url="",
            generated_at="2026-08-29T00:00:00+00:00",
        )
        return (d / "g.graphml").read_bytes(), (d / "g.json").read_bytes(), identity.graph_sha256

    g1, m1, sha1 = save_to("a")
    g2, m2, sha2 = save_to("b")
    assert g1 == g2 and m1 == m2 and sha1 == sha2 == hashlib.sha256(g1).hexdigest()


def test_insertion_order_is_not_canonicalized_bytes_may_differ(tmp_path: Path) -> None:
    """No graph canonicalization is performed: two logically-equal graphs built in different node
    insertion order both load correctly, but their GraphML bytes are NOT asserted equal."""
    g_forward = nx.MultiDiGraph(crs="EPSG:4326")
    g_forward.add_node(1, x=1.0, y=2.0)
    g_forward.add_node(2, x=3.0, y=4.0)
    g_forward.add_edge(1, 2, key=0, length=5.0)
    g_reverse = nx.MultiDiGraph(crs="EPSG:4326")
    g_reverse.add_node(2, x=3.0, y=4.0)
    g_reverse.add_node(1, x=1.0, y=2.0)
    g_reverse.add_edge(1, 2, key=0, length=5.0)

    (tmp_path / "f").mkdir()
    (tmp_path / "r").mkdir()
    fg, fm = _write_graph(tmp_path / "f", g_forward)
    rg, rm = _write_graph(tmp_path / "r", g_reverse)
    # Both are valid and equivalent when loaded; byte-equality is intentionally NOT asserted.
    lf = rs.load_sillim_snapshot(snapshot_path=fg, metadata_path=fm).graph
    lr = rs.load_sillim_snapshot(snapshot_path=rg, metadata_path=rm).graph
    assert set(lf.nodes) == set(lr.nodes) == {1, 2}
    assert lf.nodes[1]["x"] == lr.nodes[1]["x"] == 1.0


# ── native/reserved dual representation rejected (Codex 5th-audit MAJOR #2) ────────────────────


def _edge_reserved_pair(tmp_path: Path, reserved_value: str) -> tuple[Path, Path]:
    """A snapshot whose edge (1,2,0) has reserved ``savers::enc::tags`` = ``reserved_value`` and
    manifest ``edge=["tags"]`` (built by saving a real list attr, then patching the payload)."""
    graph = nx.MultiDiGraph(crs="EPSG:4326")
    graph.add_node(1, x=1.0, y=2.0)
    graph.add_node(2, x=1.0, y=2.0)
    graph.add_edge(1, 2, key=0, length=5.0, tags=[1])
    gpath, mpath = _write_graph(tmp_path, graph)
    if reserved_value != "[1]":
        gpath.write_text(
            gpath.read_text(encoding="utf-8").replace(
                '<data key="savers::enc::tags">[1]</data>',
                f'<data key="savers::enc::tags">{reserved_value}</data>',
            ),
            encoding="utf-8",
        )
        _reseal(gpath, mpath)
    return gpath, mpath


_GRAPHML_NS = "http://graphml.graphdrawing.org/xmlns"


def _inject_sibling_key(
    gpath: Path,
    mpath: Path,
    *,
    scope: str,
    beside_reserved_base: str,
    new_key_id: str,
    new_value: str,
    only_first: bool = False,
    reseal_overrides: dict[str, object] | None = None,
) -> None:
    """Structurally add ``<key id=new_key_id for=scope .../>`` plus a ``<data key=new_key_id>`` on
    each entity that already carries reserved ``savers::enc::{beside_reserved_base}``, then reseal.

    Edits the *parsed XML tree* — not raw bytes — so it is independent of the writer's self-closing
    style, attribute order, and whitespace (``nx.write_graphml`` output differs with vs without
    lxml, which is why the previous byte-``replace`` no-op'd under lxml and left an uncorrupted
    file). Asserts the intended corruption is actually present before returning, so a mis-targeted
    edit fails loudly instead of silently producing a file the test then 'passes' for the wrong
    reason. The corrupt file is loaded through the real ``load_sillim_snapshot`` unchanged.
    """
    q = f"{{{_GRAPHML_NS}}}"
    ET.register_namespace("", _GRAPHML_NS)
    # S314: the input is GraphML this test itself just wrote (fully trusted), not external data.
    tree = ET.parse(gpath)  # noqa: S314
    root = tree.getroot()
    reserved_key = rs._RESERVED_ATTR_PREFIX + beside_reserved_base
    # GraphML declares <key> elements before the <graph>; inserting at the front is valid.
    root.insert(
        0,
        ET.Element(
            f"{q}key",
            {"id": new_key_id, "for": scope, "attr.name": new_key_id, "attr.type": "string"},
        ),
    )
    parents = {child: parent for parent in root.iter() for child in parent}
    injected = 0
    for data_el in list(root.iter(f"{q}data")):
        if data_el.get("key") != reserved_key:
            continue
        sibling = ET.SubElement(parents[data_el], f"{q}data", {"key": new_key_id})
        sibling.text = new_value
        injected += 1
        if only_first:
            break
    assert injected > 0, f"no reserved {reserved_key!r} data element found to inject beside"
    tree.write(gpath, encoding="utf-8", xml_declaration=True)
    # Precondition: the file now really carries both the reserved key and the injected sibling.
    text = gpath.read_text(encoding="utf-8")
    assert f'key="{reserved_key}"' in text
    assert f'key="{new_key_id}"' in text
    _reseal(gpath, mpath, **(reseal_overrides or {}))


def _inject_native_alongside_reserved(gpath: Path, mpath: Path) -> None:
    """Add a native ``tags`` edge attribute next to the existing reserved ``savers::enc::tags``."""
    _inject_sibling_key(
        gpath,
        mpath,
        scope="edge",
        beside_reserved_base="tags",
        new_key_id="tags",
        new_value="native",
    )


def test_native_and_reserved_dual_representation_rejected(tmp_path: Path) -> None:
    """MAJOR #2: an entity carrying both a native and a reserved value for the same base key is
    rejected — the native value is never overwritten by the decoded reserved one."""
    gpath, mpath = _edge_reserved_pair(tmp_path, "[1]")
    _inject_native_alongside_reserved(gpath, mpath)
    with pytest.raises(rs.SnapshotSchemaMismatchError, match="both a native and an encoded"):
        rs.load_sillim_snapshot(snapshot_path=gpath, metadata_path=mpath)


def test_empty_reserved_base_key_rejected(tmp_path: Path) -> None:
    graph = nx.MultiDiGraph(crs="EPSG:4326")
    graph.add_node(1, x=1.0, y=2.0)
    graph.add_node(2, x=1.0, y=2.0)
    graph.add_edge(1, 2, key=0, length=5.0, tags=[1])
    gpath, mpath = _write_graph(tmp_path, graph)
    # Inject a second reserved key with an EMPTY base (bare prefix) beside savers::enc::tags.
    _inject_sibling_key(
        gpath,
        mpath,
        scope="edge",
        beside_reserved_base="tags",
        new_key_id=rs._RESERVED_ATTR_PREFIX,
        new_value="[9]",
        reseal_overrides={"encoded_attrs": {"graph": [], "node": [], "edge": ["", "tags"]}},
    )
    with pytest.raises(rs.SnapshotSchemaMismatchError, match="empty base name"):
        rs.load_sillim_snapshot(snapshot_path=gpath, metadata_path=mpath)


@pytest.mark.parametrize("scope", ["graph", "node", "edge"])
def test_dual_representation_rejected_per_scope(tmp_path: Path, scope: str) -> None:
    """A native+reserved collision is detected independently in graph, node and edge scope."""
    graph = rs.build_sample_graph()
    if scope == "graph":
        graph.graph["tags"] = [1]
    elif scope == "node":
        graph.nodes[1000001]["tags"] = [1]
    else:
        first = next(iter(graph.edges(keys=True)))
        graph.edges[first]["tags"] = [1]
    gpath, mpath = _write_graph(tmp_path, graph)
    # inject a native `tags` next to the reserved one on the first entity of this scope
    _inject_sibling_key(
        gpath,
        mpath,
        scope=scope,
        beside_reserved_base="tags",
        new_key_id="tags",
        new_value="native",
        only_first=True,
    )
    with pytest.raises(rs.SnapshotSchemaMismatchError, match="both a native and an encoded"):
        rs.load_sillim_snapshot(snapshot_path=gpath, metadata_path=mpath)


def test_same_base_key_reserved_independently_across_scopes(tmp_path: Path) -> None:
    """The same base name may be reserved in one scope and native in another without collision."""
    graph = rs.build_sample_graph()
    graph.graph["tags"] = [1, 2]  # graph scope: encoded
    for node_id in graph.nodes:
        graph.nodes[node_id]["tags"] = "plain"  # node scope: homogeneous str, native
    gpath, mpath = _write_graph(tmp_path, graph)
    manifest = json.loads(mpath.read_text(encoding="utf-8"))["encoded_attrs"]
    assert manifest["graph"] == ["tags"] and manifest["node"] == []
    loaded = rs.load_sillim_snapshot(snapshot_path=gpath, metadata_path=mpath).graph
    assert loaded.graph["tags"] == [1, 2]
    assert loaded.nodes[1000001]["tags"] == "plain"


def test_partial_conflict_rejects_whole_load(tmp_path: Path) -> None:
    """When only one edge has a native+reserved conflict, the whole load is rejected and no
    partially-restored graph is returned."""
    graph = nx.MultiDiGraph(crs="EPSG:4326")
    graph.add_node(1, x=1.0, y=2.0)
    graph.add_node(2, x=1.0, y=2.0)
    graph.add_edge(1, 2, key=0, length=5.0, tags=[1])
    graph.add_edge(1, 2, key=1, length=6.0, tags=[2])
    gpath, mpath = _write_graph(tmp_path, graph)
    # add native tags to only the first reserved edge; the whole load must still be rejected
    _inject_sibling_key(
        gpath,
        mpath,
        scope="edge",
        beside_reserved_base="tags",
        new_key_id="tags",
        new_value="native",
        only_first=True,
    )
    with pytest.raises(rs.SnapshotSchemaMismatchError, match="both a native and an encoded"):
        rs.load_sillim_snapshot(snapshot_path=gpath, metadata_path=mpath)


def test_reserved_marker_not_in_returned_graph(tmp_path: Path) -> None:
    gpath, mpath = _edge_reserved_pair(tmp_path, "[1]")
    loaded = rs.load_sillim_snapshot(snapshot_path=gpath, metadata_path=mpath).graph
    assert loaded[1][2][0]["tags"] == [1]
    for _u, _v, data in loaded.edges(data=True):
        assert not any(k.startswith(rs._RESERVED_ATTR_PREFIX) for k in data)


# ── decoded reserved payload re-validated with the writer's value contract (MINOR) ─────────────


@pytest.mark.parametrize(
    "payload",
    ['{"a": 1}', "NaN", "Infinity", "-Infinity", "1e309", "[" * 40 + "1" + "]" * 40],
    ids=["dict", "NaN", "Infinity", "-Infinity", "overflow-1e309", "too-deep"],
)
def test_decoded_reserved_payload_is_rejected(tmp_path: Path, payload: str) -> None:
    gpath, mpath = _edge_reserved_pair(tmp_path, payload)
    with pytest.raises(rs.SnapshotSchemaMismatchError):
        rs.load_sillim_snapshot(snapshot_path=gpath, metadata_path=mpath)


def test_decoded_malformed_json_has_cause(tmp_path: Path) -> None:
    gpath, mpath = _edge_reserved_pair(tmp_path, "[1,")  # malformed JSON
    with pytest.raises(rs.SnapshotSchemaMismatchError, match="malformed JSON-encoded") as excinfo:
        rs.load_sillim_snapshot(snapshot_path=gpath, metadata_path=mpath)
    assert excinfo.value.__cause__ is not None


@pytest.mark.parametrize(
    "payload,expected",
    [
        ("[1, 2, 3]", [1, 2, 3]),
        ("[[1], [2, 3]]", [[1], [2, 3]]),
        ('"plain"', "plain"),
        ("true", True),
    ],
    ids=["list", "nested-list", "str", "bool"],
)
def test_decoded_valid_payload_restores_original_type(
    tmp_path: Path, payload: str, expected: object
) -> None:
    gpath, mpath = _edge_reserved_pair(tmp_path, payload)
    loaded = rs.load_sillim_snapshot(snapshot_path=gpath, metadata_path=mpath).graph
    got = loaded[1][2][0]["tags"]
    assert got == expected and type(got) is type(expected)


# ── real numpy scalars only; imposters rejected (Codex 5th-audit MAJOR #3) ─────────────────────


def test_real_numpy_scalars_normalized(tmp_path: Path) -> None:
    np = pytest.importorskip("numpy")
    # mix with a str so the key is encoded and each value's type is preserved through JSON
    graph = _graph_with_edge_vals([np.int64(5), np.float64(1.5), np.bool_(True), "x"])
    gpath, mpath = _write_graph(tmp_path, graph)
    loaded = rs.load_sillim_snapshot(snapshot_path=gpath, metadata_path=mpath).graph
    got = [loaded[1][2][k]["val"] for k in range(4)]
    assert got == [5, 1.5, True, "x"]
    assert [type(x) for x in got] == [int, float, bool, str]


def test_numpy_array_rejected(tmp_path: Path) -> None:
    np = pytest.importorskip("numpy")
    with pytest.raises(rs.SnapshotSerializationError):
        _write_graph(tmp_path, _graph_with_edge_vals([np.array([1, 2])]))  # 1-d array
    with pytest.raises(rs.SnapshotSerializationError):
        _write_graph(tmp_path, _graph_with_edge_vals([np.array(5)]))  # 0-d array (not a scalar)


def test_real_numpy_nonfinite_rejected(tmp_path: Path) -> None:
    np = pytest.importorskip("numpy")
    with pytest.raises(rs.SnapshotSerializationError, match="finite"):
        _write_graph(tmp_path, _graph_with_edge_vals([np.float64("nan")]))
    with pytest.raises(rs.SnapshotSerializationError, match="finite"):
        _write_graph(tmp_path, _graph_with_edge_vals([np.float64("inf")]))


class _NumpyImposter:
    """Duck-typed like a numpy scalar but not a real numpy.generic."""

    ndim = 0

    def __init__(self, module: str) -> None:
        type(self).__module__ = module

    def item(self) -> int:  # pragma: no cover - must never be called
        raise AssertionError("item() must not be called on an imposter")


@pytest.mark.parametrize("module", ["numpy", "numpy.fake"])
def test_numpy_imposter_rejected_without_calling_item(tmp_path: Path, module: str) -> None:
    pytest.importorskip("numpy")  # imposter path is only meaningful when numpy is importable
    imposter = _NumpyImposter(module)
    with pytest.raises(rs.SnapshotSerializationError):
        _write_graph(tmp_path, _graph_with_edge_vals([imposter]))


def test_plain_object_with_ndim_and_item_is_rejected(tmp_path: Path) -> None:
    """A non-numpy object that merely has ndim/item() is an unsupported type, not a numpy scalar;
    its item() is never called."""

    class Plain:
        ndim = 0

        def item(self) -> int:  # pragma: no cover
            raise AssertionError("item() must not be called")

    with pytest.raises(rs.SnapshotSerializationError, match="unsupported attribute type"):
        _write_graph(tmp_path, _graph_with_edge_vals([Plain()]))


# ── non-string attribute keys rejected as typed errors (Codex 6th-audit) ───────────────────────


def _graph_with_nonstring_key(scope: str, key: object) -> nx.MultiDiGraph:
    """A valid MultiDiGraph with one extra non-string attribute key in the given scope."""
    graph = nx.MultiDiGraph(crs="EPSG:4326")
    graph.add_node(1, x=126.9, y=37.4)
    graph.add_node(2, x=126.91, y=37.41)
    graph.add_edge(1, 2, key=0, length=5.0)
    if scope == "graph":
        graph.graph[key] = "v"
    elif scope == "node":
        graph.nodes[1][key] = "v"
    else:
        graph[1][2][0][key] = "v"
    return graph


@pytest.mark.parametrize("scope", ["graph", "node", "edge"])
def test_nonstring_attribute_key_rejected_as_typed_error(tmp_path: Path, scope: str) -> None:
    """An ``int`` attribute key in any scope is rejected with SnapshotSerializationError — never a
    raw AttributeError — and no output pair or ``.tmp`` file is produced."""
    graph = _graph_with_nonstring_key(scope, 123)
    gpath = tmp_path / "g.graphml"
    mpath = tmp_path / "g.metadata.json"
    with pytest.raises(
        rs.SnapshotSerializationError, match=f"{scope} attribute key must be an exact built-in str"
    ):
        rs.save_snapshot(
            graph,
            snapshot_path=gpath,
            metadata_path=mpath,
            place="t",
            network_type="walk",
            simplify=True,
            osmnx_version="t",
            source="t",
            source_kind=rs.SOURCE_KIND_SYNTHETIC,
            attribution="t",
            source_license="",
            source_license_url="",
            generated_at="2026-08-29T00:00:00+00:00",
        )
    # no output pair and no temp files left behind
    assert not gpath.exists() and not mpath.exists()
    assert not any(p.name.endswith(".tmp") for p in tmp_path.iterdir())


@pytest.mark.parametrize("scope", ["graph", "node", "edge"])
def test_nonstring_attribute_key_does_not_leak_raw_attributeerror(
    tmp_path: Path, scope: str
) -> None:
    graph = _graph_with_nonstring_key(scope, 123)
    try:
        _write_graph(tmp_path, graph)
    except AttributeError:  # pragma: no cover - would fail the test
        raise AssertionError(f"raw AttributeError leaked for {scope} scope") from None
    except rs.SnapshotSerializationError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected SnapshotSerializationError")


@pytest.mark.parametrize("scope", ["graph", "node", "edge"])
def test_nonstring_attribute_key_leaves_input_graph_unchanged(tmp_path: Path, scope: str) -> None:
    ref_list = [1, 2]
    graph = _graph_with_nonstring_key(scope, 123)
    graph[1][2][0]["tags"] = ref_list  # a nested object to check identity survives
    before_graph = dict(graph.graph)
    before_node = dict(graph.nodes[1])
    before_edge = dict(graph[1][2][0])
    with pytest.raises(rs.SnapshotSerializationError):
        _write_graph(tmp_path, graph)
    assert dict(graph.graph) == before_graph
    assert dict(graph.nodes[1]) == before_node
    assert dict(graph[1][2][0]) == before_edge
    assert graph[1][2][0]["tags"] is ref_list  # nested object reference unchanged
    assert 123 in {"graph": graph.graph, "node": graph.nodes[1], "edge": graph[1][2][0]}[scope]


def test_nonstring_key_error_message_names_scope_and_type(tmp_path: Path) -> None:
    """The typed error is diagnostic (scope + key type) and does not embed a user repr of the key."""
    with pytest.raises(
        rs.SnapshotSerializationError, match="edge attribute key must be an exact built-in str"
    ):
        _write_graph(tmp_path, _graph_with_nonstring_key("edge", 123))
    with pytest.raises(rs.SnapshotSerializationError, match="type 'int'"):
        _write_graph(tmp_path, _graph_with_nonstring_key("node", 123))


# ── str-subclass attribute keys rejected without running their methods (Codex 7th-audit) ────────


class _EvilStrKey(str):
    """A ``str`` subclass whose ``startswith``/``__repr__``/``__str__`` raise if the writer ever
    touches them; a shared class-level counter records any call so tests can assert zero."""

    calls: ClassVar[dict[str, int]] = {"startswith": 0, "repr": 0, "str": 0}

    @classmethod
    def reset(cls) -> None:
        cls.calls = {"startswith": 0, "repr": 0, "str": 0}

    def startswith(self, *args: object, **kwargs: object) -> bool:
        type(self).calls["startswith"] += 1
        raise RuntimeError("startswith override must not run")

    def __repr__(self) -> str:
        type(self).calls["repr"] += 1
        raise RuntimeError("repr override must not run")

    def __str__(self) -> str:
        type(self).calls["str"] += 1
        raise RuntimeError("str override must not run")


@pytest.mark.parametrize("scope", ["graph", "node", "edge"])
def test_malicious_str_subclass_key_rejected_without_running_its_methods(
    tmp_path: Path, scope: str
) -> None:
    """A str-subclass key with hostile startswith/repr/str is rejected with a typed error, and none
    of its overrides run. No output pair or .tmp file is produced."""
    graph = _graph_with_nonstring_key(scope, _EvilStrKey("evil"))
    gpath = tmp_path / "g.graphml"
    mpath = tmp_path / "g.metadata.json"
    _EvilStrKey.reset()  # ignore any hash/insertion calls; measure only the save
    with pytest.raises(rs.SnapshotSerializationError, match=f"{scope} attribute key must be"):
        rs.save_snapshot(
            graph,
            snapshot_path=gpath,
            metadata_path=mpath,
            place="t",
            network_type="walk",
            simplify=True,
            osmnx_version="t",
            source="t",
            source_kind=rs.SOURCE_KIND_SYNTHETIC,
            attribution="t",
            source_license="",
            source_license_url="",
            generated_at="2026-08-29T00:00:00+00:00",
        )
    assert _EvilStrKey.calls == {"startswith": 0, "repr": 0, "str": 0}
    assert not gpath.exists() and not mpath.exists()
    assert not any(p.name.endswith(".tmp") for p in tmp_path.iterdir())


@pytest.mark.parametrize("scope", ["graph", "node", "edge"])
def test_str_subclass_key_does_not_leak_raw_runtimeerror(tmp_path: Path, scope: str) -> None:
    graph = _graph_with_nonstring_key(scope, _EvilStrKey("evil"))
    _EvilStrKey.reset()
    # SnapshotSerializationError subclasses RuntimeError, so catch the typed error FIRST; only a
    # *raw* RuntimeError (from the key's hostile override) should reach the RuntimeError clause.
    try:
        _write_graph(tmp_path, graph)
    except rs.SnapshotSerializationError:
        pass
    except RuntimeError:  # pragma: no cover - would fail the test
        raise AssertionError(f"raw RuntimeError leaked for {scope} scope") from None
    else:  # pragma: no cover
        raise AssertionError("expected SnapshotSerializationError")
    assert _EvilStrKey.calls == {"startswith": 0, "repr": 0, "str": 0}


def test_str_subclass_key_error_names_scope_and_subclass_type(tmp_path: Path) -> None:
    """The message includes scope + subclass type name, and never the key's own str/repr."""
    _EvilStrKey.reset()
    with pytest.raises(rs.SnapshotSerializationError, match="edge attribute key must be an exact"):
        _write_graph(tmp_path, _graph_with_nonstring_key("edge", _EvilStrKey("evil")))
    with pytest.raises(rs.SnapshotSerializationError, match="type '_EvilStrKey'"):
        _write_graph(tmp_path, _graph_with_nonstring_key("node", _EvilStrKey("evil")))
    assert _EvilStrKey.calls == {"startswith": 0, "repr": 0, "str": 0}


def test_benign_str_subclass_key_also_rejected(tmp_path: Path) -> None:
    """Even a plain str subclass (no overrides) is rejected — exact built-in str is required."""

    class PlainSub(str):
        pass

    with pytest.raises(rs.SnapshotSerializationError, match="type 'PlainSub'"):
        _write_graph(tmp_path, _graph_with_nonstring_key("edge", PlainSub("k")))


def test_str_subclass_key_leaves_input_and_existing_pair_unchanged(tmp_path: Path) -> None:
    """A failed save over an existing valid pair leaves both files byte-for-byte unchanged and the
    input graph (structure/values/nested references) intact."""
    # establish a valid pair at the target paths
    valid = nx.MultiDiGraph(crs="EPSG:4326")
    valid.add_node(1, x=1.0, y=2.0)
    valid.add_node(2, x=1.0, y=2.0)
    valid.add_edge(1, 2, key=0, length=5.0)
    gpath, mpath = _write_graph(tmp_path, valid)
    before_g, before_m = gpath.read_bytes(), mpath.read_bytes()

    ref_list = [1, 2]
    graph = _graph_with_nonstring_key("edge", _EvilStrKey("evil"))
    graph[1][2][0]["tags"] = ref_list
    before_edge = dict(graph[1][2][0])
    _EvilStrKey.reset()
    with pytest.raises(rs.SnapshotSerializationError):
        rs.save_snapshot(
            graph,
            snapshot_path=gpath,
            metadata_path=mpath,
            place="t",
            network_type="walk",
            simplify=True,
            osmnx_version="t",
            source="t",
            source_kind=rs.SOURCE_KIND_SYNTHETIC,
            attribution="t",
            source_license="",
            source_license_url="",
            generated_at="2026-08-29T00:00:00+00:00",
        )
    assert gpath.read_bytes() == before_g and mpath.read_bytes() == before_m  # existing pair intact
    assert not any(p.name.endswith(".tmp") for p in tmp_path.iterdir())
    assert dict(graph[1][2][0]) == before_edge and graph[1][2][0]["tags"] is ref_list


def test_string_keys_still_round_trip_after_key_type_check(tmp_path: Path) -> None:
    """Regression guard: the new key-type check does not disturb normal string-key handling,
    including reserved-marker encoding of a list attribute."""
    graph = nx.MultiDiGraph(crs="EPSG:4326")
    graph.add_node(1, x=126.9, y=37.4, ref="n1")
    graph.add_node(2, x=126.91, y=37.41)
    graph.add_edge(1, 2, key=0, length=5.0, osmid=[101, 202], name="road")
    gpath, mpath = _write_graph(tmp_path, graph)
    loaded = rs.load_sillim_snapshot(snapshot_path=gpath, metadata_path=mpath).graph
    assert loaded.nodes[1]["ref"] == "n1"
    assert loaded[1][2][0]["osmid"] == [101, 202]
    assert loaded[1][2][0]["name"] == "road"


# ── file-level atomicity + fail-closed on a broken pair (Codex 5th-audit MINOR) ────────────────


def test_partial_pair_new_graphml_old_metadata_is_checksum_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failure between the two replaces (new GraphML, old metadata) is caught by the loader as a
    checksum mismatch — never silently accepted; a retry then produces a loadable pair."""
    gpath = tmp_path / "g.graphml"
    mpath = tmp_path / "g.metadata.json"
    # establish a valid initial pair
    _write_graph(tmp_path, _graph_with_edge_vals([1, 2, 3]))
    old_meta = mpath.read_bytes()

    real_atomic = rs._atomic_write
    calls = {"n": 0}

    def flaky(path: Path, data: bytes) -> None:
        calls["n"] += 1
        if calls["n"] == 2:  # the metadata write (second call)
            raise OSError("disk full")
        real_atomic(path, data)

    monkeypatch.setattr(rs, "_atomic_write", flaky)
    with pytest.raises(OSError, match="disk full"):
        _write_graph(tmp_path, _graph_with_edge_vals([9, 9, 9]))
    monkeypatch.undo()

    # new GraphML is on disk but metadata is the stale one -> checksum mismatch, not silent accept
    assert mpath.read_bytes() == old_meta
    with pytest.raises(rs.SnapshotChecksumMismatchError):
        rs.load_sillim_snapshot(snapshot_path=gpath, metadata_path=mpath)
    # no leftover temp files
    assert not any(p.name.endswith(".tmp") for p in tmp_path.iterdir())
    # a retry recovers a complete, loadable pair
    _write_graph(tmp_path, _graph_with_edge_vals([9, 9, 9]))
    assert (
        rs.load_sillim_snapshot(snapshot_path=gpath, metadata_path=mpath).graph.number_of_edges()
        == 3
    )


def test_graphml_only_partial_is_file_missing_on_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no prior pair, a failure before the metadata replace leaves GraphML-only, which the
    loader reports as a missing metadata file (fail-closed)."""
    gpath = tmp_path / "g.graphml"
    mpath = tmp_path / "g.metadata.json"
    real_atomic = rs._atomic_write
    calls = {"n": 0}

    def flaky(path: Path, data: bytes) -> None:
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("disk full")
        real_atomic(path, data)

    monkeypatch.setattr(rs, "_atomic_write", flaky)
    with pytest.raises(OSError):
        _write_graph(tmp_path, _graph_with_edge_vals([1, 2, 3]))
    monkeypatch.undo()
    assert gpath.exists() and not mpath.exists()
    with pytest.raises(rs.SnapshotFileMissingError):
        rs.load_sillim_snapshot(snapshot_path=gpath, metadata_path=mpath)


# ── loader propagates MemoryError / control-flow signals (Codex 5th-audit MINOR) ───────────────


@pytest.mark.parametrize("exc", [MemoryError, KeyboardInterrupt, SystemExit])
def test_loader_propagates_non_schema_signals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, exc: type[BaseException]
) -> None:
    graph, meta = _copy_sample(tmp_path)

    def boom(*_a: object, **_k: object) -> None:
        raise exc()

    monkeypatch.setattr(rs.nx, "read_graphml", boom)
    with pytest.raises(exc):
        rs.load_sillim_snapshot(snapshot_path=graph, metadata_path=meta)


@pytest.mark.parametrize("exc", [ValueError("x"), TypeError("x"), nx.NetworkXError("x")])
def test_loader_normalizes_expected_parse_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, exc: Exception
) -> None:
    graph, meta = _copy_sample(tmp_path)

    def boom(*_a: object, **_k: object) -> None:
        raise exc

    monkeypatch.setattr(rs.nx, "read_graphml", boom)
    with pytest.raises(rs.SnapshotSchemaMismatchError, match="could not be parsed") as excinfo:
        rs.load_sillim_snapshot(snapshot_path=graph, metadata_path=meta)
    assert excinfo.value.__cause__ is exc


# ── schema version + determinism ──────────────────────────────────────────────────────────────


def test_schema_v1_metadata_is_rejected(tmp_path: Path) -> None:
    """A v1 sidecar (the old, pre-manifest contract) is rejected, not silently reinterpreted."""
    graph, meta = _copy_sample(tmp_path)
    _reseal(graph, meta, schema_version=1)
    with pytest.raises(rs.SnapshotSchemaMismatchError, match="schema version"):
        rs.load_sillim_snapshot(snapshot_path=graph, metadata_path=meta)


def test_same_input_and_generated_at_is_deterministic(tmp_path: Path) -> None:
    """Same graph + same generated_at -> identical GraphML bytes, metadata bytes, and checksum."""
    graph = _mdg_with_osmid([101, [303, 404]])

    def save_to(sub: str) -> tuple[bytes, bytes, str]:
        d = tmp_path / sub
        d.mkdir()
        identity = rs.save_snapshot(
            graph,
            snapshot_path=d / "g.graphml",
            metadata_path=d / "g.json",
            place="t",
            network_type="walk",
            simplify=True,
            osmnx_version="t",
            source="t",
            source_kind=rs.SOURCE_KIND_SYNTHETIC,
            attribution="t",
            source_license="",
            source_license_url="",
            generated_at="2026-08-29T00:00:00+00:00",
        )
        return (d / "g.graphml").read_bytes(), (d / "g.json").read_bytes(), identity.graph_sha256

    g1, m1, sha1 = save_to("a")
    g2, m2, sha2 = save_to("b")
    assert g1 == g2
    assert m1 == m2
    assert sha1 == sha2 == hashlib.sha256(g1).hexdigest()


# ── bounded reader closes its file handle on success and failure ──────────────────────────────


def test_bounded_reader_closes_handle_on_success(tmp_path: Path) -> None:
    """After a successful load, both files can be deleted — proving no handle is left open
    (on Windows an open handle blocks unlink)."""
    graph, meta = _copy_sample(tmp_path)
    rs.load_sillim_snapshot(snapshot_path=graph, metadata_path=meta)
    graph.unlink()
    meta.unlink()
    assert not graph.exists() and not meta.exists()


def test_bounded_reader_closes_handle_on_failure(tmp_path: Path) -> None:
    """Each failure path (oversize, invalid UTF-8, malformed JSON) still closes its handle."""
    # oversize metadata
    graph, meta = _copy_sample(tmp_path)
    size = meta.stat().st_size
    with pytest.raises(rs.SnapshotTooLargeError):
        rs.load_sillim_snapshot(
            snapshot_path=graph, metadata_path=meta, max_metadata_bytes=size - 1
        )
    meta.unlink()  # would fail if the handle were still open
    # invalid UTF-8 metadata
    graph2, meta2 = _copy_sample(tmp_path)
    meta2.write_bytes(b"\xff\xfe bad")
    with pytest.raises(rs.SnapshotSchemaMismatchError):
        rs.load_sillim_snapshot(snapshot_path=graph2, metadata_path=meta2)
    meta2.unlink()
    # malformed JSON metadata
    graph3, meta3 = _copy_sample(tmp_path)
    meta3.write_text("{ not json", encoding="utf-8")
    with pytest.raises(rs.SnapshotSchemaMismatchError):
        rs.load_sillim_snapshot(snapshot_path=graph3, metadata_path=meta3)
    meta3.unlink()
    graph3.unlink()  # graphml handle also released


# ── TOCTOU-free bounded reads (single handle; exact ceiling boundary) ─────────────────────────


def test_metadata_at_exact_ceiling_loads_and_one_over_rejected(tmp_path: Path) -> None:
    """Exactly MAX_SNAPSHOT_METADATA_BYTES of valid metadata loads; one byte over is rejected on
    size before any parse. Uses the real default ceiling and real files (no stat monkeypatch)."""
    graph, meta = _copy_sample(tmp_path)
    payload = json.loads(meta.read_text(encoding="utf-8"))
    target = rs.MAX_SNAPSHOT_METADATA_BYTES
    current = len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    pad = target - current
    assert pad >= 0
    payload["source"] = payload["source"] + " " * pad  # ASCII pad: 1 byte each
    exact = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    assert len(exact) == target

    meta.write_bytes(exact)
    loaded = rs.load_sillim_snapshot(snapshot_path=graph, metadata_path=meta)
    assert loaded.identity.node_count == 6  # exactly at the ceiling: accepted

    meta.write_bytes(exact + b" ")  # one byte over
    with pytest.raises(rs.SnapshotTooLargeError, match="metadata exceeds"):
        rs.load_sillim_snapshot(snapshot_path=graph, metadata_path=meta)


def test_graphml_at_exact_ceiling_loads_and_one_over_rejected(tmp_path: Path) -> None:
    """The GraphML uses the same bounded-read contract: exactly at the ceiling loads, one byte over
    is rejected, and the bytes the size check saw are the bytes parsed (single handle)."""
    graph, meta = _copy_sample(tmp_path)
    size = graph.stat().st_size
    loaded = rs.load_sillim_snapshot(snapshot_path=graph, metadata_path=meta, max_bytes=size)
    assert loaded.graph.number_of_nodes() == 6
    with pytest.raises(rs.SnapshotTooLargeError, match="GraphML exceeds"):
        rs.load_sillim_snapshot(snapshot_path=graph, metadata_path=meta, max_bytes=size - 1)


def test_invalid_utf8_metadata_is_schema_error(tmp_path: Path) -> None:
    graph, meta = _copy_sample(tmp_path)
    meta.write_bytes(b"\xff\xfe not utf-8 at all")
    with pytest.raises(rs.SnapshotSchemaMismatchError, match="not valid UTF-8") as excinfo:
        rs.load_sillim_snapshot(snapshot_path=graph, metadata_path=meta)
    assert excinfo.value.__cause__ is not None


# ── generated_at contract: ISO 8601, timezone-aware, not in the future ────────────────────────


def test_generated_at_malformed_is_rejected_with_cause(tmp_path: Path) -> None:
    graph, meta = _copy_sample(tmp_path)
    _reseal(graph, meta, generated_at="not-a-timestamp")
    with pytest.raises(rs.SnapshotSchemaMismatchError, match="ISO 8601") as excinfo:
        rs.load_sillim_snapshot(snapshot_path=graph, metadata_path=meta)
    assert excinfo.value.__cause__ is not None  # the parse error is chained


def test_generated_at_naive_without_timezone_is_rejected(tmp_path: Path) -> None:
    graph, meta = _copy_sample(tmp_path)
    _reseal(graph, meta, generated_at="2026-08-29T00:00:00")  # no offset
    with pytest.raises(rs.SnapshotSchemaMismatchError, match="timezone-aware"):
        rs.load_sillim_snapshot(snapshot_path=graph, metadata_path=meta)


def test_generated_at_in_the_future_is_rejected(tmp_path: Path) -> None:
    graph, meta = _copy_sample(tmp_path)
    future = (datetime.now(UTC) + timedelta(days=365)).isoformat()
    _reseal(graph, meta, generated_at=future)
    with pytest.raises(rs.SnapshotSchemaMismatchError, match="future"):
        rs.load_sillim_snapshot(snapshot_path=graph, metadata_path=meta)


def test_generated_at_far_future_year_is_rejected(tmp_path: Path) -> None:
    """An obviously-wrong future value (e.g. year 2027) is rejected despite the tiny skew window."""
    graph, meta = _copy_sample(tmp_path)
    _reseal(graph, meta, generated_at="2027-01-01T00:00:00+00:00")
    with pytest.raises(rs.SnapshotSchemaMismatchError, match="future"):
        rs.load_sillim_snapshot(snapshot_path=graph, metadata_path=meta)


def test_generated_at_non_utc_offset_is_accepted(tmp_path: Path) -> None:
    """A timezone-aware value in a non-UTC offset normalizes to UTC and is accepted when past."""
    graph, meta = _copy_sample(tmp_path)
    _reseal(graph, meta, generated_at="2026-08-29T09:00:00+09:00")  # = 00:00Z, past
    loaded = rs.load_sillim_snapshot(snapshot_path=graph, metadata_path=meta)
    assert loaded.identity.node_count == 6


def test_writer_current_utc_generated_at_is_accepted(tmp_path: Path) -> None:
    """The value the writer stamps (real current UTC via the default) passes loader validation
    without flakiness — the tiny skew absorbs the sub-second gap."""
    gpath = tmp_path / "now.graphml"
    mpath = tmp_path / "now.metadata.json"
    rs.save_snapshot(
        rs.build_sample_graph(),
        snapshot_path=gpath,
        metadata_path=mpath,
        place="t",
        network_type="walk",
        simplify=True,
        osmnx_version="t",
        source="t",
        source_kind=rs.SOURCE_KIND_SYNTHETIC,
        attribution="t",
        source_license="",
        source_license_url="",
    )  # generated_at defaults to datetime.now(UTC)
    loaded = rs.load_sillim_snapshot(snapshot_path=gpath, metadata_path=mpath)
    assert loaded.identity.node_count == 6


# ── snapshot-first boundary (route_engine): pair-wise fallback ────────────────────────────────


def test_boundary_uses_snapshot_and_never_calls_overpass_when_present() -> None:
    overpass = _SpyLoader(exc=AssertionError("Overpass must not run when a snapshot is present"))
    loaded = load_sillim_walking_graph_snapshot_first(
        snapshot_path=rs.SAMPLE_SNAPSHOT_PATH,
        metadata_path=rs.SAMPLE_SNAPSHOT_METADATA_PATH,
        overpass_loader=overpass,
    )
    assert isinstance(loaded, LoadedRouteGraph)
    assert loaded.graph.number_of_nodes() == 6
    assert loaded.identity is not None and loaded.identity.is_synthetic is True
    assert overpass.calls == 0


def test_boundary_falls_back_to_overpass_exactly_once_when_both_absent(tmp_path: Path) -> None:
    overpass = _SpyLoader(result=rs.build_sample_graph())
    loaded = load_sillim_walking_graph_snapshot_first(
        snapshot_path=tmp_path / "absent.graphml",
        metadata_path=tmp_path / "absent.json",
        overpass_loader=overpass,
    )
    assert loaded.graph.number_of_nodes() == 6
    assert loaded.identity is None  # the Overpass path carries no committed provenance
    assert overpass.calls == 1


def test_boundary_metadata_only_half_pair_raises_and_never_calls_overpass(tmp_path: Path) -> None:
    """Metadata present but GraphML absent is a *broken* snapshot, not an absent one."""
    _graph, meta = _copy_sample(tmp_path)
    overpass = _SpyLoader(exc=AssertionError("a half-pair must not fall back to Overpass"))
    with pytest.raises(rs.SnapshotFileMissingError, match="GraphML is missing"):
        load_sillim_walking_graph_snapshot_first(
            snapshot_path=tmp_path / "absent.graphml",
            metadata_path=meta,
            overpass_loader=overpass,
        )
    assert overpass.calls == 0


def test_boundary_graphml_only_half_pair_raises_and_never_calls_overpass(tmp_path: Path) -> None:
    """GraphML present but metadata absent is a *broken* snapshot, not an absent one."""
    graph, _meta = _copy_sample(tmp_path)
    overpass = _SpyLoader(exc=AssertionError("a half-pair must not fall back to Overpass"))
    with pytest.raises(rs.SnapshotFileMissingError, match="metadata is missing"):
        load_sillim_walking_graph_snapshot_first(
            snapshot_path=graph,
            metadata_path=tmp_path / "absent.json",
            overpass_loader=overpass,
        )
    assert overpass.calls == 0


def test_boundary_propagates_overpass_failure_when_both_absent(tmp_path: Path) -> None:
    overpass = _SpyLoader(exc=RuntimeError("overpass down"))
    with pytest.raises(RuntimeError, match="overpass down"):
        load_sillim_walking_graph_snapshot_first(
            snapshot_path=tmp_path / "absent.graphml",
            metadata_path=tmp_path / "absent.json",
            overpass_loader=overpass,
        )


def test_boundary_default_overpass_resolves_at_call_time(tmp_path: Path, monkeypatch) -> None:
    """The default overpass_loader is None and resolved at call time, so monkeypatching the
    module attribute reaches the fallback (the definition-time-binding bug is fixed)."""
    spy = _SpyLoader(result=rs.build_sample_graph())
    monkeypatch.setattr(route_engine, "load_raw_sillim_walking_graph", spy)
    loaded = load_sillim_walking_graph_snapshot_first(
        snapshot_path=tmp_path / "absent.graphml", metadata_path=tmp_path / "absent.json"
    )
    assert loaded.graph.number_of_nodes() == 6
    assert spy.calls == 1


def test_boundary_does_not_fall_back_on_checksum_mismatch(tmp_path: Path) -> None:
    graph, meta = _copy_sample(tmp_path)
    graph.write_bytes(graph.read_bytes() + b"<!-- tampered -->")
    overpass = _SpyLoader(exc=AssertionError("no fallback on a corrupt snapshot"))
    with pytest.raises(rs.SnapshotChecksumMismatchError):
        load_sillim_walking_graph_snapshot_first(
            snapshot_path=graph, metadata_path=meta, overpass_loader=overpass
        )
    assert overpass.calls == 0


def test_boundary_does_not_fall_back_on_schema_mismatch(tmp_path: Path) -> None:
    graph, meta = _copy_sample(tmp_path)
    _reseal(graph, meta, schema_version=999)
    overpass = _SpyLoader(exc=AssertionError("no fallback on a corrupt snapshot"))
    with pytest.raises(rs.SnapshotSchemaMismatchError):
        load_sillim_walking_graph_snapshot_first(
            snapshot_path=graph, metadata_path=meta, overpass_loader=overpass
        )
    assert overpass.calls == 0


# ── default prepare() boundary: same contract + provenance preserved ──────────────────────────


def test_prepare_default_path_uses_snapshot_first(monkeypatch: pytest.MonkeyPatch) -> None:
    """The engine's default prepare path must resolve through the snapshot-first boundary."""
    monkeypatch.setattr(rs, "SNAPSHOT_PATH", rs.SAMPLE_SNAPSHOT_PATH)
    monkeypatch.setattr(rs, "SNAPSHOT_METADATA_PATH", rs.SAMPLE_SNAPSHOT_METADATA_PATH)

    def no_overpass() -> nx.MultiDiGraph:
        raise AssertionError("default prepare must load the snapshot, not Overpass")

    monkeypatch.setattr(route_engine, "load_raw_sillim_walking_graph", no_overpass)
    engine = prepare_sillim_safe_route_engine(_grade_all_r0)  # no explicit graph_loader
    result = engine.find_route(
        origin_node=1000001,
        candidates=[ShelterRouteCandidate(shelter_id="a", node_id=1000004)],
        walking_speed_mps=1.4,
    )
    assert result.status is RouteStatus.FOUND


def test_prepare_default_path_preserves_provenance(monkeypatch: pytest.MonkeyPatch) -> None:
    """All five provenance fields survive the default prepare() boundary via the accessor."""
    monkeypatch.setattr(rs, "SNAPSHOT_PATH", rs.SAMPLE_SNAPSHOT_PATH)
    monkeypatch.setattr(rs, "SNAPSHOT_METADATA_PATH", rs.SAMPLE_SNAPSHOT_METADATA_PATH)

    engine = prepare_sillim_safe_route_engine(_grade_all_r0)  # default snapshot-first loader
    identity = engine.snapshot_identity
    expected = _load_sample().identity
    assert identity is not None
    assert identity.snapshot_id == expected.snapshot_id
    assert identity.source == expected.source
    assert identity.source_kind == rs.SOURCE_KIND_SYNTHETIC
    assert identity.attribution == expected.attribution
    assert identity.is_synthetic is True


def test_prepare_overpass_fallback_has_no_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When both snapshot files are absent, prepare() falls back to Overpass and identity is None."""
    monkeypatch.setattr(rs, "SNAPSHOT_PATH", tmp_path / "absent.graphml")
    monkeypatch.setattr(rs, "SNAPSHOT_METADATA_PATH", tmp_path / "absent.json")
    monkeypatch.setattr(
        route_engine, "load_raw_sillim_walking_graph", lambda: rs.build_sample_graph()
    )
    engine = prepare_sillim_safe_route_engine(_grade_all_r0)
    assert engine.snapshot_identity is None


def test_prepare_with_bare_graph_loader_is_backward_compatible() -> None:
    """A legacy loader returning a bare graph (PR #220 contract) still works; identity is None."""
    loaded = _load_sample()
    engine = prepare_sillim_safe_route_engine(_grade_all_r0, graph_loader=lambda: loaded.graph)
    assert engine.snapshot_identity is None
    result = engine.find_route(
        origin_node=1000001,
        candidates=[ShelterRouteCandidate(shelter_id="a", node_id=1000004)],
        walking_speed_mps=1.4,
    )
    assert result.status is RouteStatus.FOUND


# ── route engine integration + determinism ───────────────────────────────────────────────────


def test_sample_graph_feeds_route_engine() -> None:
    loaded = _load_sample()
    engine = prepare_sillim_safe_route_engine(_grade_all_r0, graph_loader=lambda: loaded.graph)
    result = engine.find_route(
        origin_node=1000001,
        candidates=[ShelterRouteCandidate(shelter_id="a", node_id=1000004)],
        walking_speed_mps=1.4,
    )
    assert result.status is RouteStatus.FOUND
    assert result.selected_shelter_id == "a"
    assert result.distance_m is not None and result.distance_m > 0
    assert result.node_coordinates[0].lat == 37.4840
    assert result.node_coordinates[0].lng == 126.9290


def test_same_fixture_yields_the_same_route_twice() -> None:
    candidate = ShelterRouteCandidate(shelter_id="a", node_id=1000004)

    def route_once() -> object:
        graph = rs.load_sillim_snapshot_graph(
            snapshot_path=rs.SAMPLE_SNAPSHOT_PATH, metadata_path=rs.SAMPLE_SNAPSHOT_METADATA_PATH
        )
        engine = prepare_sillim_safe_route_engine(_grade_all_r0, graph_loader=lambda: graph)
        return engine.find_route(origin_node=1000001, candidates=[candidate], walking_speed_mps=1.4)

    assert route_once() == route_once()


def test_snapshot_graph_is_raw_without_risk_grade() -> None:
    graph = rs.load_sillim_snapshot_graph(
        snapshot_path=rs.SAMPLE_SNAPSHOT_PATH, metadata_path=rs.SAMPLE_SNAPSHOT_METADATA_PATH
    )
    assert all("risk_grade" not in data for _u, _v, data in graph.edges(data=True))
