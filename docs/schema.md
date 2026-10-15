# `kg` input schema

The JSON format used by deterministic extraction and by external agents to
describe entities and relations (RF-01, RF-02). The official schema is JSON
Schema draft 2020-12 and ships with the package:

```bash
kg schema            # print the schema
kg schema --path     # path of the installed file
kg schema --json     # {"ok": true, "result": {"path": ..., "schema": {...}}}
```

Source: `src/kg/schema/kg.schema.json`. Valid examples in `examples/`.

## Structure

```json
{
  "version": "1",
  "nodes": [{ "id": "...", "type": "...", "provenance": { ... } }],
  "edges": [{ "source": "<id>", "target": "<id>", "type": "...", "provenance": { ... } }]
}
```

| Field | Node | Edge | Notes |
|-------|:----:|:----:|-------|
| `id` | required | — | Stable ID (see below) |
| `source`, `target` | — | required | IDs of the nodes it connects |
| `type` | required | required | Standard catalog or custom |
| `label`, `description` | optional | — | Human-readable text |
| `attrs` | optional | optional | Object with free-form attributes |
| `provenance` | required | required | See *Provenance* |

No other fields are accepted: custom attributes go inside `attrs`.

## Stable IDs (PA-02)

`<type>:<path | qualified name | slug>`, with a lowercase prefix:

| Entity | ID |
|--------|----|
| File | `file:src/app/main.py` (path relative to the root, with `/`) |
| Module, class, function | `module:app.main`, `class:app.main.App`, `function:app.main.run` |
| Dependency | `dependency:networkx` |
| No physical origin | `concept:knowledge-graph`, `decision:use-networkx` |

The same element must always produce the same ID: that is how `kg add` merges
instead of duplicating (RF-30).

## Standard catalog

**Entities:** `Repo`, `Package`, `Module`, `File`, `Class`, `Function`,
`Dependency`, `Test`, `Document`, `Config`, `Service`, `Endpoint`, `Person`,
`Issue`, `Decision`, `Concept`.

**Relations:** `contains`, `imports`, `depends_on`, `defines`, `calls`,
`documents`, `tests`, `configures`, `authored_by`, `implements`, `justifies`
(Decision → entity).

Descriptions of each type: [requirements.md](requirements.md), sections 3.2
and 3.3.

## Custom types

A type outside the catalog is **valid**, but `kg` emits a warning so you can
check whether an equivalent standard type exists. Format: entities in
PascalCase (`Requirement`) and relations in snake_case (`satisfies`).

## Provenance

| Field | Required | Example |
|-------|:--------:|---------|
| `method` | yes | `parser` \| `llm` \| `manual` |
| `extractor` | yes | `python-ast@0.1`, `claude-code` |
| `confidence` | yes | `1.0` (parser), `0.0`–`1.0` (LLM) |
| `source` | no | `src/app/main.py` |
| `lines` | no | `[12, 40]` (1-indexed, inclusive) |
| `timestamp` | no | `2026-10-09T12:00:00Z` (ISO-8601 with time zone) |

`timestamp` is optional so that deterministic extraction can produce the same
output byte for byte (RNF-08).

## Validation

```bash
kg validate graph.json          # human-readable text
kg validate graph.json --json   # for agents
cat graph.json | kg validate -  # from stdin
```

It does not modify the store (RF-03). Each issue reports the **JSON path**,
the **received value**, the **expected value** and a **suggestion** (RF-04):

```text
error: $.edges[0].target: the edge points to a node that does not exist in the file
  received:   "function:a.g"
  expected:   the ID of a node declared in `nodes`
  suggestion: Did you mean "function:a.f"? Fix the ID or add the node to `nodes`.
```

With `--json`, errors are in `error.details.errors`, and warnings and notes in
`warnings` and `notes` (in `result` if the document is valid). Each item has
`code`, `path`, `message`, `received` (`null` if the field is missing),
`expected`, `suggestion`, `severity` and `paths`. `paths` lists every
occurrence of an issue that groups several (a custom type is reported once,
however often it is used), and is empty otherwise; `path` is the first one.

Severities: an **error** makes the document invalid; a **warning** is valid but
probably a mistake; a **note** is valid by design and needs no action.

| Code | Severity | Cause |
|------|----------|-------|
| `invalid_json`, `invalid_encoding` | error | The file is not UTF-8 JSON |
| `required`, `unknown_field` | error | A field is missing or unexpected (with a suggestion if it is a typo) |
| `wrong_type`, `not_allowed`, `out_of_range`, `wrong_length`, `empty` | error | Wrong value |
| `invalid_id`, `invalid_timestamp`, `invalid_type_name` | error | Wrong format |
| `duplicate_id` | error | Two nodes with the same ID (RF-05) |
| `broken_reference` | error | Edge to a node that is not in the file (RF-05); with `kg add`, not in the store either |
| `custom_type` | warning | A type outside the standard catalog that looks like a standard one, by name (`Decison`) or meaning (`Tutorial` → `Document`, `invokes` → `calls`): the suggestion names it (RF-02) |
| `custom_type` | note | Any other type outside the standard catalog: valid (RF-02). The text output lists them in one line, `note: custom types, valid (no standard type fits): EntryPoint ×3, reads_argv` |
| `id_prefix_mismatch` | warning | The ID prefix does not match the node's `type` |
| `missing_description` | warning | A node with `method: llm` has no `description` (#36): agents describe every node they create |

Exit codes: `0` valid (even with warnings), `1` there are errors, `2` the
file does not exist or cannot be read.
