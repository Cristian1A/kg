"""Static PNG/SVG image of the graph (RF-50, RNF-08).

Builds a `matplotlib.figure.Figure` without `pyplot`: no global state, no GUI
backend and never `plt.show()`. The layout uses a fixed seed and the files are
written without timestamps, so the same graph gives the same bytes.
"""

from __future__ import annotations

import importlib.util
import math
from collections import Counter
from collections.abc import Collection
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import matplotlib
import networkx as nx
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import FancyArrowPatch
from matplotlib.patheffects import withStroke

from kg.render.defaults import DPI, MAX_NODES
from kg.render.style import EDGE, INK, INK_MUTED, SURFACE, type_style

Format = Literal["png", "svg"]

SEED = 42
# Types hidden first, in this order, when the graph exceeds `max_nodes`: the
# most numerous and the least useful in an overview.
HIDE_ORDER = ("Function", "Test", "File", "Class")
# With more nodes than this, only these types are labeled.
LABEL_ALL_UP_TO = 60
LABELED_TYPES = frozenset(
    {"Repo", "Package", "Module", "Dependency", "Config"}
    # What agents add: few nodes, and the point of an enriched graph.
    | {"Document", "Decision", "Concept", "Service", "Endpoint"}
)
# NetworkX needs scipy for spring_layout from this size on.
_SCIPY_FROM = 500
_BASE_MARKER = 36.0  # points², a Function node
_LABEL_SIZE = 7  # points
_LABEL_OFFSET = 9  # points below the node


class RenderError(Exception):
    """The graph cannot be rendered with the given options."""


@dataclass
class Selection:
    """Nodes that are drawn, and those hidden by type."""

    graph: nx.MultiDiGraph
    hidden: dict[str, int] = field(default_factory=dict)


def select(
    graph: nx.MultiDiGraph,
    types: Collection[str] | None = None,
    max_nodes: int = MAX_NODES,
) -> Selection:
    """Keep the nodes of `types` (all if `None`), then hide whole types in
    `HIDE_ORDER` until at most `max_nodes` remain."""
    keep = [
        n
        for n, data in graph.nodes(data=True)
        if types is None or data.get("type") in types
    ]
    hidden: Counter[str] = Counter(
        graph.nodes[n].get("type") for n in graph if n not in set(keep)
    )
    for type_ in HIDE_ORDER:
        if len(keep) <= max_nodes:
            break
        removed = [n for n in keep if graph.nodes[n].get("type") == type_]
        if removed:
            hidden[type_] += len(removed)
            keep = [n for n in keep if graph.nodes[n].get("type") != type_]
    if len(keep) > max_nodes:
        raise RenderError(
            f"{len(keep)} nodes left after hiding {', '.join(HIDE_ORDER)}; "
            f"the limit is {max_nodes}. Choose types with --types or raise "
            "--max-nodes"
        )
    return Selection(graph.subgraph(keep).copy(), dict(sorted(hidden.items())))


def layout(graph: nx.MultiDiGraph) -> dict[str, tuple[float, float]]:
    """Deterministic positions: nodes and edges sorted, fixed seed."""
    simple = nx.Graph()
    simple.add_nodes_from(sorted(graph.nodes))
    simple.add_edges_from(sorted({tuple(sorted((u, v))) for u, v in graph.edges()}))
    if len(simple) >= _SCIPY_FROM and importlib.util.find_spec("scipy") is None:
        raise RenderError(
            f"laying out {len(simple)} nodes needs scipy (pip install scipy); "
            f"or render fewer than {_SCIPY_FROM} with --types or --max-nodes"
        )
    if len(simple) == 0:
        return {}
    k = 2.0 / math.sqrt(len(simple))  # more room than the default 1/sqrt(n)
    pos = nx.spring_layout(simple, seed=SEED, k=k, iterations=100)
    return {n: (float(x), float(y)) for n, (x, y) in pos.items()}


def draw(
    graph: nx.MultiDiGraph, title: str | None = None, note: str | None = None
) -> Figure:
    """Figure of the graph: nodes by type, edges as arrows, a legend."""
    n = graph.number_of_nodes()
    side = min(30.0, max(8.0, 4.0 + 1.1 * math.sqrt(n)))
    fig = Figure(figsize=(side * 1.25, side), facecolor=SURFACE)
    ax = fig.add_axes((0.02, 0.02, 0.74, 0.9))
    ax.set_axis_off()
    ax.set_facecolor(SURFACE)
    if title:
        fig.text(0.02, 0.965, title, fontsize=14, color=INK, va="center")
    if note:
        fig.text(0.02, 0.94, note, fontsize=9, color=INK_MUTED, va="center")
    if n == 0:
        ax.text(0.5, 0.5, "empty graph", ha="center", va="center", color=INK_MUTED)
        return fig

    pos = layout(graph)
    sizes = {
        node: _BASE_MARKER * type_style(data.get("type", "")).size
        for node, data in graph.nodes(data=True)
    }
    _draw_edges(ax, graph, pos, sizes)
    counts: Counter[str] = Counter()
    for node in sorted(graph.nodes):
        data = graph.nodes[node]
        style = type_style(data.get("type", ""))
        counts[data.get("type", "")] += 1
        x, y = pos[node]
        ax.scatter(
            [x],
            [y],
            s=sizes[node] * (3 if style.marker == "." else 1),
            marker=style.marker,
            c=style.family.color,
            edgecolors=style.family.stroke,
            linewidths=0.8,
            zorder=3,
        )
    labels = _draw_labels(ax, graph, pos)
    _legend(fig, ax, counts)
    ax.margins(*_label_margins(fig, ax, labels))
    return fig


def save(fig: Figure, path: Path, fmt: Format, dpi: int = DPI) -> Path:
    """Write the figure; the same figure gives the same bytes. `dpi`: PNG only."""
    if fmt == "svg":
        with matplotlib.rc_context({"svg.hashsalt": "kg"}):
            fig.savefig(path, format="svg", metadata={"Date": None})
    else:
        fig.savefig(path, format="png", dpi=dpi, metadata={"Software": None})
    return path


def render_static(
    graph: nx.MultiDiGraph,
    path: Path,
    fmt: Format,
    types: Collection[str] | None = None,
    max_nodes: int = MAX_NODES,
    title: str | None = None,
    dpi: int = DPI,
) -> Selection:
    """Select, draw and save; return what was drawn and what was hidden."""
    selection = select(graph, types, max_nodes)
    shown = selection.graph
    note = f"{shown.number_of_nodes()} nodes, {shown.number_of_edges()} edges"
    if selection.hidden:
        hidden = ", ".join(f"{c} {t}" for t, c in selection.hidden.items())
        note += f" · hidden: {hidden}"
    save(draw(shown, title, note), path, fmt, dpi)
    return selection


def _draw_edges(
    ax: Any,
    graph: nx.MultiDiGraph,
    pos: dict[str, tuple[float, float]],
    sizes: dict[str, float],
) -> None:
    for u, v in sorted({(u, v) for u, v in graph.edges() if u != v}):
        ax.add_patch(
            FancyArrowPatch(
                pos[u],
                pos[v],
                arrowstyle="-|>",
                mutation_scale=7,
                color=EDGE,
                linewidth=0.6,
                shrinkA=math.sqrt(sizes[u]) / 2,
                shrinkB=math.sqrt(sizes[v]) / 2 + 1,
                zorder=1,
            )
        )


def _label_margins(fig: Figure, ax: Any, labels: list[str]) -> tuple[float, float]:
    """Axes margins (x, y) so that centered labels are not cut at the edges.

    Estimated from the text length: a figure without pyplot has no renderer to
    measure text with before saving.
    """
    width, height = fig.get_size_inches() * 72 * ax.get_position().size  # points
    half_label = max((len(t) for t in labels), default=0) * _LABEL_SIZE * 0.3
    fx = min(0.4, half_label / width)
    fy = min(0.4, (_LABEL_OFFSET + 2 * _LABEL_SIZE) / height)
    return max(0.04, fx / (1 - 2 * fx)), max(0.04, fy / (1 - 2 * fy))


def _draw_labels(
    ax: Any, graph: nx.MultiDiGraph, pos: dict[str, tuple[float, float]]
) -> list[str]:
    """Label the nodes; return the texts drawn."""
    drawn: list[str] = []
    label_all = graph.number_of_nodes() <= LABEL_ALL_UP_TO
    halo = [withStroke(linewidth=2.5, foreground=SURFACE)]
    for node in sorted(graph.nodes):
        data = graph.nodes[node]
        if not label_all and data.get("type") not in LABELED_TYPES:
            continue
        x, y = pos[node]
        text = data.get("label") or node.split(":", 1)[-1]
        ax.annotate(
            text,
            (x, y),
            xytext=(0, -_LABEL_OFFSET),
            textcoords="offset points",
            ha="center",
            va="top",
            fontsize=_LABEL_SIZE,
            color=INK,
            path_effects=halo,
            zorder=4,
        )
        drawn.append(text)
    return drawn


def _legend(fig: Figure, ax: Any, counts: Counter[str]) -> None:
    def order(type_: str) -> tuple[int, str]:
        families = ("code", "tests", "context", "other")
        return families.index(type_style(type_).family.name), type_

    handles = []
    for type_ in sorted(counts, key=order):
        style = type_style(type_)
        handles.append(
            Line2D(
                [],
                [],
                linestyle="",
                marker=style.marker,
                markersize=(12 if style.marker == "." else 6.5)
                * math.sqrt(min(style.size, 2.2)),
                markerfacecolor=style.family.color,
                markeredgecolor=style.family.stroke,
                label=f"{type_} ({counts[type_]})",
            )
        )
    legend = fig.legend(
        handles=handles,
        loc="upper left",
        bbox_to_anchor=(0.78, 0.92),
        frameon=False,
        fontsize=9,
        labelcolor=INK,
        title="Entity types",
        title_fontsize=10,
        alignment="left",
    )
    legend.get_title().set_color(INK)
