---
name: architecture
description: Decisiones de estructura del código, módulos y dependencias del proyecto. Úsala al crear módulos nuevos, refactorizar o mover scripts de exploración a src/.
---

# Arquitectura

## Layout
```
src/networkx_project/
├── __init__.py
├── graphs.py      # construcción de grafos (funciones puras que devuelven nx.Graph/DiGraph)
├── analysis.py    # métricas y consultas sobre grafos
├── viz.py         # visualización (matplotlib / pyvis); sin lógica de negocio
└── io.py          # carga/guardado (JSON, GraphML, CSV de aristas)
```

## Principios
- **Separar construcción, análisis y visualización.** Una función que calcula no dibuja.
- Funciones puras que reciben y devuelven grafos; sin estado global.
- Las funciones de `viz.py` devuelven la figura (`matplotlib.figure.Figure`) en vez de llamar a `plt.show()`.
- Dependencias de un solo sentido: `viz` y `analysis` → `graphs`; nunca al revés.
- Los scripts de la raíz (`graph.py`, `di_graph.py`, `tuto.py`) son prototipos: al consolidarlos, mover la lógica a `src/` y dejar el script como un punto de entrada fino.

## Al añadir un módulo
1. Crear el archivo en `src/networkx_project/`.
2. Añadir su test en `tests/test_<modulo>.py` (ver skill `testing`).
3. Si requiere dependencias nuevas, añadirlas a `pyproject.toml` y justificarlo.
4. Actualizar la tabla de estructura en `AGENTS.md` si cambia el layout.
