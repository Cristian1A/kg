"""Queries over the graph: lookups, neighbors, paths, impact and the use cases.

Pure functions on the `nx.MultiDiGraph` returned by `kg.store.load_graph`
(RF-40–RF-43). Results are deterministic for the same graph and options, and
every node reached carries the edges that justify it. Documented in
`docs/query.md`.
"""

from __future__ import annotations

import difflib
from collections.abc import Callable, Collection, Iterable
from dataclasses import dataclass
from typing import Any

import networkx as nx

CODE_TYPES = ("Function", "Class")


def untested(
    graph: nx.MultiDiGraph,
    types: Collection[str] = CODE_TYPES,
    include_private: bool = False,
) -> list[str]:
    """Code with no incoming `tests` edge, sorted by ID (CU-02).

    Leaves out code defined in test files or `conftest.py` (helpers and
    fixtures) and, unless `include_private`, names with `attrs.public` false.
    The `tests` edges come from a static heuristic (see `docs/extract.md`):
    code exercised only indirectly also shows up here.
    """
    test_files = {
        data.get("provenance", {}).get("source")
        for _, data in graph.nodes(data=True)
        if data.get("type") == "Test"
    }
    result = []
    for node_id, data in graph.nodes(data=True):
        if data.get("type") not in types:
            continue
        source = data.get("provenance", {}).get("source", "")
        if source in test_files or source.rsplit("/", 1)[-1] == "conftest.py":
            continue
        if not include_private and data.get("attrs", {}).get("public") is False:
            continue
        if not any(key == "tests" for _, _, key in graph.in_edges(node_id, keys=True)):
            result.append(node_id)
    return sorted(result)


# --- Lookups, neighbors and paths (RF-40) ---------------------------------------

# Code that `undocumented` looks at
DOCUMENTABLE_TYPES = ("Package", "Module", "Class", "Function")
# A change in the target may affect the source: `A imports B`, `T tests B`,
# `D documents B`... Custom relations only propagate when asked for (RF-41).
IMPACT_RELATIONS = (
    "calls",
    "depends_on",
    "documents",
    "implements",
    "imports",
    "justifies",
    "tests",
)
# Never results: the root of everything, and files (their module stands for them)
_SKIPPED_TYPES = ("Repo", "File")


class QueryError(Exception):
    """A query that cannot run (e.g. an unknown ID), with a suggestion."""

    def __init__(self, message: str, suggestion: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.suggestion = suggestion


@dataclass(frozen=True)
class Step:
    """One edge of the graph, as traversed by a query."""

    source: str
    target: str
    type: str
    method: str | None
    confidence: float | None

    @property
    def label(self) -> str:
        return f"{self.source} -[{self.type}]-> {self.target}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "type": self.type,
            "method": self.method,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class Hit:
    """A node reached by a query, with the edges that justify it."""

    id: str
    type: str
    label: str | None
    depth: int
    path: tuple[Step, ...]

    @property
    def confidence(self) -> float | None:
        """The weakest link of the path (`None` if no edge says)."""
        values = [s.confidence for s in self.path if s.confidence is not None]
        return min(values) if values else None

    @property
    def methods(self) -> list[str]:
        return sorted({s.method for s in self.path if s.method})

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "label": self.label,
            "depth": self.depth,
            "direct": self.depth == 1,
            "confidence": self.confidence,
            "methods": self.methods,
            "path": [s.to_dict() for s in self.path],
        }


def require(graph: nx.MultiDiGraph, node_id: str) -> None:
    """Raise `QueryError` with the closest ID if `node_id` is not in the graph."""
    if node_id in graph:
        return
    close = difflib.get_close_matches(node_id, [str(n) for n in graph], n=1)
    hint = f'Did you mean "{close[0]}"?' if close else "Find IDs with `kg query find`."
    raise QueryError(f"no node {node_id!r} in the graph", hint)


def node_fields(graph: nx.MultiDiGraph, node_id: str) -> dict[str, Any]:
    """The stored fields of a node, as in `graph.json`."""
    require(graph, node_id)
    return {"id": node_id, **graph.nodes[node_id]}


def find(
    graph: nx.MultiDiGraph,
    text: str | None = None,
    types: Collection[str] | None = None,
    attrs: dict[str, Any] | None = None,
) -> list[str]:
    """IDs whose label, ID or description contains `text` (best matches first),
    of the given types and with the given `attrs` values."""
    query = (text or "").strip().lower()
    scored = []
    for node_id, data in graph.nodes(data=True):
        if types and data.get("type") not in types:
            continue
        node_attrs = data.get("attrs") or {}
        if attrs and any(node_attrs.get(k) != v for k, v in attrs.items()):
            continue
        score = _match_score(query, str(node_id), data) if query else 0
        if score is not None:
            scored.append((score, str(node_id)))
    return [node_id for _, node_id in sorted(scored)]


def neighbors(
    graph: nx.MultiDiGraph,
    node_id: str,
    direction: str = "both",
    relations: Collection[str] | None = None,
    types: Collection[str] | None = None,
    depth: int = 1,
) -> list[Hit]:
    """Nodes reachable from `node_id` within `depth` edges, in breadth-first order.

    `direction` is `out`, `in` or `both`; `relations` limits the edges walked
    and `types` the nodes returned (others are still walked through).
    """
    require(graph, node_id)

    def steps(current: str) -> list[tuple[str, Step]]:
        found = []
        if direction in ("out", "both"):
            found += [(v, _step(u, v, k, d)) for u, v, k, d in _out(graph, current)]
        if direction in ("in", "both"):
            found += [(u, _step(u, v, k, d)) for u, v, k, d in _in(graph, current)]
        return [(n, s) for n, s in found if not relations or s.type in relations]

    hits = _walk(graph, node_id, steps, depth, skip=())
    return [h for h in hits if not types or h.type in types]


def shortest_path(
    graph: nx.MultiDiGraph,
    source: str,
    target: str,
    relations: Collection[str] | None = None,
) -> tuple[str, list[Step]] | None:
    """Fewest edges between two nodes, or `None` if they are not connected.

    Returns how the path runs and its steps: `forward` (every edge from
    `source` towards `target`), `backward` (every edge from `target` towards
    `source`) or, only if neither exists, `mixed` (edges in either
    direction). Each step keeps the real direction of its edge.
    """
    require(graph, source)
    require(graph, target)
    if source == target:
        return "forward", []

    def walker(out: bool, inn: bool) -> Callable[[str], list[tuple[str, Step]]]:
        def steps(current: str) -> list[tuple[str, Step]]:
            found = []
            if out:
                found += [(v, _step(u, v, k, d)) for u, v, k, d in _out(graph, current)]
            if inn:
                found += [(u, _step(u, v, k, d)) for u, v, k, d in _in(graph, current)]
            return [(n, s) for n, s in found if not relations or s.type in relations]

        return steps

    for kind, out, inn in (
        ("forward", True, False),
        ("backward", False, True),
        ("mixed", True, True),
    ):
        for hit in _walk(graph, source, walker(out, inn), None, skip=()):
            if hit.id == target:
                return kind, list(hit.path)
    return None


# --- Predefined queries (RF-42) ----------------------------------------------------


def undocumented(
    graph: nx.MultiDiGraph,
    types: Collection[str] = DOCUMENTABLE_TYPES,
    include_private: bool = False,
) -> list[str]:
    """Code that no `documents` edge points to, sorted by ID (CU-03).

    Leaves out test code and, unless `include_private`, names with
    `attrs.public` false. A docstring is not a document: see `description`.
    """
    result = []
    for node_id, data in graph.nodes(data=True):
        if data.get("type") not in types:
            continue
        if not include_private and (data.get("attrs") or {}).get("public") is False:
            continue
        if not any(k == "documents" for _, _, k in graph.in_edges(node_id, keys=True)):
            result.append(node_id)
    return sorted(result)


# --- Impact (RF-41) ----------------------------------------------------------------


def impact(
    graph: nx.MultiDiGraph,
    node_id: str,
    depth: int | None = None,
    relations: Collection[str] = IMPACT_RELATIONS,
    containment: bool = True,
) -> list[Hit]:
    """Elements that **may** be affected by a change in `node_id`.

    Walks the given relations backwards (`A imports B`: a change in B may
    affect A). With `containment`, a class or function also reaches the
    module or class that defines it, so whatever imports that module is
    reached too. `Repo` and `File` nodes are never results. Breadth-first:
    each element comes with its shortest justifying path and its depth.
    """
    require(graph, node_id)

    def steps(current: str) -> list[tuple[str, Step]]:
        found = [
            (u, _step(u, v, k, d))
            for u, v, k, d in _in(graph, current)
            if k in relations
        ]
        if containment:
            found += _owners(graph, current)
        return found

    return _walk(graph, node_id, steps, depth)


def _owners(graph: nx.MultiDiGraph, node_id: str) -> list[tuple[str, Any]]:
    """Class or module that defines a class or function, with the edges to it."""
    if graph.nodes[node_id].get("type") in ("Repo", "File", "Module", "Package"):
        return []
    if (graph.nodes[node_id].get("attrs") or {}).get("kind") == "module":
        return []  # a test module
    owners = []
    for parent, _, key, data in _in(graph, node_id):
        if key != "defines":
            continue
        first = _step(parent, node_id, key, data)
        if graph.nodes[parent].get("type") != "File":
            owners.append((parent, first))
            continue
        for _, module, k, d in _out(graph, parent):
            if k == "defines" and _is_module(graph, module) and module != node_id:
                owners.append((module, (first, _step(parent, module, k, d))))
    return owners


# --- Coverage limits (RF-43) -----------------------------------------------------


def unread_files(graph: nx.MultiDiGraph) -> list[str]:
    """Extracted files with no recorded digest: never read successfully, or
    extracted before kg recorded digests. Their contents may be missing."""
    return sorted(
        node_id.removeprefix("file:")
        for node_id, data in graph.nodes(data=True)
        if data.get("type") == "File"
        and (data.get("provenance") or {}).get("method") == "parser"
        and "digest" not in (data.get("attrs") or {})
    )


def missing_relations(graph: nx.MultiDiGraph, relations: Iterable[str]) -> list[str]:
    """The relation types among `relations` with no edge in the graph."""
    present = {k for _, _, k in graph.edges(keys=True)}
    return sorted(set(relations) - present)


# --- Helpers ---------------------------------------------------------------------


def _walk(
    graph: nx.MultiDiGraph,
    start: str,
    steps: Callable[[str], list[tuple[str, Any]]],
    depth: int | None,
    skip: Collection[str] = _SKIPPED_TYPES,
) -> list[Hit]:
    """Breadth-first walk; `steps` gives `(next node, Step or steps)` pairs.

    Deterministic: neighbors are visited sorted by relation and ID. Nodes of
    a `skip` type are neither returned nor walked through.
    """
    seen = {start}
    frontier: list[tuple[str, tuple[Step, ...]]] = [(start, ())]
    hits: list[Hit] = []
    level = 0
    while frontier and (depth is None or level < depth):
        level += 1
        found: dict[str, tuple[Step, ...]] = {}
        for current, path in frontier:
            options = []
            for nxt, step in steps(current):
                chain = step if isinstance(step, tuple) else (step,)
                options.append(((chain[-1].type, nxt), nxt, chain))
            for _, nxt, chain in sorted(options, key=lambda o: o[0]):
                if nxt in seen or nxt in found:
                    continue
                if graph.nodes[nxt].get("type") in skip:
                    continue
                found[nxt] = path + chain
        seen |= found.keys()
        frontier = sorted(found.items())
        for node_id, path in frontier:
            data = graph.nodes[node_id]
            hits.append(
                Hit(node_id, data.get("type", ""), data.get("label"), level, path)
            )
    return hits


def _out(graph: nx.MultiDiGraph, node_id: str) -> list[tuple[str, str, str, Any]]:
    return sorted(graph.out_edges(node_id, keys=True, data=True), key=_edge_key)


def _in(graph: nx.MultiDiGraph, node_id: str) -> list[tuple[str, str, str, Any]]:
    return sorted(graph.in_edges(node_id, keys=True, data=True), key=_edge_key)


def _edge_key(edge: tuple[str, str, str, Any]) -> tuple[str, str, str]:
    return (str(edge[2]), str(edge[0]), str(edge[1]))


def _step(source: str, target: str, type_: str, data: dict[str, Any]) -> Step:
    provenance = data.get("provenance") or {}
    return Step(
        source, target, type_, provenance.get("method"), provenance.get("confidence")
    )


def _is_module(graph: nx.MultiDiGraph, node_id: str) -> bool:
    data = graph.nodes[node_id]
    if data.get("type") in ("Module", "Package"):
        return True
    return (
        data.get("type") == "Test" and (data.get("attrs") or {}).get("kind") == "module"
    )


def _match_score(query: str, node_id: str, data: dict[str, Any]) -> int | None:
    """Like the HTML search: names, then IDs, then descriptions."""
    name = str(data.get("label") or node_id.split(":", 1)[-1]).lower()
    lowered = node_id.lower()
    if query in (name, lowered):
        return 0
    if name.startswith(query):
        return 1
    if query in name:
        return 2
    if query in lowered:
        return 3
    if query in str(data.get("description") or "").lower():
        return 4
    return None
