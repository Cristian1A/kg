"""Basic merge by ID of a document into the graph (RF-21, RF-30, S-03).

MVP policy: a node with an existing ID or an edge with the same identity
(`source`, `target`, `type`) is combined instead of duplicated. Fields missing
from the document are kept; if it brings a different value, the new one wins
and a conflict is recorded. Exception: a `parser` provenance is not replaced by
a non-`parser` one, so enriching with an agent does not lose deterministic
data. A configurable policy is RF-33 (v0.2).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

import networkx as nx

from kg import store
from kg.schema.validation import Report, validate_text

Kind = Literal["node", "edge"]


@dataclass(frozen=True)
class Conflict:
    """Document value that differs from the existing one; `kept` says which stays."""

    kind: Kind
    element: str
    field: str
    old: Any
    new: Any
    kept: Literal["new", "old"] = "new"

    def to_text(self) -> str:
        show = _show_provenance if self.field == "provenance" else _show
        if self.kept == "old":
            return (
                f"{self.element} · {self.field}: kept {show(self.old)}; "
                f"discarded {show(self.new)}"
            )
        return f"{self.element} · {self.field}: {show(self.old)} → {show(self.new)}"


@dataclass
class Changes:
    """Document elements grouped by their effect on the graph."""

    added: list[str] = field(default_factory=list)
    merged: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, list[str]]:
        return {
            "added": self.added,
            "merged": self.merged,
            "unchanged": self.unchanged,
        }


@dataclass
class MergeReport:
    """Summary of a merge."""

    nodes: Changes = field(default_factory=Changes)
    edges: Changes = field(default_factory=Changes)
    conflicts: list[Conflict] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(
            self.nodes.added
            or self.nodes.merged
            or self.edges.added
            or self.edges.merged
        )

    def to_text(self) -> str:
        lines = [
            f"  nodes: {_counts(self.nodes)}",
            f"  edges: {_counts(self.edges)}",
        ]
        if self.conflicts:
            n = len(self.conflicts)
            lines.append(f"  {n} {'conflict' if n == 1 else 'conflicts'}:")
            lines += [f"    {c.to_text()}" for c in self.conflicts]
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "changed": self.changed,
            "nodes": self.nodes.to_dict(),
            "edges": self.edges.to_dict(),
            "conflicts": [asdict(c) for c in self.conflicts],
        }


@dataclass
class AddResult:
    """Result of `add_to_store`: `merge` is `None` if the document is not valid."""

    graph_path: Path
    validation: Report
    merge: MergeReport | None = None


def add_to_store(kg_dir: Path, text: str) -> AddResult:
    """Validate a JSON document and merge it into the store (`kg add`).

    Edges may point to nodes already in the store. On validation errors nothing
    is modified; if the merge changes nothing, nothing is written. Lets the
    `StoreError`s from loading or saving the store through.
    """
    graph = store.load_graph(kg_dir)
    report = validate_text(text, known_ids=set(graph.nodes))
    result = AddResult(store.graph_path(kg_dir), report)
    if not report.ok:
        return result
    merged, result.merge = merge_document(graph, json.loads(text))
    if result.merge.changed:
        store.save_graph(merged, kg_dir)
    return result


def edge_label(source: str, target: str, type_: str) -> str:
    """Readable identity of an edge: `source -[type]-> target`."""
    return f"{source} -[{type_}]-> {target}"


def merge_document(
    graph: nx.MultiDiGraph, document: dict[str, Any]
) -> tuple[nx.MultiDiGraph, MergeReport]:
    """Return a copy of the graph with the document merged in, and a summary.

    The document must already be validated (with the graph IDs as known IDs).
    """
    merged = graph.copy()
    report = MergeReport()

    for node in document["nodes"]:
        node_id = node["id"]
        incoming = {k: v for k, v in node.items() if k != "id"}
        if node_id not in merged:
            merged.add_node(node_id, **incoming)
            report.nodes.added.append(node_id)
            continue
        changed = _merge_into(merged.nodes[node_id], incoming, "node", node_id, report)
        (report.nodes.merged if changed else report.nodes.unchanged).append(node_id)

    for edge in document["edges"]:
        source, target, type_ = edge["source"], edge["target"], edge["type"]
        label = edge_label(source, target, type_)
        incoming = {k: v for k, v in edge.items() if k not in ("source", "target")}
        if not merged.has_edge(source, target, key=type_):
            merged.add_edge(source, target, key=type_, **incoming)
            report.edges.added.append(label)
            continue
        data = merged.edges[source, target, type_]
        changed = _merge_into(data, incoming, "edge", label, report)
        (report.edges.merged if changed else report.edges.unchanged).append(label)

    return merged, report


def _merge_into(
    current: dict[str, Any],
    incoming: dict[str, Any],
    kind: Kind,
    element: str,
    report: MergeReport,
) -> bool:
    """Merge `incoming` into `current` in place. Return whether anything changed."""
    changed = False
    for name, value in incoming.items():
        if name == "attrs":
            changed |= _merge_attrs(current, value, kind, element, report)
            continue
        old = current.get(name)
        if old == value:
            continue
        if name == "provenance" and _keeps_parser(old, value):
            report.conflicts.append(Conflict(kind, element, name, old, value, "old"))
            continue
        if name in current:
            report.conflicts.append(Conflict(kind, element, name, old, value))
        current[name] = value
        changed = True
    return changed


def _keeps_parser(old: Any, new: dict[str, Any]) -> bool:
    """A `parser` provenance wins over `llm` or `manual` (part of RF-33)."""
    return (
        isinstance(old, dict)
        and old.get("method") == "parser"
        and new.get("method") != "parser"
    )


def _merge_attrs(
    current: dict[str, Any],
    attrs: dict[str, Any],
    kind: Kind,
    element: str,
    report: MergeReport,
) -> bool:
    # Merge per top-level key; nested values are replaced as a whole.
    target = dict(current.get("attrs", {}))
    changed = False
    for key, value in attrs.items():
        if key in target and target[key] == value:
            continue
        if key in target:
            report.conflicts.append(
                Conflict(kind, element, f"attrs.{key}", target[key], value)
            )
        target[key] = value
        changed = True
    if changed:
        current["attrs"] = target
    return changed


def _counts(changes: Changes) -> str:
    return (
        f"{len(changes.added)} added, {len(changes.merged)} merged, "
        f"{len(changes.unchanged)} unchanged"
    )


def _show(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return text if len(text) <= 60 else text[:59] + "…"


def _show_provenance(value: Any) -> str:
    if not isinstance(value, dict):
        return _show(value)
    return (
        f"{value.get('method')} ({value.get('extractor')}, "
        f"confidence {value.get('confidence')})"
    )
