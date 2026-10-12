"""Validación de documentos de entrada con errores accionables (RF-03–RF-05).

Cada problema indica ruta JSON, valor recibido, valor esperado y una sugerencia,
para que un agente pueda corregir el documento en una sola iteración.
"""

from __future__ import annotations

import difflib
import json
import re
from collections.abc import Iterable, Sequence
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
    "object": "objeto",
    "array": "lista",
    "string": "texto",
    "integer": "entero",
    "number": "número",
    "boolean": "booleano",
    "null": "null",
}
_MAX_RECEIVED = 80


@dataclass(frozen=True)
class Issue:
    """Problema de validación. `received` es `None` cuando el valor falta."""

    code: str
    path: str
    message: str
    received: str | None
    expected: str
    suggestion: str
    severity: Severity = "error"

    def to_text(self) -> str:
        received = "(ausente)" if self.received is None else self.received
        return (
            f"{self.severity}: {self.path}: {self.message}\n"
            f"  recibido:   {received}\n"
            f"  esperado:   {self.expected}\n"
            f"  sugerencia: {self.suggestion}"
        )


@dataclass
class Report:
    """Resultado de validar un documento."""

    errors: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)
    nodes: int = 0
    edges: int = 0

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self, name: str) -> str:
        if self.ok:
            nodes = _plural(self.nodes, "nodo", "nodos")
            edges = _plural(self.edges, "arista", "aristas")
            head = f"{name} es válido ({nodes}, {edges})"
        else:
            head = (
                f"{name} no es válido: {_plural(len(self.errors), 'error', 'errores')}"
            )
        if self.warnings:
            head += f", {_plural(len(self.warnings), 'aviso', 'avisos')}"
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


def validate_text(text: str) -> Report:
    """Valida el contenido de un archivo JSON."""
    try:
        document = json.loads(text)
    except json.JSONDecodeError as e:
        return Report(
            errors=[
                Issue(
                    code="invalid_json",
                    path="$",
                    message=f"JSON mal formado: {e.msg}",
                    received=f"línea {e.lineno}, columna {e.colno}",
                    expected="un documento JSON válido",
                    suggestion="Corrige la sintaxis en esa posición (comas, comillas, "
                    "llaves) y vuelve a validar.",
                )
            ]
        )
    return validate_document(document)


def validate_path(path: Path) -> Report:
    """Lee y valida un archivo. Deja pasar `OSError` para que lo trate la CLI."""
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        return Report(
            errors=[
                Issue(
                    code="invalid_encoding",
                    path="$",
                    message="el archivo no está en UTF-8",
                    received=f"byte {e.start}",
                    expected="texto UTF-8",
                    suggestion="Guarda el archivo con codificación UTF-8.",
                )
            ]
        )
    return validate_text(text)


def validate_document(document: Any) -> Report:
    """Valida un documento ya cargado: esquema, IDs duplicados y referencias."""
    report = Report()
    seen: set[tuple[str, str]] = set()
    for error in validator().iter_errors(document):
        for issue in _translate(error, document):
            # jsonschema emite un error `required` por campo con la lista completa
            if (issue.code, issue.path) not in seen:
                seen.add((issue.code, issue.path))
                report.errors.append(issue)

    if not isinstance(document, dict):
        return report
    nodes = _items(document, "nodes")
    edges = _items(document, "edges")
    report.nodes, report.edges = len(nodes), len(edges)

    ids = _check_duplicate_ids(nodes, report)
    _check_references(edges, ids, report)
    _check_custom_types(document, report)
    _check_id_prefixes(nodes, report)
    report.errors.sort(key=lambda i: _sort_key(_parse_path(i.path)))
    report.warnings.sort(key=lambda i: _sort_key(_parse_path(i.path)))
    return report


# --- Comprobaciones semánticas ----------------------------------------------


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
                    message=f"ID duplicado; ya se usa en $.nodes[{first[node_id]}]",
                    received=_show(node_id),
                    expected="un ID único en el archivo",
                    suggestion="Fusiona ambos nodos en uno solo o, si son entidades "
                    "distintas, dales IDs distintos.",
                )
            )
        else:
            first[node_id] = i
    return first


def _check_references(
    edges: Sequence[tuple[int, dict[str, Any]]], ids: dict[str, int], report: Report
) -> None:
    for i, edge in edges:
        for end in ("source", "target"):
            ref = edge.get(end)
            if not isinstance(ref, str) or ref in ids:
                continue
            close = difflib.get_close_matches(ref, list(ids), n=1)
            hint = f"¿Querías decir {_show(close[0])}? " if close else ""
            report.errors.append(
                Issue(
                    code="broken_reference",
                    path=f"$.edges[{i}].{end}",
                    message="la arista apunta a un nodo que no existe en el archivo",
                    received=_show(ref),
                    expected="el ID de un nodo declarado en `nodes`",
                    suggestion=f"{hint}Corrige el ID o añade el nodo a `nodes`.",
                )
            )


def _check_custom_types(document: dict[str, Any], report: Report) -> None:
    for custom in find_custom_types(document):
        if not re.match(_CUSTOM_TYPE_PATTERNS[custom.kind], custom.type):
            continue  # ya se informa como error de esquema
        standard = STANDARD_NODE_TYPES if custom.kind == "node" else STANDARD_EDGE_TYPES
        close = _closest(custom.type, standard)
        hint = (
            f"Si equivale a {_show(close)}, usa el tipo estándar; si no, mantenlo."
            if close
            else "Comprueba que ningún tipo estándar encaja; si no, mantenlo."
        )
        entity = "entidad" if custom.kind == "node" else "relación"
        report.warnings.append(
            Issue(
                code="custom_type",
                path=custom.path,
                message=f"tipo de {entity} personalizado",
                received=_show(custom.type),
                expected=f"un tipo del catálogo estándar de {entity}",
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
                    message=f"el prefijo del ID no coincide con el tipo {_show(type_)}",
                    received=_show(node_id),
                    expected=f"{type_.lower()}:<…>",
                    suggestion=f"Usa {_show(f'{type_.lower()}:{rest}')} o revisa el "
                    "tipo del nodo.",
                    severity="warning",
                )
            )


# --- Traducción de errores de jsonschema -------------------------------------


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
                message="falta un campo obligatorio",
                received=None,
                expected=_describe_property(error.schema, name),
                suggestion=_required_hint(name),
            )
        return

    if kind == "additionalProperties":
        allowed = list(error.schema.get("properties", {}))
        for name in sorted(set(value) - set(allowed)):
            close = _closest(name, allowed)
            hint = f"¿Querías decir {_show(close)}? " if close else ""
            where = (
                ""
                if "attrs" not in allowed
                else " Los atributos propios van en `attrs`."
            )
            yield Issue(
                code="unknown_field",
                path=_join(path, name),
                message="campo no permitido",
                received=_show(value[name]),
                expected=f"solo los campos {_show_list(allowed)}",
                suggestion=f"{hint}Elimina el campo o renómbralo.{where}",
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
        "PascalCase (p. ej. `Requirement`)"
        if is_node
        else "snake_case (p. ej. `satisfies`)"
    )
    entity = "entidad" if is_node else "relación"
    if isinstance(value, str):
        close = _closest(value, standard)
        hint = f"Usa el tipo estándar {_show(close)}." if close else ""
        hint += f" Un tipo personalizado debe ir en {style}."
    else:
        hint = f"Usa un texto: un tipo estándar o uno personalizado en {style}."
    return Issue(
        code="invalid_type_name",
        path=path,
        message=f"tipo de {entity} no válido",
        received=_show(value),
        expected=f"uno de {_show_list(sorted(standard))} "
        f"o un tipo personalizado en {style}",
        suggestion=hint.strip(),
    )


def _node_type(document: Any, error: SchemaError) -> str | None:
    """Tipo del nodo al que pertenece un `$.nodes[i].id`, si se conoce."""
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
            message="fecha con formato incorrecto",
            received=_show(value),
            expected="fecha ISO-8601 con zona horaria, p. ej. `2026-10-09T12:00:00Z`",
            suggestion="Usa el formato `AAAA-MM-DDTHH:MM:SS` seguido de `Z` "
            "o `+HH:MM`.",
        )
    if pattern == _ID_PATTERN:
        hint = "Usa `<tipo>:<ruta|nombre cualificado|slug>` con el tipo en minúsculas"
        prefix, sep, rest = (
            value.partition(":") if isinstance(value, str) else ("", "", "")
        )
        if sep and rest.strip() and prefix:
            hint += f", p. ej. {_show(f'{prefix.lower()}:{rest}')}"
        elif not sep and isinstance(value, str) and value.strip() and node_type:
            hint += f", p. ej. {_show(f'{node_type.lower()}:{value.strip()}')}"
        else:
            hint += ", p. ej. `file:src/app/main.py` o `concept:mi-concepto`"
        return Issue(
            code="invalid_id",
            path=path,
            message="ID con formato incorrecto",
            received=_show(value),
            expected="`<tipo>:<identificador>`",
            suggestion=hint + ".",
        )
    return Issue(
        code="pattern",
        path=path,
        message="el valor no tiene el formato esperado",
        received=_show(value),
        expected=f"texto que cumpla `{pattern}`",
        suggestion="Ajusta el valor al formato indicado.",
    )


def _generic_issue(path: str, error: SchemaError) -> Issue:
    kind, expected_value, value = error.validator, error.validator_value, error.instance
    match kind:
        case "type":
            names = (
                expected_value if isinstance(expected_value, list) else [expected_value]
            )
            expected = " o ".join(_JSON_TYPES.get(n, n) for n in names)
            return Issue(
                code="wrong_type",
                path=path,
                message="tipo de dato incorrecto",
                received=f"{_show(value)} ({_json_type(value)})",
                expected=expected,
                suggestion=f"Cambia el valor por un {expected}.",
            )
        case "enum":
            close = _closest(value, expected_value) if isinstance(value, str) else None
            hint = (
                f"Usa {_show(close)}." if close else "Usa uno de los valores esperados."
            )
            return Issue(
                code="not_allowed",
                path=path,
                message="valor no permitido",
                received=_show(value),
                expected=f"uno de {_show_list(expected_value)}",
                suggestion=hint,
            )
        case "const":
            return Issue(
                code="not_allowed",
                path=path,
                message="valor no permitido",
                received=_show(value),
                expected=_show(expected_value),
                suggestion=f"Usa {_show(expected_value)}.",
            )
        case "minimum" | "maximum":
            low, high = _bounds(error.schema)
            return Issue(
                code="out_of_range",
                path=path,
                message="número fuera de rango",
                received=_show(value),
                expected=f"un número entre {low} y {high}",
                suggestion=f"Usa un valor entre {low} y {high}.",
            )
        case "minItems" | "maxItems":
            low, high = error.schema.get("minItems", 0), error.schema.get("maxItems")
            count = _plural(len(value), "elemento", "elementos")
            expected = (
                f"exactamente {low} elementos"
                if low == high
                else f"entre {low} y {high or '∞'} elementos"
            )
            return Issue(
                code="wrong_length",
                path=path,
                message="número de elementos incorrecto",
                received=f"{_show(value)} ({count})",
                expected=expected,
                suggestion="Para `lines` usa `[inicio, fin]`, p. ej. `[12, 40]`.",
            )
        case "minLength":
            return Issue(
                code="empty",
                path=path,
                message="texto vacío",
                received=_show(value),
                expected="texto no vacío",
                suggestion="Rellena el campo o elimínalo si es opcional.",
            )
    return Issue(
        code=str(kind),
        path=path,
        message=error.message,
        received=_show(value),
        expected=f"{kind}: {_show(expected_value)}",
        suggestion="Revisa el valor según `kg schema`.",
    )


def _required_hint(name: str) -> str:
    if name == "provenance":
        return f"Añade `provenance`, p. ej. {_PROVENANCE_EXAMPLE}."
    if name in {"nodes", "edges"}:
        return f'Añade `"{name}": []` aunque esté vacío.'
    if name == "version":
        return 'Añade `"version": "1"`.'
    return f"Añade el campo `{name}`."


def _describe_property(schema: dict[str, Any], name: str) -> str:
    prop = schema.get("properties", {}).get(name, {})
    if "$ref" in prop:
        ref = prop["$ref"].rsplit("/", 1)[-1]
        prop = {**_DEFS.get(ref, {}), **prop}
    description = prop.get("description")
    return f"campo `{name}`" + (f": {description}" if description else "")


# --- Utilidades ---------------------------------------------------------------


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
    """Orden del documento: version, nodes, edges; índices en orden numérico."""
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
        ("booleano", bool),
        ("entero", int),
        ("número", float),
        ("texto", str),
        ("lista", list),
        ("objeto", dict),
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
