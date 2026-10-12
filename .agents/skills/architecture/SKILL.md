---
name: architecture
description: Decisions about code structure, modules and dependencies. Use it when creating new modules, refactoring or moving exploration scripts into src/.
---

# Architecture

## Layout
```
src/kg/
├── __init__.py    # __version__
├── __main__.py    # python -m kg
├── cli.py         # argparse: subcommands, --json, --kg-dir, exit codes
├── graphs.py      # graph building (pure functions returning nx.Graph/DiGraph)
├── schema/        # JSON Schema and validation                       (#2, #3)
├── store.py       # .kg/ store (deterministic read/write)              (#4)
├── merge.py       # merge by ID and `kg add`                          (#5)
├── extract/       # deterministic extractors (python, deps, tests)    (#6–#8)
└── render/        # PNG/SVG with matplotlib, HTML with pyvis          (#9, #10)
```

## CLI
- Each subcommand is a *handler* `(argparse.Namespace) -> Result` registered in `build_parser()`.
- The logic lives in its module; the handler only translates arguments and returns `Result(message, data)`.
- Errors are raised as `KgError` (or `ValidationError`/`UsageError`); never `sys.exit()` or `print()` outside `cli.py`.
- Exit codes: 0 OK, 1 validation, 2 usage, 3 internal. With `--json`, a single JSON object on stdout.
- Modules raise their own exceptions (e.g. `StoreError`); `cli.py` maps them to `KgError`. Dependencies point one way: `cli` → modules, never the reverse.

## Principles
- **Separate building, analysis and visualization.** A function that computes does not draw.
- Pure functions that take and return graphs; no global state.
- Plotting functions return the figure (`matplotlib.figure.Figure`) instead of calling `plt.show()`.
- One-way dependencies: `render` and `analysis` → `graphs`/`store`; never the other way round.
- Root scripts (`graph.py`, `di_graph.py`, `tuto.py`) are prototypes (excluded from ruff): when consolidating them, move the logic into `src/` and leave the script as a thin entry point.

## When adding a module
1. Create the file in `src/kg/`.
2. Add its test in `tests/test_<module>.py` (see the `testing` skill).
3. If it needs new dependencies, add them to `pyproject.toml` with a justification.
4. Update the layout table in `AGENTS.md` if the layout changes.
