# Building a kg knowledge graph as an agent

`kg` turns a project's knowledge into a graph. A deterministic parser
(`kg extract`) already maps the **code**: repo, packages, modules, files,
classes, functions, tests, dependencies and configuration. Your job as an
agent is to add what a parser cannot see: **what the documents say, why
things are the way they are and what the domain is about**. `kg` never calls
an LLM; you do the reading and send it JSON.

Print this guide with `kg guide`, and the JSON Schema with `kg schema`.

## The loop

```bash
kg init                                   # once: creates .kg/
kg extract .                              # the parser's part (rerun when code changes)
kg status                                 # is the graph up to date with the code?
kg render --html -o kg-graph.html         # look at what is already there
# ... write draft.json (see below) ...
kg add draft.json --dry-run --json        # validate against the store, change nothing
# ... fix every error, repeat until "ok": true ...
kg add draft.json                         # merge it
kg render --html -o kg-graph.html         # review the result
```

- Use `kg add --dry-run`, not `kg validate`, for documents that point to
  extracted nodes: `kg validate` only sees the file, so an edge to
  `function:app.main.run` looks broken there. `--dry-run` checks against the
  store and shows what would be added, merged and in conflict.
- Every error has `path`, `received`, `expected` and `suggestion`. Fix exactly
  what it says and run again; a typo in an ID comes with
  `Did you mean "..."?`.
- Warnings (`custom_type`, `id_prefix_mismatch`, `missing_description`) do
  not block, but read them: keep a custom type only if no standard type fits,
  and add the description `missing_description` asks for.
- Adding the same document twice changes nothing. Send corrections as a new
  version of the same elements (same IDs); use `kg edit` and `kg remove` to
  change or delete what is already stored.

## Read the store before writing

Reuse the IDs that exist. Look them up instead of guessing:

```bash
kg query find size                     # by name, ID or description
kg query find --type Module            # every module
kg query node module:size              # a node and what it is linked to
```

If `kg status` lists changed files, run `kg extract .` before reading or
answering from the graph. It removes what the code no longer has; if an
element you linked to is gone, it is kept and reported. Send your edges again
with the new ID (`kg add`), then `kg remove <old ID>`; if the knowledge no
longer applies, only remove it.

Never re-create what the parser produces: no `module:`, `class:`,
`function:`, `file:`, `test:` or `dependency:` nodes of your own, and no
`config:` node for `pyproject.toml` or `requirements*.txt`. Point your edges
at them. If the parser got something wrong, say so to the
user instead of overriding it: `kg add` keeps the parser's provenance and the
next `kg extract` restores its values. The one exception is adding a
description to extracted code that has none (see *Descriptions*).

## What to look for (minimum)

Walk the README, `docs/`, ADRs, changelogs, module docstrings and the code
itself. At least:

| You find | Add | ID | Edges |
|----------|-----|----|-------|
| A document that explains code (README, `docs/*.md`, ADR) | `Document` | `document:<path>` | `Document -[documents]-> Module/Class/Function/Endpoint`, one per element it explains, with the lines of the passage |
| A design choice and its reason ("we use X because Y", ADRs) | `Decision` | `decision:<slug>` | `Decision -[justifies]-> Dependency/Module/…` it explains |
| A domain idea the code implements (an order, a fee, "size in MB") | `Concept` | `concept:<slug>` | `Function/Class -[implements]-> Concept` |
| An HTTP route, CLI command or job | `Endpoint` | `endpoint:<METHOD> <path>` or `endpoint:<command>` | `Function -[implements]-> Endpoint`; `Service -[contains]-> Endpoint` |
| A deployable unit (an API, a worker) | `Service` | `service:<slug>` | `Service -[contains]-> Endpoint`, `Service -[depends_on]-> Dependency` |
| Configuration the parser does not read (CI workflows, `docker-compose.yml`, `.env.example`, tool configs) | `Config` | `config:<path>` | `Config -[configures]-> Repo/Service/Module` it sets up or runs |
| A tracked task or bug the docs mention | `Issue` | `issue:<number or slug>` | `Issue -[documents]->` what it is about |
| An author named in the docs | `Person` | `person:<slug>` | `Module/Document -[authored_by]-> Person` |

These are what the three reference questions need:

- **Which tests are missing?** `kg extract` already links tests to code with
  `tests` edges; `kg query untested` lists code with none. You add
  nothing for it, but read the list critically: code reached only through
  fixtures or other functions also shows up.
- **Is the documentation in line with the code?** Needs `Document` nodes and
  `documents` edges with `source` and `lines`. When a document names
  something that does not exist in the graph, do **not** invent a node for
  it: report it, or record it as an `Issue` that `documents` the document.
- **How can the project be extended with these requirements?** Needs
  `Decision`, `Concept` and `Service`/`Endpoint` nodes, so the responsibilities
  and constraints of each module are visible. New requirements can be added
  as a custom type: `Requirement` (`requirement:<slug>`), linked to the
  modules that would change with a custom `affects` relation.

## Answering questions with the graph

Once the graph is built, use it to answer questions about the repo, and back
every claim with the IDs and edges the commands return:

| Question | Command |
|----------|---------|
| What is X, and what is it linked to? | `kg query node <id>` (`--depth 2` for more) |
| Where is X? Which nodes are about Y? | `kg query find <text>`, `--type`, `--attr` |
| How are X and Y related? | `kg query path <x> <y>` |
| Which tests are missing? | `kg query untested` (`--type Module` for modules) |
| Which tests cover what? | `kg query tested`: each element with its tests |
| Which code has no documentation? | `kg query undocumented` |
| What may break if X changes? | `kg impact <id>` (`--depth`, `--relation`, `--type`) |

- Add `--json` to read results reliably; every result carries its `path` of
  edges, each with its provenance `method` and `confidence`.
- `kg impact` lists **possible** effects. Say "may be affected", quote the
  path that justifies each one, and give less weight to paths through
  low-confidence `llm` edges. Tests are often most of the results: use
  `--type Module,Package` (or the types you need) and read `omitted` for the
  rest.
- `untested` and `tested` split the same code: one call to each checks an
  answer, without walking the tests one by one. Their `criterion` says what
  counts as tested.
- Read the `note:` lines (`limits` in JSON) before answering: a stale graph,
  files that could not be read or relation types the graph lacks (no `calls`
  edges, for instance) mean the answer may be incomplete. Say so.
- An empty result means "nothing in the graph", not "nothing in the code".
  Check the code when it matters.

## Standard catalog and custom types

Entities: `Repo`, `Package`, `Module`, `File`, `Class`, `Function`,
`Dependency`, `Test`, `Document`, `Config`, `Service`, `Endpoint`, `Person`,
`Issue`, `Decision`, `Concept`.

Relations: `contains`, `imports`, `depends_on`, `defines`, `calls`,
`documents`, `tests`, `configures`, `authored_by`, `implements`, `justifies`
(Decision → entity).

Use a **custom type** only when no standard one fits: entities in PascalCase
(`Requirement`, `Tutorial`), relations in snake_case (`affects`, `links_to`).
They are valid and produce a warning. Do not create near-synonyms of standard
types (`Doc`, `Function_`, `uses` for `depends_on`).

## IDs

`<type in lowercase>:<path | qualified name | slug>`, always the same for
the same thing, so that adding twice merges instead of duplicating.

- Files and documents: the path from the repo root, with `/`
  (`document:docs/architecture.md`).
- Code: the qualified name, as the parser writes it (`function:app.core.run`).
- Everything else: a short **ASCII kebab-case slug in English**, stable even
  when labels are in another language: `concept:size-in-mb` with
  `"label": "Tamaño en MB"`.
- Check every edge's `source` and `target` against the store or your own
  `nodes` before sending.

## Text: one language

Every human-readable text you write (`label`, `description`, free-text
values in `attrs`) uses **one language**: the one the user asks for, or else
the language of the project's documentation. Do not mix languages in the same
graph, and translate titles you quote from documents only if the user asks.
IDs and type names stay as above (ASCII, English slugs).

- `label`: short, a few words, what a person would call it.
- `description`: one or two sentences with the substance (see below).
- `attrs`: facts worth querying (`{"status": "accepted", "date": "2025-03"}`
  for a Decision), not prose.

## Descriptions

Descriptions are what make the graph fast to search and understand: a node
with only an ID and a label sends the reader, person or agent, back to the
source files. The HTML search also matches them.

**Every node you create has a `description`**: one or two sentences, in the
graph's language, saying what the element is and why it matters. Do not
repeat the label. `kg add` warns with `missing_description` when an `llm`
node has none.

**Describe the main extracted nodes that lack one.** The parser takes
descriptions from docstrings, so code without docstrings has none. For the
packages, modules and important classes without a description (not every
function), send the existing ID with its type, your description and your
provenance:

```json
{ "id": "module:size", "type": "Module",
  "description": "Command-line entry point: prints the size of a file in MB.",
  "provenance": { "method": "llm", "extractor": "claude-code", "confidence": 0.85, "source": "size.py", "lines": [1, 12] } }
```

- The node keeps the parser's provenance: `--dry-run` reports it as a
  conflict with `kept` set to the old value. That is expected.
- If the code later gets a docstring, the next `kg extract` replaces your
  description with it.
- Leave nodes that already have a description alone.

## Provenance

Every node and edge you send carries:

```json
{ "method": "llm", "extractor": "<your name, e.g. claude-code>", "confidence": 0.8,
  "source": "docs/architecture.md", "lines": [12, 20] }
```

- `method` is `llm`. Never `parser`; `manual` is for people.
- `source` and `lines` point to the evidence (1-indexed, inclusive). Always
  give them when the claim comes from a file.
- `confidence`:

  | Value | When |
  |-------|------|
  | 0.9–1.0 | The source states it explicitly ("we chose PostgreSQL because…") |
  | 0.7–0.9 | Clearly implied by the source or by unambiguous code |
  | 0.5–0.7 | Your inference from several hints |
  | < 0.5 | Do not add it; mention it to the user instead |

- `timestamp` is optional (ISO-8601 with time zone). Leave it out if the
  graph should be reproducible.

## Example

For a repo whose README explains `size.py` and states that the CLI avoids
external dependencies on purpose:

```json
{
  "version": "1",
  "nodes": [
    {
      "id": "document:README.md",
      "type": "Document",
      "label": "README",
      "description": "Explains how to run the size CLI and why it has no dependencies.",
      "provenance": { "method": "llm", "extractor": "claude-code", "confidence": 0.95, "source": "README.md", "lines": [1, 20] }
    },
    {
      "id": "decision:no-external-dependencies",
      "type": "Decision",
      "label": "No external dependencies",
      "description": "The CLI uses only the standard library so it runs anywhere.",
      "attrs": { "status": "accepted" },
      "provenance": { "method": "llm", "extractor": "claude-code", "confidence": 0.9, "source": "README.md", "lines": [8, 9] }
    },
    {
      "id": "concept:size-in-mb",
      "type": "Concept",
      "label": "File size in MB",
      "description": "Size in bytes divided by 1024², rounded down.",
      "provenance": { "method": "llm", "extractor": "claude-code", "confidence": 0.85, "source": "size.py", "lines": [4, 7] }
    },
    {
      "id": "module:size",
      "type": "Module",
      "description": "Command-line entry point: prints the size of a file in MB.",
      "provenance": { "method": "llm", "extractor": "claude-code", "confidence": 0.85, "source": "size.py", "lines": [1, 12] }
    }
  ],
  "edges": [
    {
      "source": "document:README.md", "target": "module:size", "type": "documents",
      "provenance": { "method": "llm", "extractor": "claude-code", "confidence": 0.9, "source": "README.md", "lines": [3, 12] }
    },
    {
      "source": "decision:no-external-dependencies", "target": "module:size", "type": "justifies",
      "provenance": { "method": "llm", "extractor": "claude-code", "confidence": 0.9, "source": "README.md", "lines": [8, 9] }
    },
    {
      "source": "function:size.main", "target": "concept:size-in-mb", "type": "implements",
      "provenance": { "method": "llm", "extractor": "claude-code", "confidence": 0.85, "source": "size.py", "lines": [4, 7] }
    }
  ]
}
```

`module:size` and `function:size.main` come from `kg extract`; the document
adds three new nodes, the edges that connect them and a description for
`module:size`, which has no docstring.

## Checklist before `kg add`

- [ ] `kg add --dry-run --json` returns `"ok": true`.
- [ ] No node duplicates something the parser extracts; edges use its IDs.
- [ ] Every node and edge has `method: llm`, your `extractor`, a calibrated
      `confidence`, and `source`/`lines` when it comes from a file.
- [ ] Every node you create has a `description`, and the main extracted
      nodes without one got one.
- [ ] All labels and descriptions are in one language.
- [ ] Custom types only where no standard type fits.
- [ ] Every `Document` has at least one `documents` edge; every `Decision` at
      least one `justifies` edge.
