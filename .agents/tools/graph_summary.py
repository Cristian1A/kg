"""Imprime un resumen JSON de un grafo (GraphML) o del grafo de ejemplo del proyecto."""

import argparse
import json

import networkx as nx


def example_graph() -> nx.DiGraph:
    G = nx.DiGraph()
    G.add_edge("Cris", "Python", relation="uses")
    G.add_edge("Python", "NetworkX", relation="has_library")
    G.add_edge("Python", "pandas", relation="has_library")
    return G


def summarize(G: nx.Graph) -> dict:
    return {
        "directed": G.is_directed(),
        "nodes": G.number_of_nodes(),
        "edges": G.number_of_edges(),
        "density": round(nx.density(G), 4),
        "degree_centrality": {
            n: round(c, 4) for n, c in nx.degree_centrality(G).items()
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", help="Archivo .graphml (opcional)")
    args = parser.parse_args()
    G = nx.read_graphml(args.path) if args.path else example_graph()
    print(json.dumps(summarize(G), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
