import json
import subprocess
import sys

import networkx as nx
import pytest

from kg import store
from kg.cli import EXIT_OK, EXIT_USAGE, EXIT_VALIDATION, main
from kg.render import RenderError, render_static
from kg.render.static import draw, layout, select
from kg.render.style import CODE, CONTEXT, CUSTOM_MARKERS, OTHER, TESTS, type_style

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
PROV = {"method": "parser", "extractor": "python-ast@0.1", "confidence": 1.0}


def graph_of(nodes, edges=()):
    """MultiDiGraph from (id, type) pairs and (source, target, type) triples."""
    document = {
        "version": "1",
        "nodes": [{"id": i, "type": t, "provenance": dict(PROV)} for i, t in nodes],
        "edges": [
            {"source": s, "target": d, "type": t, "provenance": dict(PROV)}
            for s, d, t in edges
        ],
    }
    return store.document_to_graph(document)


@pytest.fixture
def small():
    return graph_of(
        [
            ("repo:demo", "Repo"),
            ("package:app", "Package"),
            ("module:app.core", "Module"),
            ("class:app.core.Engine", "Class"),
            ("function:app.core.run", "Function"),
            ("test:tests.test_core", "Test"),
            ("dependency:networkx", "Dependency"),
            ("file:src/app/core.py", "File"),
            ("requirement:rf-1", "Requirement"),
        ],
        [
            ("repo:demo", "package:app", "contains"),
            ("package:app", "module:app.core", "contains"),
            ("file:src/app/core.py", "module:app.core", "defines"),
            ("file:src/app/core.py", "class:app.core.Engine", "defines"),
            ("file:src/app/core.py", "function:app.core.run", "defines"),
            ("module:app.core", "dependency:networkx", "imports"),
            ("test:tests.test_core", "module:app.core", "imports"),
            ("test:tests.test_core", "module:app.core", "tests"),
            ("repo:demo", "dependency:networkx", "depends_on"),
        ],
    )


def big(n_functions, n_tests=0, n_files=0):
    nodes = [("repo:big", "Repo"), ("module:m", "Module")]
    nodes += [(f"function:m.f{i}", "Function") for i in range(n_functions)]
    nodes += [(f"test:t.test_{i}", "Test") for i in range(n_tests)]
    nodes += [(f"file:f{i}.py", "File") for i in range(n_files)]
    return graph_of(nodes, [("repo:big", "module:m", "contains")])


# --- Style ---------------------------------------------------------------------


def test_custom_types_get_a_stable_shape_of_their_own():
    assert type_style("EntryPoint") == type_style("EntryPoint")
    assert type_style("EntryPoint").marker != type_style("Tutorial").marker
    assert type_style("Tutorial").marker in CUSTOM_MARKERS


def test_families_and_fallback_style():
    assert type_style("Module").family is CODE
    assert type_style("Test").family is TESTS
    assert type_style("Decision").family is CONTEXT
    assert type_style("File").family is OTHER
    assert type_style("Requirement").family is OTHER
    assert len({f.color for f in (CODE, TESTS, CONTEXT, OTHER)}) == 4


# --- Selection -----------------------------------------------------------------


def test_select_keeps_everything_under_the_limit(small):
    selection = select(small)
    assert nx.utils.graphs_equal(selection.graph, small)
    assert selection.hidden == {}


def test_select_hides_whole_types_in_order():
    graph = big(n_functions=100, n_tests=40, n_files=10)  # 152 nodes
    selection = select(graph, max_nodes=60)
    assert selection.hidden == {"Function": 100}
    assert selection.graph.number_of_nodes() == 52
    selection = select(graph, max_nodes=20)
    assert selection.hidden == {"Function": 100, "Test": 40}


def test_select_by_types(small):
    selection = select(small, types={"Module", "Dependency"})
    assert sorted(selection.graph.nodes) == ["dependency:networkx", "module:app.core"]
    assert list(selection.graph.edges(keys=True)) == [
        ("module:app.core", "dependency:networkx", "imports")
    ]
    assert selection.hidden["Function"] == 1
    assert "Module" not in selection.hidden


def test_select_fails_if_hiding_is_not_enough():
    graph = graph_of([(f"concept:c{i}", "Concept") for i in range(10)])
    with pytest.raises(RenderError, match="--types or raise"):
        select(graph, max_nodes=5)


# --- Layout and figure ---------------------------------------------------------


def test_layout_is_deterministic_and_independent_of_insertion_order(small):
    reversed_graph = nx.MultiDiGraph()
    for node in reversed(list(small.nodes)):
        reversed_graph.add_node(node, **small.nodes[node])
    for u, v, k in reversed(list(small.edges(keys=True))):
        reversed_graph.add_edge(u, v, key=k)
    assert layout(small) == layout(small) == layout(reversed_graph)


def test_layout_needs_scipy_for_large_graphs(monkeypatch):
    monkeypatch.setattr("importlib.util.find_spec", lambda name: None)
    with pytest.raises(RenderError, match="scipy"):
        layout(big(n_functions=600))


def test_figure_has_one_marker_per_node_and_a_legend(small):
    fig = draw(small, title="demo")
    ax = fig.axes[0]
    assert len(ax.collections) == small.number_of_nodes()
    legend = fig.legends[0]
    labels = [t.get_text() for t in legend.get_texts()]
    # Grouped by family: code, tests, context, other
    assert labels == [
        "Class (1)",
        "Function (1)",
        "Module (1)",
        "Package (1)",
        "Repo (1)",
        "Test (1)",
        "Dependency (1)",
        "File (1)",
        "Requirement (1)",
    ]
    # Color follows the type's family
    colors = {
        handle.get_label(): handle.get_markerfacecolor()
        for handle in legend.legend_handles
    }
    assert colors["Module (1)"] == CODE.color
    assert colors["Test (1)"] == TESTS.color
    assert colors["Requirement (1)"] == OTHER.color


def test_long_labels_widen_the_margins():
    short = draw(graph_of([("concept:a", "Concept"), ("concept:b", "Concept")]))
    long_ = graph_of([("concept:a", "Concept"), ("concept:b", "Concept")])
    long_.nodes["concept:a"]["label"] = "a very long label that would be cut " * 2
    assert draw(long_).axes[0].margins()[0] > short.axes[0].margins()[0]


def test_empty_graph_figure():
    fig = draw(nx.MultiDiGraph())
    texts = [t.get_text() for t in fig.axes[0].texts]
    assert texts == ["empty graph"]


# --- Files ---------------------------------------------------------------------


@pytest.mark.parametrize("fmt", ["png", "svg"])
def test_render_writes_a_deterministic_file(small, tmp_path, fmt):
    first, second = tmp_path / f"a.{fmt}", tmp_path / f"b.{fmt}"
    render_static(small, first, fmt, title="demo")
    render_static(small, second, fmt, title="demo")
    data = first.read_bytes()
    assert data == second.read_bytes()
    if fmt == "png":
        assert data.startswith(PNG_MAGIC)
    else:
        assert b"<svg" in data[:500]
        assert b"<dc:date>" not in data


def test_render_does_not_use_pyplot(tmp_path):
    code = (
        "import sys\n"
        "from pathlib import Path\n"
        "import networkx as nx\n"
        "from kg.render import render_static\n"
        "g = nx.MultiDiGraph()\n"
        "g.add_node('module:a', type='Module')\n"
        f"render_static(g, Path({str(tmp_path / 'x.png')!r}), 'png')\n"
        "print('matplotlib.pyplot' in sys.modules)\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == "False"


# --- CLI -----------------------------------------------------------------------


@pytest.fixture
def kg_dir(tmp_path, small):
    path = tmp_path / ".kg"
    store.init_store(path)
    store.save_graph(small, path)
    return path


def test_cli_render_png_default_output(kg_dir, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["render", "--png", "--kg-dir", str(kg_dir)]) == EXIT_OK
    assert (tmp_path / "kg-graph.png").read_bytes().startswith(PNG_MAGIC)
    out = capsys.readouterr().out
    assert out.strip() == "rendered 9 nodes and 9 edges to kg-graph.png"


def test_cli_render_svg_json(kg_dir, tmp_path, capsys):
    output = tmp_path / "out" / "g.svg"
    output.parent.mkdir()
    argv = ["render", "--svg", "-o", str(output), "--kg-dir", str(kg_dir), "--json"]
    assert main(argv) == EXIT_OK
    result = json.loads(capsys.readouterr().out)["result"]
    assert result == {
        "path": str(output),
        "format": "svg",
        "nodes": 9,
        "edges": 9,
        "hidden": {},
    }
    assert output.is_file()


def test_cli_render_reports_hidden_types(tmp_path, capsys):
    kg_dir = tmp_path / ".kg"
    store.init_store(kg_dir)
    store.save_graph(big(n_functions=30), kg_dir)
    output = tmp_path / "g.png"
    argv = ["render", "--png", "-o", str(output), "--kg-dir", str(kg_dir)]
    assert main([*argv, "--max-nodes", "10"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "  hidden: 30 Function" in out
    assert "raise --max-nodes" in out


def test_cli_render_types(kg_dir, tmp_path, capsys):
    output = tmp_path / "g.png"
    argv = ["render", "--png", "-o", str(output), "--kg-dir", str(kg_dir)]
    assert main([*argv, "--types", "Module, Package", "--json"]) == EXIT_OK
    result = json.loads(capsys.readouterr().out)["result"]
    assert result["nodes"] == 2
    assert result["edges"] == 1


def test_cli_render_without_store(tmp_path, capsys):
    argv = ["render", "--png", "--kg-dir", str(tmp_path / "missing")]
    assert main(argv) == EXIT_USAGE
    assert "kg init" in capsys.readouterr().err


def test_cli_render_corrupt_store(tmp_path, capsys):
    kg_dir = tmp_path / ".kg"
    kg_dir.mkdir()
    store.graph_path(kg_dir).write_text("{}", encoding="utf-8")
    assert main(["render", "--png", "--kg-dir", str(kg_dir)]) == EXIT_VALIDATION


def test_cli_render_missing_output_dir(kg_dir, tmp_path, capsys):
    output = tmp_path / "nope" / "g.png"
    argv = ["render", "--png", "-o", str(output), "--kg-dir", str(kg_dir)]
    assert main(argv) == EXIT_USAGE
    assert "does not exist" in capsys.readouterr().err


@pytest.mark.parametrize(
    "extra", [["--max-nodes", "0"], ["--max-nodes", "x"], ["--types", " , "]]
)
def test_cli_render_invalid_options(kg_dir, extra, capsys):
    assert main(["render", "--png", "--kg-dir", str(kg_dir), *extra]) == EXIT_USAGE


def test_cli_render_too_many_nodes(tmp_path, capsys):
    kg_dir = tmp_path / ".kg"
    store.init_store(kg_dir)
    store.save_graph(graph_of([(f"concept:c{i}", "Concept") for i in range(5)]), kg_dir)
    argv = ["render", "--png", "--max-nodes", "2", "--kg-dir", str(kg_dir)]
    assert main([*argv, "-o", str(tmp_path / "g.png")]) == EXIT_USAGE
    assert "--types" in capsys.readouterr().err


def test_cli_render_dpi(kg_dir, tmp_path):
    sizes = {}
    for dpi in ("75", "300"):
        output = tmp_path / f"g{dpi}.png"
        argv = ["render", "--png", "--dpi", dpi, "-o", str(output)]
        assert main([*argv, "--kg-dir", str(kg_dir)]) == EXIT_OK
        data = output.read_bytes()
        sizes[dpi] = int.from_bytes(data[16:20], "big")  # IHDR width
    assert sizes["300"] == 4 * sizes["75"]


def test_cli_render_invalid_dpi(kg_dir):
    argv = ["render", "--png", "--dpi", "0", "--kg-dir", str(kg_dir)]
    assert main(argv) == EXIT_USAGE
