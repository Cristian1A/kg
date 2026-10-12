# Deterministic extraction: `kg extract`

Walks a Python repo with `ast` and merges its code structure into the store
(RF-10). It does not run or import the code, and calls no LLM (RF-24).

```bash
kg init
kg extract                    # the current directory
kg extract path/to/repo       # another repo; the store is still --kg-dir
kg extract . --json           # summary for agents
```

The extracted document goes through the same validation and merge as
`kg add` (see [store.md](store.md)): running `kg extract` twice leaves the
store byte for byte identical, and an element that changed (a function that
moved, a new docstring) is merged and reported as a conflict.

## Files that are read

Only `.py` files.

- **Inside a git work tree**, git decides: tracked and untracked files that
  are not ignored (`git ls-files --cached --others --exclude-standard`), so
  every `.gitignore`, `.git/info/exclude` and the global excludes apply.
- **Without git** (or if the enclosing repo ignores the directory, e.g. a copy
  under `samples/` without its own `.git`), the tree is walked and only the
  root `.gitignore` is applied, with a simplified matcher: globs, `!`, a
  trailing `/` for directories and a `/` that anchors to the root. `**` is not
  supported.
- **Always skipped**: `.git/`, `.hg/`, `.kg/`, `env/`, `venv/`, `.venv/`,
  `__pycache__/`, `.tox/`, `.nox/`, `.mypy_cache/`, `.pytest_cache/`,
  `.ruff_cache/`, `node_modules/` and any directory containing `pyvenv.cfg`
  (a virtual environment, whatever its name).

A file that cannot be parsed (syntax error, null bytes) is **reported and
skipped**: it keeps its `File` and `Module` nodes, but its classes, functions
and imports are not extracted. Extraction goes on with the rest.

```text
extracted 12 Python files from . into .kg/graph.json
  nodes: 3 added, 1 merged, 140 unchanged
  edges: 4 added, 0 merged, 160 unchanged
  skipped 1:
    src/app/broken.py:14: syntax error: invalid syntax
```

At most 10 conflicts are listed in the text output; `--json` has all of them,
plus `files` (count), `skipped` (`path`, `line`, `message`) and the same
fields as `kg add`.

## Module names

The dotted name is what `import` would use:

| File | Module | Why |
|------|--------|-----|
| `src/app/core.py` (with `src/app/__init__.py`) | `app.core` | From the outermost package; `src/` is on `sys.path` |
| `src/app/__init__.py` | `app` | A package |
| `tests/test_core.py` (no `__init__.py`) | `tests.test_core` | Not in a package: its path |
| `script.py` | `script` | |
| any file, with an `__init__.py` at the repo root | `<repo-dir>.…` | The repo itself is a package |

If two files produce the same name, the first one (by path) wins and the
other is reported as skipped.

## Nodes

All with `provenance` `method: parser`, `extractor: python-ast@0.1`,
`confidence: 1.0` and `source` (the file, relative to the repo root).

| Type | ID | Notes |
|------|----|-------|
| `Repo` | `repo:<dir name>` | `source: "."` |
| `File` | `file:<path>` | `label`: file name |
| `Package` | `package:<name>` | A directory with `__init__.py`; description from its docstring |
| `Module` | `module:<name>` | Description from its docstring |
| `Class` | `class:<module>.<Class>` | Nested classes: `class:m.Outer.Inner` |
| `Function` | `function:<module>.<name>` | Methods: `function:m.Class.method` |
| `Dependency` | `dependency:<import name>` | Normalized as in PEP 503 (`yaml_lib` → `yaml-lib`) |

`Class` and `Function` have `provenance.lines` (`[first, last]`, starting at
the first decorator), a `description` (first paragraph of the docstring) and
`attrs`:

| Attribute | On | Value |
|-----------|----|-------|
| `public` | both | `false` if the name starts with `_` (dunders are public) |
| `async` | `Function` | `true`, only for `async def` |
| `decorators` | both | Source of each decorator, if any |
| `bases` | `Class` | Source of each base class, if any |

Definitions inside module-level `if`/`try`/`with`/loops are included;
functions nested in functions are not. If a name is defined twice in the same
scope (`if`/`else`, `@overload`, a property setter), the first one is kept.

## Relations

| Relation | From → to |
|----------|-----------|
| `contains` | `Repo` → every `File` |
| `contains` | `Repo` → top-level `Package` and `Module`s outside packages; `Package` → its `Package`s and `Module`s |
| `defines` | `File` → its `Module`/`Package`, and its top-level `Class`es and `Function`s |
| `defines` | `Class` → its methods and nested classes |
| `imports` | `Module`/`Package` → `Module`/`Package` (internal) or `Dependency` (external) |

`imports` covers every `import` in the file, including those inside functions
and `if TYPE_CHECKING:`. One edge per imported target; its `lines` are those
of the first statement. Resolution:

- `from a import b` points to the module `a.b` if it exists, otherwise to `a`.
  `import a.b.c` points to the deepest known module.
- Relative imports are resolved against the importing package; if they cannot
  be resolved inside the repo they are ignored.
- A name next to a script outside any package (e.g. `import helpers` in
  `tests/test_x.py`) is also looked up in that script's directory.
- Anything else is external: the standard library (`sys.stdlib_module_names`)
  is ignored and the rest becomes a `Dependency`. Its ID uses the **import
  name**, which is not always the distribution name (`yaml` vs. `PyYAML`);
  reconciling them is RF-32 (v0.2).

## Not yet

- `Dependency` and `Config` from `pyproject.toml` and `requirements*.txt`
  (RF-11, #7) and `Test` nodes with `tests` relations (RF-12, #8).
- Removing entities of deleted files and processing only changed files
  (RF-72, v0.2): today a deleted file's nodes stay in the store.
- `calls` relations (RF-13, v0.2).
