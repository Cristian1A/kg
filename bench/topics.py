"""Topic-specific stores for the `topic` strategy (#39).

A topic store keeps the entity types a topic's questions need, and the edges
between them, so an agent queries a smaller graph. It is built with the type
filters of RF-40 from the full store; topic views inside kg are RF-44 (v0.3).
"""

from __future__ import annotations

from pathlib import Path

import networkx as nx

from kg import store

# Always kept: `Repo`, `File` and `Config` record what was extracted, so the
# freshness check (`stale_graph`) and containment in `kg impact` keep working.
BASE_TYPES = ("Repo", "File", "Config")
CODE_TYPES = ("Package", "Module", "Class", "Function")
TOPIC_TYPES = {
    "development": (*CODE_TYPES, "Dependency", "Service", "Endpoint"),
    "tests": (*CODE_TYPES, "Test"),
    "documentation": (*CODE_TYPES, "Document", "Issue", "Concept"),
    "decisions": ("Package", "Module", "Dependency", "Decision", "Concept", "Document"),
}


def topic_graph(graph: nx.MultiDiGraph, topic: str) -> nx.MultiDiGraph:
    """The subgraph of `topic`'s types, with the edges between them."""
    keep = {*BASE_TYPES, *TOPIC_TYPES[topic]}
    nodes = [n for n, data in graph.nodes(data=True) if data.get("type") in keep]
    return graph.subgraph(nodes).copy()


def build_topic_stores(repo: Path) -> dict[str, Path]:
    """Write `.kg-<topic>` next to the repo's `.kg`, once per topic."""
    full = store.load_graph(repo / ".kg")
    built = {}
    for topic in TOPIC_TYPES:
        kg_dir = repo / f".kg-{topic}"
        if not store.graph_path(kg_dir).is_file():
            store.init_store(kg_dir)
            store.save_graph(topic_graph(full, topic), kg_dir)
        built[topic] = kg_dir
    return built
