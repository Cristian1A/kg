import networkx as nx

from networkx_project.graphs import build_tech_graph


def test_shortest_path_cris_to_pandas():
    G = build_tech_graph()
    assert nx.shortest_path(G, "Cris", "pandas") == ["Cris", "Python", "pandas"]


def test_edge_relations():
    G = build_tech_graph()
    assert G["Cris"]["Python"]["relation"] == "uses"
