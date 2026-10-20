"""Interactive, self-contained HTML of the graph (RF-51–RF-55, PA-03).

One file with everything inline: the graph as JSON, the page's own code and
vis-network 9.1.2 (the engine pyvis wraps; see `assets/README.md`). It works
offline and from `file://`. The page is read-only: for each element it shows
the `kg edit`/`kg remove` command that changes it in the store.
"""

from __future__ import annotations

import html
import json
import math
import re
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

import networkx as nx

from kg import __version__
from kg.render import style
from kg.render.defaults import INITIAL_NODES
from kg.render.static import HIDE_ORDER

# Matplotlib marker → vis-network shape.
_SHAPES = {
    "*": "star",
    "s": "square",
    "o": "dot",
    ".": "dot",
    "D": "diamond",
    "d": "diamond",
    "^": "triangle",
    "v": "triangleDown",
    "h": "hexagon",
    "p": "hexagon",
    "P": "star",
    "X": "star",
}
# Types whose marker has no vis shape of its own get a dashed border, so no
# two types of a family look the same.
_DASHED = frozenset({"Document", "Person", "Issue"})

# Relation styles: a dash pattern each; `tests` wears the tests color.
_RELATIONS: dict[str, dict[str, Any]] = {
    "contains": {"dashes": None},
    "defines": {"dashes": None},
    "imports": {"dashes": [6, 4]},
    "depends_on": {"dashes": [10, 4]},
    "calls": {"dashes": [2, 3]},
    "tests": {"dashes": [2, 3], "family": "tests"},
    "configures": {"dashes": [4, 4]},
    "documents": {"dashes": [1, 3]},
    "implements": {"dashes": [8, 3, 2, 3]},
    "justifies": {"dashes": [8, 3, 2, 3]},
    "authored_by": {"dashes": [1, 3]},
}
_CUSTOM_RELATION: dict[str, Any] = {"dashes": [3, 6]}

_TOKEN = re.compile(r"\{\{([A-Z_]+)\}\}")


@dataclass
class HtmlResult:
    """What the page contains and which types start hidden."""

    nodes: int
    edges: int
    hidden: list[str] = field(default_factory=list)


def render_html(
    graph: nx.MultiDiGraph, path: Path, title: str | None = None
) -> HtmlResult:
    """Write the interactive page for the graph."""
    page, result = build_html(graph, title)
    path.write_text(page, encoding="utf-8")
    return result


def build_html(
    graph: nx.MultiDiGraph, title: str | None = None
) -> tuple[str, HtmlResult]:
    """The page as text: the same graph always gives the same text."""
    data = graph_data(graph, title)
    values = {
        "KG_TITLE": html.escape(title or "Knowledge graph"),
        "KG_VERSION": html.escape(__version__),
        "KG_DATA": _json_for_script(data),
        "VIS_JS": _asset("vis-network.min.js"),
        "SURFACE": style.SURFACE,
        "INK": style.INK,
        "INK_MUTED": style.INK_MUTED,
        "SURFACE_DARK": style.SURFACE_DARK,
        "INK_DARK": style.INK_DARK,
        "INK_MUTED_DARK": style.INK_MUTED_DARK,
    }
    # One pass, so a value that happens to contain `{{X}}` is never expanded.
    page = _TOKEN.sub(lambda m: values[m.group(1)], _asset("template.html"))
    result = HtmlResult(len(data["nodes"]), len(data["edges"]), data["hidden"])
    return page, result


def graph_data(graph: nx.MultiDiGraph, title: str | None = None) -> dict[str, Any]:
    """Everything the page needs, in a deterministic order."""
    nodes = [
        {
            "id": node,
            **_fields(
                graph.nodes[node],
                ("type", "label", "description", "attrs", "provenance"),
            ),
        }
        for node in sorted(graph.nodes)
    ]
    edges = [
        {"source": u, "target": v, "type": k, **_fields(d, ("attrs", "provenance"))}
        for u, v, k, d in sorted(graph.edges(keys=True, data=True), key=lambda e: e[:3])
    ]
    types = sorted({n["type"] for n in nodes}, key=_type_order)
    relations = sorted({e["type"] for e in edges})
    return {
        "title": title,
        "nodes": nodes,
        "edges": edges,
        # Keys get sorted in the JSON; the `*_order` lists keep the legend's order.
        "types": {t: _type_style(t) for t in types},
        "type_order": types,
        "relations": {r: _RELATIONS.get(r, _CUSTOM_RELATION) for r in relations},
        "relation_order": relations,
        "families": {
            f.name: {
                "color": f.color,
                "stroke": f.stroke,
                "dark": f.dark,
                "dark_stroke": f.dark_stroke,
            }
            for f in style.FAMILIES
        },
        "theme": {
            "light": {
                "ink": style.INK,
                "ink_muted": style.INK_MUTED,
                "surface": style.SURFACE,
                "edge": style.EDGE,
            },
            "dark": {
                "ink": style.INK_DARK,
                "ink_muted": style.INK_MUTED_DARK,
                "surface": style.SURFACE_DARK,
                "edge": style.EDGE_DARK,
            },
        },
        "hidden": initially_hidden(nodes),
    }


def initially_hidden(
    nodes: list[dict[str, Any]], limit: int = INITIAL_NODES
) -> list[str]:
    """Types unticked when the page opens: as in the static image, whole types
    in `HIDE_ORDER` until at most `limit` nodes show. Never fails."""
    counts: dict[str, int] = {}
    for node in nodes:
        counts[node["type"]] = counts.get(node["type"], 0) + 1
    shown, hidden = len(nodes), []
    for type_ in HIDE_ORDER:
        if shown <= limit:
            break
        if type_ in counts:
            hidden.append(type_)
            shown -= counts[type_]
    return hidden


def _type_style(type_: str) -> dict[str, Any]:
    s = style.type_style(type_)
    return {
        "family": s.family.name,
        "shape": _SHAPES.get(s.marker, "dot"),
        "dashed": type_ in _DASHED,
        "size": s.size,
        "px": round(7 * math.sqrt(s.size) + 3, 1),
    }


def _type_order(type_: str) -> tuple[int, str]:
    families = [f.name for f in style.FAMILIES]
    return families.index(style.type_style(type_).family.name), type_


def _fields(data: dict[str, Any], names: tuple[str, ...]) -> dict[str, Any]:
    return {name: data[name] for name in names if name in data}


def _json_for_script(data: dict[str, Any]) -> str:
    """JSON safe inside `<script>`: no `<`, `>` or `&` that could close it."""
    text = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def _asset(name: str) -> str:
    return resources.files("kg.render").joinpath("assets", name).read_text("utf-8")
