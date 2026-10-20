"""The graph's `.kg/` store: deterministic read and write (RF-70, RF-71, RNF-08).

The store is a single `graph.json` that conforms to the input schema
(`kg schema`), so `kg validate .kg/graph.json` can check it. The order of nodes,
edges and keys is fixed: the same graph produces the same file byte for byte.
Format documented in `docs/store.md`.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Iterable
from functools import cache
from pathlib import Path
from typing import Any

import networkx as nx

from kg import __version__
from kg.schema import load_schema
from kg.schema.validation import Report, validate_bytes, validate_document

GRAPH_FILE = "graph.json"
# Markers of documents already validated, kept in the user's cache, not the store
VALIDATED_DIR = Path("kg") / "validated"
# Markers kept; the oldest are removed beyond this
VALIDATED_KEEP = 256
FORMAT_VERSION: str = load_schema()["properties"]["version"]["const"]

# Field order in the file: identity first, then content.
_NODE_FIELDS = ("type", "label", "description", "attrs", "provenance")
_EDGE_FIELDS = ("type", "attrs", "provenance")


class StoreError(Exception):
    """Store error; `path` is the affected path."""

    def __init__(self, message: str, path: Path) -> None:
        super().__init__(message)
        self.message = message
        self.path = path


class StoreExistsError(StoreError):
    """`kg init` on a path that already exists."""


class StoreNotFoundError(StoreError):
    """There is no store (or it lacks `graph.json`) at the given path."""


class StoreCorruptError(StoreError):
    """The store does not conform to the schema; `report` has the details."""

    def __init__(self, message: str, path: Path, report: Report) -> None:
        super().__init__(message, path)
        self.report = report


def graph_path(kg_dir: Path) -> Path:
    """Path of the graph file inside the store."""
    return kg_dir / GRAPH_FILE


def init_store(kg_dir: Path) -> Path:
    """Create the store with an empty graph and return the path of `graph.json`."""
    if kg_dir.exists():
        raise StoreExistsError(f"{kg_dir} already exists; nothing was changed", kg_dir)
    if not kg_dir.parent.is_dir():
        raise StoreNotFoundError(
            f"directory {kg_dir.parent} does not exist; cannot create the store", kg_dir
        )
    kg_dir.mkdir()
    return save_graph(nx.MultiDiGraph(), kg_dir)


def load_graph(kg_dir: Path) -> nx.MultiDiGraph:
    """Read the graph from the store, validating it against the schema.

    A document validated before (by `save_graph` or an earlier load) is not
    validated again: the cache keys it by its content, so any change to
    `graph.json` is validated in full.
    """
    path = graph_path(kg_dir)
    if not path.is_file():
        raise StoreNotFoundError(
            f"no store at {kg_dir}; create one with `kg init`", path
        )
    data = path.read_bytes()
    if not _is_validated(data):
        report = validate_bytes(data)
        if not report.ok:
            raise StoreCorruptError(
                f"{path} is not a valid store; check it with `kg validate {path}`",
                path,
                report,
            )
        _mark_validated(data)
    return document_to_graph(json.loads(data), path)


def save_graph(graph: nx.MultiDiGraph, kg_dir: Path) -> Path:
    """Write the graph atomically; never leaves an invalid store behind."""
    path = graph_path(kg_dir)
    document = graph_to_document(graph)
    report = validate_document(document)
    if not report.ok:
        raise StoreCorruptError(
            "the graph does not conform to the schema; the store was not written",
            path,
            report,
        )
    document_to_graph(document, path)  # rejects duplicate edges
    text = dumps(document)
    _write_atomic(path, text)
    _mark_validated(text.encode("utf-8"))
    return path


# --- Document <-> graph conversion -------------------------------------------


def document_to_graph(
    document: dict[str, Any], path: Path | None = None
) -> nx.MultiDiGraph:
    """Build the graph from an already validated document.

    An edge's identity is `(source, target, type)` and `type` is its key in the
    `MultiDiGraph`; two edges with the same identity are an error.
    """
    graph = nx.MultiDiGraph(version=document["version"])
    for node in document["nodes"]:
        graph.add_node(node["id"], **_pick(node, _NODE_FIELDS))
    for i, edge in enumerate(document["edges"]):
        source, target, type_ = edge["source"], edge["target"], edge["type"]
        if graph.has_edge(source, target, key=type_):
            raise StoreError(
                f"$.edges[{i}]: duplicate edge {source} -[{type_}]-> {target}",
                path or Path("-"),
            )
        graph.add_edge(source, target, key=type_, **_pick(edge, _EDGE_FIELDS))
    return graph


def graph_to_document(graph: nx.MultiDiGraph) -> dict[str, Any]:
    """Canonical document of the graph: nodes by ID, edges by (source, target, type).

    Fields follow a fixed order and the keys of `attrs` and `provenance` are
    sorted, so the result does not depend on insertion order.
    """
    nodes = [
        {"id": node_id, **_fields(data, _NODE_FIELDS)}
        for node_id, data in sorted(graph.nodes(data=True), key=lambda n: str(n[0]))
    ]
    edges = [
        {"source": u, "target": v, **_fields(data, _EDGE_FIELDS)}
        for u, v, data in graph.edges(data=True)
    ]
    edges.sort(key=_edge_sort_key)
    return {"version": FORMAT_VERSION, "nodes": nodes, "edges": edges}


def dumps(document: dict[str, Any]) -> str:
    """Serialize a canonical document: readable UTF-8, 2 spaces, trailing newline."""
    return json.dumps(document, ensure_ascii=False, indent=2) + "\n"


# --- Helpers -----------------------------------------------------------------


def _pick(data: dict[str, Any], fields: Iterable[str]) -> dict[str, Any]:
    return {f: data[f] for f in fields if f in data}


def _fields(data: dict[str, Any], fields: Iterable[str]) -> dict[str, Any]:
    """Fields in the order of `fields`, with their values in canonical form."""
    return {f: _canonical(v) for f, v in _pick(data, fields).items()}


def _canonical(value: Any) -> Any:
    """Copy with nested object keys sorted; lists keep their order."""
    if isinstance(value, dict):
        return {k: _canonical(value[k]) for k in sorted(value)}
    if isinstance(value, list):
        return [_canonical(v) for v in value]
    return value


def _edge_sort_key(edge: dict[str, Any]) -> tuple[str, str, str]:
    return (str(edge["source"]), str(edge["target"]), str(edge.get("type", "")))


@cache
def _validator_key() -> bytes:
    # kg's version and the schema: either may change what is valid.
    schema = json.dumps(load_schema(), sort_keys=True)
    return f"{__version__}\0{schema}\0".encode()


def _validated_marker(data: bytes) -> Path:
    key = hashlib.sha256(_validator_key())
    key.update(data)
    cache = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(cache) / VALIDATED_DIR / key.hexdigest()


def _is_validated(data: bytes) -> bool:
    try:
        return _validated_marker(data).is_file()
    except OSError:
        return False


def _mark_validated(data: bytes) -> None:
    # Best effort: without a writable cache, every load validates in full.
    try:
        marker = _validated_marker(data)
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch()
        markers = sorted(marker.parent.iterdir(), key=lambda m: m.stat().st_mtime)
        for old in markers[:-VALIDATED_KEEP]:
            old.unlink(missing_ok=True)
    except OSError:
        pass


def _write_atomic(path: Path, text: str) -> None:
    # mkstemp creates the file with 0600; keep the existing file's permissions.
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
