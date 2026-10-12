"""Almacén `.kg/` del grafo: lectura y escritura deterministas (RF-70, RF-71, RNF-08).

El almacén es un único `graph.json` que cumple el esquema de entrada (`kg schema`),
así que `kg validate .kg/graph.json` sirve para revisarlo. El orden de nodos,
aristas y claves es fijo: el mismo grafo produce el mismo archivo byte a byte.
Formato documentado en `docs/almacen.md`.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import networkx as nx

from kg.schema import load_schema
from kg.schema.validation import Report, validate_document, validate_path

GRAPH_FILE = "graph.json"
FORMAT_VERSION: str = load_schema()["properties"]["version"]["const"]

# Orden de los campos en el archivo: primero la identidad, luego el contenido.
_NODE_FIELDS = ("type", "label", "description", "attrs", "provenance")
_EDGE_FIELDS = ("type", "attrs", "provenance")


class StoreError(Exception):
    """Error del almacén; `path` es la ruta afectada."""

    def __init__(self, message: str, path: Path) -> None:
        super().__init__(message)
        self.message = message
        self.path = path


class StoreExistsError(StoreError):
    """`kg init` sobre una ruta que ya existe."""


class StoreNotFoundError(StoreError):
    """No hay almacén (o le falta `graph.json`) en la ruta indicada."""


class StoreCorruptError(StoreError):
    """El contenido del almacén no cumple el esquema; `report` tiene el detalle."""

    def __init__(self, message: str, path: Path, report: Report) -> None:
        super().__init__(message, path)
        self.report = report


def graph_path(kg_dir: Path) -> Path:
    """Ruta del archivo del grafo dentro del almacén."""
    return kg_dir / GRAPH_FILE


def init_store(kg_dir: Path) -> Path:
    """Crea el almacén con un grafo vacío y devuelve la ruta de `graph.json`."""
    if kg_dir.exists():
        raise StoreExistsError(f"ya existe {kg_dir}; no se ha modificado", kg_dir)
    if not kg_dir.parent.is_dir():
        raise StoreNotFoundError(
            f"no existe el directorio {kg_dir.parent} donde crear el almacén", kg_dir
        )
    kg_dir.mkdir()
    return save_graph(nx.MultiDiGraph(), kg_dir)


def load_graph(kg_dir: Path) -> nx.MultiDiGraph:
    """Lee el grafo del almacén, validándolo contra el esquema."""
    path = graph_path(kg_dir)
    if not path.is_file():
        raise StoreNotFoundError(
            f"no hay almacén en {kg_dir}; créalo con `kg init`", path
        )
    report = validate_path(path)
    if not report.ok:
        raise StoreCorruptError(
            f"{path} no es un almacén válido; revísalo con `kg validate {path}`",
            path,
            report,
        )
    return document_to_graph(json.loads(path.read_text(encoding="utf-8")), path)


def save_graph(graph: nx.MultiDiGraph, kg_dir: Path) -> Path:
    """Escribe el grafo de forma atómica; nunca deja un almacén inválido."""
    path = graph_path(kg_dir)
    document = graph_to_document(graph)
    report = validate_document(document)
    if not report.ok:
        raise StoreCorruptError(
            "el grafo no cumple el esquema; no se ha escrito el almacén", path, report
        )
    document_to_graph(document, path)  # rechaza aristas duplicadas
    _write_atomic(path, dumps(document))
    return path


# --- Conversión documento <-> grafo -------------------------------------------


def document_to_graph(
    document: dict[str, Any], path: Path | None = None
) -> nx.MultiDiGraph:
    """Construye el grafo a partir de un documento ya validado.

    La identidad de una arista es `(source, target, type)` y `type` es su clave en
    el `MultiDiGraph`; dos aristas con la misma identidad son un error.
    """
    graph = nx.MultiDiGraph(version=document["version"])
    for node in document["nodes"]:
        graph.add_node(node["id"], **_pick(node, _NODE_FIELDS))
    for i, edge in enumerate(document["edges"]):
        source, target, type_ = edge["source"], edge["target"], edge["type"]
        if graph.has_edge(source, target, key=type_):
            raise StoreError(
                f"$.edges[{i}]: arista duplicada {source} -[{type_}]-> {target}",
                path or Path("-"),
            )
        graph.add_edge(source, target, key=type_, **_pick(edge, _EDGE_FIELDS))
    return graph


def graph_to_document(graph: nx.MultiDiGraph) -> dict[str, Any]:
    """Documento canónico del grafo: nodos por ID y aristas por (source, target, type).

    Los campos siguen un orden fijo y las claves de `attrs` y `provenance` van
    ordenadas, de modo que el resultado no depende del orden de inserción.
    """
    nodes = [
        {"id": node_id, **_fields(data, _NODE_FIELDS)}
        for node_id, data in sorted(graph.nodes(data=True), key=lambda n: str(n[0]))
    ]
    edges = [
        {"source": u, "target": v, **_fields(data, _EDGE_FIELDS)}
        for u, v, data in graph.edges(data=True)
    ]
    edges.sort(key=_edge_sort_key)
    return {"version": FORMAT_VERSION, "nodes": nodes, "edges": edges}


def dumps(document: dict[str, Any]) -> str:
    """Serializa un documento canónico: UTF-8 legible, 2 espacios y salto final."""
    return json.dumps(document, ensure_ascii=False, indent=2) + "\n"


# --- Utilidades ---------------------------------------------------------------


def _pick(data: dict[str, Any], fields: Iterable[str]) -> dict[str, Any]:
    return {f: data[f] for f in fields if f in data}


def _fields(data: dict[str, Any], fields: Iterable[str]) -> dict[str, Any]:
    """Campos en el orden de `fields`, con sus valores en forma canónica."""
    return {f: _canonical(v) for f, v in _pick(data, fields).items()}


def _canonical(value: Any) -> Any:
    """Copia con las claves de los objetos anidados ordenadas; las listas no."""
    if isinstance(value, dict):
        return {k: _canonical(value[k]) for k in sorted(value)}
    if isinstance(value, list):
        return [_canonical(v) for v in value]
    return value


def _edge_sort_key(edge: dict[str, Any]) -> tuple[str, str, str]:
    return (str(edge["source"]), str(edge["target"]), str(edge.get("type", "")))


def _write_atomic(path: Path, text: str) -> None:
    # mkstemp crea el archivo con 0600; se conservan los permisos del existente.
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
