"""Dependencies and configuration from `pyproject.toml` and `requirements*.txt` (RF-11).

Produces `Config` nodes for each manifest and a single `Dependency` node per
package, whatever the number of places that declare it, with `configures`
(Config → Repo) and `depends_on` (Repo → Dependency) edges. Rules in
`docs/extract.md`.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from kg.extract.files import DIGEST, file_digest
from kg.extract.python import Extraction, SkippedFile, normalize_name
from kg.store import FORMAT_VERSION

PYPROJECT = "pyproject.toml"
PYPROJECT_EXTRACTOR = "pyproject@0.1"
REQUIREMENTS_EXTRACTOR = "requirements@0.1"

# PEP 508: name, optional [extras], then version spec or `@ url`, then `; markers`.
_REQUIREMENT = re.compile(
    r"""^\s*(?P<name>[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)\s*
        (?:\[(?P<extras>[^\]]*)\])?\s*
        (?P<spec>[^;]*?)\s*
        (?:;\s*(?P<markers>.*?))?\s*$""",
    re.VERBOSE,
)


@dataclass(frozen=True)
class Requirement:
    """A parsed PEP 508 requirement."""

    name: str
    spec: str
    extras: tuple[str, ...] = ()
    markers: str = ""


def parse_requirement(text: str) -> Requirement | None:
    """Parse a PEP 508 string; `None` if it is not one."""
    match = _REQUIREMENT.match(text)
    if match is None:
        return None
    spec = match["spec"]
    if spec and not re.match(r"^(@|[<>=!~(])", spec):
        return None  # e.g. `pkg foo`: garbage after the name
    extras = tuple(
        sorted(e.strip() for e in (match["extras"] or "").split(",") if e.strip())
    )
    return Requirement(match["name"], spec, extras, match["markers"] or "")


@dataclass
class _Declared:
    requirement: Requirement
    source: str
    extractor: str
    line: int | None
    group: str | None


@dataclass
class _Dependencies:
    """Declarations by normalized name, in priority order."""

    by_name: dict[str, list[_Declared]] = field(default_factory=dict)

    def add(self, declared: _Declared) -> None:
        name = normalize_name(declared.requirement.name)
        self.by_name.setdefault(name, []).append(declared)


def extract_dependencies(root: Path, repo_id: str) -> Extraction:
    """Extract `Config` and `Dependency` nodes from the manifests at `root`."""
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    extraction = Extraction({})
    deps = _Dependencies()

    def config(path: str, extractor: str, attrs: dict[str, Any] | None) -> None:
        prov = _provenance(extractor, path)
        node: dict[str, Any] = {
            "id": f"config:{path}",
            "type": "Config",
            "label": path.rsplit("/", 1)[-1],
        }
        digest = file_digest(root / path)
        attrs = {**(attrs or {}), **({DIGEST: digest} if digest else {})}
        if attrs:
            node["attrs"] = attrs
        nodes.append(node | {"provenance": prov})
        edges.append(
            {
                "source": f"config:{path}",
                "target": repo_id,
                "type": "configures",
                "provenance": prov,
            }
        )
        extraction.files.append(path)

    if (root / PYPROJECT).is_file():
        attrs = _read_pyproject(root, deps, extraction.skipped)
        config(PYPROJECT, PYPROJECT_EXTRACTOR, attrs)
    for path in requirement_files(root):
        _read_requirements(root, path, deps, extraction.skipped)
        config(path, REQUIREMENTS_EXTRACTOR, {"format": "requirements"})

    for name in sorted(deps.by_name):
        declarations = deps.by_name[name]
        first = declarations[0]
        prov = _provenance(first.extractor, first.source, first.line)
        node_id = f"dependency:{name}"
        nodes.append(
            {
                "id": node_id,
                "type": "Dependency",
                "label": first.requirement.name,
                "attrs": _dependency_attrs(declarations),
                "provenance": prov,
            }
        )
        edges.append(
            {
                "source": repo_id,
                "target": node_id,
                "type": "depends_on",
                "provenance": prov,
            }
        )

    extraction.document = {"version": FORMAT_VERSION, "nodes": nodes, "edges": edges}
    return extraction


def requirement_files(root: Path) -> list[str]:
    """`requirements*.txt` at the root (`requirements.txt` first), then
    `requirements/*.txt`."""
    found = [p.name for p in root.glob("requirements*.txt") if p.is_file()]
    found.sort(key=lambda name: (name != "requirements.txt", name))
    nested = sorted(
        f"requirements/{p.name}"
        for p in (root / "requirements").glob("*.txt")
        if p.is_file()
    )
    return found + nested


def _read_pyproject(
    root: Path, deps: _Dependencies, skipped: list[SkippedFile]
) -> dict[str, Any]:
    """Collect the pyproject's dependencies; return the Config node's `attrs`."""
    attrs: dict[str, Any] = {"format": "pyproject"}
    try:
        data = tomllib.loads((root / PYPROJECT).read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError, OSError) as e:
        skipped.append(SkippedFile(PYPROJECT, None, f"cannot parse: {e}"))
        return attrs

    tools = data.get("tool")
    if isinstance(tools, dict) and tools:
        attrs["tools"] = sorted(tools)
    project = data.get("project")
    project = project if isinstance(project, dict) else {}
    for key in ("name", "version", "requires-python"):
        if isinstance(project.get(key), str):
            attrs[key.replace("-", "_")] = project[key]

    groups: list[tuple[str, str, Any]] = [
        ("main", "project.dependencies", project.get("dependencies", []))
    ]
    for kind, table in (
        ("project.optional-dependencies", project.get("optional-dependencies", {})),
        ("dependency-groups", data.get("dependency-groups", {})),
    ):
        if not isinstance(table, dict):
            skipped.append(SkippedFile(PYPROJECT, None, f"{kind} is not a table"))
            continue
        groups += [(name, f"{kind}.{name}", table[name]) for name in sorted(table)]

    for group, where, items in groups:
        if not isinstance(items, list):
            skipped.append(SkippedFile(PYPROJECT, None, f"{where} is not a list"))
            continue
        for item in items:
            if isinstance(item, dict):  # `{include-group = "..."}` (PEP 735)
                continue
            req = parse_requirement(item) if isinstance(item, str) else None
            if req is None:
                message = f"{where}: not a valid requirement: {item!r}"
                skipped.append(SkippedFile(PYPROJECT, None, message))
                continue
            deps.add(_Declared(req, PYPROJECT, PYPROJECT_EXTRACTOR, None, group))
    return attrs


def _read_requirements(
    root: Path, path: str, deps: _Dependencies, skipped: list[SkippedFile]
) -> None:
    try:
        text = (root / path).read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as e:
        skipped.append(SkippedFile(path, None, f"cannot read: {e}"))
        return
    for number, line in _logical_lines(text):
        line = re.sub(r"(^|\s)#.*$", "", line).strip()
        if not line or line.startswith("-"):  # options: -r, -e, --index-url…
            continue
        if "://" in line.split("@")[0] or line.startswith((".", "/")):
            continue  # a URL or a local path, not a named requirement
        req = parse_requirement(line)
        if req is None:
            skipped.append(
                SkippedFile(path, number, f"not a valid requirement: {line}")
            )
            continue
        deps.add(_Declared(req, path, REQUIREMENTS_EXTRACTOR, number, None))


def _logical_lines(text: str) -> list[tuple[int, str]]:
    """Lines joined at a trailing `\\`, with the number of their first line."""
    out: list[tuple[int, str]] = []
    pending: tuple[int, str] | None = None
    for number, raw in enumerate(text.splitlines(), start=1):
        start, prefix = pending if pending else (number, "")
        if raw.endswith("\\"):
            pending = (start, prefix + raw[:-1])
            continue
        pending = None
        out.append((start, prefix + raw))
    if pending:
        out.append(pending)
    return out


def _dependency_attrs(declarations: list[_Declared]) -> dict[str, Any]:
    """`spec`, `extras` and `markers` of the first declaration, plus where."""
    first = declarations[0].requirement
    attrs: dict[str, Any] = {}
    if first.spec:
        attrs["spec"] = first.spec
    if first.extras:
        attrs["extras"] = list(first.extras)
    if first.markers:
        attrs["markers"] = first.markers
    groups = sorted({d.group for d in declarations if d.group})
    if groups:
        attrs["groups"] = groups
    attrs["declared_in"] = list(dict.fromkeys(d.source for d in declarations))
    return attrs


def _provenance(extractor: str, source: str, line: int | None = None) -> dict[str, Any]:
    prov: dict[str, Any] = {
        "method": "parser",
        "extractor": extractor,
        "confidence": 1.0,
        "source": source,
    }
    if line is not None:
        prov["lines"] = [line, line]
    return prov
