"""Visual encoding of entity types, shared by every renderer (RF-52).

Color identifies a **family** and the marker shape the type within it. A node
graph shows every pair of colors at once, and only three hues of the palette
stay distinguishable that way, also with color-vision deficiencies (validated
all-pairs: CVD ΔE ≥ 9.2, normal-vision ΔE ≥ 24). Anything else is neutral gray.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass

# Text and neutral tones: labels never wear a family color.
INK = "#0b0b0b"
INK_MUTED = "#52514e"
EDGE = "#b9b8b3"
SURFACE = "#ffffff"


@dataclass(frozen=True)
class Family:
    name: str
    color: str
    stroke: str  # darker ring, so light fills keep 3:1 against the surface


CODE = Family("code", "#2a78d6", "#184f95")
TESTS = Family("tests", "#1baf7a", "#0f6e4c")
CONTEXT = Family("context", "#eb6834", "#a8441c")
OTHER = Family("other", "#9a9993", "#5f5e5a")
FAMILIES = (CODE, TESTS, CONTEXT, OTHER)


@dataclass(frozen=True)
class TypeStyle:
    family: Family
    marker: str  # matplotlib marker
    size: float  # relative to a Function node


# Fixed per type, so a type keeps its look whatever else is in the graph.
TYPE_STYLES: dict[str, TypeStyle] = {
    "Repo": TypeStyle(CODE, "*", 4.0),
    "Package": TypeStyle(CODE, "s", 2.2),
    "Module": TypeStyle(CODE, "o", 1.8),
    "Class": TypeStyle(CODE, "D", 1.3),
    "Function": TypeStyle(CODE, "v", 1.0),
    "Test": TypeStyle(TESTS, "^", 1.2),
    "Dependency": TypeStyle(CONTEXT, "o", 1.5),
    "Config": TypeStyle(CONTEXT, "s", 1.5),
    "Service": TypeStyle(CONTEXT, "h", 1.8),
    "Endpoint": TypeStyle(CONTEXT, "v", 1.3),
    "Document": TypeStyle(CONTEXT, "p", 1.5),
    "Decision": TypeStyle(CONTEXT, "D", 1.5),
    "Concept": TypeStyle(CONTEXT, "^", 1.5),
    "Issue": TypeStyle(CONTEXT, "X", 1.5),
    "Person": TypeStyle(CONTEXT, "P", 1.5),
    "File": TypeStyle(OTHER, ".", 1.0),
}
# Custom types are gray; the shape comes from a checksum of the name, so it
# does not depend on which other types are drawn. Two custom types may still
# share a shape (1 in 10); the legend tells them apart by name.
CUSTOM_MARKERS = ("o", "s", "D", "^", "v", "p", "h", "P", "X", "d")
CUSTOM_SIZE = 1.3


def type_style(type_: str) -> TypeStyle:
    """Style of an entity type: fixed for the catalog, derived for custom ones."""
    style = TYPE_STYLES.get(type_)
    if style is not None:
        return style
    marker = CUSTOM_MARKERS[zlib.crc32(type_.encode("utf-8")) % len(CUSTOM_MARKERS)]
    return TypeStyle(OTHER, marker, CUSTOM_SIZE)
