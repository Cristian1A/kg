"""Print a JSON summary of a kg store: counts by type, density and hubs."""

import argparse
import json
from collections import Counter
from pathlib import Path

import networkx as nx

from kg import store


def summarize(graph: nx.MultiDiGraph, top: int = 10) -> dict:
    """Counts by entity and relation type, density and best-connected nodes."""
    degree = sorted(graph.degree(), key=lambda item: (-item[1], item[0]))
    return {
        "nodes": graph.number_of_nodes(),
        "edges": graph.number_of_edges(),
        "density": round(nx.density(graph), 4) if len(graph) > 1 else 0.0,
        "weakly_connected_components": nx.number_weakly_connected_components(graph)
        if len(graph)
        else 0,
        "node_types": dict(Counter(d["type"] for _, d in graph.nodes(data=True))),
        "edge_types": dict(Counter(k for _, _, k in graph.edges(keys=True))),
        "hubs": [{"id": n, "degree": d} for n, d in degree[:top]],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kg-dir", type=Path, default=Path(".kg"), help="store")
    parser.add_argument("--top", type=int, default=10, help="hubs to list")
    args = parser.parse_args()
    summary = summarize(store.load_graph(args.kg_dir), args.top)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
