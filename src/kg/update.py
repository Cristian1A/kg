"""Keep the graph consistent with the code (RF-72) and detect a stale one (RF-77).

`kg extract` replaces the **derived layer**: the elements whose provenance is
`method: parser` from one of kg's own extractors. Before merging a new
extraction, the derived elements it no longer produces (deleted, renamed or
moved code) are removed. Knowledge added by agents or people (`llm`,
`manual`) is never removed; a derived node that an agent edge still uses is
kept and reported instead. Rules in `docs/store.md`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import networkx as nx

from kg import store
from kg.extract import DIGEST, EXTRACTORS, Extraction, input_digests, repo_id
from kg.merge import MergeReport, edge_label, merge_document
from kg.schema.validation import Report, validate_document

# Node types whose `attrs.digest` records the content of the file they stand for.
_FILE_TYPES = {"File": "file:", "Config": "config:"}


@dataclass
class Orphan:
    """A node the code no longer has, kept because agent edges still use it."""

    id: str
    edges: list[str]


@dataclass
class PruneReport:
    """What a new extraction removes from the derived layer."""

    nodes: list[str] = field(default_factory=list)
    edges: list[str] = field(default_factory=list)
    orphans: list[Orphan] = field(default_factory=list)
    # Stale elements kept because their source file could not be read this time
    kept_skipped: list[str] = field(default_factory=list)
    # Repo nodes of another extraction in the store: nothing is removed then
    other_repos: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.nodes or self.edges)

    def to_text(self) -> str:
        lines = []
        if self.changed:
            lines.append(
                f"  removed: {_plural(len(self.nodes), 'node')}, "
                f"{_plural(len(self.edges), 'edge')} the code no longer has"
            )
        if self.orphans:
            lines.append(
                f"  kept {_plural(len(self.orphans), 'node')} the code no longer has, "
                "because agent edges use them (re-add the edges to the new ID with "
                "`kg add`, then `kg remove` the old node):"
            )
            for orphan in self.orphans:
                lines.append(f"    {orphan.id}")
                lines += [f"      {e}" for e in orphan.edges]
        if self.kept_skipped:
            lines.append(
                f"  kept {_plural(len(self.kept_skipped), 'element')} of skipped "
                "files until they can be read again"
            )
        if self.other_repos:
            lines.append(
                f"  warning: the store also holds the extraction of "
                f"{', '.join(self.other_repos)}; nothing was removed. If the repo "
                "was renamed, remove the old node with `kg remove` and extract again"
            )
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": self.nodes,
            "edges": self.edges,
            "orphans": [{"id": o.id, "edges": o.edges} for o in self.orphans],
            "kept_skipped": self.kept_skipped,
            "other_repos": self.other_repos,
        }


@dataclass
class UpdateResult:
    """Result of `update_store`: `merge` is `None` if the document is not valid."""

    graph_path: Path
    validation: Report
    removed: PruneReport
    merge: MergeReport | None = None

    @property
    def changed(self) -> bool:
        return self.removed.changed or bool(self.merge and self.merge.changed)


def is_derived(data: Mapping[str, Any]) -> bool:
    """Whether a node or edge was produced by one of `kg extract`'s extractors."""
    provenance = data.get("provenance") or {}
    extractor = str(provenance.get("extractor", "")).split("@", 1)[0]
    return provenance.get("method") == "parser" and extractor in EXTRACTORS


def update_store(
    kg_dir: Path, extraction: Extraction, dry_run: bool = False
) -> UpdateResult:
    """Replace the derived layer of the store with a new extraction (`kg extract`).

    The store is written once, atomically, and only if something changed and
    not `dry_run`; an invalid document leaves it untouched. Lets the
    `StoreError`s from loading or saving the store through.
    """
    graph = store.load_graph(kg_dir)
    skipped = {s.path for s in extraction.skipped}
    pruned, removed = prune(graph, extraction.document, skipped)
    report = validate_document(extraction.document, known_ids=set(pruned.nodes))
    result = UpdateResult(store.graph_path(kg_dir), report, removed)
    if not report.ok:
        return result
    merged, result.merge = merge_document(pruned, extraction.document)
    # A new digest is bookkeeping for `kg status`, not a disagreement
    result.merge.conflicts = [
        c for c in result.merge.conflicts if c.field != f"attrs.{DIGEST}"
    ]
    if result.changed and not dry_run:
        store.save_graph(merged, kg_dir)
    return result


def prune(
    graph: nx.MultiDiGraph, document: dict[str, Any], skipped: Iterable[str] = ()
) -> tuple[nx.MultiDiGraph, PruneReport]:
    """Copy of the graph without the derived elements `document` no longer has.

    Elements whose provenance `source` is in `skipped` (files that could not be
    read this time) are kept. A node with non-derived edges is kept too.
    """
    report = PruneReport()
    produced_nodes = {n["id"] for n in document["nodes"]}
    produced_edges = {(e["source"], e["target"], e["type"]) for e in document["edges"]}
    skipped = set(skipped)

    report.other_repos = [r for r in _derived_repos(graph) if r not in produced_nodes]
    if report.other_repos:
        return graph.copy(), report

    def stale(data: Mapping[str, Any], label: str) -> bool:
        if not is_derived(data):
            return False
        if data["provenance"].get("source") in skipped:
            report.kept_skipped.append(label)
            return False
        return True

    pruned = graph.copy()
    for u, v, key, data in sorted(graph.edges(keys=True, data=True), key=_edge_key):
        label = edge_label(u, v, key)
        if (u, v, key) not in produced_edges and stale(data, label):
            pruned.remove_edge(u, v, key=key)
            report.edges.append(label)

    for node, data in sorted(graph.nodes(data=True)):
        if node in produced_nodes or not stale(data, node):
            continue
        incident = _incident(pruned, node)
        agent_edges = sorted(e for e, d in incident.items() if not is_derived(d))
        if agent_edges:
            report.orphans.append(Orphan(node, agent_edges))
            continue
        report.edges += incident
        pruned.remove_node(node)
        report.nodes.append(node)
    report.edges.sort()
    return pruned, report


# --- Stale graph (RF-77) -----------------------------------------------------


@dataclass
class Staleness:
    """Files that changed since the last extraction."""

    repo: str
    modified: list[str] = field(default_factory=list)
    added: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    # Extracted files with no recorded digest: never read successfully, or
    # extracted before kg recorded digests
    unknown: list[str] = field(default_factory=list)

    @property
    def stale(self) -> bool:
        return bool(self.modified or self.added or self.deleted or self.unknown)

    def to_dict(self) -> dict[str, Any]:
        return {
            "repo": self.repo,
            "stale": self.stale,
            "modified": self.modified,
            "added": self.added,
            "deleted": self.deleted,
            "unknown": self.unknown,
        }


class RepoMismatchError(Exception):
    """The store holds no extraction of the given repo."""


def staleness(graph: nx.MultiDiGraph, root: Path) -> Staleness:
    """Compare the files recorded in the graph with the ones at `root` now.

    Raises `RepoMismatchError` if the graph has a derived `Repo` node and none of
    them is the repo at `root`.
    """
    repo = repo_id(root)
    repos = _derived_repos(graph)
    if repos and repo not in repos:
        raise RepoMismatchError(
            f"the store holds {', '.join(repos)}, not {repo}; "
            "pass the path of that repo"
        )
    recorded: dict[str, str | None] = {}
    for node, data in graph.nodes(data=True):
        prefix = _FILE_TYPES.get(data.get("type", ""))
        if prefix and node.startswith(prefix) and is_derived(data):
            recorded[node.removeprefix(prefix)] = (data.get("attrs") or {}).get(DIGEST)

    current = input_digests(root)
    result = Staleness(repo)
    for path in sorted(recorded.keys() | current.keys()):
        if path not in current:
            result.deleted.append(path)
        elif path not in recorded:
            result.added.append(path)
        elif recorded[path] is None:
            result.unknown.append(path)
        elif recorded[path] != current[path]:
            result.modified.append(path)
    return result


# --- Helpers -----------------------------------------------------------------


def _derived_repos(graph: nx.MultiDiGraph) -> list[str]:
    return sorted(
        n
        for n, d in graph.nodes(data=True)
        if d.get("type") == "Repo" and is_derived(d)
    )


def _incident(graph: nx.MultiDiGraph, node: str) -> dict[str, Any]:
    """Edges into or out of `node` (a self-loop once), by label."""
    edges = [
        *graph.in_edges(node, keys=True, data=True),
        *graph.out_edges(node, keys=True, data=True),
    ]
    return {edge_label(u, v, k): d for u, v, k, d in edges}


def _edge_key(edge: tuple[str, str, str, Any]) -> tuple[str, str, str]:
    return (str(edge[0]), str(edge[1]), str(edge[2]))


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"
