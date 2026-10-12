"""Fusión básica por ID de un documento en el grafo (RF-21, RF-30, S-03).

Política del MVP: un nodo con ID existente o una arista con la misma identidad
(`source`, `target`, `type`) se combinan en vez de duplicarse. Los campos que
el documento no trae se conservan; si trae un valor distinto, gana el nuevo y
se registra un conflicto. Excepción: una procedencia `parser` no la sustituye
otra que no sea `parser`, para no perder el dato determinista al enriquecer con
un agente. La política configurable es RF-33 (v0.2).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

import networkx as nx

from kg import store
from kg.schema.validation import Report, validate_text

Kind = Literal["node", "edge"]


@dataclass(frozen=True)
class Conflict:
    """Valor del documento distinto del existente; `kept` indica cuál se queda."""

    kind: Kind
    element: str
    field: str
    old: Any
    new: Any
    kept: Literal["new", "old"] = "new"

    def to_text(self) -> str:
        show = _show_provenance if self.field == "provenance" else _show
        if self.kept == "old":
            return (
                f"{self.element} · {self.field}: se mantiene {show(self.old)}; "
                f"se descarta {show(self.new)}"
            )
        return f"{self.element} · {self.field}: {show(self.old)} → {show(self.new)}"


@dataclass
class Changes:
    """Elementos del documento según su efecto en el grafo."""

    added: list[str] = field(default_factory=list)
    merged: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, list[str]]:
        return {
            "added": self.added,
            "merged": self.merged,
            "unchanged": self.unchanged,
        }


@dataclass
class MergeReport:
    """Resumen de una fusión."""

    nodes: Changes = field(default_factory=Changes)
    edges: Changes = field(default_factory=Changes)
    conflicts: list[Conflict] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(
            self.nodes.added
            or self.nodes.merged
            or self.edges.added
            or self.edges.merged
        )

    def to_text(self) -> str:
        lines = [
            f"  nodos:   {_counts(self.nodes, 'añadido', 'fusionado')}",
            f"  aristas: {_counts(self.edges, 'añadida', 'fusionada')}",
        ]
        if self.conflicts:
            n = len(self.conflicts)
            lines.append(f"  {n} {'conflicto' if n == 1 else 'conflictos'}:")
            lines += [f"    {c.to_text()}" for c in self.conflicts]
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "changed": self.changed,
            "nodes": self.nodes.to_dict(),
            "edges": self.edges.to_dict(),
            "conflicts": [asdict(c) for c in self.conflicts],
        }


@dataclass
class AddResult:
    """Resultado de `add_to_store`: `merge` es `None` si el documento no es válido."""

    graph_path: Path
    validation: Report
    merge: MergeReport | None = None


def add_to_store(kg_dir: Path, text: str) -> AddResult:
    """Valida un documento JSON y lo fusiona en el almacén (`kg add`).

    Las aristas pueden apuntar a nodos que ya están en el almacén. Si hay errores
    de validación no se modifica nada; si la fusión no cambia nada, no se escribe.
    Deja pasar los `StoreError` de cargar o guardar el almacén.
    """
    graph = store.load_graph(kg_dir)
    report = validate_text(text, known_ids=set(graph.nodes))
    result = AddResult(store.graph_path(kg_dir), report)
    if not report.ok:
        return result
    merged, result.merge = merge_document(graph, json.loads(text))
    if result.merge.changed:
        store.save_graph(merged, kg_dir)
    return result


def edge_label(source: str, target: str, type_: str) -> str:
    """Identidad legible de una arista: `source -[type]-> target`."""
    return f"{source} -[{type_}]-> {target}"


def merge_document(
    graph: nx.MultiDiGraph, document: dict[str, Any]
) -> tuple[nx.MultiDiGraph, MergeReport]:
    """Devuelve una copia del grafo con el documento fusionado y el resumen.

    El documento debe estar validado (con los IDs del grafo como conocidos).
    """
    merged = graph.copy()
    report = MergeReport()

    for node in document["nodes"]:
        node_id = node["id"]
        incoming = {k: v for k, v in node.items() if k != "id"}
        if node_id not in merged:
            merged.add_node(node_id, **incoming)
            report.nodes.added.append(node_id)
            continue
        changed = _merge_into(merged.nodes[node_id], incoming, "node", node_id, report)
        (report.nodes.merged if changed else report.nodes.unchanged).append(node_id)

    for edge in document["edges"]:
        source, target, type_ = edge["source"], edge["target"], edge["type"]
        label = edge_label(source, target, type_)
        incoming = {k: v for k, v in edge.items() if k not in ("source", "target")}
        if not merged.has_edge(source, target, key=type_):
            merged.add_edge(source, target, key=type_, **incoming)
            report.edges.added.append(label)
            continue
        data = merged.edges[source, target, type_]
        changed = _merge_into(data, incoming, "edge", label, report)
        (report.edges.merged if changed else report.edges.unchanged).append(label)

    return merged, report


def _merge_into(
    current: dict[str, Any],
    incoming: dict[str, Any],
    kind: Kind,
    element: str,
    report: MergeReport,
) -> bool:
    """Combina `incoming` en `current` (in situ). Devuelve si algo cambió."""
    changed = False
    for name, value in incoming.items():
        if name == "attrs":
            changed |= _merge_attrs(current, value, kind, element, report)
            continue
        old = current.get(name)
        if old == value:
            continue
        if name == "provenance" and _keeps_parser(old, value):
            report.conflicts.append(Conflict(kind, element, name, old, value, "old"))
            continue
        if name in current:
            report.conflicts.append(Conflict(kind, element, name, old, value))
        current[name] = value
        changed = True
    return changed


def _keeps_parser(old: Any, new: dict[str, Any]) -> bool:
    """La procedencia `parser` prevalece sobre `llm` o `manual` (avance de RF-33)."""
    return (
        isinstance(old, dict)
        and old.get("method") == "parser"
        and new.get("method") != "parser"
    )


def _merge_attrs(
    current: dict[str, Any],
    attrs: dict[str, Any],
    kind: Kind,
    element: str,
    report: MergeReport,
) -> bool:
    # Fusión por clave de primer nivel; los valores anidados se sustituyen enteros.
    target = dict(current.get("attrs", {}))
    changed = False
    for key, value in attrs.items():
        if key in target and target[key] == value:
            continue
        if key in target:
            report.conflicts.append(
                Conflict(kind, element, f"attrs.{key}", target[key], value)
            )
        target[key] = value
        changed = True
    if changed:
        current["attrs"] = target
    return changed


def _counts(changes: Changes, added: str, merged: str) -> str:
    def plural(n: int, word: str) -> str:
        return f"{n} {word if n == 1 else word + 's'}"

    return (
        f"{plural(len(changes.added), added)}, "
        f"{plural(len(changes.merged), merged)}, "
        f"{len(changes.unchanged)} sin cambios"
    )


def _show(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return text if len(text) <= 60 else text[:59] + "…"


def _show_provenance(value: Any) -> str:
    if not isinstance(value, dict):
        return _show(value)
    return (
        f"{value.get('method')} ({value.get('extractor')}, "
        f"confianza {value.get('confidence')})"
    )
