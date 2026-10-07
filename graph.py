import networkx as nx
import matplotlib.pyplot as plt

G = nx.DiGraph()

G.add_edge("Cris", "Python", relation="uses")
G.add_edge("Python", "NetworkX", relation="has_library")
G.add_edge("Python", "pandas", relation="has_library")

pos = nx.spring_layout(G)

nx.draw(
    G,
    pos,
    with_labels=True,
    node_size=2000,
    arrows=True
)

nx.draw_networkx_edge_labels(
    G,
    pos,
    edge_labels={
        (u, v): data["relation"]
        for u, v, data in G.edges(data=True)
    }
)

plt.show()