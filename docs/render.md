# Visualization: `kg render`

Draws the store's graph: a static PNG or SVG image (RF-50) or an interactive
HTML page (RF-51–55).

```bash
kg render --png                          # kg-graph.png in the current directory
kg render --svg -o docs/graph.svg        # another path (its directory must exist)
kg render --png --types Module,Package,Dependency
kg render --png --max-nodes 400          # draw more before hiding types
kg render --png --dpi 300                # bigger PNG, to zoom in (default: 150)
kg render --png --json                   # {"path", "format", "nodes", "edges", "hidden"}
kg render --html                         # kg-graph.html: open it in a browser
kg render --html --types Module,Test,Dependency
```

## Interactive HTML

`kg render --html` writes **one self-contained file** (about 500 KB): the
graph as JSON, the page code and vis-network 9.1.2, the engine pyvis uses,
all inline. It needs no server and no internet; open it from disk.

- **Zoom and pan**: scroll wheel, drag the background, `+`/`−`/`Fit` buttons.
  Nodes can be dragged.
- **Legend and filters** (RF-52, RF-53): the sidebar lists every entity type
  (color by family and shape by type, as in the image) and every relation
  type (a dash pattern each; `tests` in the tests color), with counts. The
  checkboxes and `All`/`None` show and hide them. An edge shows when its
  relation and both of its nodes are visible.
- **Details on click** (RF-54): a node shows its label, type, ID,
  description, attributes, provenance (method, extractor, confidence, source
  and lines) and its incoming and outgoing relations, which link to the
  other node and to the edge. Empty fields are left out. An edge shows its
  endpoints, attributes and provenance.
- **Search** (RF-55): by label or ID, best matches first. Choosing a result
  centers the node, opens its details and shows its type if it was hidden.
- **Read-only, with commands**: the page cannot write to the store (it is a
  file, with no server). For the selected element it shows the matching
  `kg edit`/`kg remove` command with a copy button; run it in the repo and
  render again.
- **Edge labels**: off by default; the toolbar button shows each edge's
  relation type.
- **Links to a node**: `kg-graph.html#node=module:app.core` opens with that
  node selected.
- **Light and dark**: follows the system setting. The dark colors are the
  same hues re-stepped for the dark surface, also validated all-pairs.

Above 300 nodes, whole types start unticked (`Function`, then `Test`,
`File`, `Class`, the same order as the image) so the first layout is quick;
everything is in the file and one click brings them back. `--types` leaves
the other types out of the file altogether.

The layout runs in the browser with a fixed seed. The file is deterministic:
the same graph gives the same bytes.

## What is drawn (PNG and SVG)

- **Nodes**: color by family and marker shape by type, with a legend that
  lists each type present and its count.
- **Edges**: thin gray arrows, one per connected pair (several relation types
  between the same two nodes are drawn once). Relation types are not
  distinguished in the static image; the HTML does that.
- **Labels**: the node's `label` (or its ID without the prefix), in text
  color. Up to 60 nodes every node is labeled; above that, only `Repo`,
  `Package`, `Module`, `Dependency` and `Config`.
- **Title**: the `Repo` name, plus a line with the counts and what was hidden.

| Family | Color | Types (marker) |
|--------|-------|----------------|
| Code | blue | `Repo` ★, `Package` ■, `Module` ●, `Class` ◆, `Function` ▼ |
| Tests | green | `Test` ▲ |
| Context | orange | `Dependency` ●, `Config` ■, `Service` ⬢, `Endpoint` ▼, `Document` ⬟, `Decision` ◆, `Concept` ▲, `Issue` ✖, `Person` ✚ |
| Other | gray | `File` · and every custom type ● |

Why only three hues: in a node graph every pair of colors is on screen at
once, and with the project palette only three hues stay distinguishable
across all pairs, also with color-vision deficiencies (validated all-pairs:
CVD ΔE ≥ 9.2, normal-vision ΔE ≥ 24). Shape and the legend carry the type;
color never does it alone. The encoding lives in `src/kg/render/style.py` and
the HTML will reuse it.

## Large graphs

A static image stops being readable long before NetworkX struggles. By
default at most **150 nodes** are drawn: if the graph (after `--types`) has
more, whole types are hidden in this order until it fits:
`Function`, `Test`, `File`, `Class`. The output says what was hidden:

```text
rendered 103 nodes and 159 edges to kg-graph.png
  hidden: 187 Function, 185 Test
  (more than 150 nodes; choose them with --types or raise --max-nodes)
```

If hiding those types is not enough, the command fails (exit code `2`) and
suggests `--types` or `--max-nodes`. From 500 nodes on, NetworkX's layout
needs `scipy`, which `kg` does not install: install it or draw fewer nodes.

## Zooming

The PNG has a fixed size: `--dpi` makes it larger (300 doubles the default
150 in each dimension) so it can be zoomed into without pixelation. The SVG
is vector and stays sharp at any zoom in a browser. For interactive zoom and pan,
use the HTML.

## Determinism (RNF-08)

The same graph gives the same file, byte for byte:

- spring layout (`nx.spring_layout`) with `seed=42`, nodes and edges sorted
  by ID, so insertion order does not matter;
- PNG without the `Software` tag, SVG without `<dc:date>` and with fixed
  element IDs (`svg.hashsalt`).

The layout may change with a different NetworkX or NumPy version.

## From Python

```python
from pathlib import Path
from kg import store
from kg.render import render_static

graph = store.load_graph(Path(".kg"))
selection = render_static(graph, Path("graph.svg"), "svg", types={"Module"})
selection.hidden  # {"Function": 187, ...}
```

`kg.render.static.draw(graph)` returns the `matplotlib.figure.Figure` without
saving it. Nothing here uses `pyplot` or calls `plt.show()`.

## Errors

| Situation | Exit code |
|-----------|-----------|
| No store (suggests `kg init`) or the output directory does not exist | `2` |
| The store does not conform to the schema | `1` |
| Too many nodes after hiding, or ≥ 500 nodes without scipy | `2` |
| `--max-nodes` not a positive integer, empty `--types` | `2` |
