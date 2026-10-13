# Deterministic extraction: `kg extract`

Walks a Python repo with `ast` and reads its manifests, then merges its code
structure (RF-10), its tests (RF-12) and its dependencies and configuration
(RF-11) into the store. It does not run or import the code, and calls no LLM (RF-24).

```bash
kg init
kg extract                    # the current directory
kg extract path/to/repo       # another repo; the store is still --kg-dir
kg extract . --json           # summary for agents
kg extract --dry-run          # what would be added, merged and removed
kg status                     # has the code changed since the last extract?
```

Each run **replaces the parser's layer** of the graph (RF-72). The new
extraction is validated and merged like `kg add`, and the elements the parser
produced before but no longer finds (deleted, renamed or moved code) are
removed. What agents and people added is kept. The rules are in
[store.md](store.md#updating-after-code-changes-kg-extract). Running
`kg extract` twice leaves the store byte for byte identical, and an element
that changed (a function that moved, a new docstring) is merged and reported
as a conflict.

## Files that are read

**Code**: `.py` files, chosen as follows.

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

**Manifests**: `pyproject.toml` at the root, `requirements*.txt` at the root
(`requirements.txt` first) and `requirements/*.txt`.

A file that cannot be parsed (syntax error, null bytes) is **reported and
skipped**: it keeps its `File` and `Module` nodes, but its classes, functions
and imports are not extracted. Extraction goes on with the rest.

```text
extracted 14 files from . into .kg/graph.json
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
| `File` | `file:<path>` | `label`: file name; `attrs.digest`: content hash |
| `Package` | `package:<name>` | A directory with `__init__.py`; description from its docstring |
| `Module` | `module:<name>` | Description from its docstring |
| `Class` | `class:<module>.<Class>` | Nested classes: `class:m.Outer.Inner` |
| `Function` | `function:<module>.<name>` | Methods: `function:m.Class.method` |
| `Dependency` | `dependency:<name>` | See *Dependencies and configuration* |
| `Config` | `config:<path>` | `pyproject.toml`, each requirements file; `attrs.digest` |
| `Test` | `test:<name>` | Test file, class or function; see *Tests* |

`Class` and `Function` have `provenance.lines` (`[first, last]`, starting at
the first decorator), a `description` (first paragraph of the docstring) and
`attrs`:

| Attribute | On | Value |
|-----------|----|-------|
| `public` | both | `false` if the name starts with `_` (dunders are public) |
| `async` | `Function` | `true`, only for `async def` |
| `decorators` | both | Source of each decorator, if any |
| `bases` | `Class` | Source of each base class, if any |
| `kind` | `Test` | `module`, `class` or `function` |

`attrs.digest` is `sha256:` plus the first 16 hex digits of the SHA-256 of
the file's bytes. `kg status` compares it with the files on disk (RF-77). A
file that cannot be parsed keeps the digest of its last good extraction, so it
keeps showing as modified until it is fixed.

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
| `depends_on` | `Repo` → every declared `Dependency` |
| `configures` | `Config` → `Repo` |
| `tests` | `Test` → `Module`/`Package`/`Class`/`Function`; see *Tests* |

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
  is ignored and the rest becomes a `Dependency` (see below).

## Tests

Detection follows pytest's defaults. A **test file** is `test_*.py` or
`*_test.py`; in it, these are `Test` nodes instead of `Module`, `Class` or
`Function`, with the same ID suffix (`test:tests.test_core`,
`test:tests.test_core.TestEngine.test_start`) and `attrs.kind`:

- the module itself (`kind: module`);
- `Test*` classes and `unittest.TestCase` subclasses at module level
  (`kind: class`);
- `test*` functions at module level or in one of those classes
  (`kind: function`).

Everything else in a test file (helpers, fixtures, other classes) and
`conftest.py` keeps its usual type. `defines`, `contains` and `imports` edges
are the same as for any module.

`tests` edges point only to **repo code outside test files and
`conftest.py`**:

- **Test module → module/package**: every internal module it imports.
- **Test function → module/package/class/function**: every name its body
  (decorators and arguments included) refers to through the file's imports.
  Resolution follows `mod.Class.method` chains, re-exports by packages
  (`from app import Engine` when `app/__init__.py` imports it from
  `app.core`), `Class(...).method()` and `x = Class(...)` followed by
  `x.method()`. `lines` is the first reference.

This is a **static heuristic**, so it does not see:

- fixtures (`def test_x(engine): engine.start()`) or values returned by
  functions;
- code reached indirectly: a test that calls `main()` does not test what
  `main()` calls (that needs `calls`, RF-13, v0.3);
- dynamic access (`getattr`, `importlib`), `monkeypatch` targets given as
  strings, or other test runners' conventions.

**Code without tests** (CU-02) is the code with no incoming `tests` edge:
`kg query untested` lists it (see [query.md](query.md)). It leaves out code in
test files and `conftest.py`; `--include-private` adds `_private` names and
`--type Module,Package` checks modules instead. Given the limits above, a
result means "no test refers to it directly", not "never runs under tests".

## Dependencies and configuration

`Dependency` IDs use the package name normalized as in PEP 503 (lowercase,
`-` for runs of `-_.`): `NetworkX`, `networkx` and `import networkx` are all
`dependency:networkx`. **The same dependency yields a single node**, however
many manifests declare or modules import it.

Sources, in priority order:

1. `pyproject.toml`: `[project.dependencies]` (group `main`),
   `[project.optional-dependencies]` and `[dependency-groups]` (PEP 735;
   `{include-group = …}` entries are ignored). Groups in alphabetical order.
2. Requirements files, in the order above. Blank lines, comments, options
   (`-r`, `-e`, `--index-url`…), URLs and local paths are ignored; a line
   ending in `\` continues on the next one.

The first declaration gives the node its `label`, `provenance` and `spec`;
`Dependency` `attrs`:

| Attribute | Value |
|-----------|-------|
| `spec` | Version constraint or `@ url` of the first declaration, if any |
| `extras` | Extras requested (`requests[socks]` → `["socks"]`) |
| `markers` | Environment markers (`python_version < '3.13'`) |
| `groups` | pyproject groups that declare it (`main`, `dev`…) |
| `declared_in` | Every manifest that declares it, in priority order |
| `import_name` | Name used in `import`, if the code imports it |

A dependency that is imported but not declared only has `import_name`. The
import name is not always the distribution name (`yaml` vs. `PyYAML`), in
which case two nodes appear; reconciling them is RF-32 (v0.3).

`Config` `attrs`: `format` (`pyproject` or `requirements`) and, for the
pyproject, `name`, `version`, `requires_python` and `tools` (the
`[tool.*]` tables, e.g. `["pytest", "ruff"]`).

An invalid `pyproject.toml`, a field of the wrong type or an entry that is not
a PEP 508 requirement is reported as skipped (with its line in requirements
files); the rest is still extracted. Poetry's `[tool.poetry.dependencies]` and
`setup.py`/`setup.cfg` are not read.

## Not yet

- Processing only the files that changed (RF-78, v0.3): every run reads the
  whole repo, about 1 s for 100 files.
- `calls` relations (RF-13, v0.3).
