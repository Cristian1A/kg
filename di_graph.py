import networkx as nx

G = nx.DiGraph()

G.add_edge("Cris", "Python", relation="uses")
G.add_edge("Python", "pandas", relation="has_library")

print(G["Cris"]["Python"])

for node in G.successors("Cris"):
    print(node)


path = nx.shortest_path(
    G,
    "Cris",
    "pandas"
)

print(path)