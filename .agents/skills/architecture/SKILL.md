---
name: architecture
description: Decisiones de estructura del código, módulos y dependencias del proyecto. Úsala al crear módulos nuevos, refactorizar o mover scripts de exploración a src/.
---

# Arquitectura

## Layout
```
src/kg/
├── __init__.py    # __version__
├── __main__.py    # python -m kg
├── cli.py         # argparse: subcomandos, --json, --kg-dir, códigos de salida
├── graphs.py      # construcción de grafos (funciones puras que devuelven nx.Graph/DiGraph)
├── schema/        # JSON Schema y validación                         (#2, #3)
├── store.py       # almacén .kg/ (lectura/escritura determinista)    (#4)
├── merge.py       # fusión por ID                                    (#5)
├── extract/       # extractores deterministas (python, deps, tests)  (#6–#8)
└── render/        # PNG/SVG con matplotlib, HTML con pyvis           (#9, #10)
```

## CLI
- Cada subcomando es un *handler* `(argparse.Namespace) -> Result` registrado en `build_parser()`.
- La lógica vive en su módulo; el handler solo traduce argumentos y devuelve `Result(message, data)`.
- Los errores se lanzan como `KgError` (o `ValidationError`/`UsageError`); nunca `sys.exit()` ni `print()` fuera de `cli.py`.
- Códigos de salida: 0 OK, 1 validación, 2 uso, 3 interno. Con `--json`, un único objeto JSON en stdout.

## Principios
- **Separar construcción, análisis y visualización.** Una función que calcula no dibuja.
- Funciones puras que reciben y devuelven grafos; sin estado global.
- Las funciones de `viz.py` devuelven la figura (`matplotlib.figure.Figure`) en vez de llamar a `plt.show()`.
- Dependencias de un solo sentido: `viz` y `analysis` → `graphs`; nunca al revés.
- Los scripts de la raíz (`graph.py`, `di_graph.py`, `tuto.py`) son prototipos (excluidos de ruff): al consolidarlos, mover la lógica a `src/` y dejar el script como un punto de entrada fino.

## Al añadir un módulo
1. Crear el archivo en `src/kg/`.
2. Añadir su test en `tests/test_<modulo>.py` (ver skill `testing`).
3. Si requiere dependencias nuevas, añadirlas a `pyproject.toml` y justificarlo.
4. Actualizar la tabla de estructura en `AGENTS.md` si cambia el layout.
