import json

import pytest

from kg import store
from kg.cli import EXIT_OK, EXIT_USAGE, EXIT_VALIDATION, main
from kg.edit import EditError, edit_node, parse_value, remove

PROV = {"method": "parser", "extractor": "python-ast@0.1", "confidence": 1.0}


def node(id_, type_, **extra):
    return {"id": id_, "type": type_, "provenance": dict(PROV), **extra}


def edge(source, target, type_):
    return {"source": source, "target": target, "type": type_, "provenance": dict(PROV)}


DOCUMENT = {
    "version": "1",
    "nodes": [
        node("repo:demo", "Repo"),
        node("module:size", "Module", label="size", attrs={"public": True}),
        node("function:size.main", "Function", label="main"),
        node("dependency:os", "Dependency", attrs={"import_name": "os"}),
        node("concept:size-in-mb", "Concept", label="Size in MB"),
    ],
    "edges": [
        edge("repo:demo", "module:size", "contains"),
        edge("module:size", "function:size.main", "defines"),
        edge("module:size", "dependency:os", "imports"),
        edge("function:size.main", "concept:size-in-mb", "implements"),
        edge("function:size.main", "concept:size-in-mb", "documents"),
    ],
}


@pytest.fixture
def graph():
    return store.document_to_graph(json.loads(json.dumps(DOCUMENT)))


@pytest.fixture
def kg_dir(tmp_path, graph):
    path = tmp_path / ".kg"
    store.init_store(path)
    store.save_graph(graph, path)
    return path


def stored(kg_dir):
    return store.graph_path(kg_dir).read_text(encoding="utf-8")


# --- remove --------------------------------------------------------------------


def test_remove_node_takes_its_edges(graph):
    result, report = remove(graph, ["dependency:os"])
    assert "dependency:os" not in result
    assert report.nodes == ["dependency:os"]
    assert report.edges == ["module:size -[imports]-> dependency:os"]
    assert result.number_of_edges() == graph.number_of_edges() - 1
    assert "dependency:os" in graph  # the input graph is untouched


def test_remove_one_edge_of_several_between_two_nodes(graph):
    result, report = remove(
        graph, edges=[("function:size.main", "documents", "concept:size-in-mb")]
    )
    assert report.nodes == []
    assert report.edges == ["function:size.main -[documents]-> concept:size-in-mb"]
    assert result.has_edge("function:size.main", "concept:size-in-mb", "implements")
    assert not result.has_edge("function:size.main", "concept:size-in-mb", "documents")


def test_remove_node_and_one_of_its_edges_counts_the_edge_once(graph):
    _, report = remove(
        graph,
        ["dependency:os", "dependency:os"],
        [("module:size", "imports", "dependency:os")],
    )
    assert report.nodes == ["dependency:os"]
    assert report.edges == ["module:size -[imports]-> dependency:os"]


def test_remove_unknown_node_changes_nothing(graph):
    with pytest.raises(EditError) as exc:
        remove(graph, ["dependency:os", "dependency:sis"])
    assert exc.value.message == "no node dependency:sis in the store"
    assert exc.value.suggestion is None or "dependency:" in exc.value.suggestion
    with pytest.raises(EditError) as exc:
        remove(graph, ["module:siz"])
    assert exc.value.suggestion == 'Did you mean ID "module:size"?'


@pytest.mark.parametrize(
    ("edge_", "suggestion"),
    [
        (
            ("module:size", "contains", "dependency:os"),
            "Edges from module:size to dependency:os: imports.",
        ),
        (
            ("module:size", "imports", "function:size.main"),
            "Edges from module:size to function:size.main: defines.",
        ),
        (
            ("repo:demo", "imports", "dependency:os"),
            "There is no edge from repo:demo to dependency:os.",
        ),
        (("module:siz", "imports", "dependency:os"), 'Did you mean ID "module:size"?'),
    ],
)
def test_remove_unknown_edge(graph, edge_, suggestion):
    with pytest.raises(EditError) as exc:
        remove(graph, edges=[edge_])
    assert exc.value.suggestion == suggestion


# --- edit ----------------------------------------------------------------------


def test_edit_texts_type_and_attrs(graph):
    result, report = edit_node(
        graph,
        "concept:size-in-mb",
        type_="Requirement",
        texts={"label": "Tamaño en MB", "description": "Redondeo hacia abajo"},
        set_attrs={"unit": "MB"},
    )
    data = result.nodes["concept:size-in-mb"]
    assert data["type"] == "Requirement"
    assert data["label"] == "Tamaño en MB"
    assert data["description"] == "Redondeo hacia abajo"
    assert data["attrs"] == {"unit": "MB"}
    assert data["provenance"] == PROV  # provenance is kept
    assert [c.field for c in report.changes] == [
        "type",
        "label",
        "description",
        "attrs.unit",
    ]
    assert graph.nodes["concept:size-in-mb"]["label"] == "Size in MB"


def test_edit_removes_texts_and_attrs(graph):
    result, report = edit_node(
        graph, "module:size", texts={"label": ""}, unset_attrs=["public"]
    )
    data = result.nodes["module:size"]
    assert "label" not in data
    assert "attrs" not in data
    assert [c.to_text() for c in report.changes] == [
        'label: "size" → (none)',
        "attrs.public: true → (none)",
    ]


def test_edit_without_changes(graph):
    _, report = edit_node(graph, "module:size", texts={"label": "size"})
    assert not report.changed
    assert report.to_text() == "  nothing to change"


def test_edit_renames_and_rewrites_edges(graph):
    result, report = edit_node(graph, "module:size", new_id="module:app.size")
    assert "module:size" not in result
    assert result.has_edge("repo:demo", "module:app.size", "contains")
    assert result.has_edge("module:app.size", "dependency:os", "imports")
    assert report.id == "module:app.size"
    assert report.edges_rewritten == 3
    assert report.changes[0].to_text() == 'id: "module:size" → "module:app.size"'


def test_edit_errors(graph):
    with pytest.raises(EditError, match="already exists"):
        edit_node(graph, "module:size", new_id="dependency:os")
    with pytest.raises(EditError) as exc:
        edit_node(graph, "module:size", unset_attrs=["publik"])
    assert exc.value.suggestion == 'Did you mean attrs "public"?'
    with pytest.raises(EditError, match="no node"):
        edit_node(graph, "module:nope", texts={"label": "x"})


@pytest.mark.parametrize(
    ("text", "value"),
    [("3", 3), ("true", True), ('["a", 1]', ["a", 1]), ("MB", "MB"), ("", "")],
)
def test_parse_value(text, value):
    assert parse_value(text) == value


# --- CLI -----------------------------------------------------------------------


def test_cli_remove(kg_dir, capsys):
    argv = ["remove", "dependency:os", "--kg-dir", str(kg_dir)]
    assert main(argv) == EXIT_OK
    out = capsys.readouterr().out
    assert "updated:" in out
    assert "    module:size -[imports]-> dependency:os" in out
    assert "dependency:os" not in stored(kg_dir)


def test_cli_remove_edge_json(kg_dir, capsys):
    argv = ["remove", "--edge", "module:size", "imports", "dependency:os", "--json"]
    assert main([*argv, "--kg-dir", str(kg_dir)]) == EXIT_OK
    result = json.loads(capsys.readouterr().out)["result"]
    assert result["saved"] is True
    assert result["nodes"] == []
    assert result["edges"] == ["module:size -[imports]-> dependency:os"]


def test_cli_remove_dry_run_does_not_write(kg_dir, capsys):
    before = stored(kg_dir)
    argv = ["remove", "dependency:os", "--dry-run", "--json", "--kg-dir", str(kg_dir)]
    assert main(argv) == EXIT_OK
    result = json.loads(capsys.readouterr().out)["result"]
    assert result["dry_run"] is True
    assert result["saved"] is False
    assert result["nodes"] == ["dependency:os"]
    assert stored(kg_dir) == before


def test_cli_remove_unknown_id(kg_dir, capsys):
    before = stored(kg_dir)
    argv = ["remove", "module:siz", "--json", "--kg-dir", str(kg_dir)]
    assert main(argv) == EXIT_USAGE
    error = json.loads(capsys.readouterr().out)["error"]
    assert error["details"]["suggestion"] == 'Did you mean ID "module:size"?'
    assert stored(kg_dir) == before


def test_cli_remove_needs_something(kg_dir, capsys):
    assert main(["remove", "--kg-dir", str(kg_dir)]) == EXIT_USAGE
    assert "--edge" in capsys.readouterr().err


def test_cli_edit(kg_dir, capsys):
    argv = [
        "edit",
        "concept:size-in-mb",
        "--label",
        "Tamaño en MB",
        "--set",
        "unit=MB",
        "--set",
        "precision=0",
        "--kg-dir",
        str(kg_dir),
    ]
    assert main(argv) == EXIT_OK
    assert "  attrs.precision: (none) → 0" in capsys.readouterr().out
    data = store.load_graph(kg_dir).nodes["concept:size-in-mb"]
    assert data["label"] == "Tamaño en MB"
    assert data["attrs"] == {"unit": "MB", "precision": 0}
    # Readable UTF-8 in the store
    assert "Tamaño en MB" in stored(kg_dir)


def test_cli_edit_no_changes_does_not_write(kg_dir, capsys):
    before = stored(kg_dir)
    argv = ["edit", "module:size", "--label", "size", "--json", "--kg-dir", str(kg_dir)]
    assert main(argv) == EXIT_OK
    result = json.loads(capsys.readouterr().out)["result"]
    assert result["changed"] is False
    assert result["saved"] is False
    assert stored(kg_dir) == before


def test_cli_edit_rename(kg_dir, capsys):
    argv = ["edit", "module:size", "--id", "module:app.size", "--kg-dir", str(kg_dir)]
    assert main(argv) == EXIT_OK
    assert "3 edges now point to module:app.size" in capsys.readouterr().out
    graph = store.load_graph(kg_dir)
    assert graph.has_edge("module:app.size", "function:size.main", "defines")


def test_cli_edit_invalid_id_is_not_saved(kg_dir, capsys):
    before = stored(kg_dir)
    argv = ["edit", "module:size", "--id", "Not An ID", "--kg-dir", str(kg_dir)]
    assert main(argv) == EXIT_VALIDATION
    assert stored(kg_dir) == before


@pytest.mark.parametrize("bad", ["noequals", "=value"])
def test_cli_edit_bad_set(kg_dir, bad):
    argv = ["edit", "module:size", "--set", bad, "--kg-dir", str(kg_dir)]
    assert main(argv) == EXIT_USAGE
