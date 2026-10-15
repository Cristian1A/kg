# The `.kg/` store

Where `kg` keeps the project graph (RF-70, RF-71). It lives inside the
analyzed repo and is versioned with its git: the format is designed to keep PR
diffs readable.

```bash
kg init                    # create .kg/ in the current directory
kg init --kg-dir path/.kg  # somewhere else (the parent directory must exist)
kg init --json             # {"ok": true, "result": {"kg_dir", "graph", "version"}}
```

`kg init` fails with exit code `2` if the path already exists (it is left
untouched) or if its parent directory does not exist.

## Adding entities and relations: `kg add`

```bash
kg add graph.json          # validate and merge into .kg/graph.json
cat graph.json | kg add -  # from stdin
kg add graph.json --json   # summary for agents
```

1. Loads the store (if there is none: exit code `2`, suggests `kg init`).
2. Validates the document like `kg validate`, with one difference: edges may
   point to nodes that are **already in the store**, not only to those in the
   file. This lets an agent add `documents` edges to functions created by
   `kg extract`.
3. If there are errors, nothing is modified (exit code `1`).
4. Merges by ID (RF-30) and saves. If nothing changes, the file is not
   rewritten: repeating the same `add` leaves the store identical.

### Merge rules (MVP)

| Case | Result |
|------|--------|
| Node with a new ID | Added |
| Node with an existing ID | Fields are combined; those missing from the document are kept |
| `attrs` | Combined per top-level key; nested values are replaced as a whole |
| Edge with a new (`source`, `target`, `type`) | Added |
| Existing edge | `attrs` and `provenance` combined as for nodes; never duplicated |
| Same field with a different value | **The new value wins** and is reported as a conflict |
| Existing `provenance` with `method: parser` and new one with `llm` or `manual` | **The parser's is kept** and reported as a conflict |

`provenance` is treated as a single value. The parser exception prevents
enrichment by an agent (`kg extract` → `kg add`) from wiping out the
deterministic data; if only the provenance differed, the element counts as
"unchanged". Note that other fields are still updated, so provenance
describes the origin of the element, not of each field. Keeping several
provenances is RF-31 and a configurable conflict policy is RF-33, both
planned for v0.3.

### Summary

```text
graph.json merged into .kg/graph.json
  nodes: 2 added, 1 merged, 9 unchanged
  edges: 4 added, 0 merged, 9 unchanged
  2 conflicts:
    function:size.main · label: "main" → "main(file)"
    function:size.main · provenance: kept parser (python-ast@0.1, confidence 1.0); discarded llm (claude-code, confidence 0.85)
```

With `--json`, `result` contains `changed`, `nodes` and `edges` (lists
`added`, `merged` and `unchanged`; edges as `source -[type]-> target`),
`conflicts` (`kind`, `element`, `field`, `old`, `new` and `kept`: `"new"` or
`"old"`, the value that stays) and the validation `warnings`. If the document
is not valid, the error carries the same `details` as `kg validate`.

## Updating after code changes: `kg extract`

`kg extract` (see [extract.md](extract.md)) owns the **derived layer**: the
nodes and edges whose provenance is `method: parser` with one of its
extractors (`python-ast`, `pyproject`, `requirements`, any version). Every run
replaces that layer, so the graph follows the code (RF-72):

1. The repo is extracted. If extraction fails, the store is not touched.
2. Derived elements that the new extraction does not produce are removed:
   deleted functions, classes and files, and the edges that no longer exist.
   A renamed or moved element gets a new ID (IDs come from paths and qualified
   names), so a rename or a move is a removal plus an addition.
3. The new extraction is validated and merged as in `kg add`.
4. The store is written once, atomically, and only if something changed.

What is **never removed**:

| Element | Why |
|---------|-----|
| `llm` and `manual` nodes and edges | Knowledge from agents and people |
| `parser` elements of other extractors | They belong to another tool |
| Elements of a file that was skipped this time (syntax error, unreadable) | The file could not be read; they are removed once it can be, if they are gone |
| A derived node that an agent or manual edge still uses | Removing it would break that edge. It is kept and reported until the edge is fixed |

```text
extracted 4 files from . into .kg/graph.json
  nodes: 5 added, 1 merged, 5 unchanged
  edges: 8 added, 0 merged, 7 unchanged
  removed: 3 nodes, 6 edges the code no longer has
  kept 1 node the code no longer has, because agent edges use them (re-add the edges to the new ID with `kg add`, then `kg remove` the old node):
    function:app.util.old
      function:app.util.old -[implements]-> concept:legacy
```

To resolve a kept node, add the agent's edges again pointing at the new
element (`kg add` with `function:app.tools.old` as the source), then
`kg remove function:app.util.old`, which also drops its old edges. If the
knowledge no longer applies, `kg remove` alone is enough. (`kg edit --id`
does not help here: the new ID already exists after the extraction.)

If the store also holds the derived `Repo` node of **another** repo (another
directory name), nothing is removed and a warning says so. This happens when
the repo directory is renamed: remove the old `repo:` node with `kg remove`
and extract again.

`--dry-run` reports what would be added, merged and removed without writing.
`--json` adds `changed`, `dry_run` and `removed` (`nodes`, `edges`,
`orphans` with their agent `edges`, `kept_skipped`, `other_repos`) to the
fields of `kg add`. A new `attrs.digest` is not reported as a conflict.

## Is the graph up to date? `kg status`

```bash
kg status            # the repo in the current directory
kg status path/repo  # another one; the store is still --kg-dir
kg status --json
```

```text
.kg/graph.json: 13 nodes, 16 edges (1 llm, 12 parser)
stale: . changed since the last `kg extract`
  modified (1): app/core.py
  added (2): app/new.py, app/tools.py
  deleted (1): app/util.py
run `kg extract .` to update the graph
```

`kg status` compares the `attrs.digest` of the `File` and `Config` nodes with
the files `kg extract` would read now (RF-77). It needs neither git nor a
commit: a committed `.kg/graph.json` stays up to date as long as the code has
not changed since it was extracted. Files with no recorded digest (extracted
before kg recorded digests, or never read successfully) are listed as
`unknown`. It is read-only, and returns `0` whether the graph is stale or
not; `--json` has `stale`, `modified`, `added`, `deleted`, `unknown`,
`nodes`, `edges` and `methods` (nodes by provenance method). If the store
holds another repo, it fails with exit code `2`.

`kg status --check` exits with code `1` when files were modified, added or
deleted since the last extraction, for CI and hooks; the output is the same
(with `--json`, `ok` is still `true`). `unknown` files alone do not fail the
check: a file kg cannot read, such as one with a syntax error, never gets a
digest, so a new extraction would not clear it.

## Keeping the graph fresh

A graph describes the code at its last `kg extract`. Once the code moves on,
answers can miss what changed: `kg query` and `kg impact` warn
(`stale_graph`), but the graph cannot tell what is in a file it has not read.
An agent can still open the changed files, at a higher cost than with a
fresh graph ([benchmark](benchmark.md#update-reading-what-a-stale-graph-reports-52)).
The cheapest fix is to commit the graph with the code it describes.

The two layers of the graph are kept fresh differently:

- **The parser layer** (files, modules, imports, functions, tests) is
  deterministic, needs no model and takes seconds: automate it with a hook,
  and check it in CI.
- **The agent layer** (documents, decisions, concepts) is written by an agent;
  kg calls no model, so nothing regenerates it. `kg extract` keeps it, and
  reports agent edges whose endpoints disappeared. Review it when the code it
  describes changes.

**A pre-commit hook** (convenience). With [pre-commit](https://pre-commit.com),
add to `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/Cristian1A/kg
    rev: main        # better: a release tag or a commit
    hooks:
      - id: kg-extract   # or kg-status, to check without changing anything
```

`kg-extract` re-extracts the graph. Like a formatter, it fails the commit when
`.kg/graph.json` changes: add it and commit again, so every commit carries
code and graph that match. pre-commit sets unstaged changes aside first;
untracked files that git does not ignore are still read, as `kg extract`
always does. `kg-status` only runs `kg status --check`. Without the
framework, a plain `.git/hooks/pre-commit` can run
`kg extract . && git add .kg/graph.json`, but it reads the working tree,
unstaged changes included.

**A CI check** (guarantee): a stale graph cannot reach the main branch.

```yaml
# .github/workflows/kg.yml
name: Knowledge graph
on: [push, pull_request]
permissions:
  contents: read
jobs:
  fresh:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pipx install git+https://github.com/Cristian1A/kg.git
      - run: kg status --check
```

Install kg outside the repo, as here, or ignore the install directory in
`.gitignore`: a virtual environment inside the repo would be read as added
files. The digests compare contents, not timestamps, so a fresh checkout is
up to date.

**Not recommended: a workflow that commits the graph.** It adds a bot commit
after every push, can trigger other workflows in a loop, and needs write
access to the repo. A failing check and a hook give the same result without
any of that.

## Removing and editing: `kg remove`, `kg edit`

`kg add` only adds and `kg extract` only removes what the parser no longer
finds; these commands delete and modify any element without editing
`graph.json` by hand (RF-75, RF-76).

```bash
kg remove dependency:os entrypoint:size        # nodes, with all their edges
kg remove --edge file:size.py contains module:size
kg remove dependency:os --dry-run              # show what would go, write nothing

kg edit concept:size --label "Tamaño en MB" --description ""   # "" removes it
kg edit concept:size --set unit=MB --set precision=0 --unset old_key
kg edit concept:size --type Requirement
kg edit tutorial:build-a-cli --id tutorial:cli-sencillo        # edges follow
```

- **All or nothing**: if an ID, edge or attribute does not exist, nothing is
  changed (exit code `2`) and the error suggests the closest one
  (`Did you mean ID "module:size"?`).
- **Validated**: the result goes through the same validation as any store
  write; an invalid new ID is rejected (exit code `1`) and the file is left
  as it was.
- `--set KEY=VALUE` parses `VALUE` as JSON when it can (`3`, `true`,
  `["a"]`, `"quoted"`), otherwise keeps it as text. `--label`/`--description`
  with an empty string remove the field.
- `--id` renames the node and rewrites its edges. `--type` may leave an ID
  whose prefix no longer matches; that is a warning, as in `kg validate`.
- `provenance` is not changed: it records where the element came from.
- Edits are not protected from later merges: `kg extract` brings the parser's
  values back for elements it produces (e.g. a function's label), and a
  removed element that the parser still finds is added again. Remove or edit
  what the extractor does not produce, or what you also changed in the code.
  A derived node renamed with `--id` to an ID the parser does not produce is
  removed by the next `kg extract`, unless agent edges use it.
- `--dry-run` reports without saving; `--json` returns `graph`, `dry_run`,
  `saved` and, for `remove`, `nodes` and `edges` (as `source -[type]-> target`);
  for `edit`, `id`, `changed`, `changes` (`field`, `old`, `new`) and
  `edges_rewritten`.

## Layout

```
.kg/
└── graph.json   # graph nodes and edges
```

A single file: writes are atomic (temporary file + `rename`) and the graph is
never left half-written across two files. With one object per node/edge and a
fixed order, a change to an entity only touches its own lines.

## Format

`graph.json` is a **valid document of the input schema** (see
[schema.md](schema.md)), so it can be checked with
`kg validate .kg/graph.json`. The format version is the `version` field
(currently `"1"`, the same as the schema).

```json
{
  "version": "1",
  "nodes": [
    {
      "id": "dependency:networkx",
      "type": "Dependency",
      "attrs": {
        "spec": ">=3.7"
      },
      "provenance": {
        "confidence": 1.0,
        "extractor": "pyproject@0.1",
        "method": "parser",
        "source": "pyproject.toml"
      }
    }
  ],
  "edges": []
}
```

## Determinism (RNF-08)

The same graph produces the same file byte for byte, regardless of the order
in which its elements were added:

| What | Order |
|------|-------|
| Root | `version`, `nodes`, `edges` |
| Nodes | by `id` |
| Edges | by (`source`, `target`, `type`) |
| Node fields | `id`, `type`, `label`, `description`, `attrs`, `provenance` (missing ones are omitted) |
| Edge fields | `source`, `target`, `type`, `attrs`, `provenance` |
| Keys inside `attrs` and `provenance` | alphabetical, also in nested objects |
| Lists (`lines`, `attrs` values) | kept as they are |

Unescaped UTF-8 text (`ensure_ascii=False`), 2-space indentation, `\n` line
endings and a trailing newline. Fields outside the schema, such as `$schema`,
are not stored.

## In-memory model

`kg.store.load_graph()` returns an `nx.MultiDiGraph`:

- Node: key = `id`; attributes `type`, `label`, `description`, `attrs`,
  `provenance` (only those present).
- Edge: key = `type`, so its identity is (`source`, `target`, `type`) and
  there cannot be two identical ones. Attributes `type`, `attrs`,
  `provenance`.

```python
from pathlib import Path
from kg import store

graph = store.load_graph(Path(".kg"))  # validated against the schema
graph.edges["file:a.py", "function:a.f", "defines"]
store.save_graph(graph, Path(".kg"))  # validated before writing
```

## Errors

| Situation | Exception | In the CLI |
|-----------|-----------|------------|
| `kg init` on an existing path | `StoreExistsError` | exit code `2` |
| `kg init` without the parent directory | `StoreNotFoundError` | exit code `2` |
| No `.kg/graph.json` when loading | `StoreNotFoundError` (suggests `kg init`) | exit code `2` |
| The file does not conform to the schema | `StoreCorruptError` with the validation `Report` | exit code `1` |
| Two edges with the same identity | `StoreError` with the JSON path | exit code `2` |

`save_graph` writes nothing if the graph is not valid: the previous store is
left intact.
