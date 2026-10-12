"""JSON Schema of the `kg` input format and standard catalog (RF-01, RF-02).

The schema lives in `kg.schema.json` as package data and is the single source
of truth: the type catalogs are read from it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from pathlib import Path
from typing import Any, Literal

from jsonschema import Draft202012Validator

SCHEMA_RESOURCE = "kg.schema.json"


def schema_path() -> Path:
    """Path of the schema file inside the installed package."""
    return Path(str(files(__package__) / SCHEMA_RESOURCE))


@cache
def _schema_text() -> str:
    return (files(__package__) / SCHEMA_RESOURCE).read_text(encoding="utf-8")


def load_schema() -> dict[str, Any]:
    """Return a copy of the JSON Schema (draft 2020-12)."""
    return json.loads(_schema_text())


def validator() -> Draft202012Validator:
    """Schema validator; human-friendly errors live in `validation`."""
    return Draft202012Validator(load_schema())


_DEFS = load_schema()["$defs"]
STANDARD_NODE_TYPES: frozenset[str] = frozenset(_DEFS["standardNodeType"]["enum"])
STANDARD_EDGE_TYPES: frozenset[str] = frozenset(_DEFS["standardEdgeType"]["enum"])


@dataclass(frozen=True)
class CustomType:
    """Use of a type outside the standard catalog: valid, but warned about."""

    path: str
    kind: Literal["node", "edge"]
    type: str

    @property
    def message(self) -> str:
        entity = "entity" if self.kind == "node" else "relation"
        return f"{self.path}: custom {entity} type '{self.type}'"


def find_custom_types(document: dict[str, Any]) -> list[CustomType]:
    """List the non-standard types of a document, with their JSON path.

    It does not validate: malformed items are ignored.
    """
    found: list[CustomType] = []
    for kind, key, standard in (
        ("node", "nodes", STANDARD_NODE_TYPES),
        ("edge", "edges", STANDARD_EDGE_TYPES),
    ):
        items = document.get(key)
        if not isinstance(items, list):
            continue
        for i, item in enumerate(items):
            type_ = item.get("type") if isinstance(item, dict) else None
            if isinstance(type_, str) and type_ not in standard:
                found.append(CustomType(f"$.{key}[{i}].type", kind, type_))
    return found
