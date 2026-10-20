"""Renderers of the stored graph: static PNG/SVG (RF-50) and HTML (RF-51).

The renderers are imported on first use: matplotlib takes about a third of a
second to import, and most commands never render (RNF-06).
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

from kg.render.defaults import DPI, INITIAL_NODES, MAX_NODES

if TYPE_CHECKING:
    from kg.render.html import HtmlResult, render_html
    from kg.render.static import RenderError, Selection, render_static

# Name → the module that defines it
_LAZY = {
    "HtmlResult": "html",
    "render_html": "html",
    "RenderError": "static",
    "Selection": "static",
    "render_static": "static",
}

__all__ = [
    "DPI",
    "MAX_NODES",
    "HtmlResult",
    "INITIAL_NODES",
    "render_html",
    "RenderError",
    "Selection",
    "render_static",
]


def __getattr__(name: str) -> Any:
    if name in _LAZY:
        return getattr(import_module(f"kg.render.{_LAZY[name]}"), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
