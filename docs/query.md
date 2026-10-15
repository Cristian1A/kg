# Querying the graph: `kg query` and `kg impact`

Ask the store about entities, their relations and the effect of a change,
without reading `.kg/graph.json` by hand (RF-40–RF-43, CU-02, CU-03, CU-05).
Results are deterministic for the same graph and options. Every node reached
comes with the edges that justify it and their provenance, and every answer
states what it may be missing.

```bash
kg query node module:app.core                 # a node, its attributes and neighbors
kg query find payment --type Function         # find IDs by name, ID or description
kg query path module:app.api dependency:requests
kg query untested                             # code with no `tests` edge (CU-02)
kg query tested --type Module                 # code with tests, and which tests
kg query undocumented --type Module,Package   # code no document points to (CU-03)
kg impact function:app.core.charge            # what a change may affect (CU-05)
```

All of them take `--json` (one object on stdout, see *JSON output*) and
`--kg-dir`. An unknown ID is a usage error (exit code `2`) with the closest
ID as a suggestion:

```text
error: no node 'function:kg.merge.merge_doc' in the graph
  suggestion: Did you mean "function:kg.merge.merge_document"?
```

## `kg query node <ID>`

The node's fields, then its neighbors: one line per edge, with its direction,
relation and provenance (`method`, `confidence`).

```text
module:kg.merge (Module)
  label: merge
  description: Basic merge by ID of a document into the graph (RF-21, RF-30, S-03).
  provenance: parser (python-ast@0.1, confidence 1) from src/kg/merge.py
12 neighbors:
  <-[justifies]- decision:parser-wins-over-llm (Decision)  [llm, 1]
  -[imports]-> dependency:networkx (Dependency)  [parser, 1]
  <-[documents]- document:docs/store.md (Document)  [llm, 0.9]
  ...
```

| Option | Effect |
|--------|--------|
| `--direction out\|in\|both` | Edges to follow (default `both`) |
| `--relation R1,R2` | Only these relation types |
| `--type T1,T2` | Only list nodes of these types; others are still walked through |
| `--depth N` | Up to N edges away (default 1). Deeper nodes show the edges that lead to them |

## `kg query find [TEXT]`

IDs whose label, ID or description contains `TEXT` (case-insensitive), ranked
like the HTML search: an exact name or ID, then names that start with it,
names that contain it, IDs, and descriptions last. Narrow it with
`--type T1,T2` and `--attr KEY=VALUE` (repeatable; `VALUE` is JSON if it
parses, e.g. `--attr public=false`). At least one of the three is required.

## `kg query path <FROM> <TO>`

The shortest chain of edges between two nodes. It first looks for a path
whose edges all point from `FROM` towards `TO` (`forward`), then one whose
edges all point back (`backward`), and only then mixes directions (`mixed`).
Each step keeps the real direction of its edge. `--relation` limits the
edges a path may use. If there is none: `no path between … in the graph`.

## `kg query untested`, `tested` and `undocumented`

The predefined queries for the reference questions (RF-42):

- **`untested`** (CU-02): public `Function` and `Class` nodes with no
  incoming `tests` edge, leaving out test files and `conftest.py`. The
  `tests` edges come from a static heuristic (see
  [extract.md](extract.md#tests)): a result means "no test refers to it
  directly", not "never runs under tests". `--type Module,Package` checks
  modules: a module is tested when a test module imports it.
- **`tested`**: the complement, each element with the tests that point to it
  (`<-[tests]- test:…`). For the same options, `tested` and `untested` split
  the same set, so one call to each is enough to check an answer. Both say
  what counts as tested (`criterion` in JSON).
- **`undocumented`** (CU-03): public `Package`, `Module`, `Class` and
  `Function` nodes that no `documents` edge points to. A docstring is not a
  document: it is the node's `description`.

All three take `--type T1,T2` and `--include-private`. Documents that mention
something missing from the code are recorded by agents as `Issue` nodes that
`documents` the document (see `kg guide`): list them with
`kg query find --type Issue`.

## `kg impact <ID>`

Elements that **may** be affected by a change in the given one (RF-41). They
are possible effects, not certain ones: the output says so, and each result
carries the path of relations that justifies it, its depth and, in `--json`,
the weakest `confidence` along the path and the provenance methods involved.

```text
a change in function:app.util.helper may affect 2 elements (possible effects, not certain ones):
  module:app.util (Module)  [direct]
      file:app/util.py -[defines]-> function:app.util.helper  [parser, 1]
      file:app/util.py -[defines]-> module:app.util  [parser, 1]
  module:app.core (Module)  [depth 2]
      file:app/util.py -[defines]-> function:app.util.helper  [parser, 1]
      file:app/util.py -[defines]-> module:app.util  [parser, 1]
      module:app.core -[imports]-> module:app.util  [parser, 1]
```

How a change propagates:

- **Relations, walked backwards.** If `A -[imports]-> B`, a change in `B` may
  affect `A`. The default relations are `calls`, `depends_on`, `documents`,
  `implements`, `imports`, `justifies` and `tests`: whatever uses, tests,
  documents or justifies the changed element. `--relation R1,R2` replaces the
  list; custom relations (e.g. an agent's `affects`) only propagate when
  listed there.
- **Containment.** A changed class or function also changes what defines it:
  a method reaches its class, and a top-level class or function reaches the
  module of its file. From there, whatever imports that module is reached.
  `--no-containment` turns this off.
- **Breadth-first**, so each element appears once, with its shortest path.
  `--depth N` stops N edges away (a containment hop counts as one); by
  default there is no limit.
- `Repo` and `File` nodes are never results: the repo would match
  everything, and a file is represented by its module.
- `--type T1,T2` lists only results of these types; the walk still goes
  through the others. Tests are often most of the results (109 of 125 for a
  change in `kg.schema.validation`), so `--type Module,Package` keeps an
  answer short. The text ends with `left out by --type: Test 109, …` and the
  JSON gives the same counts in `omitted`.

The default relations are a starting point. `calls` edges are not extracted
yet (RF-13), so a change to a function reaches the modules that import its
module, not only the functions that call it.

## Coverage limits

The graph never holds everything, so every answer ends with notes on what it
may be missing (RF-43). An empty answer reads "no relation found in the
graph", never "no dependency".

| Code | When |
|------|------|
| `stale_graph` | The code changed since the last `kg extract` (the files are listed; see `kg status`) |
| `freshness_unknown` | The store is not inside its repo (`--kg-dir` elsewhere), so freshness could not be checked: run `kg status <repo>` |
| `unread_files` | Extracted files that could not be fully read (e.g. a syntax error): their classes, functions and imports may be missing |
| `missing_relations` | Relation types the answer relies on that have no edge in the graph, e.g. `calls`, or `documents` before an agent added documents |

The freshness check takes the parent of the store directory as the repo
root, as `kg init` creates `.kg/` inside the repo (RF-70).

## JSON output

`--json` returns the usual envelope (`ok`, `command`, `result`). The
`result` of each query:

| Command | `result` |
|---------|----------|
| `query node` | `node` (stored fields), `neighbors` (results), `limits` |
| `query find` | `nodes` (`id`, `type`, `label`) |
| `query path` | `found`, `direction` (`forward`, `backward`, `mixed` or `null`), `path` (steps), `source`, `target`, `limits` |
| `query untested` | `nodes`, `criterion`, `limits` |
| `query tested` | `nodes` (each with `tests`: the IDs of its tests), `criterion`, `limits` |
| `query undocumented` | `nodes`, `limits` |
| `impact` | `id`, `depth`, `relations`, `containment`, `types` (`null` without `--type`), `results`, `omitted` (left-out results by type), `limits` |

A **result** is `{id, type, label, depth, direct, confidence, methods,
path}`; a **step** is `{source, target, type, method, confidence}`; a
**limit** is `{code, message}` plus `files` or `relations` where they apply.
These keys are stable: agents can rely on them.
