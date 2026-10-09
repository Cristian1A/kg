"""JSON Schema del formato de entrada de `kg` y catálogo estándar (RF-01, RF-02).

El esquema vive en `kg.schema.json` como dato del paquete y es la única fuente
de verdad: los catálogos de tipos se leen de él.
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
    """Ruta del archivo del esquema dentro del paquete instalado."""
    return Path(str(files(__package__) / SCHEMA_RESOURCE))


@cache
def _schema_text() -> str:
    return (files(__package__) / SCHEMA_RESOURCE).read_text(encoding="utf-8")


def load_schema() -> dict[str, Any]:
    """Devuelve una copia del JSON Schema (draft 2020-12)."""
    return json.loads(_schema_text())


def validator() -> Draft202012Validator:
    """Validador del esquema; el análisis de errores para humanos es de #3."""
    return Draft202012Validator(load_schema())


_DEFS = load_schema()["$defs"]
STANDARD_NODE_TYPES: frozenset[str] = frozenset(_DEFS["standardNodeType"]["enum"])
STANDARD_EDGE_TYPES: frozenset[str] = frozenset(_DEFS["standardEdgeType"]["enum"])


@dataclass(frozen=True)
class CustomType:
    """Uso de un tipo fuera del catálogo estándar: válido, pero se avisa."""

    path: str
    kind: Literal["node", "edge"]
    type: str

    @property
    def message(self) -> str:
        entity = "entidad" if self.kind == "node" else "relación"
        return f"{self.path}: tipo de {entity} personalizado '{self.type}'"


def find_custom_types(document: dict[str, Any]) -> list[CustomType]:
    """Lista los tipos no estándar de un documento, con su ruta JSON.

    No valida: los elementos mal formados se ignoran.
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
