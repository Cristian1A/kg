"""Rendering defaults the CLI needs without importing the renderers (RNF-06)."""

# Above this many nodes, the static image hides whole types (see `HIDE_ORDER`).
MAX_NODES = 150
# PNG resolution; the SVG is vector and has none.
DPI = 150
# Above this many nodes, whole types start hidden (in `HIDE_ORDER`) so the
# first HTML layout is quick and readable; the filters bring them back.
INITIAL_NODES = 300
