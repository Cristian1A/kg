import json
import re
import shutil
import subprocess

import pytest

from kg import store
from kg.cli import EXIT_OK, EXIT_USAGE, main
from kg.render.html import (
    INITIAL_NODES,
    build_html,
    graph_data,
    initially_hidden,
    render_html,
)

PROV = {"method": "parser", "extractor": "python-ast@0.1", "confidence": 1.0}
VIS_SHAPES = {"dot", "square", "diamond", "triangle", "triangleDown", "star", "hexagon"}


def graph_of(nodes, edges=()):
    document = {
        "version": "1",
        "nodes": [
            {"id": i, "type": t, "provenance": dict(PROV), **extra}
            for i, t, *rest in nodes
            for extra in [rest[0] if rest else {}]
        ],
        "edges": [
            {"source": s, "target": d, "type": t, "provenance": dict(PROV)}
            for s, d, t in edges
        ],
    }
    return store.document_to_graph(document)


@pytest.fixture
def graph():
    return graph_of(
        [
            ("repo:demo", "Repo", {"label": "demo"}),
            ("module:size", "Module", {"label": "size"}),
            (
                "function:size.main",
                "Function",
                {
                    "label": "main",
                    "description": "Imprime el tamaño",
                    "attrs": {"public": True},
                },
            ),
            ("test:test_size.test_main", "Test"),
            ("dependency:os", "Dependency"),
            ("document:README.md", "Document"),
            ("entrypoint:size", "EntryPoint"),
        ],
        [
            ("repo:demo", "module:size", "contains"),
            ("module:size", "function:size.main", "defines"),
            ("module:size", "dependency:os", "imports"),
            ("test:test_size.test_main", "function:size.main", "tests"),
            ("document:README.md", "function:size.main", "documents"),
            ("entrypoint:size", "function:size.main", "invokes"),
        ],
    )


def embedded_data(page):
    match = re.search(
        r'<script type="application/json" id="kg-data">(.*?)</script>', page, re.S
    )
    return json.loads(match.group(1))


# --- Page ----------------------------------------------------------------------


def test_page_embeds_the_graph(graph):
    page, result = build_html(graph, title="demo")
    data = embedded_data(page)
    assert [n["id"] for n in data["nodes"]] == sorted(graph.nodes)
    main_node = next(n for n in data["nodes"] if n["id"] == "function:size.main")
    assert main_node["description"] == "Imprime el tamaño"
    assert main_node["attrs"] == {"public": True}
    assert main_node["provenance"] == PROV
    assert len(data["edges"]) == 6
    assert (result.nodes, result.edges, result.hidden) == (7, 6, [])
    assert "<title>demo · kg</title>" in page


def test_page_is_self_contained(graph):
    page, _ = build_html(graph)
    # No external scripts, styles or images: it must work offline (RF-51)
    assert not re.search(r'<(script|link|img)[^>]+(src|href)=["\']?(https?:)?//', page)
    assert "vis-network" in page
    assert "sourceMappingURL" not in page
    assert page.count("</script>") == 3  # data, vis-network, page code


def test_page_is_deterministic(graph):
    assert build_html(graph, "demo") == build_html(graph, "demo")


def test_untrusted_text_cannot_break_out(tmp_path):
    evil = "</script><script>alert(1)</script> & {{VIS_JS}}"
    graph = graph_of([("concept:x", "Concept", {"label": evil, "description": evil})])
    page, _ = build_html(graph, title=evil)
    assert page.count("</script>") == 3  # data, vis-network, page code
    assert "alert(1)</script>" not in page
    assert "<title>&lt;/script&gt;" in page
    assert embedded_data(page)["nodes"][0]["label"] == evil
    # The template token in the data was not expanded
    assert len(page) < 2 * len(build_html(graph_of([("concept:x", "Concept")]))[0])


def test_legend_order_styles_and_relations(graph):
    data = graph_data(graph)
    # Grouped by family: code, tests, context, other
    assert data["type_order"] == [
        "Function",
        "Module",
        "Repo",
        "Test",
        "Dependency",
        "Document",
        "EntryPoint",
    ]
    for style in data["types"].values():
        assert style["shape"] in VIS_SHAPES
        assert style["px"] > 0
    assert data["types"]["Document"]["dashed"] is True
    assert data["types"]["Function"]["shape"] == "triangleDown"
    assert data["types"]["EntryPoint"]["family"] == "other"
    assert data["relations"]["tests"]["family"] == "tests"
    assert data["relations"]["imports"]["dashes"] == [6, 4]
    assert data["relations"]["invokes"]["dashes"]  # custom relation
    assert data["relation_order"] == sorted(data["relations"])
    assert set(data["families"]) == {"code", "tests", "context", "other"}
    assert set(data["theme"]) == {"light", "dark"}


@pytest.mark.parametrize(
    ("counts", "hidden"),
    [
        ({"Module": 10}, []),
        ({"Module": 10, "Function": INITIAL_NODES}, ["Function"]),
        ({"Module": 10, "Function": 100, "Test": 300}, ["Function", "Test"]),
        ({"Concept": INITIAL_NODES + 50}, []),  # nothing to hide: never fails
    ],
)
def test_initially_hidden(counts, hidden):
    nodes = [{"type": t} for t, n in counts.items() for _ in range(n)]
    assert initially_hidden(nodes) == hidden


def test_empty_graph(tmp_path):
    graph = graph_of([])
    result = render_html(graph, tmp_path / "g.html")
    assert (result.nodes, result.edges) == (0, 0)
    assert embedded_data((tmp_path / "g.html").read_text("utf-8"))["nodes"] == []


@pytest.mark.skipif(
    not shutil.which("google-chrome") and not shutil.which("chromium"),
    reason="no headless Chrome",
)
def test_page_runs_in_a_browser(graph, tmp_path):
    path = tmp_path / "g.html"
    render_html(graph, path, title="demo")
    chrome = shutil.which("google-chrome") or shutil.which("chromium")
    proc = subprocess.run(
        [
            chrome,
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            f"--user-data-dir={tmp_path / 'profile'}",
            "--virtual-time-budget=8000",
            "--dump-dom",
            f"{path.as_uri()}#node=function:size.main",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    dom = proc.stdout
    assert '<span class="stats" id="stats">7 nodes · 6 edges</span>' in dom
    assert dom.count('class="filter"') == 7 + 6  # entity types + relations
    # The deep link opened the details panel of the node
    assert 'id="panel" aria-live="polite" class="open"' in dom
    assert "Imprime el tamaño" in dom
    assert "kg remove function:size.main" in dom


# --- CLI -----------------------------------------------------------------------


@pytest.fixture
def kg_dir(tmp_path, graph):
    path = tmp_path / ".kg"
    store.init_store(path)
    store.save_graph(graph, path)
    return path


def test_cli_render_html(kg_dir, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["render", "--html", "--kg-dir", str(kg_dir)]) == EXIT_OK
    assert capsys.readouterr().out.strip() == (
        "rendered 7 nodes and 6 edges to kg-graph.html"
    )
    data = embedded_data((tmp_path / "kg-graph.html").read_text("utf-8"))
    assert data["title"] == "demo"


def test_cli_render_html_json_and_types(kg_dir, tmp_path, capsys):
    output = tmp_path / "g.html"
    argv = ["render", "--html", "-o", str(output), "--types", "Module,Function"]
    assert main([*argv, "--kg-dir", str(kg_dir), "--json"]) == EXIT_OK
    result = json.loads(capsys.readouterr().out)["result"]
    assert result == {
        "path": str(output),
        "format": "html",
        "nodes": 2,
        "edges": 1,
        "hidden": [],
    }


def test_cli_render_html_reports_initially_hidden_types(tmp_path, capsys):
    nodes = [("module:m", "Module")] + [
        (f"function:m.f{i}", "Function") for i in range(INITIAL_NODES)
    ]
    kg_dir = tmp_path / ".kg"
    store.init_store(kg_dir)
    store.save_graph(graph_of(nodes), kg_dir)
    argv = ["render", "--html", "-o", str(tmp_path / "g.html"), "--kg-dir", str(kg_dir)]
    assert main(argv) == EXIT_OK
    out = capsys.readouterr().out
    assert "Function start hidden" in out
    assert "tick them under Entity types" in out


def test_cli_render_html_errors(kg_dir, tmp_path, capsys):
    argv = ["render", "--html", "-o", str(tmp_path / "nope" / "g.html")]
    assert main([*argv, "--kg-dir", str(kg_dir)]) == EXIT_USAGE
    argv = ["render", "--html", "--kg-dir", str(tmp_path / "missing")]
    assert main(argv) == EXIT_USAGE
    assert "kg init" in capsys.readouterr().err
