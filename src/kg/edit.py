"""Remove and edit elements of the stored graph (`kg remove`, `kg edit`, #28).

Operations are all-or-nothing: they work on a copy of the graph, and an
unknown ID raises `EditError` before anything changes. Saving goes through
`store.save_graph`, which validates against the schema.
"""

from __future__ import annotations

import difflib
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import networkx as nx

from kg.merge import edge_label

# Node fields that `kg edit` may change besides `attrs`.
TEXT_FIELDS = ("label", "description")


class EditError(Exception):
    """Unknown element or impossible change; nothing was modified."""

    def __init__(self, message: str, suggestion: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.suggestion = suggestion


@dataclass
class RemoveReport:
    """What a removal deleted: nodes, and edges (their own or explicitly)."""

    nodes: list[str] = field(default_factory=list)
    edges: list[str] = field(default_factory=list)

    def to_text(self) -> str:
        lines = [f"  nodes: {len(self.nodes)} removed"]
        lines += [f"    {n}" for n in self.nodes]
        lines.append(f"  edges: {len(self.edges)} removed")
        lines += [f"    {e}" for e in self.edges]
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {"nodes": self.nodes, "edges": self.edges}


@dataclass
class Change:
    """A field of a node before and after (`None`: absent)."""

    field: str
    old: Any
    new: Any

    def to_text(self) -> str:
        return f"{self.field}: {_show(self.old)} → {_show(self.new)}"


@dataclass
class EditReport:
    """Changes applied to a node; `id` is its ID after the edit."""

    id: str
    changes: list[Change] = field(default_factory=list)
    edges_rewritten: int = 0

    @property
    def changed(self) -> bool:
        return bool(self.changes)

    def to_text(self) -> str:
        lines = [f"  {c.to_text()}" for c in self.changes]
        if self.edges_rewritten:
            n = self.edges_rewritten
            noun = "edge now points" if n == 1 else "edges now point"
            lines.append(f"  {n} {noun} to {self.id}")
        return "\n".join(lines) if lines else "  nothing to change"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "changed": self.changed,
            "changes": [vars(c) for c in self.changes],
            "edges_rewritten": self.edges_rewritten,
        }


def remove(
    graph: nx.MultiDiGraph,
    nodes: Sequence[str] = (),
    edges: Sequence[tuple[str, str, str]] = (),
) -> tuple[nx.MultiDiGraph, RemoveReport]:
    """Copy of the graph without `nodes` (and their edges) and `edges`.

    `edges` are `(source, type, target)`, the order used on the command line.
    """
    for node in nodes:
        _require_node(graph, node)
    for source, type_, target in edges:
        if not graph.has_edge(source, target, key=type_):
            raise EditError(
                f"no edge {edge_label(source, target, type_)} in the store",
                _edge_suggestion(graph, source, type_, target),
            )

    result = graph.copy()
    report = RemoveReport()
    removed_edges: set[tuple[str, str, str]] = set()
    for source, type_, target in edges:
        removed_edges.add((source, target, type_))
    for node in dict.fromkeys(nodes):
        removed_edges |= set(result.in_edges(node, keys=True))
        removed_edges |= set(result.out_edges(node, keys=True))
        report.nodes.append(node)
    for source, target, type_ in sorted(removed_edges):
        result.remove_edge(source, target, key=type_)
        report.edges.append(edge_label(source, target, type_))
    result.remove_nodes_from(report.nodes)
    return result, report


def edit_node(
    graph: nx.MultiDiGraph,
    node_id: str,
    *,
    new_id: str | None = None,
    type_: str | None = None,
    texts: dict[str, str] | None = None,
    set_attrs: dict[str, Any] | None = None,
    unset_attrs: list[str] | None = None,
) -> tuple[nx.MultiDiGraph, EditReport]:
    """Copy of the graph with the node changed.

    `texts` sets `label`/`description` (an empty string removes the field);
    `set_attrs` and `unset_attrs` change keys of `attrs`. A new ID rewrites the
    node's edges. Provenance is kept: it describes where the element came from.
    """
    _require_node(graph, node_id)
    result = graph.copy()
    data = result.nodes[node_id]
    report = EditReport(node_id)

    if type_ is not None and type_ != data.get("type"):
        report.changes.append(Change("type", data.get("type"), type_))
        data["type"] = type_
    for name, value in (texts or {}).items():
        if name not in TEXT_FIELDS:
            raise EditError(f"{name} is not an editable field")
        old = data.get(name)
        new = value or None
        if old != new:
            report.changes.append(Change(name, old, new))
            if new is None:
                del data[name]
            else:
                data[name] = new

    attrs = dict(data.get("attrs", {}))
    for key in unset_attrs or []:
        if key not in attrs:
            raise EditError(
                f"{node_id} has no attribute {key!r}",
                _did_you_mean(key, attrs, "attrs"),
            )
        report.changes.append(Change(f"attrs.{key}", attrs.pop(key), None))
    for key, value in (set_attrs or {}).items():
        if attrs.get(key) != value:
            report.changes.append(Change(f"attrs.{key}", attrs.get(key), value))
            attrs[key] = value
    if attrs:
        data["attrs"] = attrs
    else:
        data.pop("attrs", None)

    if new_id is not None and new_id != node_id:
        if new_id in result:
            raise EditError(
                f"{new_id} already exists; remove it first or merge with `kg add`"
            )
        report.edges_rewritten = result.degree(node_id)
        nx.relabel_nodes(result, {node_id: new_id}, copy=False)
        report.changes.insert(0, Change("id", node_id, new_id))
        report.id = new_id
    return result, report


def parse_value(text: str) -> Any:
    """Value of `--set key=value`: JSON if it parses (`3`, `true`, `["a"]`),
    otherwise the text itself."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _require_node(graph: nx.MultiDiGraph, node_id: str) -> None:
    if node_id not in graph:
        raise EditError(
            f"no node {node_id} in the store", _did_you_mean(node_id, graph.nodes, "ID")
        )


def _edge_suggestion(
    graph: nx.MultiDiGraph, source: str, type_: str, target: str
) -> str | None:
    for node in (source, target):
        if node not in graph:
            return _did_you_mean(node, graph.nodes, "ID")
    types = sorted(k for _, t, k in graph.out_edges(source, keys=True) if t == target)
    if types:
        return f"Edges from {source} to {target}: {', '.join(types)}."
    return f"There is no edge from {source} to {target}."


def _did_you_mean(value: str, options: Any, what: str) -> str | None:
    options = list(options)
    lowered = {o.lower(): o for o in options}
    match = lowered.get(value.lower())
    if match is None:
        close = difflib.get_close_matches(value, options, n=1, cutoff=0.6)
        match = close[0] if close else None
    return f'Did you mean {what} "{match}"?' if match else None


def _show(value: Any) -> str:
    if value is None:
        return "(none)"
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= 60 else text[:59] + "…"
