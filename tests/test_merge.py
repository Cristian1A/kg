import io
import json

import networkx as nx
import pytest

from kg import store
from kg.cli import EXIT_OK, EXIT_USAGE, EXIT_VALIDATION, main
from kg.merge import Conflict, add_to_store, edge_label, merge_document

PARSER = {"method": "parser", "extractor": "python-ast@0.1", "confidence": 1.0}
LLM = {"method": "llm", "extractor": "claude-code", "confidence": 0.8}


def node(id_, type_="Module", provenance=PARSER, **extra):
    return {"id": id_, "type": type_, "provenance": dict(provenance), **extra}


def edge(source, target, type_="imports", provenance=PARSER, **extra):
    return {
        "source": source,
        "target": target,
        "type": type_,
        "provenance": dict(provenance),
        **extra,
    }


def doc(nodes=(), edges=()):
    return {"version": "1", "nodes": list(nodes), "edges": list(edges)}


BASE = doc(
    [
        node("module:a", label="a", attrs={"public": True, "loc": 10}),
        node("module:b"),
    ],
    [edge("module:a", "module:b")],
)


@pytest.fixture
def kg_dir(tmp_path):
    path = tmp_path / ".kg"
    store.init_store(path)
    return path


def add(kg_dir, document):
    return add_to_store(kg_dir, json.dumps(document))


def stored(kg_dir):
    return json.loads(store.graph_path(kg_dir).read_text(encoding="utf-8"))


# --- merge_document -----------------------------------------------------------


def test_merge_into_empty_graph_adds_everything():
    graph, report = merge_document(nx.MultiDiGraph(), BASE)
    assert sorted(graph.nodes) == ["module:a", "module:b"]
    assert graph.edges["module:a", "module:b", "imports"]["type"] == "imports"
    assert report.nodes.added == ["module:a", "module:b"]
    assert report.edges.added == ["module:a -[imports]-> module:b"]
    assert report.changed
    assert report.conflicts == []


def test_merge_does_not_modify_input_graph():
    graph, _ = merge_document(nx.MultiDiGraph(), BASE)
    snapshot = store.graph_to_document(graph)
    merge_document(graph, doc([node("module:a", attrs={"loc": 99})]))
    assert store.graph_to_document(graph) == snapshot


def test_same_id_combines_attributes_without_duplicating():
    graph, _ = merge_document(nx.MultiDiGraph(), BASE)
    graph, report = merge_document(
        graph,
        doc([node("module:a", description="Módulo A", attrs={"tested": False})]),
    )
    assert graph.number_of_nodes() == 2
    data = graph.nodes["module:a"]
    assert data["label"] == "a"  # el documento no lo trae: se conserva
    assert data["description"] == "Módulo A"
    assert data["attrs"] == {"public": True, "loc": 10, "tested": False}
    assert report.nodes.merged == ["module:a"]
    assert report.conflicts == []


def test_conflicting_values_last_wins_and_is_reported():
    graph, _ = merge_document(nx.MultiDiGraph(), BASE)
    graph, report = merge_document(
        graph, doc([node("module:a", provenance=LLM, label="A", attrs={"loc": 12})])
    )
    data = graph.nodes["module:a"]
    assert data["label"] == "A"
    assert data["attrs"]["loc"] == 12
    assert data["provenance"] == LLM
    assert report.conflicts == [
        Conflict("node", "module:a", "provenance", PARSER, LLM),
        Conflict("node", "module:a", "label", "a", "A"),
        Conflict("node", "module:a", "attrs.loc", 10, 12),
    ]


def test_existing_edge_is_not_duplicated():
    graph, _ = merge_document(nx.MultiDiGraph(), BASE)
    graph, report = merge_document(
        graph, doc(edges=[edge("module:a", "module:b", attrs={"alias": "b"})])
    )
    assert graph.number_of_edges() == 1
    assert graph.edges["module:a", "module:b", "imports"]["attrs"] == {"alias": "b"}
    label = edge_label("module:a", "module:b", "imports")
    assert report.edges.merged == [label]


def test_edges_with_different_type_are_distinct():
    graph, _ = merge_document(nx.MultiDiGraph(), BASE)
    graph, report = merge_document(
        graph, doc(edges=[edge("module:a", "module:b", "depends_on")])
    )
    assert graph.number_of_edges() == 2
    assert report.edges.added == ["module:a -[depends_on]-> module:b"]


def test_same_document_twice_is_unchanged():
    graph, _ = merge_document(nx.MultiDiGraph(), BASE)
    again, report = merge_document(graph, BASE)
    assert not report.changed
    assert report.nodes.unchanged == ["module:a", "module:b"]
    assert report.edges.unchanged == ["module:a -[imports]-> module:b"]
    assert store.graph_to_document(again) == store.graph_to_document(graph)


def test_empty_document_changes_nothing():
    graph, report = merge_document(nx.MultiDiGraph(), doc())
    assert graph.number_of_nodes() == 0
    assert not report.changed


def test_repeated_edge_inside_document_is_merged():
    _, report = merge_document(
        nx.MultiDiGraph(),
        doc(
            [node("module:a"), node("module:b")],
            [edge("module:a", "module:b"), edge("module:a", "module:b")],
        ),
    )
    assert len(report.edges.added) == 1
    assert len(report.edges.unchanged) == 1


# --- add_to_store -------------------------------------------------------------


def test_add_writes_store(kg_dir):
    result = add(kg_dir, BASE)
    assert result.validation.ok
    assert [n["id"] for n in stored(kg_dir)["nodes"]] == ["module:a", "module:b"]


def test_add_is_idempotent_byte_for_byte(kg_dir):
    add(kg_dir, BASE)
    first = store.graph_path(kg_dir).read_bytes()
    result = add(kg_dir, BASE)
    assert not result.merge.changed
    assert store.graph_path(kg_dir).read_bytes() == first


def test_add_edge_to_node_already_in_store(kg_dir):
    add(kg_dir, BASE)
    result = add(
        kg_dir,
        doc(
            [node("document:README.md", "Document", LLM)],
            [edge("document:README.md", "module:a", "documents", LLM)],
        ),
    )
    assert result.validation.ok
    assert result.merge.edges.added == ["document:README.md -[documents]-> module:a"]


def test_add_invalid_document_does_not_modify_store(kg_dir):
    add(kg_dir, BASE)
    before = store.graph_path(kg_dir).read_bytes()
    result = add(
        kg_dir,
        doc(
            [node("module:c")],
            [edge("module:c", "module:zz")],  # ni en el archivo ni en el almacén
        ),
    )
    assert not result.validation.ok
    assert result.merge is None
    assert store.graph_path(kg_dir).read_bytes() == before
    (issue,) = result.validation.errors
    assert issue.code == "broken_reference"
    assert "ni en el almacén" in issue.message


def test_broken_reference_suggests_id_from_store(kg_dir):
    add(kg_dir, BASE)
    result = add(kg_dir, doc(edges=[edge("module:a", "module:bb")]))
    (issue,) = result.validation.errors
    assert issue.suggestion.startswith('¿Querías decir "module:b"?')


def test_add_invalid_json(kg_dir):
    result = add_to_store(kg_dir, "{ roto")
    assert [i.code for i in result.validation.errors] == ["invalid_json"]


def test_add_without_store(tmp_path):
    with pytest.raises(store.StoreNotFoundError):
        add(tmp_path / ".kg", BASE)


# --- CLI ----------------------------------------------------------------------


def write(tmp_path, document, name="in.json"):
    path = tmp_path / name
    path.write_text(json.dumps(document), encoding="utf-8")
    return str(path)


def test_cli_add_summary(kg_dir, tmp_path, capsys):
    argv = ["add", write(tmp_path, BASE), "--kg-dir", str(kg_dir)]
    assert main(argv) == EXIT_OK
    out = capsys.readouterr().out
    assert "fusionado en" in out
    assert "nodos:   2 añadidos, 0 fusionados, 0 sin cambios" in out
    assert "aristas: 1 añadida, 0 fusionadas, 0 sin cambios" in out

    assert main(argv) == EXIT_OK
    out = capsys.readouterr().out
    assert out.startswith("sin cambios:")
    assert "nodos:   0 añadidos, 0 fusionados, 2 sin cambios" in out


def test_cli_add_reports_conflicts(kg_dir, tmp_path, capsys):
    add(kg_dir, BASE)
    path = write(tmp_path, doc([node("module:a", label="A")]))
    assert main(["add", path, "--kg-dir", str(kg_dir)]) == EXIT_OK
    out = capsys.readouterr().out
    assert "1 conflicto (se conserva el valor nuevo):" in out
    assert 'module:a · label: "a" → "A"' in out


def test_cli_add_json(kg_dir, tmp_path, capsys):
    add(kg_dir, BASE)
    document = doc([node("module:a", label="A"), node("idea:x", "Idea")])
    path = write(tmp_path, document)
    assert main(["add", path, "--json", "--kg-dir", str(kg_dir)]) == EXIT_OK
    result = json.loads(capsys.readouterr().out)["result"]
    assert result["changed"] is True
    assert result["nodes"] == {
        "added": ["idea:x"],
        "merged": ["module:a"],
        "unchanged": [],
    }
    assert result["conflicts"] == [
        {
            "kind": "node",
            "element": "module:a",
            "field": "label",
            "old": "a",
            "new": "A",
        }
    ]
    assert [w["code"] for w in result["warnings"]] == ["custom_type"]


def test_cli_add_from_stdin(kg_dir, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(BASE)))
    assert main(["add", "-", "--kg-dir", str(kg_dir)]) == EXIT_OK
    assert capsys.readouterr().out.startswith("stdin fusionado en")


def test_cli_add_invalid_exit_1(kg_dir, tmp_path, capsys):
    before = store.graph_path(kg_dir).read_bytes()
    path = write(tmp_path, doc([node("module:a", provenance={})]))
    assert main(["add", path, "--kg-dir", str(kg_dir)]) == EXIT_VALIDATION
    err = capsys.readouterr().err
    assert "no es válido" in err
    assert err.rstrip().endswith("no se ha modificado el almacén")
    assert store.graph_path(kg_dir).read_bytes() == before


def test_cli_add_invalid_json_details(kg_dir, tmp_path, capsys):
    path = write(tmp_path, doc(edges=[edge("module:a", "module:b")]))
    assert main(["add", path, "--json", "--kg-dir", str(kg_dir)]) == EXIT_VALIDATION
    details = json.loads(capsys.readouterr().out)["error"]["details"]
    assert details["valid"] is False
    assert {e["code"] for e in details["errors"]} == {"broken_reference"}


def test_cli_add_without_store_is_usage_error(tmp_path, capsys):
    path = write(tmp_path, BASE)
    assert main(["add", path, "--kg-dir", str(tmp_path / ".kg")]) == EXIT_USAGE
    assert "kg init" in capsys.readouterr().err


def test_cli_add_missing_file(kg_dir, tmp_path, capsys):
    argv = ["add", str(tmp_path / "no.json"), "--kg-dir", str(kg_dir)]
    assert main(argv) == EXIT_USAGE
    assert "no existe el archivo" in capsys.readouterr().err


def test_cli_add_corrupt_store_exit_1(kg_dir, tmp_path, capsys):
    store.graph_path(kg_dir).write_text("{}", encoding="utf-8")
    path = write(tmp_path, BASE)
    assert main(["add", path, "--kg-dir", str(kg_dir)]) == EXIT_VALIDATION
    assert "no es un almacén válido" in capsys.readouterr().err
