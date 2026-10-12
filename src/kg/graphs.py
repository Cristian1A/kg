"""Graph building for the project."""

import networkx as nx


def build_tech_graph() -> nx.DiGraph:
    """Directed graph person → technology → libraries."""
    G = nx.DiGraph()
    G.add_edge("Cris", "Python", relation="uses")
    G.add_edge("Python", "NetworkX", relation="has_library")
    G.add_edge("Python", "pandas", relation="has_library")
    return G
