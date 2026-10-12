"""Static name resolution for `tests` relations (RF-12).

A heuristic, not type inference: it follows imports, attribute chains such as
`mod.Class.method`, `Class(...).method` and `x = Class(...)` followed by
`x.method`, and nothing else (no fixtures, no return types).
"""

from __future__ import annotations

import ast
from collections.abc import Iterator


def bindings(tree: ast.Module, package: list[str]) -> dict[str, str]:
    """Local names bound by the imports in `tree` → absolute dotted names.

    `package` is the importing module's package (for relative imports). Every
    import counts, including those inside functions; the first binding wins.
    """
    names: dict[str, str] = {}
    imports = [n for n in ast.walk(tree) if isinstance(n, ast.Import | ast.ImportFrom)]
    imports.sort(key=lambda n: (n.lineno, n.col_offset))
    for stmt in imports:
        if isinstance(stmt, ast.Import):
            for alias in stmt.names:
                if alias.asname:  # `import a.b as x`: x is a.b
                    names.setdefault(alias.asname, alias.name)
                else:  # `import a.b`: binds `a`
                    top = alias.name.split(".")[0]
                    names.setdefault(top, top)
            continue
        base = from_base(stmt, package)
        if base is None:
            continue
        for alias in stmt.names:
            if alias.name != "*":
                names.setdefault(alias.asname or alias.name, f"{base}.{alias.name}")
    return names


def references(node: ast.AST, names: dict[str, str]) -> list[tuple[str, int]]:
    """Dotted names (`a.b.C.method`) that `node` refers to, with their first line."""
    local = dict(names)
    # `x = Class(...)` or `x = mod.Class(...)` makes `x` an instance: x.m → Class.m
    for stmt in ast.walk(node):
        if (
            isinstance(stmt, ast.Assign)
            and len(stmt.targets) == 1
            and isinstance(stmt.targets[0], ast.Name)
            and isinstance(stmt.value, ast.Call)
        ):
            dotted = _dotted(stmt.value.func, names)
            if dotted is not None:
                local.setdefault(stmt.targets[0].id, dotted)
    found: dict[str, int] = {}
    for dotted, line in _walk(node, local):
        if dotted not in found or line < found[dotted]:
            found[dotted] = line
    return sorted(found.items(), key=lambda item: (item[1], item[0]))


def _walk(node: ast.AST, names: dict[str, str]) -> Iterator[tuple[str, int]]:
    if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Load):
        return  # an assignment target, not a reference
    if isinstance(node, ast.Attribute | ast.Name):
        calls: list[ast.Call] = []
        dotted = _dotted(node, names, calls)
        if dotted is not None:
            yield dotted, node.lineno
            for call in calls:  # `Class(...).m` also uses `Class`, and its args
                callee = _dotted(call.func, names)
                if callee is not None:
                    yield callee, call.lineno
                for arg in [*call.args, *call.keywords]:
                    yield from _walk(arg, names)
            return
    for child in ast.iter_child_nodes(node):
        yield from _walk(child, names)


def _dotted(
    node: ast.expr, names: dict[str, str], calls: list[ast.Call] | None = None
) -> str | None:
    """Absolute name of `a.b.c`, `a.b(...).c`…, if its root is a bound name.

    Calls found along the chain are appended to `calls`.
    """
    attrs: list[str] = []
    while True:
        if isinstance(node, ast.Attribute):
            attrs.append(node.attr)
            node = node.value
        elif isinstance(node, ast.Call):  # Class(...).method → Class.method
            if calls is not None:
                calls.append(node)
            node = node.func
        elif isinstance(node, ast.Name):
            root = names.get(node.id)
            if root is None:
                return None
            return ".".join([root, *reversed(attrs)])
        else:
            return None


def from_base(stmt: ast.ImportFrom, package: list[str]) -> str | None:
    """Absolute module of `from … import`; `None` if it goes beyond the top."""
    if not stmt.level:
        return stmt.module
    if stmt.level - 1 >= len(package):
        return None
    parts = package[: len(package) - (stmt.level - 1)]
    return ".".join([*parts, stmt.module] if stmt.module else parts)
