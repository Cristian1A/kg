# kg — turn a codebase into a knowledge graph

`kg` is a command-line tool, for humans and AI agents, that turns what a
software project knows about itself — code, dependencies, docs, tests, design
decisions — into a **knowledge graph** you can query, visualize and export.

The graph lives inside the repo (`.kg/graph.json`), as readable, deterministic
JSON that is versioned with git like any other file.

> **Status: early development (v0.1 MVP in progress).** The schema,
> validation, the store, extraction (code, dependencies and tests) and
> static rendering are in place; the interactive HTML is next.
> See the [roadmap](#roadmap).

## Why

- **Ask real questions about a project.** Which code has no tests? Is the
  documentation in line with the code? Where would these new requirements
  fit? An agent can answer them reliably when it reasons over a graph instead
  of grepping files.
- **Two ways in, one graph.** A deterministic parser extracts the structure
  (files, modules, functions, imports, dependencies), and an external agent
  adds what only a reader understands (docs, decisions, concepts). Both write
  the same JSON format and are merged by stable IDs.
- **Built for agents.** Every command has `--json` output, and validation
  errors carry a JSON path, the received and expected values and a suggestion,
  so an agent can fix its own output in one iteration.
- **Traceable.** Every node and edge records its provenance: where it came
  from, how (`parser`, `llm`, `manual`) and with what confidence.
- **Offline and LLM-free.** `kg` never calls a model or sends data anywhere.
  Agents use it as a tool.

## Install

Requires Python ≥ 3.12 (Linux). Not on PyPI yet:

```bash
git clone https://github.com/Cristian1A/kg.git
cd kg
python -m venv env && source env/bin/activate
pip install -e ".[dev]"
kg --help
```

## Quick start

```bash
kg init                  # create .kg/graph.json in the current repo
kg schema                # print the JSON Schema an agent should follow
kg validate graph.json   # check a document without touching the store
kg add graph.json        # validate and merge it into the store
```

A minimal input document:

```json
{
  "version": "1",
  "nodes": [
    {
      "id": "function:size.main",
      "type": "Function",
      "label": "main",
      "provenance": { "method": "parser", "extractor": "python-ast@0.1", "confidence": 1.0 }
    },
    {
      "id": "document:README.md",
      "type": "Document",
      "provenance": { "method": "llm", "extractor": "claude-code", "confidence": 0.8 }
    }
  ],
  "edges": [
    {
      "source": "document:README.md",
      "target": "function:size.main",
      "type": "documents",
      "provenance": { "method": "llm", "extractor": "claude-code", "confidence": 0.7 }
    }
  ]
}
```

When something is wrong, `kg` says exactly what and how to fix it:

```text
$ kg validate graph.json
error: graph.json is not valid: 1 error
error: $.edges[0].target: the edge points to a node that does not exist in the file
  received:   "function:size.mian"
  expected:   the ID of a node declared in `nodes`
  suggestion: Did you mean "function:size.main"? Fix the ID or add the node to `nodes`.
```

Adding the same document twice changes nothing, and conflicts are reported:

```text
$ kg add graph.json
graph.json merged into .kg/graph.json
  nodes: 1 added, 1 merged, 0 unchanged
  edges: 1 added, 0 merged, 0 unchanged
  1 conflict:
    function:size.main · label: "main" → "main(file)"
```

## Data model

- **Nodes** have a stable ID `<type>:<path|qualified name|slug>`
  (`file:src/app/main.py`, `function:app.main.run`, `decision:use-networkx`).
- **Standard catalog** of entity types (`Repo`, `Module`, `File`, `Function`,
  `Dependency`, `Test`, `Document`, `Decision`, `Concept`…) and relation types
  (`contains`, `imports`, `defines`, `calls`, `documents`, `tests`,
  `justifies`…). Custom types are allowed and produce a warning.
- The graph is an `nx.MultiDiGraph`; an edge is identified by
  (`source`, `target`, `type`).

Details in [docs/schema.md](docs/schema.md), [docs/store.md](docs/store.md),
[docs/extract.md](docs/extract.md) and [docs/render.md](docs/render.md).

## Roadmap

| Command | What it does | Status |
|---------|--------------|--------|
| `kg schema` | Print the input JSON Schema | ✅ |
| `kg validate` | Validate a document with actionable errors | ✅ |
| `kg init` | Create the `.kg/` store | ✅ |
| `kg add` | Merge a document into the store by ID | ✅ |
| `kg extract` | Deterministic extraction of a Python repo | ✅ |
| `kg render` | PNG/SVG image and interactive offline HTML | PNG/SVG ✅, HTML 🚧 v0.1 |
| `kg query`, `kg impact` | Neighbors, paths, transitive impact | v0.2 |
| `kg export` | Mermaid and Graphviz DOT | v0.2 |
| MCP server | Expose the operations as agent tools | v0.2 |

Full requirements: [docs/requirements.md](docs/requirements.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) (Conventional Commits, branch naming,
issue templates) and [AGENTS.md](AGENTS.md) for rules that AI coding agents
follow in this repo.

```bash
pytest && ruff check . && ruff format --check .
```

## License

[MIT](LICENSE)
