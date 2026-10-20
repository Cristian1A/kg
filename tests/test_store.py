import json
import random
from pathlib import Path

import networkx as nx
import pytest

from kg import store
from kg.cli import EXIT_OK, EXIT_USAGE, main
from kg.store import (
    StoreCorruptError,
    StoreError,
    StoreExistsError,
    StoreNotFoundError,
)

EXAMPLE = Path(__file__).parents[1] / "examples" / "basic-repo.json"

PROV = {"method": "parser", "extractor": "python-ast@0.1", "confidence": 1.0}


def node(id_, type_, **extra):
    return {"id": id_, "type": type_, "provenance": dict(PROV), **extra}


def edge(source, target, type_="contains", **extra):
    return {
        "source": source,
        "target": target,
        "type": type_,
        "provenance": dict(PROV),
        **extra,
    }


def example_document():
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


@pytest.fixture
def kg_dir(tmp_path):
    path = tmp_path / ".kg"
    store.init_store(path)
    return path


# --- init ---------------------------------------------------------------------


def test_init_creates_empty_valid_store(tmp_path):
    path = store.init_store(tmp_path / ".kg")
    assert path == tmp_path / ".kg" / "graph.json"
    assert path.read_text(encoding="utf-8") == (
        '{\n  "version": "1",\n  "nodes": [],\n  "edges": []\n}\n'
    )
    assert path.stat().st_mode & 0o777 == 0o644
    graph = store.load_graph(tmp_path / ".kg")
    assert graph.number_of_nodes() == graph.number_of_edges() == 0


def test_init_fails_if_store_exists_and_keeps_it(kg_dir):
    graph_file = store.graph_path(kg_dir)
    graph_file.write_text("contenido previo", encoding="utf-8")
    with pytest.raises(StoreExistsError, match="already exists"):
        store.init_store(kg_dir)
    assert graph_file.read_text(encoding="utf-8") == "contenido previo"


def test_init_fails_if_path_is_a_file(tmp_path):
    (tmp_path / ".kg").write_text("", encoding="utf-8")
    with pytest.raises(StoreExistsError):
        store.init_store(tmp_path / ".kg")


def test_init_fails_if_parent_is_missing(tmp_path):
    with pytest.raises(StoreNotFoundError, match="does not exist"):
        store.init_store(tmp_path / "no" / "existe" / ".kg")
    assert not (tmp_path / "no").exists()


# --- load and save -------------------------------------------------------------


def test_round_trip_preserves_nodes_and_edges(kg_dir):
    document = example_document()
    store.save_graph(store.document_to_graph(document), kg_dir)
    graph = store.load_graph(kg_dir)

    assert isinstance(graph, nx.MultiDiGraph)
    assert set(graph.nodes) == {n["id"] for n in document["nodes"]}
    assert graph.number_of_edges() == len(document["edges"])
    main_fn = graph.nodes["function:kg.cli.main"]
    assert main_fn["type"] == "Function"
    assert main_fn["attrs"] == {"public": True}
    assert main_fn["provenance"]["lines"] == [179, 202]
    for e in document["edges"]:
        data = graph.edges[e["source"], e["target"], e["type"]]
        assert data["provenance"] == e["provenance"]


def test_saved_store_is_valid_input_document(kg_dir):
    store.save_graph(store.document_to_graph(example_document()), kg_dir)
    assert main(["validate", str(store.graph_path(kg_dir))]) == EXIT_OK


def test_save_is_idempotent(kg_dir):
    store.save_graph(store.document_to_graph(example_document()), kg_dir)
    first = store.graph_path(kg_dir).read_bytes()
    store.save_graph(store.load_graph(kg_dir), kg_dir)
    assert store.graph_path(kg_dir).read_bytes() == first


@pytest.mark.parametrize("seed", range(5))
def test_same_graph_any_insertion_order_same_bytes(tmp_path, seed):
    """RNF-08: the file does not depend on the order of nodes, edges or keys."""
    reference = tmp_path / "ref"
    reference.mkdir()
    store.save_graph(store.document_to_graph(example_document()), reference)

    document = example_document()
    rng = random.Random(seed)
    rng.shuffle(document["nodes"])
    rng.shuffle(document["edges"])
    for item in [*document["nodes"], *document["edges"]]:
        keys = list(item["provenance"])
        rng.shuffle(keys)
        item["provenance"] = {k: item["provenance"][k] for k in keys}
    shuffled = tmp_path / "shuffled"
    shuffled.mkdir()
    store.save_graph(store.document_to_graph(document), shuffled)

    assert (shuffled / "graph.json").read_bytes() == (
        reference / "graph.json"
    ).read_bytes()


def test_canonical_order_of_items_and_fields():
    graph = store.document_to_graph(
        {
            "version": "1",
            "nodes": [
                node("module:b", "Module", attrs={"z": 1, "a": {"y": 2, "b": 3}}),
                node("module:a", "Module", description="d", label="A"),
            ],
            "edges": [
                edge("module:b", "module:a", "imports"),
                edge("module:a", "module:b", "imports"),
                edge("module:a", "module:b", "contains"),
            ],
        }
    )
    document = store.graph_to_document(graph)

    assert list(document) == ["version", "nodes", "edges"]
    assert [n["id"] for n in document["nodes"]] == ["module:a", "module:b"]
    a, b = document["nodes"]
    assert list(a) == ["id", "type", "label", "description", "provenance"]
    assert list(b["attrs"]) == ["a", "z"]
    assert list(b["attrs"]["a"]) == ["b", "y"]
    assert list(a["provenance"]) == ["confidence", "extractor", "method"]
    assert [(e["source"], e["target"], e["type"]) for e in document["edges"]] == [
        ("module:a", "module:b", "contains"),
        ("module:a", "module:b", "imports"),
        ("module:b", "module:a", "imports"),
    ]
    assert list(document["edges"][0]) == ["source", "target", "type", "provenance"]


def test_non_ascii_is_written_as_utf8(kg_dir):
    graph = nx.MultiDiGraph()
    graph.add_node("concept:diseño", type="Concept", provenance=dict(PROV))
    store.save_graph(graph, kg_dir)
    text = store.graph_path(kg_dir).read_text(encoding="utf-8")
    assert '"concept:diseño"' in text


def test_extra_fields_are_not_stored(kg_dir):
    document = example_document()
    assert "$schema" in document
    store.save_graph(store.document_to_graph(document), kg_dir)
    saved = json.loads(store.graph_path(kg_dir).read_text(encoding="utf-8"))
    assert "$schema" not in saved


# --- errores ------------------------------------------------------------------


def test_load_without_store(tmp_path):
    with pytest.raises(StoreNotFoundError, match="kg init"):
        store.load_graph(tmp_path / ".kg")


@pytest.mark.parametrize(
    ("content", "code"),
    [
        ("", "invalid_json"),
        ("{ not json", "invalid_json"),
        ('{"version": "1", "nodes": []}', "required"),
        ('{"version": "2", "nodes": [], "edges": []}', "not_allowed"),
    ],
)
def test_load_corrupt_store_reports_issues(kg_dir, content, code):
    store.graph_path(kg_dir).write_text(content, encoding="utf-8")
    with pytest.raises(StoreCorruptError, match="kg validate") as exc:
        store.load_graph(kg_dir)
    assert code in {i.code for i in exc.value.report.errors}


def test_load_rejects_duplicate_edges(kg_dir):
    document = {
        "version": "1",
        "nodes": [node("module:a", "Module"), node("module:b", "Module")],
        "edges": [edge("module:a", "module:b"), edge("module:a", "module:b")],
    }
    store.graph_path(kg_dir).write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(StoreError, match=r"\$\.edges\[1\]: duplicate edge"):
        store.load_graph(kg_dir)


# --- Validated-content cache -------------------------------------------------


def validated(cache_home):
    return list((cache_home / store.VALIDATED_DIR).iterdir())


def test_saved_store_loads_without_validating_again(kg_dir, monkeypatch):
    graph = store.document_to_graph(example_document())
    store.save_graph(graph, kg_dir)

    def fail(data):
        raise AssertionError("validated again")

    monkeypatch.setattr(store, "validate_bytes", fail)
    assert nx.utils.graphs_equal(store.load_graph(kg_dir), graph)


def test_edited_store_is_validated_again(kg_dir):
    store.load_graph(kg_dir)  # the empty store is now known to be valid
    path = store.graph_path(kg_dir)
    path.write_text('{"version": "1", "nodes": []}', encoding="utf-8")
    with pytest.raises(StoreCorruptError):
        store.load_graph(kg_dir)


def test_store_validated_on_load_is_remembered(kg_dir, cache_home, monkeypatch):
    document = example_document()
    store.graph_path(kg_dir).write_text(json.dumps(document), encoding="utf-8")
    calls = []
    real = store.validate_bytes
    monkeypatch.setattr(store, "validate_bytes", lambda d: calls.append(d) or real(d))
    store.load_graph(kg_dir)
    store.load_graph(kg_dir)
    assert len(calls) == 1


def test_invalid_store_is_never_remembered(kg_dir, cache_home):
    before = validated(cache_home)
    store.graph_path(kg_dir).write_text("{ not json", encoding="utf-8")
    for _ in range(2):
        with pytest.raises(StoreCorruptError):
            store.load_graph(kg_dir)
    assert validated(cache_home) == before


def test_unwritable_cache_still_loads(kg_dir, tmp_path, monkeypatch):
    blocked = tmp_path / "blocked"
    blocked.write_text("a file, not a directory")
    monkeypatch.setenv("XDG_CACHE_HOME", str(blocked))
    store.save_graph(store.document_to_graph(example_document()), kg_dir)
    assert store.load_graph(kg_dir).number_of_nodes() > 0


def test_cache_keeps_only_the_latest_markers(kg_dir, cache_home, monkeypatch):
    monkeypatch.setattr(store, "VALIDATED_KEEP", 3)
    for i in range(5):
        graph = nx.MultiDiGraph()
        graph.add_node(f"module:m{i}", type="Module", provenance=dict(PROV))
        store.save_graph(graph, kg_dir)
    assert len(validated(cache_home)) == 3


def test_save_invalid_graph_keeps_previous_store(kg_dir):
    before = store.graph_path(kg_dir).read_bytes()
    graph = nx.MultiDiGraph()
    graph.add_node("module:a")  # no type or provenance
    with pytest.raises(StoreCorruptError) as exc:
        store.save_graph(graph, kg_dir)
    assert {i.path for i in exc.value.report.errors} == {
        "$.nodes[0].type",
        "$.nodes[0].provenance",
    }
    assert store.graph_path(kg_dir).read_bytes() == before
    assert list(kg_dir.iterdir()) == [store.graph_path(kg_dir)]


def test_save_rejects_duplicate_edges_without_type_key(kg_dir):
    graph = nx.MultiDiGraph()
    for n in ("module:a", "module:b"):
        graph.add_node(n, type="Module", provenance=dict(PROV))
    graph.add_edge("module:a", "module:b", type="imports", provenance=dict(PROV))
    graph.add_edge("module:a", "module:b", type="imports", provenance=dict(PROV))
    with pytest.raises(StoreError, match="duplicate edge"):
        store.save_graph(graph, kg_dir)


# --- CLI ----------------------------------------------------------------------


def test_cli_init(tmp_path, capsys):
    kg_dir = tmp_path / ".kg"
    assert main(["init", "--kg-dir", str(kg_dir)]) == EXIT_OK
    assert "store created" in capsys.readouterr().out
    assert store.graph_path(kg_dir).is_file()


def test_cli_init_uses_current_directory_by_default(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["init"]) == EXIT_OK
    assert (tmp_path / ".kg" / "graph.json").is_file()


def test_cli_init_json(tmp_path, capsys):
    kg_dir = tmp_path / ".kg"
    assert main(["init", "--json", "--kg-dir", str(kg_dir)]) == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "ok": True,
        "command": "init",
        "result": {
            "kg_dir": str(kg_dir),
            "graph": str(kg_dir / "graph.json"),
            "version": "1",
        },
    }


def test_cli_init_existing_store_is_usage_error(kg_dir, capsys):
    assert main(["init", "--kg-dir", str(kg_dir)]) == EXIT_USAGE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == f"error: {kg_dir} already exists; nothing was changed\n"


def test_cli_init_existing_store_json(kg_dir, capsys):
    assert main(["--json", "init", "--kg-dir", str(kg_dir)]) == EXIT_USAGE
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["error"]["type"] == "UsageError"
    assert payload["error"]["details"] == {"path": str(kg_dir)}
