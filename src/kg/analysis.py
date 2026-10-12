"""Queries over the graph that support the use cases (CU-02).

Pure functions on the `nx.MultiDiGraph` returned by `kg.store.load_graph`.
"""

from __future__ import annotations

from collections.abc import Collection

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
