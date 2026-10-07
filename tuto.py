import networkx as nx

G = nx.Graph()

# Nodes
G.add_node(
    "Cris",
    type="person",
    age=23
)

G.add_node(
    "Python",
    type="technology"
)

G.add_edge("Cris", "Python", relation="knows")

print(G.nodes["Cris"])
print(G.edges)