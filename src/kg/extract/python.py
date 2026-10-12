"""Deterministic extraction of a Python repo's code structure (RF-10, RF-12).

Produces a schema document with `Repo`, `Package`, `Module`, `File`, `Class`,
`Function` and `Test` nodes, `contains`, `defines`, `imports` and `tests`
edges, and external imports as `Dependency` nodes. Rules and IDs are
documented in `docs/extract.md`.
"""

from __future__ import annotations

import ast
import re
import sys
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from kg.extract.files import python_files
from kg.extract.references import bindings, from_base, references
from kg.store import FORMAT_VERSION

EXTRACTOR = "python-ast@0.1"

_Def = ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
# Compound statements whose bodies still belong to the enclosing scope.
_BLOCKS = (ast.If, ast.Try, ast.TryStar, ast.With, ast.AsyncWith, ast.For, ast.While)


@dataclass(frozen=True)
class SkippedFile:
    """A file, or an entry in it, that could not be extracted (with the reason)."""

    path: str
    line: int | None
    message: str

    def to_text(self) -> str:
        where = self.path if self.line is None else f"{self.path}:{self.line}"
        return f"{where}: {self.message}"


@dataclass
class Extraction:
    """Result of `extract_python`: the document plus what was read and skipped."""

    document: dict[str, Any]
    files: list[str] = field(default_factory=list)
    skipped: list[SkippedFile] = field(default_factory=list)


@dataclass(frozen=True)
class _Module:
    name: str  # dotted name, e.g. `kg.cli`
    path: str  # file, e.g. `src/kg/cli.py`
    is_package: bool
    search_root: str  # dotted dir that is on `sys.path` for it (`` at the root)
    is_test: bool = False  # a pytest test file

    @property
    def id(self) -> str:
        if self.is_test:
            return f"test:{self.name}"
        return f"{'package' if self.is_package else 'module'}:{self.name}"

    @property
    def package(self) -> list[str]:
        """Package that relative imports start from."""
        parts = self.name.split(".")
        return parts if self.is_package else parts[:-1]


@dataclass(frozen=True)
class _TestDef:
    node_id: str
    stmt: ast.FunctionDef | ast.AsyncFunctionDef
    module: _Module


def repo_id(root: Path) -> str:
    """ID of the `Repo` node: `repo:<directory name>`."""
    return f"repo:{root.resolve().name}"


def extract_python(root: Path) -> Extraction:
    """Extract the code structure of the repo at `root` (a directory)."""
    builder = _Builder(root)
    builder.run()
    return builder.extraction


class _Builder:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.repo_id = repo_id(root)
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.extraction = Extraction({})
        # Qualified name → ID of every module, class and function in the repo
        self.entities: dict[str, str] = {}
        # ID → file, to leave test code out of `tests` targets
        self.entity_files: dict[str, str] = {}
        self.trees: dict[str, tuple[_Module, ast.Module]] = {}
        self.test_defs: list[_TestDef] = []
        self._bindings: dict[str, dict[str, str]] = {}

    def run(self) -> None:
        files = python_files(self.root)
        self.extraction.files = files
        self._node(self.repo_id, "Repo", ".", label=self.root.resolve().name)

        modules = self._modules(files)
        by_name = {m.name: m for m in modules.values()}
        for path in files:
            self._node(f"file:{path}", "File", path, label=path.rsplit("/", 1)[-1])
            self._edge(self.repo_id, f"file:{path}", "contains", path)
            module = modules.get(path)
            if module is None:
                continue
            tree = self._parse(path)
            self._module(module, by_name, tree)
            if tree is not None:
                self.trees[module.name] = (module, tree)
                self._definitions(tree.body, module, f"file:{path}")
                self._imports(tree, module, by_name)
        self._tests(by_name)

        self.extraction.document = {
            "version": FORMAT_VERSION,
            "nodes": list(self.nodes.values()),
            "edges": list(self.edges.values()),
        }

    # --- Modules -------------------------------------------------------------

    def _modules(self, files: list[str]) -> dict[str, _Module]:
        """Module of each file; on a name clash the first file (sorted) wins."""
        inits = {p.rsplit("/", 1)[0] if "/" in p else "" for p in files if _is_init(p)}
        modules: dict[str, _Module] = {}
        owners: dict[str, str] = {}
        for path in files:
            module = _module_for(path, inits, self.root.resolve().name)
            if module.name in owners:
                self._skip(
                    path,
                    None,
                    f"module {module.name} is already defined by {owners[module.name]}",
                )
                continue
            owners[module.name] = path
            modules[path] = module
        return modules

    def _module(
        self, module: _Module, by_name: dict[str, _Module], tree: ast.Module | None
    ) -> None:
        doc = _summary(tree) if tree is not None else None
        type_ = "Package" if module.is_package else "Module"
        attrs = None
        if module.is_test:
            type_, attrs = "Test", {"kind": "module"}
        label = module.name.rsplit(".", 1)[-1]
        self._node(
            module.id, type_, module.path, label=label, description=doc, attrs=attrs
        )
        self._entity(module.name, module.id, module.path)
        self._edge(f"file:{module.path}", module.id, "defines", module.path)
        parent = (
            by_name.get(module.name.rsplit(".", 1)[0]) if "." in module.name else None
        )
        if parent is not None and parent.is_package:
            self._edge(parent.id, module.id, "contains", module.path)
        else:
            self._edge(self.repo_id, module.id, "contains", module.path)

    def _parse(self, path: str) -> ast.Module | None:
        try:
            source = (self.root / path).read_bytes()
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")  # e.g. SyntaxWarning: invalid escape
                return ast.parse(source, filename=path)
        except SyntaxError as e:
            self._skip(path, e.lineno, f"syntax error: {e.msg}")
        except (ValueError, OSError) as e:  # e.g. null bytes, unreadable file
            self._skip(path, None, f"cannot parse: {e}")
        return None

    # --- Classes and functions -------------------------------------------------

    def _definitions(
        self,
        body: list[ast.stmt],
        module: _Module,
        parent_id: str,
        scope: str | None = None,
        test_class: bool = False,
    ) -> None:
        """Classes and functions of a scope; `scope` is `None` at module level."""
        path = module.path
        for stmt in _flatten(body):
            if not isinstance(stmt, _Def):
                continue
            qualname = f"{scope or module.name}.{stmt.name}"
            is_class = isinstance(stmt, ast.ClassDef)
            kind = _test_kind(stmt, module, scope is None, test_class)
            prefix = "test" if kind else "class" if is_class else "function"
            node_id = f"{prefix}:{qualname}"
            if qualname in self.entities:  # redefinition (if/else, overload, setter)
                continue
            first = min([stmt.lineno, *(d.lineno for d in stmt.decorator_list)])
            lines = [first, stmt.end_lineno or stmt.lineno]
            attrs: dict[str, Any] = {"public": _is_public(stmt.name)}
            if isinstance(stmt, ast.AsyncFunctionDef):
                attrs["async"] = True
            if stmt.decorator_list:
                attrs["decorators"] = [ast.unparse(d) for d in stmt.decorator_list]
            if is_class and stmt.bases:
                attrs["bases"] = [ast.unparse(b) for b in stmt.bases]
            if kind:
                attrs["kind"] = kind
            self._node(
                node_id,
                "Test" if kind else "Class" if is_class else "Function",
                path,
                lines=lines,
                label=stmt.name,
                description=_summary(stmt),
                attrs=attrs,
            )
            self._edge(parent_id, node_id, "defines", path, lines)
            self._entity(qualname, node_id, path)
            if kind == "function" and not isinstance(stmt, ast.ClassDef):
                self.test_defs.append(_TestDef(node_id, stmt, module))
            if is_class:
                self._definitions(
                    stmt.body, module, node_id, qualname, test_class=kind == "class"
                )

    # --- Tests -------------------------------------------------------------------

    def _tests(self, by_name: dict[str, _Module]) -> None:
        """`tests` edges, once every entity of the repo is known (RF-12)."""
        for (source, target, type_), edge in list(self.edges.items()):
            module = self._module_of(source)
            if (
                type_ == "imports"
                and module is not None
                and module.is_test
                and self._is_code(target)
            ):
                self._edge(
                    source,
                    target,
                    "tests",
                    module.path,
                    edge["provenance"].get("lines"),
                )
        for test in self.test_defs:
            names = self._module_bindings(test.module)
            for dotted, line in references(test.stmt, names):
                target = self._target(dotted, test.module, by_name)
                if target is not None and self._is_code(target):
                    self._edge(
                        test.node_id, target, "tests", test.module.path, [line, line]
                    )

    def _target(
        self, dotted: str, module: _Module, by_name: dict[str, _Module]
    ) -> str | None:
        """Entity that a referenced name designates, following re-exports."""
        candidates = [dotted]
        if module.search_root:  # next to a loose script
            candidates.append(f"{module.search_root}.{dotted}")
        for candidate in candidates:
            first: str | None = None
            for _ in range(5):  # bounded: re-exports may form cycles
                parts = candidate.split(".")
                for i in range(len(parts), 0, -1):  # longest known prefix
                    prefix = ".".join(parts[:i])
                    if prefix in self.entities:
                        break
                else:
                    break
                first = first or self.entities[prefix]
                rest = parts[i:]
                owner = by_name.get(prefix)
                exported = (
                    self._module_bindings(owner).get(rest[0])
                    if owner is not None and rest
                    else None
                )
                if exported is None:
                    return self.entities[prefix]
                candidate = ".".join([exported, *rest[1:]])
            if first is not None:  # a cycle, or a re-export of something unknown
                return first
        return None

    def _module_bindings(self, module: _Module) -> dict[str, str]:
        if module.name not in self._bindings:
            entry = self.trees.get(module.name)
            self._bindings[module.name] = (
                bindings(entry[1], module.package) if entry else {}
            )
        return self._bindings[module.name]

    def _module_of(self, node_id: str) -> _Module | None:
        entry = self.trees.get(node_id.split(":", 1)[1])
        return entry[0] if entry and entry[0].id == node_id else None

    def _is_code(self, node_id: str) -> bool:
        """Repo code that tests can target: not a test, nor in a test file."""
        path = self.entity_files.get(node_id)
        if path is None or node_id.startswith("test:"):
            return False
        name = path.rsplit("/", 1)[-1]
        return not (_is_test_file(path) or name == "conftest.py")

    def _entity(self, qualname: str, node_id: str, path: str) -> None:
        self.entities.setdefault(qualname, node_id)
        self.entity_files.setdefault(node_id, path)

    # --- Imports -----------------------------------------------------------------

    def _imports(
        self, tree: ast.Module, module: _Module, by_name: dict[str, _Module]
    ) -> None:
        statements = [
            n for n in ast.walk(tree) if isinstance(n, ast.Import | ast.ImportFrom)
        ]
        statements.sort(key=lambda n: (n.lineno, n.col_offset))
        for stmt in statements:
            for name in _imported_names(stmt, module):
                target = self._resolve(name, module, by_name, stmt)
                if target is None or target == module.id:
                    continue
                lines = [stmt.lineno, stmt.end_lineno or stmt.lineno]
                self._edge(module.id, target, "imports", module.path, lines)

    def _resolve(
        self,
        name: str,
        module: _Module,
        by_name: dict[str, _Module],
        stmt: ast.Import | ast.ImportFrom,
    ) -> str | None:
        """ID of the imported module or dependency; `None` for stdlib or unknown."""
        relative = isinstance(stmt, ast.ImportFrom) and stmt.level > 0
        # (dotted name, parts that must match): a name next to a loose script
        # is also looked up under the script's directory, which is on sys.path.
        candidates = [(name, 1)]
        if module.search_root and not relative:
            root_parts = module.search_root.count(".") + 1
            candidates.append((f"{module.search_root}.{name}", root_parts + 1))
        for candidate, min_parts in candidates:
            parts = candidate.split(".")
            for i in range(len(parts), min_parts - 1, -1):  # longest known prefix
                found = by_name.get(".".join(parts[:i]))
                if found is not None:
                    return found.id
        top = name.split(".")[0]
        if relative or top in sys.stdlib_module_names or top == "__future__":
            return None
        dep_id = f"dependency:{normalize_name(top)}"
        if dep_id not in self.nodes:
            self._node(
                dep_id, "Dependency", module.path, label=top, attrs={"import_name": top}
            )
        return dep_id

    # --- Document ---------------------------------------------------------------

    def _node(
        self,
        node_id: str,
        type_: str,
        source: str,
        lines: list[int] | None = None,
        **fields: Any,
    ) -> None:
        node = {"id": node_id, "type": type_}
        node |= {k: v for k, v in fields.items() if v is not None}
        node["provenance"] = _provenance(source, lines)
        self.nodes.setdefault(node_id, node)

    def _edge(
        self,
        source: str,
        target: str,
        type_: str,
        path: str,
        lines: list[int] | None = None,
    ) -> None:
        edge = {
            "source": source,
            "target": target,
            "type": type_,
            "provenance": _provenance(path, lines),
        }
        self.edges.setdefault((source, target, type_), edge)

    def _skip(self, path: str, line: int | None, message: str) -> None:
        self.extraction.skipped.append(SkippedFile(path, line, message))


def _module_for(path: str, init_dirs: set[str], root_name: str) -> _Module:
    """Dotted name of a file: from the outermost package, or from the repo root.

    `src/kg/cli.py` (with `src/kg/__init__.py`) is `kg.cli` with `src` as the
    search root; `tests/test_cli.py` without `__init__.py` is `tests.test_cli`.
    A root `__init__.py` makes the whole repo a package named after it.
    """
    parts = path.removesuffix(".py").split("/")
    dirs = parts[:-1]
    top = len(dirs)  # index of the first dir of the outermost package
    while top > 0 and "/".join(dirs[:top]) in init_dirs:
        top -= 1
    if top == 0 and "" in init_dirs:
        names, search_root = [root_name, *parts], ""
    elif top < len(dirs) and "/".join(dirs[: top + 1]) in init_dirs:
        names, search_root = parts[top:], ".".join(dirs[:top])
    else:  # not inside a package
        names, search_root = parts, ".".join(dirs)
    is_package = _is_init(path)
    if is_package:
        names = names[:-1]
    return _Module(".".join(names), path, is_package, search_root, _is_test_file(path))


def _imported_names(stmt: ast.Import | ast.ImportFrom, module: _Module) -> list[str]:
    """Absolute dotted names a statement may refer to (submodule or attribute)."""
    if isinstance(stmt, ast.Import):
        return [alias.name for alias in stmt.names]
    base = from_base(stmt, module.package)
    if base is None:
        return []  # beyond the top-level package: an error at runtime
    # `from a import b` imports the submodule `a.b` if it exists, else `a`;
    # _resolve takes the longest known prefix, so `a.b` covers both.
    return [f"{base}.{a.name}" if a.name != "*" else base for a in stmt.names]


def _flatten(body: list[ast.stmt]) -> list[ast.stmt]:
    """Statements of a scope, including those nested in if/try/with/loops."""
    out: list[ast.stmt] = []
    for stmt in body:
        out.append(stmt)
        if isinstance(stmt, _BLOCKS):
            nested = (
                [stmt.body, stmt.orelse] if hasattr(stmt, "orelse") else [stmt.body]
            )
            if isinstance(stmt, ast.Try | ast.TryStar):
                nested += [h.body for h in stmt.handlers] + [stmt.finalbody]
            for block in nested:
                out += _flatten(block)
    return out


def _summary(node: ast.Module | _Def) -> str | None:
    """First paragraph of the docstring, on a single line."""
    doc = ast.get_docstring(node)
    if not doc:
        return None
    return " ".join(doc.strip().split("\n\n", 1)[0].split())


def _test_kind(
    stmt: _Def, module: _Module, top_level: bool, in_test_class: bool
) -> str | None:
    """`function` or `class` if pytest would collect it as a test, else `None`.

    pytest defaults: `test*` functions at module level or in a test class, and
    `Test*` classes (or `unittest.TestCase` subclasses) at module level.
    """
    if not module.is_test:
        return None
    if isinstance(stmt, ast.ClassDef):
        bases = {ast.unparse(b).rsplit(".", 1)[-1] for b in stmt.bases}
        is_test = stmt.name.startswith("Test") or "TestCase" in bases
        return "class" if top_level and is_test else None
    if stmt.name.startswith("test") and (top_level or in_test_class):
        return "function"
    return None


def _is_test_file(path: str) -> bool:
    """pytest's default `python_files`: `test_*.py` and `*_test.py`."""
    name = path.rsplit("/", 1)[-1]
    return name.startswith("test_") or name.endswith("_test.py")


def _is_public(name: str) -> bool:
    return not name.startswith("_") or (name.startswith("__") and name.endswith("__"))


def _is_init(path: str) -> bool:
    return path == "__init__.py" or path.endswith("/__init__.py")


def normalize_name(name: str) -> str:
    """Package name as in PEP 503: lowercase, `-` for runs of `-_.`."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _provenance(source: str, lines: list[int] | None) -> dict[str, Any]:
    prov: dict[str, Any] = {
        "method": "parser",
        "extractor": EXTRACTOR,
        "confidence": 1.0,
        "source": source,
    }
    if lines is not None:
        prov["lines"] = lines
    return prov
