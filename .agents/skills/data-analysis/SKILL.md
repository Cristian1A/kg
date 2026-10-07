---
name: data-analysis
description: Analizar grafos con NetworkX (métricas, caminos, comunidades) y visualizarlos. Úsala cuando se pida explorar, medir o graficar un grafo.
---

# Análisis de datos con grafos

## Flujo
1. **Cargar/construir** el grafo (`nx.Graph` no dirigido, `nx.DiGraph` dirigido). Guarda atributos en nodos (`type`, `age`...) y aristas (`relation`).
2. **Inspeccionar**: `G.number_of_nodes()`, `G.number_of_edges()`, `nx.is_directed(G)`, `nx.is_weakly_connected(G)`.
3. **Medir** según la pregunta:
   - Centralidad: `nx.degree_centrality`, `nx.betweenness_centrality`, `nx.pagerank`.
   - Caminos: `nx.shortest_path`, `nx.has_path`, `nx.descendants`.
   - Estructura: `nx.connected_components` / `nx.weakly_connected_components`, `nx.community.louvain_communities(G, seed=42)`.
4. **Tabular** resultados (dict → lista ordenada, o pandas si está instalado).
5. **Visualizar**: matplotlib para estático, pyvis para HTML interactivo.

## Reglas
- Fija `seed` en todo lo aleatorio para reproducibilidad.
- Filtra por atributos con comprensiones: `[n for n, d in G.nodes(data=True) if d.get("type") == "person"]`.
- Para grafos grandes (>10k nodos) evita `betweenness_centrality` exacta; usa `k=` para muestreo.
- Explica los resultados en lenguaje claro, no solo números.

## Visualización
```python
pos = nx.spring_layout(G, seed=42)
nx.draw(G, pos, with_labels=True, node_size=2000, arrows=G.is_directed())
nx.draw_networkx_edge_labels(G, pos, edge_labels=nx.get_edge_attributes(G, "relation"))
plt.savefig("out.png", bbox_inches="tight")
```
