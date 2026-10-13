"""Validation of input documents with actionable errors (RF-03–RF-05).

Each issue reports the JSON path, received value, expected value and a
suggestion, so an agent can fix the document in a single iteration.
"""

from __future__ import annotations

import difflib
import json
import re
from collections.abc import Collection, Iterable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from jsonschema import ValidationError as SchemaError

from kg.schema import (
    STANDARD_EDGE_TYPES,
    STANDARD_NODE_TYPES,
    find_custom_types,
    load_schema,
    validator,
)

Severity = Literal["error", "warning"]

_DEFS = load_schema()["$defs"]
_ID_PATTERN = _DEFS["id"]["pattern"]
_TIMESTAMP_PATTERN = _DEFS["provenance"]["properties"]["timestamp"]["pattern"]
_CUSTOM_TYPE_PATTERNS = {
    "node": _DEFS["nodeType"]["anyOf"][1]["pattern"],
    "edge": _DEFS["edgeType"]["anyOf"][1]["pattern"],
}
_PROVENANCE_EXAMPLE = (
    '{"method": "parser", "extractor": "python-ast@0.1", "confidence": 1.0}'
)
_JSON_TYPES = {
    "object": "object",
    "array": "array",
    "string": "string",
    "integer": "integer",
    "number": "number",
    "boolean": "boolean",
    "null": "null",
}
_MAX_RECEIVED = 80


@dataclass(frozen=True)
class Issue:
    """Validation issue. `received` is `None` when the value is missing."""

    code: str
    path: str
    message: str
    received: str | None
    expected: str
    suggestion: str
    severity: Severity = "error"

    def to_text(self) -> str:
        received = "(missing)" if self.received is None else self.received
        return (
            f"{self.severity}: {self.path}: {self.message}\n"
            f"  received:   {received}\n"
            f"  expected:   {self.expected}\n"
            f"  suggestion: {self.suggestion}"
        )


@dataclass
class Report:
    """Result of validating a document."""

    errors: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)
    nodes: int = 0
    edges: int = 0

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self, name: str) -> str:
        if self.ok:
            nodes = _plural(self.nodes, "node", "nodes")
            edges = _plural(self.edges, "edge", "edges")
            head = f"{name} is valid ({nodes}, {edges})"
        else:
            head = (
                f"{name} is not valid: {_plural(len(self.errors), 'error', 'errors')}"
            )
        if self.warnings:
            head += f", {_plural(len(self.warnings), 'warning', 'warnings')}"
        return head

    def to_text(self, name: str) -> str:
        lines = [self.summary(name)]
        lines += [issue.to_text() for issue in [*self.errors, *self.warnings]]
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.ok,
            "nodes": self.nodes,
            "edges": self.edges,
            "errors": [asdict(i) for i in self.errors],
            "warnings": [asdict(i) for i in self.warnings],
        }


def validate_text(text: str, known_ids: Collection[str] | None = None) -> Report:
    """Validate the contents of a JSON file (see `validate_document`)."""
    try:
        document = json.loads(text)
    except json.JSONDecodeError as e:
        return Report(
            errors=[
                Issue(
                    code="invalid_json",
                    path="$",
                    message=f"malformed JSON: {e.msg}",
                    received=f"line {e.lineno}, column {e.colno}",
                    expected="a valid JSON document",
                    suggestion="Fix the syntax at that position (commas, quotes, "
                    "braces) and validate again.",
                )
            ]
        )
    return validate_document(document, known_ids)


def validate_path(path: Path) -> Report:
    """Read and validate a file. Lets `OSError` through for the CLI to handle."""
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        return Report(
            errors=[
                Issue(
                    code="invalid_encoding",
                    path="$",
                    message="the file is not UTF-8",
                    received=f"byte {e.start}",
                    expected="UTF-8 text",
                    suggestion="Save the file with UTF-8 encoding.",
                )
            ]
        )
    return validate_text(text)


def validate_document(
    document: Any, known_ids: Collection[str] | None = None
) -> Report:
    """Validate a loaded document: schema, duplicate IDs and references.

    `known_ids` are nodes that exist outside the document (e.g. in the store,
    for `kg add`): edges may point to them.
    """
    report = Report()
    seen: set[tuple[str, str]] = set()
    for error in validator().iter_errors(document):
        for issue in _translate(error, document):
            # jsonschema emits one `required` error per field with the full list
            if (issue.code, issue.path) not in seen:
                seen.add((issue.code, issue.path))
                report.errors.append(issue)

    if not isinstance(document, dict):
        return report
    nodes = _items(document, "nodes")
    edges = _items(document, "edges")
    report.nodes, report.edges = len(nodes), len(edges)

    ids = _check_duplicate_ids(nodes, report)
    _check_references(edges, ids, known_ids, report)
    _check_custom_types(document, report)
    _check_id_prefixes(nodes, report)
    _check_descriptions(nodes, report)
    report.errors.sort(key=lambda i: _sort_key(_parse_path(i.path)))
    report.warnings.sort(key=lambda i: _sort_key(_parse_path(i.path)))
    return report


# --- Semantic checks -------------------------------------------------------


def _items(document: dict[str, Any], key: str) -> list[tuple[int, dict[str, Any]]]:
    items = document.get(key)
    if not isinstance(items, list):
        return []
    return [(i, item) for i, item in enumerate(items) if isinstance(item, dict)]


def _check_duplicate_ids(
    nodes: Sequence[tuple[int, dict[str, Any]]], report: Report
) -> dict[str, int]:
    first: dict[str, int] = {}
    for i, node in nodes:
        node_id = node.get("id")
        if not isinstance(node_id, str):
            continue
        if node_id in first:
            report.errors.append(
                Issue(
                    code="duplicate_id",
                    path=f"$.nodes[{i}].id",
                    message=f"duplicate ID; already used at $.nodes[{first[node_id]}]",
                    received=_show(node_id),
                    expected="an ID that is unique in the file",
                    suggestion="Merge both nodes into one or, if they are different "
                    "entities, give them different IDs.",
                )
            )
        else:
            first[node_id] = i
    return first


def _check_references(
    edges: Sequence[tuple[int, dict[str, Any]]],
    ids: dict[str, int],
    known_ids: Collection[str] | None,
    report: Report,
) -> None:
    where, expected = "in the file", "the ID of a node declared in `nodes`"
    if known_ids is None:
        known_ids = ()
    else:
        where += " or in the store"
        expected += " or already in the store"
    candidates = sorted({*ids, *known_ids})
    for i, edge in edges:
        for end in ("source", "target"):
            ref = edge.get(end)
            if not isinstance(ref, str) or ref in ids or ref in known_ids:
                continue
            close = difflib.get_close_matches(ref, candidates, n=1)
            hint = f"Did you mean {_show(close[0])}? " if close else ""
            report.errors.append(
                Issue(
                    code="broken_reference",
                    path=f"$.edges[{i}].{end}",
                    message=f"the edge points to a node that does not exist {where}",
                    received=_show(ref),
                    expected=expected,
                    suggestion=f"{hint}Fix the ID or add the node to `nodes`.",
                )
            )


def _check_custom_types(document: dict[str, Any], report: Report) -> None:
    for custom in find_custom_types(document):
        if not re.match(_CUSTOM_TYPE_PATTERNS[custom.kind], custom.type):
            continue  # already reported as a schema error
        standard = STANDARD_NODE_TYPES if custom.kind == "node" else STANDARD_EDGE_TYPES
        close = _closest(custom.type, standard)
        hint = (
            f"If it means {_show(close)}, use the standard type; otherwise keep it."
            if close
            else "Check that no standard type fits; otherwise keep it."
        )
        entity = "entity" if custom.kind == "node" else "relation"
        report.warnings.append(
            Issue(
                code="custom_type",
                path=custom.path,
                message=f"custom {entity} type",
                received=_show(custom.type),
                expected=f"a standard {entity} type",
                suggestion=hint,
                severity="warning",
            )
        )


def _check_id_prefixes(
    nodes: Sequence[tuple[int, dict[str, Any]]], report: Report
) -> None:
    for i, node in nodes:
        node_id, type_ = node.get("id"), node.get("type")
        if not (isinstance(node_id, str) and isinstance(type_, str)):
            continue
        if not re.match(_ID_PATTERN, node_id):
            continue
        prefix, _, rest = node_id.partition(":")
        if prefix != type_.lower():
            report.warnings.append(
                Issue(
                    code="id_prefix_mismatch",
                    path=f"$.nodes[{i}].id",
                    message=f"the ID prefix does not match the type {_show(type_)}",
                    received=_show(node_id),
                    expected=f"{type_.lower()}:<…>",
                    suggestion=f"Use {_show(f'{type_.lower()}:{rest}')} or check the "
                    "node type.",
                    severity="warning",
                )
            )


def _check_descriptions(
    nodes: Sequence[tuple[int, dict[str, Any]]], report: Report
) -> None:
    """Nodes created by an agent must say what they are (#36)."""
    for i, node in nodes:
        provenance = node.get("provenance")
        if not isinstance(provenance, dict) or provenance.get("method") != "llm":
            continue
        description = node.get("description")
        if isinstance(description, str) and description.strip():
            continue
        report.warnings.append(
            Issue(
                code="missing_description",
                path=f"$.nodes[{i}].description",
                message="a node created by an agent has no description",
                received=None if description is None else _show(description),
                expected="one or two sentences: what it is and why it matters",
                suggestion="Add a description in the graph's language; do not "
                "repeat the label.",
                severity="warning",
            )
        )


# --- Translation of jsonschema errors ---------------------------------------


def _translate(error: SchemaError, document: Any) -> Iterable[Issue]:
    path = _format_path(error.absolute_path)
    kind = error.validator
    value = error.instance

    if kind == "required":
        present = value if isinstance(value, dict) else {}
        for name in error.validator_value:
            if name in present:
                continue
            yield Issue(
                code="required",
                path=_join(path, name),
                message="missing required field",
                received=None,
                expected=_describe_property(error.schema, name),
                suggestion=_required_hint(name),
            )
        return

    if kind == "additionalProperties":
        allowed = list(error.schema.get("properties", {}))
        for name in sorted(set(value) - set(allowed)):
            close = _closest(name, allowed)
            hint = f"Did you mean {_show(close)}? " if close else ""
            where = (
                "" if "attrs" not in allowed else " Custom attributes go in `attrs`."
            )
            yield Issue(
                code="unknown_field",
                path=_join(path, name),
                message="field not allowed",
                received=_show(value[name]),
                expected=f"only the fields {_show_list(allowed)}",
                suggestion=f"{hint}Remove or rename the field.{where}",
            )
        return

    if kind == "anyOf" and path.endswith(".type"):
        yield _type_issue(path, value)
        return

    if kind == "pattern":
        yield _pattern_issue(
            path, value, error.validator_value, _node_type(document, error)
        )
        return

    yield _generic_issue(path, error)


def _type_issue(path: str, value: Any) -> Issue:
    is_node = path.startswith("$.nodes")
    standard = STANDARD_NODE_TYPES if is_node else STANDARD_EDGE_TYPES
    style = (
        "PascalCase (e.g. `Requirement`)"
        if is_node
        else "snake_case (e.g. `satisfies`)"
    )
    entity = "entity" if is_node else "relation"
    if isinstance(value, str):
        close = _closest(value, standard)
        hint = f"Use the standard type {_show(close)}." if close else ""
        hint += f" A custom type must be in {style}."
    else:
        hint = f"Use a string: a standard type or a custom one in {style}."
    return Issue(
        code="invalid_type_name",
        path=path,
        message=f"invalid {entity} type",
        received=_show(value),
        expected=f"one of {_show_list(sorted(standard))} or a custom type in {style}",
        suggestion=hint.strip(),
    )


def _node_type(document: Any, error: SchemaError) -> str | None:
    """Type of the node a `$.nodes[i].id` belongs to, if known."""
    parts = list(error.absolute_path)
    if len(parts) != 3 or parts[0] != "nodes" or parts[2] != "id":
        return None
    node = document["nodes"][parts[1]]
    type_ = node.get("type")
    return type_ if isinstance(type_, str) else None


def _pattern_issue(
    path: str, value: Any, pattern: str, node_type: str | None = None
) -> Issue:
    if pattern == _TIMESTAMP_PATTERN:
        return Issue(
            code="invalid_timestamp",
            path=path,
            message="badly formatted date",
            received=_show(value),
            expected="ISO-8601 date with time zone, e.g. `2026-10-09T12:00:00Z`",
            suggestion="Use the format `YYYY-MM-DDTHH:MM:SS` followed by `Z` "
            "or `+HH:MM`.",
        )
    if pattern == _ID_PATTERN:
        hint = "Use `<type>:<path|qualified name|slug>` with a lowercase type"
        prefix, sep, rest = (
            value.partition(":") if isinstance(value, str) else ("", "", "")
        )
        if sep and rest.strip() and prefix:
            hint += f", e.g. {_show(f'{prefix.lower()}:{rest}')}"
        elif not sep and isinstance(value, str) and value.strip() and node_type:
            hint += f", e.g. {_show(f'{node_type.lower()}:{value.strip()}')}"
        else:
            hint += ", e.g. `file:src/app/main.py` or `concept:my-concept`"
        return Issue(
            code="invalid_id",
            path=path,
            message="badly formatted ID",
            received=_show(value),
            expected="`<type>:<identifier>`",
            suggestion=hint + ".",
        )
    return Issue(
        code="pattern",
        path=path,
        message="the value does not have the expected format",
        received=_show(value),
        expected=f"a string matching `{pattern}`",
        suggestion="Adjust the value to the given format.",
    )


def _generic_issue(path: str, error: SchemaError) -> Issue:
    kind, expected_value, value = error.validator, error.validator_value, error.instance
    match kind:
        case "type":
            names = (
                expected_value if isinstance(expected_value, list) else [expected_value]
            )
            expected = " or ".join(_JSON_TYPES.get(n, n) for n in names)
            return Issue(
                code="wrong_type",
                path=path,
                message="wrong data type",
                received=f"{_show(value)} ({_json_type(value)})",
                expected=expected,
                suggestion=f"Change the value to a value of type {expected}.",
            )
        case "enum":
            close = _closest(value, expected_value) if isinstance(value, str) else None
            hint = (
                f"Use {_show(close)}." if close else "Use one of the expected values."
            )
            return Issue(
                code="not_allowed",
                path=path,
                message="value not allowed",
                received=_show(value),
                expected=f"one of {_show_list(expected_value)}",
                suggestion=hint,
            )
        case "const":
            return Issue(
                code="not_allowed",
                path=path,
                message="value not allowed",
                received=_show(value),
                expected=_show(expected_value),
                suggestion=f"Use {_show(expected_value)}.",
            )
        case "minimum" | "maximum":
            low, high = _bounds(error.schema)
            return Issue(
                code="out_of_range",
                path=path,
                message="number out of range",
                received=_show(value),
                expected=f"a number between {low} and {high}",
                suggestion=f"Use a value between {low} and {high}.",
            )
        case "minItems" | "maxItems":
            low, high = error.schema.get("minItems", 0), error.schema.get("maxItems")
            count = _plural(len(value), "item", "items")
            expected = (
                f"exactly {low} items"
                if low == high
                else f"between {low} and {high or '∞'} items"
            )
            return Issue(
                code="wrong_length",
                path=path,
                message="wrong number of items",
                received=f"{_show(value)} ({count})",
                expected=expected,
                suggestion="For `lines` use `[start, end]`, e.g. `[12, 40]`.",
            )
        case "minLength":
            return Issue(
                code="empty",
                path=path,
                message="empty string",
                received=_show(value),
                expected="a non-empty string",
                suggestion="Fill in the field or remove it if it is optional.",
            )
    return Issue(
        code=str(kind),
        path=path,
        message=error.message,
        received=_show(value),
        expected=f"{kind}: {_show(expected_value)}",
        suggestion="Check the value against `kg schema`.",
    )


def _required_hint(name: str) -> str:
    if name == "provenance":
        return f"Add `provenance`, e.g. {_PROVENANCE_EXAMPLE}."
    if name in {"nodes", "edges"}:
        return f'Add `"{name}": []` even if it is empty.'
    if name == "version":
        return 'Add `"version": "1"`.'
    return f"Add the field `{name}`."


def _describe_property(schema: dict[str, Any], name: str) -> str:
    prop = schema.get("properties", {}).get(name, {})
    if "$ref" in prop:
        ref = prop["$ref"].rsplit("/", 1)[-1]
        prop = {**_DEFS.get(ref, {}), **prop}
    description = prop.get("description")
    return f"field `{name}`" + (f": {description}" if description else "")


# --- Helpers -----------------------------------------------------------------


def _format_path(parts: Iterable[str | int]) -> str:
    path = "$"
    for part in parts:
        path = f"{path}[{part}]" if isinstance(part, int) else _join(path, part)
    return path


def _join(path: str, name: str) -> str:
    return (
        f"{path}.{name}"
        if re.fullmatch(r"[A-Za-z_$][\w$]*", name)
        else f"{path}[{name!r}]"
    )


def _parse_path(path: str) -> list[str | int]:
    parts: list[str | int] = []
    for name, index, quoted in re.findall(r"\.([\w$]+)|\[(\d+)\]|\['([^']*)'\]", path):
        parts.append(int(index) if index else name or quoted)
    return parts


_TOP_LEVEL_ORDER = {"version": 0, "nodes": 1, "edges": 2}


def _sort_key(parts: Iterable[str | int]) -> list[tuple[int, int, str]]:
    """Document order: version, nodes, edges; indexes in numeric order."""
    key = []
    for depth, part in enumerate(parts):
        if isinstance(part, int):
            key.append((0, part, ""))
        else:
            rank = _TOP_LEVEL_ORDER.get(part, 3) if depth == 0 else 0
            key.append((1, rank, part))
    return key


def _closest(value: str, options: Iterable[str]) -> str | None:
    options = list(options)
    for option in options:
        if option.lower() == value.lower():
            return option
    close = difflib.get_close_matches(value, options, n=1, cutoff=0.8)
    return close[0] if close else None


def _bounds(schema: dict[str, Any]) -> tuple[Any, Any]:
    return schema.get("minimum", "-∞"), schema.get("maximum", "∞")


def _json_type(value: Any) -> str:
    for name, py in (
        ("null", type(None)),
        ("boolean", bool),
        ("integer", int),
        ("number", float),
        ("string", str),
        ("array", list),
        ("object", dict),
    ):
        if isinstance(value, py):
            return name
    return type(value).__name__


def _show(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= _MAX_RECEIVED else text[: _MAX_RECEIVED - 1] + "…"


def _show_list(values: Iterable[Any]) -> str:
    return ", ".join(_show(v) for v in values)


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"
