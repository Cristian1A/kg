# AGENTS.md

General rules for any agent (Claude Code, Codex, Copilot, etc.) working in this repository.

## Project

**kg**: a CLI (for humans and AI agents) that turns a project's knowledge —code, dependencies, docs, tests, decisions— into a knowledge graph that can be queried, visualized and exported. Python 3.12 + NetworkX. Requirements in `docs/requirements.md`.

## Layout

| Path | Contents |
|------|----------|
| `src/kg/` | Package source code and the `kg` CLI |
| `tests/` | pytest tests |
| `bench/` | Benchmark: an agent answers questions from the code vs. from the graph (calls an LLM; see `bench/README.md`) |
| `examples/` | Example JSON files, valid against the schema (`kg schema`) |
| `.agents/skills/` | Specialized skills (read the relevant `SKILL.md` before acting) |
| `.agents/tools/` | Helper scripts for agents |
| `.mcp.json` | MCP servers (external tools) |
| `samples/` | Third-party repos cloned for manual testing (ignored by git; see `samples/README.md`) |
| `env/` | Virtual environment — **do not modify or read** |

## Environment

```bash
source env/bin/activate
pip install -e ".[dev]"
kg --help          # or: python -m kg --help
pytest && ruff check . && ruff format --check .
```

## Rules

1. **Read the right skill** in `.agents/skills/<name>/SKILL.md` before testing, data-analysis or architecture tasks.
2. New code goes in `src/kg/`; loose scripts at the root are for exploration.
3. Every logic change comes with its test in `tests/`. Run `pytest` before calling something done.
4. Use type hints and short docstrings. Format and lint with `ruff`.
5. Do not add dependencies without justification; declare them in `pyproject.toml`.
6. No commits, pushes or file deletions without the user's confirmation.
7. Never call `plt.show()` in library code or tests (it blocks execution); return or save the figure.
8. Everything versioned or published (code, CLI messages, docs, commits, issues, PRs) is in **English**. Reply to the user in the language they write in.
9. Commits, branches and issues follow `CONTRIBUTING.md` (Conventional Commits, reference to an issue and to RF-xx).
10. Secrets live in `.env` (in `.gitignore`). **Never** print, copy or commit its contents; load it with `set -a; source .env; set +a` and use the variable.

## Reference docs

- `docs/requirements.md` — approved functional requirements (RF-xx / RNF-xx).
- `docs/discovery.md` — the client interview behind the requirements (the *why*).
- `docs/roadmap.md` — action plan for v0.2 and v0.3: order of the issues, dependencies, exit criteria.
- `docs/schema.md` — JSON input format: IDs, standard catalog, provenance, validation.
- `docs/store.md` — the `.kg/` store: `graph.json` format, deterministic ordering, `kg add` merge rules, `kg remove` and `kg edit`.
- `docs/extract.md` — `kg extract`: which files are read, the nodes, IDs and relations it produces.
- `docs/query.md` — `kg query` and `kg impact`: lookups, paths, impact rules, coverage limits, JSON output.
- `docs/render.md` — `kg render`: visual encoding, limits for large graphs, determinism.
- `docs/benchmark.md` — the v0.2 benchmark report: does the graph help an agent, and what it means for v0.3.
- `kg guide` (source: `src/kg/agents/guide.md`) — how an agent adds documents, decisions and concepts to a graph. Exported as `.agents/skills/kg-graph/SKILL.md`: regenerate it with `kg guide --skill > .agents/skills/kg-graph/SKILL.md` after editing the guide.
