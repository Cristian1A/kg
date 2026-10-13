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

## Removing and editing: `kg remove`, `kg edit`

The store only grows with `kg add` and `kg extract`; these commands delete and
modify elements without editing `graph.json` by hand (RF-75, RF-76).

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
