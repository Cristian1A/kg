"""Deterministic extractors (RF-10–RF-12): they produce schema documents."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from kg.extract.deps import extract_dependencies
from kg.extract.python import (
    EXTRACTOR,
    Extraction,
    SkippedFile,
    extract_python,
    repo_id,
)
from kg.store import FORMAT_VERSION

__all__ = [
    "EXTRACTOR",
    "Extraction",
    "SkippedFile",
    "combine",
    "extract_dependencies",
    "extract_python",
    "extract_repo",
]


def extract_repo(root: Path) -> Extraction:
    """Run every extractor on `root` and combine their documents into one.

    Manifests go first, so a `Dependency` keeps the provenance of the file that
    declares it rather than that of the first module importing it.
    """
    parts = [extract_dependencies(root, repo_id(root)), extract_python(root)]
    return Extraction(
        combine([p.document for p in parts]),
        sorted(f for p in parts for f in p.files),
        [s for p in parts for s in p.skipped],
    )


def combine(documents: list[dict[str, Any]]) -> dict[str, Any]:
    """Join documents with no duplicate IDs: the first one to bring an element
    wins, except for `attrs`, which are joined key by key (first wins too)."""
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[tuple[str, str, str], dict[str, Any]] = {}
    for document in documents:
        for node in document["nodes"]:
            _join(nodes, node["id"], node)
        for edge in document["edges"]:
            _join(edges, (edge["source"], edge["target"], edge["type"]), edge)
    return {
        "version": FORMAT_VERSION,
        "nodes": list(nodes.values()),
        "edges": list(edges.values()),
    }


def _join(
    elements: dict[Any, dict[str, Any]], key: Any, element: dict[str, Any]
) -> None:
    current = elements.get(key)
    if current is None:
        elements[key] = dict(element)
        return
    for name, value in element.items():
        if name == "attrs" and "attrs" in current:
            current["attrs"] = value | current["attrs"]
        else:
            current.setdefault(name, value)
