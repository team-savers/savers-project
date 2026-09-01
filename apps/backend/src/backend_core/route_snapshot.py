"""Deterministic GraphML snapshot loader for the Sillim-dong walking graph (issue #224).

The route engine (ADR-0017) needs a raw OSM walking graph, but pulling it from Overpass at
startup couples every route to network weather. This module loads a pre-generated GraphML
snapshot shipped as a package-data fixture, so a valid snapshot lets the engine be prepared
with no network call at all. The snapshot-first boundary that chooses snapshot-vs-Overpass
lives in ``route_engine`` (this module never imports it, keeping the dependency one-way).

Two seams, deliberately split:

- **Loading is base-only.** It uses NetworkX's ``read_graphml`` (a core runtime dependency),
  never OSMnx, so the lean backend image and default CI can load a snapshot without the geo
  extra. Save and load share one structural contract (:func:`_validate_graph_structure`), so
  routing-critical node/edge numbers are validated finite on both sides and a writer-accepted
  snapshot is always immediately loadable.
- **Generation is dev-only.** ``save_snapshot_from_osm`` imports OSMnx **when called** (not at
  module import), so importing this module never needs the geo extra; only regenerating a real
  extract does. ``build_sample_graph`` produces the committed *synthetic* test fixture with
  NetworkX alone.

A corrupt, absent, oversized, or schema-mismatched snapshot is a distinct explicit error in
the :class:`RouteSnapshotError` hierarchy, never a silently-empty or partial graph, and never
a silent Overpass fallback (only an *absent* file falls back; that decision is the engine's).
The sidecar metadata carries a sha256 over the GraphML bytes, the exact node/edge counts, and a
``graph_kind`` marker (GraphML cannot preserve the Python graph class — a MultiDiGraph with no
parallel edges reads back as a DiGraph — so the marker declares it and the loader reads on its
strength). Non-scalar edge attributes such as a real OSMnx ``osmid=[101, 202]`` are JSON-encoded
by the writer and JSON-decoded by the loader — but only for the exact ``(scope, key)`` pairs the
metadata ``encoded_attrs`` manifest records, so a genuine user string that merely looks encoded is
never touched (no ``eval``/``exec``/``pickle`` — decoding is ``json.loads`` only). Both files are
read once through a single bounded handle, so the size check, checksum, and parse all see the same
bytes (no TOCTOU).
Any mismatch fails loudly. The loader returns a stable :class:`SnapshotIdentity` — carrying
``source_kind`` (``"osm"`` vs ``"synthetic"``) and attribution — so a downstream SafetyReceipt
can cite exactly which graph produced a route and never mistake the demo fixture for real OSM.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import xml.etree.ElementTree as ET
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import networkx as nx

_FIXTURE_DIR = Path(__file__).parent / "fixtures"

# Operational default: a real OSM extract. It is intentionally NOT committed — until it is
# generated (dev-only, needs the geo extra and network), this path is absent and the engine's
# snapshot-first boundary falls back to Overpass. The synthetic sample below is test-only and
# must never stand in for it.
SNAPSHOT_PATH = _FIXTURE_DIR / "sillim_walk.graphml"
SNAPSHOT_METADATA_PATH = _FIXTURE_DIR / "sillim_walk.metadata.json"

# Synthetic sample: committed for tests and for exercising the loader/route-engine wiring. Its
# metadata marks ``source_kind: "synthetic"`` so nothing can read it as real OSM data.
SAMPLE_SNAPSHOT_PATH = _FIXTURE_DIR / "sillim_walk.sample.graphml"
SAMPLE_SNAPSHOT_METADATA_PATH = _FIXTURE_DIR / "sillim_walk.sample.metadata.json"

# Bump when the on-disk shape changes in a way older loaders must reject. The loader accepts
# exactly this version and refuses anything else rather than guessing.
# v2 (issue #224, Codex 2nd audit): added the required ``graph_kind`` marker (GraphML cannot carry
# the Python graph type reliably — a no-parallel MultiDiGraph reads back as a DiGraph — so the
# marker declares it) and JSON-normalized non-scalar attributes (e.g. list ``osmid``).
SNAPSHOT_SCHEMA_VERSION = 2

# GraphML round-trips lose the Python graph class: a MultiDiGraph with no parallel edges is written
# and read back as a plain DiGraph. So the on-disk graph type is declared in metadata and the loader
# reads the GraphML as a multigraph on the strength of this marker (then still checks it is directed).
GRAPH_KIND_MULTIDIGRAPH = "MultiDiGraph"

# Encoding manifest scopes. GraphML's own attribute-type inference is *lossy* — a key holding both
# ``7`` and ``"7"`` collapses to one type, and ``1``/``1.5`` even makes the pair unloadable. So the
# writer never trusts that inference: a key is JSON-encoded whenever its values are not a single
# GraphML-native scalar type (see _normalize_and_encode). An encoded value is stored in the GraphML
# under a *reserved-prefixed* key name, so the GraphML itself declares which keys are encoded — the
# metadata ``encoded_attrs`` manifest is a redundant copy the loader cross-checks for exact equality
# against the observed reserved keys. A genuine user string that merely *looks* like JSON lives under
# its normal (non-reserved) key and is never decoded. Decoding is ``json.loads`` only (no
# ``eval``/``exec``/``pickle``), so a hostile payload can be malformed JSON, never code.
_ENCODING_SCOPES = ("graph", "node", "edge")
_ALLOWED_ENCODING_SCOPES = frozenset(_ENCODING_SCOPES)

# Reserved GraphML attribute-name prefix marking a JSON-encoded value. It uses ``::`` which does not
# occur in the OSM tag keys this loader handles; a user attribute whose name starts with it is
# rejected at the write boundary. The prefix never reaches the loaded graph — the loader strips it
# back to the original key name after decoding. This is an integrity/round-trip device, not a
# security boundary.
_RESERVED_ATTR_PREFIX = "savers::enc::"

# Max list-nesting depth accepted for an attribute value. Small and explicit: it bounds pathological
# / self-referential containers so a cycle surfaces as a typed SnapshotSerializationError instead of
# a raw RecursionError. Real OSM attributes are flat lists, so this is far above any legitimate need.
_MAX_ATTR_NESTING_DEPTH = 32

# GraphML-native scalar types (a homogeneous key of one of these is written as-is). ``bool`` is a
# subclass of ``int`` but is treated as a DISTINCT type by _scalar_type_tag so ``True``/``1`` never
# collapse together.
_GRAPHML_NATIVE_SCALARS = (str, bool, int, float)
_NATIVE_SCALAR_TAGS = frozenset({"bool", "int", "float", "str"})

# generated_at is validated as a timezone-aware ISO 8601 instant and rejected if it is in the
# future. This small skew tolerates a snapshot generated on a host whose clock is marginally ahead
# of the loader's; it is intentionally tiny so an obviously-wrong value (e.g. year 2027) is still
# rejected. Rationale recorded in the fixtures README.
_GENERATED_AT_MAX_SKEW = timedelta(minutes=5)

# Reject before parsing anything larger. A single 행정동 walking graph is small (the synthetic
# sample is a few KB; a real Sillim-dong OSMnx walk extract is well under a megabyte), so this
# generous 25 MiB ceiling sits far below GitHub's 50 MiB warning / 100 MiB hard limit (no Git
# LFS needed) yet still caps a corrupt or hostile file before it reaches the XML parser.
MAX_SNAPSHOT_BYTES = 25 * 1024 * 1024

# The metadata sidecar is a small flat JSON object (~15 scalar fields; the real sidecar is well
# under 2 KiB). This 64 KiB ceiling is its own explicit constant — orders of magnitude above any
# legitimate sidecar, yet it caps a corrupt or hostile file *before* json.loads reads the whole
# thing into memory. It is deliberately far smaller than MAX_SNAPSHOT_BYTES: the two files have
# very different legitimate sizes, so they get separate limits and separate errors.
MAX_SNAPSHOT_METADATA_BYTES = 64 * 1024

SOURCE_KIND_OSM = "osm"
SOURCE_KIND_SYNTHETIC = "synthetic"

# The only two provenance kinds the loader accepts; any other string in metadata is rejected so
# an arbitrary/typo'd source_kind can never pass through to a SnapshotIdentity and mislead a
# downstream SafetyReceipt about whether a route came from real OSM or the synthetic fixture.
_ALLOWED_SOURCE_KINDS = frozenset({SOURCE_KIND_OSM, SOURCE_KIND_SYNTHETIC})

# OSMnx-standard numeric attributes coerced to finite float on load (see module docstring).
_NODE_FLOAT_ATTRS = ("x", "y")
_EDGE_FLOAT_ATTRS = ("length",)

# Metadata fields the loader requires, with the JSON type each must have.
_REQUIRED_METADATA: dict[str, type] = {
    "schema_version": int,
    "graph_kind": str,
    "encoded_attrs": dict,
    "generated_at": str,
    "source": str,
    "source_kind": str,
    "source_license": str,
    "source_license_url": str,
    "attribution": str,
    "place": str,
    "network_type": str,
    "simplify": bool,
    "osmnx_version": str,
    "node_count": int,
    "edge_count": int,
    "graph_sha256": str,
}


class RouteSnapshotError(RuntimeError):
    """Base: the configured GraphML snapshot cannot be trusted as a route graph."""


class SnapshotFileMissingError(RouteSnapshotError):
    """The GraphML file or its metadata sidecar is absent."""


class SnapshotTooLargeError(RouteSnapshotError):
    """The GraphML file exceeds the size ceiling; rejected before parsing."""


class SnapshotChecksumMismatchError(RouteSnapshotError):
    """The GraphML bytes do not match the sha256 recorded in metadata."""


class SnapshotSchemaMismatchError(RouteSnapshotError):
    """The metadata is unreadable/malformed, a required field is missing or mistyped, the
    GraphML cannot be parsed, or the loaded graph fails structural validation."""


class SnapshotSerializationError(RouteSnapshotError):
    """A graph or its metadata cannot be serialized to a loadable snapshot at the write boundary:
    an unsupported attribute type (``bytes``, ``set``, ``dict``, ``tuple``, numpy array, arbitrary
    object, or a list containing any of these), a non-finite float (NaN/Infinity), a container
    nested past :data:`_MAX_ATTR_NESTING_DEPTH` (including a self-referential cycle), a user
    attribute name colliding with the reserved prefix, a metadata field that would fail the loader's
    own contract, or a ``NetworkXError``/``ValueError``/``TypeError`` from ``nx.write_graphml`` or
    ``json`` serialization. Raised *before* any file is written, so a raw library error never
    escapes the boundary and a failed save leaves no partial pair; a wrapping cause is chained with
    ``from`` while a direct preflight rejection carries none."""


@dataclass(frozen=True)
class SnapshotIdentity:
    """Stable identity of a loaded snapshot, so a downstream SafetyReceipt can cite exactly
    which graph produced a route — and never mistake the synthetic demo for real OSM."""

    schema_version: int
    generated_at: str
    place: str
    network_type: str
    graph_sha256: str
    node_count: int
    edge_count: int
    source: str
    source_kind: str
    attribution: str

    @property
    def is_synthetic(self) -> bool:
        return self.source_kind != SOURCE_KIND_OSM

    @property
    def snapshot_id(self) -> str:
        """Short, stable identifier: schema version, source kind, then graph digest prefix.

        The ``source_kind`` segment keeps a synthetic fixture legible at a glance
        (``sillim-walk-v2-synthetic-...`` vs ``sillim-walk-v2-osm-...``); the version segment is
        the current ``schema_version`` (2), so the committed sample reads ``sillim-walk-v2-synthetic-``
        followed by the first 12 hex of its graph sha256.
        """
        return f"sillim-walk-v{self.schema_version}-{self.source_kind}-{self.graph_sha256[:12]}"


@dataclass(frozen=True)
class LoadedSnapshot:
    graph: nx.MultiDiGraph
    identity: SnapshotIdentity


def _read_bounded(path: Path, max_bytes: int, what: str) -> bytes:
    """Read at most ``max_bytes + 1`` bytes from a single open handle and reject if that overruns.

    This closes the TOCTOU gap of ``stat()`` then a separate full read: the exact bytes the size
    check saw are the bytes returned, so the caller checksums and parses *those* rather than
    re-opening the path (which a racing writer could have changed). Reading one extra byte lets us
    distinguish "exactly at the ceiling" (allowed) from "over it" (rejected) without a size call.
    """
    try:
        with path.open("rb") as handle:
            data = handle.read(max_bytes + 1)
    except FileNotFoundError as exc:
        raise SnapshotFileMissingError(f"route snapshot {what} is missing: {path.name}") from exc
    except OSError as exc:
        raise SnapshotSchemaMismatchError(f"route snapshot {what} could not be read") from exc
    if len(data) > max_bytes:
        raise SnapshotTooLargeError(f"route snapshot {what} exceeds the {max_bytes}-byte ceiling")
    return data


def load_sillim_snapshot(
    *,
    snapshot_path: Path | None = None,
    metadata_path: Path | None = None,
    max_bytes: int = MAX_SNAPSHOT_BYTES,
    max_metadata_bytes: int = MAX_SNAPSHOT_METADATA_BYTES,
) -> LoadedSnapshot:
    """Load the GraphML snapshot with no network call, verifying integrity first.

    Order is deliberate: absence, then metadata (bounded read → object/fields/schema/graph_kind/
    generated_at), then the GraphML (bounded read → size), then checksum, then graph structure —
    each a distinct error so an operator reading the logs knows exactly what to fix. Both files are
    read once through a single handle each and the size check, checksum, and parse all operate on
    those same in-memory bytes (no re-open, no TOCTOU). The GraphML and its sidecar have separate
    size ceilings and separately identifiable :class:`SnapshotTooLargeError` messages. Nothing here
    imports OSMnx; loading works in the base backend environment. Every failure raises a
    :class:`RouteSnapshotError`; the caller never silently gets an empty or partial graph.
    """
    snapshot_path = snapshot_path or SNAPSHOT_PATH
    metadata_path = metadata_path or SNAPSHOT_METADATA_PATH

    if not snapshot_path.is_file():
        raise SnapshotFileMissingError(f"route snapshot GraphML is missing: {snapshot_path.name}")
    if not metadata_path.is_file():
        raise SnapshotFileMissingError(f"route snapshot metadata is missing: {metadata_path.name}")

    metadata = _load_metadata(metadata_path, max_metadata_bytes)

    graph_bytes = _read_bounded(snapshot_path, max_bytes, "GraphML")
    actual_sha = hashlib.sha256(graph_bytes).hexdigest()
    if metadata["graph_sha256"] != actual_sha:
        raise SnapshotChecksumMismatchError("route snapshot GraphML sha256 does not match metadata")

    graph = _read_graph(
        graph_bytes, metadata["node_count"], metadata["edge_count"], metadata["encoded_attrs"]
    )
    identity = SnapshotIdentity(
        schema_version=SNAPSHOT_SCHEMA_VERSION,
        generated_at=metadata["generated_at"],
        place=metadata["place"],
        network_type=metadata["network_type"],
        graph_sha256=actual_sha,
        node_count=metadata["node_count"],
        edge_count=metadata["edge_count"],
        source=metadata["source"],
        source_kind=metadata["source_kind"],
        attribution=metadata["attribution"],
    )
    return LoadedSnapshot(graph=graph, identity=identity)


def load_sillim_snapshot_graph(
    *,
    snapshot_path: Path | None = None,
    metadata_path: Path | None = None,
) -> nx.MultiDiGraph:
    """Snapshot graph only — used by the engine's snapshot-first boundary.

    Returns the raw graph (no ``risk_grade``); the annotator adds grades downstream, exactly
    as with the Overpass loader.
    """
    return load_sillim_snapshot(snapshot_path=snapshot_path, metadata_path=metadata_path).graph


def _load_metadata(
    metadata_path: Path, max_bytes: int = MAX_SNAPSHOT_METADATA_BYTES
) -> dict[str, Any]:
    """Parse and validate the sidecar from a single bounded read.

    The file is read once through one handle (at most ``max_bytes + 1`` bytes); an overrun is a
    :class:`SnapshotTooLargeError` raised *before* any UTF-8 decode or JSON parse, and the exact
    bytes the size check saw are the bytes decoded and parsed (no re-open). Everything else wrong
    — invalid UTF-8, unparseable JSON, non-object top level, a missing/mistyped required field, an
    out-of-set ``source_kind`` or ``graph_kind``, a bad ``generated_at``, or a wrong
    ``schema_version`` — is a :class:`SnapshotSchemaMismatchError` with the cause chained.
    """
    raw_bytes = _read_bounded(metadata_path, max_bytes, "metadata")
    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SnapshotSchemaMismatchError("route snapshot metadata is not valid UTF-8") from exc
    try:
        raw = json.loads(text)
    except ValueError as exc:
        raise SnapshotSchemaMismatchError("route snapshot metadata is not readable JSON") from exc

    if not isinstance(raw, dict):
        raise SnapshotSchemaMismatchError("route snapshot metadata top level is not a JSON object")

    _validate_metadata_fields(raw, error_cls=SnapshotSchemaMismatchError)
    return raw


def _validate_metadata_fields(raw: dict[str, Any], *, error_cls: type[RouteSnapshotError]) -> None:
    """Validate the metadata field contract, raising ``error_cls`` on any violation.

    The loader passes :class:`SnapshotSchemaMismatchError`; the writer passes
    :class:`SnapshotSerializationError` so it rejects would-be-unloadable metadata *before* writing.
    Every raise is a direct rejection (no fabricated cause), except ``generated_at`` parse failures
    which chain their real cause."""
    for key, expected in _REQUIRED_METADATA.items():
        if key not in raw:
            raise error_cls(f"route snapshot metadata missing field {key!r}")
        value = raw[key]
        # bool is a subclass of int, so an int field must reject True/False explicitly.
        if expected is int and (not isinstance(value, int) or isinstance(value, bool)):
            raise error_cls(f"route snapshot metadata {key!r} must be an integer")
        if expected is not int and not isinstance(value, expected):
            raise error_cls(f"route snapshot metadata {key!r} must be {expected.__name__}")

    if raw["graph_kind"] != GRAPH_KIND_MULTIDIGRAPH:
        raise error_cls(
            f"route snapshot metadata graph_kind {raw['graph_kind']!r} is not the required "
            f"{GRAPH_KIND_MULTIDIGRAPH!r}"
        )

    _validate_manifest(raw["encoded_attrs"], error_cls=error_cls)

    if raw["source_kind"] not in _ALLOWED_SOURCE_KINDS:
        raise error_cls(
            f"route snapshot metadata source_kind {raw['source_kind']!r} is not one of "
            f"{sorted(_ALLOWED_SOURCE_KINDS)}"
        )

    _validate_generated_at(raw["generated_at"], error_cls=error_cls)

    if raw["schema_version"] != SNAPSHOT_SCHEMA_VERSION:
        raise error_cls(
            f"route snapshot schema version {raw['schema_version']!r} is not the expected "
            f"{SNAPSHOT_SCHEMA_VERSION}"
        )


def _validate_generated_at(value: str, *, error_cls: type[RouteSnapshotError]) -> None:
    """``generated_at`` must be a timezone-aware ISO 8601 instant, normalizable to UTC and not in
    the future (beyond a tiny skew). A bad format, a naive (tz-less) value, or a future timestamp
    raises ``error_cls``; parse failures keep their cause via ``from exc``."""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise error_cls(
            f"route snapshot generated_at {value!r} is not an ISO 8601 datetime"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise error_cls(f"route snapshot generated_at {value!r} must be timezone-aware")
    generated_utc = parsed.astimezone(UTC)
    if generated_utc > datetime.now(UTC) + _GENERATED_AT_MAX_SKEW:
        raise error_cls(f"route snapshot generated_at {value!r} is in the future")


def _validate_manifest(manifest: dict[str, Any], *, error_cls: type[RouteSnapshotError]) -> None:
    """Validate the ``encoded_attrs`` manifest: it must contain **exactly** the three scopes
    ``graph``/``node``/``edge``, each a list of unique strings in sorted canonical order. A missing
    or unknown scope, a non-string key, a duplicate, or a non-canonical (unsorted) list raises
    ``error_cls``. The keys are cross-checked against the GraphML's own reserved-prefixed attributes
    later (see :func:`_apply_and_verify_manifest`)."""
    if set(manifest) != _ALLOWED_ENCODING_SCOPES:
        raise error_cls(
            f"route snapshot encoded_attrs must contain exactly the scopes "
            f"{sorted(_ALLOWED_ENCODING_SCOPES)}, got {sorted(manifest)}"
        )
    for scope in _ENCODING_SCOPES:
        keys = manifest[scope]
        if not isinstance(keys, list) or not all(isinstance(k, str) for k in keys):
            raise error_cls(
                f"route snapshot encoded_attrs[{scope!r}] must be a list of string keys"
            )
        if len(keys) != len(set(keys)):
            raise error_cls(f"route snapshot encoded_attrs[{scope!r}] has duplicate keys")
        if keys != sorted(keys):
            raise error_cls(
                f"route snapshot encoded_attrs[{scope!r}] is not in sorted canonical order"
            )


def _require_finite_number(
    value: object, where: str, *, error_cls: type[RouteSnapshotError]
) -> None:
    """A routing-critical value must be a real (non-bool) finite number. bool is excluded even
    though it subclasses int; NaN/Infinity are rejected."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise error_cls(f"route snapshot {where} is not a number")
    if not math.isfinite(value):
        raise error_cls(f"route snapshot {where} is not finite")


def _validate_graph_structure(
    graph: nx.MultiDiGraph,
    *,
    error_cls: type[RouteSnapshotError],
    expected_node_count: int | None = None,
    expected_edge_count: int | None = None,
) -> None:
    """The single structural contract shared by save and load, so a writer-accepted snapshot is
    always immediately loadable.

    Checks: exact :class:`nx.MultiDiGraph`; a non-empty ``str`` ``crs``; at least one node and one
    edge; every node id an integer (not ``bool``); every edge key an integer (not ``bool``); every
    node carries finite numeric ``x``/``y``; every edge carries a finite numeric ``length``; and,
    when ``expected_*_count`` is given (load), that the counts match. The writer passes
    ``error_cls=SnapshotSerializationError`` and runs this on a *copy* (the caller's graph is never
    mutated); the loader passes ``error_cls=SnapshotSchemaMismatchError``. The same invariants are
    not duplicated on either side."""
    if not isinstance(graph, nx.MultiDiGraph):
        raise error_cls(
            "route snapshot is not a directed multigraph (networkx.MultiDiGraph); got "
            f"{type(graph).__name__}"
        )
    crs = graph.graph.get("crs")
    if not isinstance(crs, str) or not crs:
        raise error_cls("route snapshot graph is missing a valid string 'crs' attribute")
    if graph.number_of_nodes() < 1:
        raise error_cls("route snapshot has no nodes")
    if graph.number_of_edges() < 1:
        raise error_cls("route snapshot has no edges")
    if expected_node_count is not None and graph.number_of_nodes() != expected_node_count:
        raise error_cls(
            f"route snapshot node count {graph.number_of_nodes()} does not match metadata "
            f"{expected_node_count}"
        )
    if expected_edge_count is not None and graph.number_of_edges() != expected_edge_count:
        raise error_cls(
            f"route snapshot edge count {graph.number_of_edges()} does not match metadata "
            f"{expected_edge_count}"
        )
    for node_id, data in graph.nodes(data=True):
        if not isinstance(node_id, int) or isinstance(node_id, bool):
            raise error_cls(f"route snapshot node id {node_id!r} is not an integer")
        for attr in _NODE_FLOAT_ATTRS:
            if attr not in data:
                raise error_cls(f"route snapshot node {node_id!r} is missing {attr}")
            _require_finite_number(data[attr], f"node {node_id!r} {attr}", error_cls=error_cls)
    for start, end, key, data in graph.edges(keys=True, data=True):
        if not isinstance(key, int) or isinstance(key, bool):
            raise error_cls(f"route snapshot edge {(start, end, key)!r} has a non-integer key")
        for attr in _EDGE_FLOAT_ATTRS:
            if attr not in data:
                raise error_cls(f"route snapshot edge {(start, end, key)!r} is missing {attr}")
            _require_finite_number(
                data[attr], f"edge {(start, end, key)!r} {attr}", error_cls=error_cls
            )


def _coerce_routing_floats(graph: nx.MultiDiGraph) -> None:
    """On the writable copy only: normalize routing attrs (node ``x``/``y``, edge ``length``) to
    ``float`` so a key mixing ``int`` and ``float`` values stays a single GraphML type — otherwise
    GraphML type inference would either lose the type or (int-then-float) produce an unloadable
    file. Coordinates/lengths are real-valued, so int->float is value-preserving. Runs after
    :func:`_validate_graph_structure` has confirmed they are finite numbers."""
    for _n, data in graph.nodes(data=True):
        for attr in _NODE_FLOAT_ATTRS:
            data[attr] = float(data[attr])
    for _u, _v, _k, data in graph.edges(keys=True, data=True):
        for attr in _EDGE_FLOAT_ATTRS:
            data[attr] = float(data[attr])


def _reject_json_constant(token: str) -> float:
    """``json.loads`` ``parse_constant`` hook: refuse ``NaN``/``Infinity``/``-Infinity`` tokens
    outright rather than materializing a non-finite float."""
    raise ValueError(f"non-finite JSON constant {token!r} is not allowed")


def _decode_reserved_payload(raw: object, where: str) -> object:
    """Decode one reserved (JSON-encoded) attribute value and re-validate it against the *same*
    value contract the writer enforces, but at load severity.

    ``json.loads`` uses ``parse_constant`` to reject ``NaN``/``Infinity``/``-Infinity`` tokens; a
    ``RecursionError`` from pathologically deep JSON is caught too. The parsed value is then run
    through :func:`_json_safe_value` with ``error_cls=SnapshotSchemaMismatchError`` so a decoded
    ``dict``, a ``1e309``-style overflow-to-infinity, or nesting past the depth limit is a schema
    error — never inserted raw into the graph. Malformed JSON chains its cause."""
    if not isinstance(raw, str):
        raise SnapshotSchemaMismatchError(f"route snapshot {where} encoded value is not a string")
    try:
        decoded = json.loads(raw, parse_constant=_reject_json_constant)
    except (ValueError, RecursionError) as exc:
        raise SnapshotSchemaMismatchError(
            f"route snapshot {where} has a malformed JSON-encoded value"
        ) from exc
    return _json_safe_value(decoded, where, error_cls=SnapshotSchemaMismatchError)


def _apply_and_verify_manifest(graph: nx.MultiDiGraph, manifest: dict[str, Any]) -> None:
    """Cross-check the metadata manifest against the GraphML's own reserved-prefixed keys, then
    decode — validating everything *before* mutating anything.

    Encoded values live in the GraphML under ``_RESERVED_ATTR_PREFIX + key`` names, so the GraphML
    itself declares which keys are encoded independently of the metadata. Per scope: the reserved
    base key must be non-empty; an entity must not carry both a native and a reserved value for the
    same base key (no dual representation — the native value is never overwritten); and the set of
    observed reserved base keys must **exactly equal** the metadata manifest. Each reserved payload
    is decoded and re-validated (see :func:`_decode_reserved_payload`). Only after every scope and
    entity passes is anything applied, so an error never leaves a partially-restored graph. No
    internal reserved marker remains on the returned graph; genuine user strings under normal keys
    are untouched. Any violation is a :class:`SnapshotSchemaMismatchError`."""
    scope_dicts: dict[str, list[dict[str, Any]]] = {
        "graph": [graph.graph],
        "node": [data for _n, data in graph.nodes(data=True)],
        "edge": [data for _u, _v, _k, data in graph.edges(keys=True, data=True)],
    }
    # Pass 1: validate + stage decoded values without mutating the graph.
    plan: list[tuple[dict[str, Any], str, str, object]] = []
    for scope, dicts in scope_dicts.items():
        observed: set[str] = set()
        for data in dicts:
            for reserved_key in [k for k in data if k.startswith(_RESERVED_ATTR_PREFIX)]:
                base = reserved_key[len(_RESERVED_ATTR_PREFIX) :]
                if not base:
                    raise SnapshotSchemaMismatchError(
                        f"route snapshot {scope} has a reserved key with an empty base name"
                    )
                if base in data:
                    raise SnapshotSchemaMismatchError(
                        f"route snapshot {scope} attribute {base!r} has both a native and an "
                        "encoded representation on one entity"
                    )
                observed.add(base)
                decoded = _decode_reserved_payload(
                    data[reserved_key], f"{scope} attribute {base!r}"
                )
                plan.append((data, reserved_key, base, decoded))
        declared = set(manifest[scope])
        if observed != declared:
            raise SnapshotSchemaMismatchError(
                f"route snapshot {scope} encoded keys {sorted(observed)} do not match metadata "
                f"encoded_attrs {sorted(declared)}"
            )
    # Pass 2: all validated — now apply.
    for data, reserved_key, base, decoded in plan:
        del data[reserved_key]
        data[base] = decoded


def _read_graph(
    graph_bytes: bytes,
    expected_node_count: int,
    expected_edge_count: int,
    manifest: dict[str, Any],
) -> nx.MultiDiGraph:
    """Parse the GraphML bytes with NetworkX only (no OSMnx) and validate the graph strictly.

    The metadata ``graph_kind`` marker (validated as ``MultiDiGraph`` before this runs) is the
    source of truth for the graph type, so the read uses ``force_multigraph=True``: GraphML cannot
    preserve the Python class, and a MultiDiGraph with no parallel edges would otherwise read back
    as a DiGraph and be wrongly rejected. Forcing a multigraph then checking :class:`nx.MultiDiGraph`
    accepts a real (possibly parallel-edge-free) MultiDiGraph while still rejecting an undirected
    graph (which forces to a MultiGraph, not a MultiDiGraph). Node ids and edge keys are coerced to
    ``int`` and re-checked. Attributes the ``manifest`` records are JSON-decoded back.

    Parse/conversion failures (malformed XML, non-integer node id / edge key, type conversion) are
    normalized to :class:`SnapshotSchemaMismatchError` with the cause chained; NetworkX's own
    ``ValueError``/``TypeError``/``ParseError`` are never surfaced raw. ``MemoryError`` (and
    ``KeyboardInterrupt``/``SystemExit``) propagate unchanged — they are not GraphML errors. The
    bytes are parsed from a :class:`io.BytesIO`, i.e. the same bytes the size check and checksum saw
    (no path re-open). After parsing, the manifest is cross-checked/decoded and then the *shared*
    structural contract (:func:`_validate_graph_structure`) is applied — the same one the writer ran
    before writing.
    """
    try:
        graph = nx.read_graphml(
            io.BytesIO(graph_bytes), node_type=int, edge_key_type=int, force_multigraph=True
        )
    except (MemoryError, KeyboardInterrupt, SystemExit):
        raise  # resource/control-flow signals are not GraphML schema errors
    except (ValueError, TypeError, nx.NetworkXError, ET.ParseError) as exc:
        raise SnapshotSchemaMismatchError("route snapshot GraphML could not be parsed") from exc

    # force_multigraph=True yields a MultiGraph/MultiDiGraph; narrow to a directed multigraph early
    # (undirected reads back as MultiGraph) so the rest operates on the concrete type.
    if not isinstance(graph, nx.MultiDiGraph):
        raise SnapshotSchemaMismatchError(
            "route snapshot is not a directed multigraph (networkx.MultiDiGraph); got "
            f"{type(graph).__name__}"
        )

    # Cross-check the manifest against the GraphML's reserved keys and restore encoded attributes,
    # then apply the shared structural contract that the writer also enforced.
    _apply_and_verify_manifest(graph, manifest)
    _validate_graph_structure(
        graph,
        error_cls=SnapshotSchemaMismatchError,
        expected_node_count=expected_node_count,
        expected_edge_count=expected_edge_count,
    )
    return graph


# ── Dev-only generation (never called at runtime) ──────────────────────────────────────────

# OSM's Open Database License terms for a stored extract. The synthetic sample fixture is not
# OSM data, so its attribution says so; a real extract generated by save_snapshot_from_osm
# carries the OSM attribution below.
OSM_ATTRIBUTION = "© OpenStreetMap contributors"
OSM_LICENSE = "ODbL 1.0"
OSM_LICENSE_URL = "https://opendatacommons.org/licenses/odbl/1-0/"
OSM_COPYRIGHT_URL = "https://www.openstreetmap.org/copyright"


def _scalar_type_tag(value: object) -> str:
    """Classify a normalized attribute value for heterogeneity detection. ``bool`` is reported as a
    DISTINCT tag from ``int`` so ``True``/``1`` never collapse together under GraphML type inference.
    (Order matters: ``bool`` is a subclass of ``int``.)"""
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if value is None:
        return "none"
    return "list"


def _normalize_numpy_scalar(
    value: object, where: str, *, error_cls: type[RouteSnapshotError]
) -> object:
    """Normalize a *real* numpy 0-d scalar to its Python equivalent; reject numpy arrays and numpy
    imposters.

    numpy is never imported at module load and never added as a core dependency: this only imports
    it lazily *when a value's own type module root is* ``numpy`` — otherwise the value passes through
    untouched (``.item()`` is never called on an arbitrary object). A value that claims a numpy type
    is confirmed with ``isinstance(value, numpy.generic)`` before ``.item()``; an imposter class
    (spoofed ``__module__``/``ndim``/``item``) or a numpy ``ndarray`` fails that check and raises. If
    the value claims numpy but numpy cannot be imported, that too is rejected (a real numpy scalar
    cannot exist without numpy)."""
    if type(value).__module__.split(".", 1)[0] != "numpy":
        return value
    try:
        import numpy as _np
    except ModuleNotFoundError as exc:
        raise error_cls(
            f"attribute at {where} claims a numpy type but numpy is not importable"
        ) from exc
    if isinstance(value, _np.generic):
        return value.item()  # genuine 0-d numpy scalar -> Python scalar
    raise error_cls(
        f"unsupported numpy value at {where} (only genuine 0-d numpy scalars are normalized)"
    )


def _json_safe_value(
    value: object,
    where: str,
    *,
    depth: int = 0,
    error_cls: type[RouteSnapshotError] = SnapshotSerializationError,
) -> object:
    """Validate/normalize one value to a JSON-safe, finite shape, else raise ``error_cls``.

    Shared by the writer (``error_cls=SnapshotSerializationError``, on raw attribute values) and the
    loader (``error_cls=SnapshotSchemaMismatchError``, on values decoded from reserved payloads), so
    both sides enforce the *same* value contract at their own severity.

    Supported: ``None``, ``bool``, ``int``, finite ``float``, ``str``, and ``list`` of these
    (recursively). Genuine numpy 0-d scalars are normalized via :func:`_normalize_numpy_scalar`.
    Every ``float`` (native, nested, or numpy-derived) must be finite — NaN/Infinity raise. A
    container nested past :data:`_MAX_ATTR_NESTING_DEPTH` (which a self-referential cycle reaches)
    raises before Python's own ``RecursionError``. Every other type — ``bytes``, ``set``, ``dict``,
    ``tuple`` (never silently coerced to a list), a numpy array/imposter, an arbitrary object, or a
    list containing any of these — raises ``error_cls``.
    """
    if depth > _MAX_ATTR_NESTING_DEPTH:
        raise error_cls(
            f"attribute at {where} nests deeper than {_MAX_ATTR_NESTING_DEPTH} levels "
            "(or is self-referential)"
        )
    value = _normalize_numpy_scalar(value, where, error_cls=error_cls)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise error_cls(f"non-finite float ({value!r}) at {where}")
        return value
    if isinstance(value, list):
        return [
            _json_safe_value(item, f"{where}[]", depth=depth + 1, error_cls=error_cls)
            for item in value
        ]
    raise error_cls(f"unsupported attribute type {type(value).__name__!r} at {where}")


def _normalize_and_encode(graph: nx.MultiDiGraph) -> dict[str, list[str]]:
    """In place: validate/normalize every graph/node/edge attribute, then JSON-encode the keys that
    need it, returning the deterministic ``encoded_attrs`` manifest.

    A key is encoded when its present values are **not a single GraphML-native scalar type** — either
    within its own scope (more than one type: ``int``+``str``, ``bool``+``int``, ``int``+``float``,
    …, or any ``list``, or any ``None``), **or** because the *same name* would be written as a native
    key of a *different* native type in another scope (see below). GraphML's own type inference is
    lossy and would collapse such a key (or make it unloadable), so *every* value of an encoded key
    (scalars included) becomes ``json.dumps(value, allow_nan=False)`` and is stored under a
    reserved-prefixed key name, making the GraphML self-describe which keys are encoded. A key absent
    on some elements is treated as absent, never as ``None``. Purely-homogeneous-native keys are left
    as-is and round-trip as their native GraphML type. A user attribute name colliding with the
    reserved prefix is rejected. Manifest key lists are sorted for deterministic output.

    **Cross-scope key-id collision (issue #224, Yopkigom review).** ``nx.write_graphml`` is called
    with ``named_key_ids=True``, so each ``<key>``'s id is the attribute name, and the NetworkX
    reader indexes ``<key>`` elements by **id alone** — it ignores ``for="node"``/``"edge"``/
    ``"graph"``. A name written as a *native* key of two different types in two scopes (e.g. node
    ``ref`` int, edge ``ref`` str) therefore emits two ``<key id="ref">`` with conflicting
    ``attr.type``; on load one silently overrides the other and that scope's values are reinterpreted
    under the wrong type (or the pair fails to parse). Per-scope heterogeneity detection cannot see
    this because each scope is individually homogeneous. So the decision is made across scopes: any
    name that would be a native key of more than one native type across scopes is force-encoded in
    **every** scope it appears in, giving it a single reserved (string-typed) ``<key>`` id that
    cannot collide. A name that is native as a *single* consistent type across scopes stays native
    and its serialization is unchanged (no needless encoding).
    """
    scopes: tuple[tuple[str, list[dict[str, Any]]], ...] = (
        ("graph", [graph.graph]),
        ("node", [data for _n, data in graph.nodes(data=True)]),
        ("edge", [data for _u, _v, _k, data in graph.edges(keys=True, data=True)]),
    )
    # Pass 1: validate/normalize every value in place and record the type tags each name takes,
    # per scope. The encode decision needs all scopes' tags first (see the cross-scope check below),
    # so encoding is deferred to pass 2.
    per_scope_tags: dict[str, dict[str, set[str]]] = {}
    for scope, dicts in scopes:
        tags_by_key: dict[str, set[str]] = {}
        for data in dicts:
            for key in list(data):
                # NetworkX allows non-string attribute keys, but GraphML keys must be strings.
                # Require an EXACT built-in ``str`` (``type(key) is str``), not merely a str
                # subclass: an ``isinstance`` check would pass a subclass and then run its
                # user-defined ``startswith``/``repr``/``str`` during the reserved-prefix check or
                # error formatting. Rejecting here — before any ``startswith`` or ``!r`` on the key,
                # and naming only the scope and the key's *type* — keeps the boundary from executing
                # untrusted key methods and surfaces a typed error instead of a raw exception.
                if type(key) is not str:
                    raise SnapshotSerializationError(
                        f"{scope} attribute key must be an exact built-in str, got a key of type "
                        f"{type(key).__name__!r}"
                    )
                if key.startswith(_RESERVED_ATTR_PREFIX):
                    raise SnapshotSerializationError(
                        f"{scope} attribute name {key!r} collides with the reserved prefix "
                        f"{_RESERVED_ATTR_PREFIX!r}"
                    )
                data[key] = _json_safe_value(data[key], f"{scope} attribute {key!r}")
                tags_by_key.setdefault(key, set()).add(_scalar_type_tag(data[key]))
        per_scope_tags[scope] = tags_by_key

    # A name is *native* in a scope when it is a single GraphML-native scalar type there; otherwise
    # it is already encoded under the reserved prefix (a different <key> id, so it never collides).
    # If a name is native as more than one distinct native type across scopes, its native <key> ids
    # would collide on load (see docstring) — force-encode it in every scope it appears in.
    cross_scope_conflicts: set[str] = set()
    all_names = {name for tags_by_key in per_scope_tags.values() for name in tags_by_key}
    for name in all_names:
        native_types: set[str] = set()
        for scope in _ENCODING_SCOPES:
            tags = per_scope_tags[scope].get(name)
            if tags is not None and len(tags) == 1:
                (only,) = tags
                if only in _NATIVE_SCALAR_TAGS:
                    native_types.add(only)
        if len(native_types) > 1:
            cross_scope_conflicts.add(name)

    # Pass 2: encode the qualifying names per scope (in-scope non-native/heterogeneous, or a
    # cross-scope native-type conflict) and build the deterministic manifest.
    manifest: dict[str, list[str]] = {}
    for scope, dicts in scopes:
        tags_by_key = per_scope_tags[scope]
        encode_keys = sorted(
            key
            for key, tags in tags_by_key.items()
            if len(tags) > 1
            or not tags.issubset(_NATIVE_SCALAR_TAGS)
            or key in cross_scope_conflicts
        )
        for data in dicts:
            for key in encode_keys:
                if key not in data:
                    continue
                try:
                    encoded = json.dumps(data[key], allow_nan=False)
                except (TypeError, ValueError) as exc:  # unreachable after normalization; defensive
                    raise SnapshotSerializationError(
                        f"{scope} attribute {key!r} could not be JSON-encoded"
                    ) from exc
                del data[key]
                data[_RESERVED_ATTR_PREFIX + key] = encoded
        manifest[scope] = encode_keys
    return manifest


def _atomic_write(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` via a sibling temp file + single-file atomic replace.

    Only the *individual* file's replace is atomic; this gives no cross-file (pair-level) atomicity.
    The temp file is always cleaned up (``finally``), including on the exception path."""
    tmp = path.with_name(f"{path.name}.tmp")
    try:
        tmp.write_bytes(data)
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def save_snapshot(
    graph: nx.MultiDiGraph,
    *,
    snapshot_path: Path,
    metadata_path: Path,
    place: str,
    network_type: str,
    simplify: bool,
    osmnx_version: str,
    source: str,
    source_kind: str,
    attribution: str,
    source_license: str,
    source_license_url: str,
    generated_at: str | None = None,
    drop_edge_attrs: tuple[str, ...] = (),
) -> SnapshotIdentity:
    """Write the GraphML and its metadata sidecar; sha256 is over the written GraphML bytes.

    Dev-only: run when regenerating a fixture. The runtime loader never writes. The input must be
    an actual :class:`nx.MultiDiGraph` — a ``DiGraph``/``Graph``/``MultiGraph`` is rejected with
    ``TypeError`` so the stored ``graph_kind`` marker can never lie about the graph type.

    **The caller's graph is never mutated:** all work happens on a ``deepcopy``. Any ``drop_edge_attrs``
    (e.g. ``("geometry",)`` for the OSM boundary) are removed on that copy only.

    **The writer never produces an unloadable pair.** On the copy, it runs the *same* structural
    contract the loader enforces (:func:`_validate_graph_structure`: exact MultiDiGraph, valid crs,
    ≥1 node/edge, integer node ids and edge keys, finite numeric x/y/length) before doing anything
    else; then it validates/normalizes attribute values (finite floats only; unsupported types and
    over-deep/cyclic containers rejected), JSON-encodes the non-native ones under reserved keys, and
    validates the metadata with the loader's own field contract — all *before* any file is written.
    Library errors from ``deepcopy``, ``json``, or ``nx.write_graphml`` (``NetworkXError``/
    ``ValueError``/``TypeError``) are normalized to :class:`SnapshotSerializationError` with the
    cause chained; a direct preflight rejection carries no fabricated cause. So the pair a
    successful save produces is immediately readable by :func:`load_sillim_snapshot`.

    **Atomicity is per file, not pair-level.** Each file is replaced atomically (temp + replace),
    GraphML first and the checksum-bearing metadata last. There is no cross-file transaction: a
    failure between the two replaces leaves the new GraphML with the old/absent metadata, which the
    loader rejects fail-closed (checksum mismatch, or ``SnapshotFileMissingError`` when no metadata
    existed) — never silent acceptance or wrong provenance. Re-running the save recovers a complete
    pair. This does not guarantee an existing pair survives an OS-level crash mid-write.

    Determinism is scoped: the same graph object with the same node/edge/attribute insertion order
    and the same ``generated_at`` yields byte-identical GraphML, metadata, and checksum. Two
    logically-equal graphs built in different insertion order are NOT guaranteed byte-identical (no
    canonicalization is performed). ``generated_at`` defaults to the real current UTC time. Keep
    ``*.graphml`` as binary in ``.gitattributes`` so the committed checksum survives autocrlf.
    """
    if not isinstance(graph, nx.MultiDiGraph):
        raise TypeError(
            f"save_snapshot requires a networkx.MultiDiGraph, got {type(graph).__name__}"
        )
    try:
        writable = deepcopy(graph)
    except (TypeError, ValueError, RecursionError) as exc:
        raise SnapshotSerializationError("route snapshot graph could not be copied") from exc
    if drop_edge_attrs:
        for _u, _v, _key, data in writable.edges(keys=True, data=True):
            for attr in drop_edge_attrs:
                data.pop(attr, None)

    # Same structural contract the loader enforces, so a writer-accepted graph is always loadable.
    _validate_graph_structure(writable, error_cls=SnapshotSerializationError)
    _coerce_routing_floats(writable)

    manifest = _normalize_and_encode(writable)

    buffer = io.BytesIO()
    try:
        nx.write_graphml(writable, buffer, named_key_ids=True)
    except (nx.NetworkXError, ValueError, TypeError) as exc:
        raise SnapshotSerializationError(
            "route snapshot GraphML could not be written from the given graph"
        ) from exc
    graph_bytes = buffer.getvalue()
    graph_sha256 = hashlib.sha256(graph_bytes).hexdigest()

    generated = generated_at or datetime.now(UTC).isoformat()
    metadata = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "graph_kind": GRAPH_KIND_MULTIDIGRAPH,
        "encoded_attrs": manifest,
        "generated_at": generated,
        "source": source,
        "source_kind": source_kind,
        "source_license": source_license,
        "source_license_url": source_license_url,
        "attribution": attribution,
        "place": place,
        "network_type": network_type,
        "simplify": simplify,
        "osmnx_version": osmnx_version,
        "node_count": writable.number_of_nodes(),
        "edge_count": writable.number_of_edges(),
        "graph_sha256": graph_sha256,
    }
    # Preflight the metadata with the loader's own contract so a bad param (non-str field, invalid
    # source_kind, bad generated_at, non-finite value) is rejected here, not silently written.
    _validate_metadata_fields(metadata, error_cls=SnapshotSerializationError)
    try:
        metadata_text = (
            json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            + "\n"
        )
    except (ValueError, TypeError) as exc:
        raise SnapshotSerializationError("route snapshot metadata could not be serialized") from exc

    # All validation is done; only now touch the disk, atomically, so an error above never leaves a
    # partial or corrupted pair.
    _atomic_write(snapshot_path, graph_bytes)
    _atomic_write(metadata_path, metadata_text.encode("utf-8"))

    return SnapshotIdentity(
        schema_version=SNAPSHOT_SCHEMA_VERSION,
        generated_at=generated,
        place=place,
        network_type=network_type,
        graph_sha256=graph_sha256,
        node_count=writable.number_of_nodes(),
        edge_count=writable.number_of_edges(),
        source=source,
        source_kind=source_kind,
        attribution=attribution,
    )


def save_snapshot_from_osm(
    *,
    place: str = "신림동, 관악구, 서울특별시, 대한민국",
    network_type: str = "walk",
    simplify: bool = True,
    snapshot_path: Path = SNAPSHOT_PATH,
    metadata_path: Path = SNAPSHOT_METADATA_PATH,
) -> SnapshotIdentity:
    """Download the real OSM extract and write the operational snapshot. Dev-only.

    OSMnx is imported here, at call time — importing this module needs no geo extra; only
    calling this function does. Needs network. Never called at runtime. Raises
    :class:`RouteSnapshotError` if OSMnx is unavailable.
    """
    try:
        import osmnx as ox
    except ModuleNotFoundError as exc:
        raise RouteSnapshotError(
            'OSMnx is unavailable; install the Backend "geo" extra to regenerate from OSM'
        ) from exc

    graph: nx.MultiDiGraph = ox.graph_from_place(
        place, network_type=network_type, simplify=simplify
    )
    # Do NOT mutate the graph OSMnx returned: save_snapshot deep-copies internally and drops the
    # shapely ``geometry`` edge attribute on that copy (``drop_edge_attrs``). geometry is non-scalar
    # and non-JSON-serializable, and routing needs only node x/y + edge length; the meaningful
    # list-valued OSMnx attributes (osmid, highway, name, …) are JSON-normalized and round-trip.
    return save_snapshot(
        graph,
        snapshot_path=snapshot_path,
        metadata_path=metadata_path,
        place=place,
        network_type=network_type,
        simplify=simplify,
        osmnx_version=getattr(ox, "__version__", "unknown"),
        source="OpenStreetMap via OSMnx graph_from_place",
        source_kind=SOURCE_KIND_OSM,
        attribution=OSM_ATTRIBUTION,
        source_license=OSM_LICENSE,
        source_license_url=OSM_LICENSE_URL,
        drop_edge_attrs=("geometry",),
    )


def build_sample_graph() -> nx.MultiDiGraph:
    """Deterministic synthetic Sillim-dong-shaped walking graph (NetworkX only, no network).

    Backs the committed *synthetic* test fixture — never the operational default. Its metadata
    is written with ``source_kind: "synthetic"``. Nodes carry ``x``/``y`` (lng/lat, EPSG:4326),
    edges carry ``length`` (metres) and ``osmid``; parallel edges exercise MultiDiGraph keys.
    No ``risk_grade`` — the annotator adds that downstream. Coordinates are a fabricated grid,
    not surveyed positions; treat this as demo topology, not real OSM geography.
    """
    graph: nx.MultiDiGraph = nx.MultiDiGraph(crs="EPSG:4326")
    nodes = {
        1000001: (126.9290, 37.4840),
        1000002: (126.9300, 37.4845),
        1000003: (126.9310, 37.4842),
        1000004: (126.9305, 37.4835),
        1000005: (126.9295, 37.4830),
        1000006: (126.9315, 37.4850),
    }
    for node_id, (lng, lat) in nodes.items():
        graph.add_node(node_id, x=lng, y=lat)

    # (u, v, length) — each is a two-way walking segment. `osmid` mirrors an OSM way id.
    segments = [
        (1000001, 1000002, 120.0),
        (1000002, 1000003, 100.0),
        (1000003, 1000004, 90.0),
        (1000002, 1000004, 150.0),
        (1000001, 1000005, 130.0),
        (1000005, 1000004, 110.0),
        (1000003, 1000006, 140.0),
    ]
    for osmid, (u, v, length) in enumerate(segments, start=1):
        graph.add_edge(u, v, length=length, osmid=osmid)
        graph.add_edge(v, u, length=length, osmid=osmid)

    # A parallel edge between 1000002 and 1000003 with a different length, so the engine's
    # minimum-weight parallel-edge selection is exercised through a snapshot round-trip.
    graph.add_edge(1000002, 1000003, length=105.0, osmid=100)
    graph.add_edge(1000003, 1000002, length=105.0, osmid=100)
    return graph
