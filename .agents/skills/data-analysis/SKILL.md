---
name: data-analysis
description: Analyze graphs with NetworkX (metrics, paths, communities) and visualize them. Use it when asked to explore, measure or plot a graph.
---

# Graph data analysis

## Flow
1. **Load/build** the graph (`nx.Graph` undirected, `nx.DiGraph` directed). Store attributes on nodes (`type`, `age`...) and edges (`relation`).
2. **Inspect**: `G.number_of_nodes()`, `G.number_of_edges()`, `nx.is_directed(G)`, `nx.is_weakly_connected(G)`.
3. **Measure** according to the question:
   - Centrality: `nx.degree_centrality`, `nx.betweenness_centrality`, `nx.pagerank`.
   - Paths: `nx.shortest_path`, `nx.has_path`, `nx.descendants`.
   - Structure: `nx.connected_components` / `nx.weakly_connected_components`, `nx.community.louvain_communities(G, seed=42)`.
4. **Tabulate** results (dict → sorted list, or pandas if installed).
5. **Visualize**: matplotlib for static output, pyvis for interactive HTML.

## Rules
- Fix `seed` for anything random, for reproducibility.
- Filter by attributes with comprehensions: `[n for n, d in G.nodes(data=True) if d.get("type") == "person"]`.
- For large graphs (>10k nodes) avoid exact `betweenness_centrality`; sample with `k=`.
- Explain results in plain language, not just numbers.

## Visualization
```python
pos = nx.spring_layout(G, seed=42)
nx.draw(G, pos, with_labels=True, node_size=2000, arrows=G.is_directed())
nx.draw_networkx_edge_labels(G, pos, edge_labels=nx.get_edge_attributes(G, "relation"))
plt.savefig("out.png", bbox_inches="tight")
```
