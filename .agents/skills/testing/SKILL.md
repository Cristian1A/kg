---
name: testing
description: Escribir y ejecutar tests con pytest para el código de grafos del proyecto. Úsala al añadir funcionalidad, corregir bugs o cuando se pida cobertura.
---

# Testing

## Cuándo usarla
- Al crear o modificar funciones en `src/networkx_project/`.
- Al reproducir un bug (primero un test que falle, luego el fix).

## Convenciones
- Framework: **pytest**. Archivos `tests/test_<modulo>.py`, funciones `test_<comportamiento>`.
- Grafos pequeños y deterministas construidos en fixtures (`tests/conftest.py`).
- Compara grafos con `nx.utils.graphs_equal(G1, G2)` o comparando `sorted(G.edges(data=True))`.
- Para layouts aleatorios fija la semilla: `nx.spring_layout(G, seed=42)`.
- Tests de plotting: usa el backend `Agg` y nunca `plt.show()`.

## Ejemplo

```python
import networkx as nx
from networkx_project.graphs import build_tech_graph

def test_shortest_path_cris_to_pandas():
    G = build_tech_graph()
    assert nx.shortest_path(G, "Cris", "pandas") == ["Cris", "Python", "pandas"]
```

## Comandos
```bash
pytest                      # todos los tests
pytest -k shortest -x -q    # filtrar y parar en el primer fallo
pytest --cov=networkx_project
```

## Checklist
- [ ] Caso normal, caso borde (grafo vacío, nodo inexistente) y caso de error (`nx.NetworkXNoPath`, `nx.NodeNotFound`).
- [ ] Todos los tests pasan antes de terminar.
