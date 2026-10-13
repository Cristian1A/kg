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
├── schema/        # JSON Schema and validation                        (#2, #3)
├── store.py       # .kg/ store (deterministic read/write)              (#4)
├── merge.py       # merge by ID, `kg add`                              (#5)
├── edit.py        # `kg remove`, `kg edit`                             (#28)
├── extract/       # deterministic extractors (code, deps, tests)       (#6–#8)
├── update.py      # `kg extract` replaces the parser layer; `kg status` (#37)
├── analysis.py    # queries over the stored graph (untested code…)     (#8)
├── render/        # PNG/SVG with matplotlib, HTML with vis-network     (#9, #10)
└── agents/        # `kg guide`: guidelines and skill for agents        (#11)
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
- One-way dependencies: `render`, `analysis`, `edit` and `merge` → `store`/`schema`; never the other way round.
- No loose scripts at the root: new code goes in `src/kg/`, helper scripts for agents in `.agents/tools/`.

## When adding a module
1. Create the file in `src/kg/`.
2. Add its test in `tests/test_<module>.py` (see the `testing` skill).
3. If it needs new dependencies, add them to `pyproject.toml` with a justification.
4. Update the layout table in `AGENTS.md` if the layout changes.
