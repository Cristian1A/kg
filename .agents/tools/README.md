# Agent tools

Helper scripts that agents can run. Each tool must be:

- **Self-contained**: one file, runnable with `python .agents/tools/<tool>.py`.
- **Non-interactive**: arguments via CLI, output to stdout (JSON preferred).
- **Safe**: no destructive side effects; if it writes files, only to a path given as an argument.

## Available tools

| Tool | Description | Usage |
|------|-------------|-------|
| `graph_summary.py` | Counts by type, density and hubs of a kg store | `python .agents/tools/graph_summary.py [--kg-dir .kg] [--top 10]` |

## Adding a tool
1. Create `<name>.py` with `argparse` and a `main()`.
2. Document it in the table above.
3. External tools (APIs, databases, browser) go in `.mcp.json`, not here.
