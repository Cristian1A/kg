import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from kg.cli import EXIT_OK, main
from kg.schema import (
    STANDARD_EDGE_TYPES,
    STANDARD_NODE_TYPES,
    CustomType,
    find_custom_types,
    load_schema,
    schema_path,
    validator,
)

EXAMPLES = sorted((Path(__file__).parents[1] / "examples").glob("*.json"))

PROV = {"method": "parser", "extractor": "python-ast@0.1", "confidence": 1.0}


@pytest.fixture
def doc():
    return {
        "version": "1",
        "nodes": [
            {"id": "file:a.py", "type": "File", "provenance": dict(PROV)},
            {"id": "function:a.f", "type": "Function", "provenance": dict(PROV)},
        ],
        "edges": [
            {
                "source": "file:a.py",
                "target": "function:a.f",
                "type": "defines",
                "provenance": dict(PROV),
            }
        ],
    }


def errors(document):
    return list(validator().iter_errors(document))


def test_schema_is_valid_draft_2020_12():
    schema = load_schema()
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    Draft202012Validator.check_schema(schema)


def test_schema_is_shipped_in_package():
    path = schema_path()
    assert path.name == "kg.schema.json"
    assert json.loads(path.read_text(encoding="utf-8")) == load_schema()


def test_load_schema_returns_independent_copy():
    load_schema()["title"] = "modificado"
    assert load_schema()["title"] != "modificado"


def test_standard_catalog_matches_requirements():
    assert STANDARD_NODE_TYPES == {
        "Repo", "Package", "Module", "File", "Class", "Function", "Dependency",
        "Test", "Document", "Config", "Service", "Endpoint", "Person", "Issue",
        "Decision", "Concept",
    }  # fmt: skip
    assert STANDARD_EDGE_TYPES == {
        "contains", "imports", "depends_on", "defines", "calls", "documents",
        "tests", "configures", "authored_by", "implements", "justifies",
    }  # fmt: skip


def test_valid_document(doc):
    assert errors(doc) == []
    assert find_custom_types(doc) == []


def test_empty_graph_is_valid():
    assert errors({"version": "1", "nodes": [], "edges": []}) == []


def test_full_provenance_is_valid(doc):
    doc["nodes"][0]["provenance"] |= {
        "source": "a.py",
        "lines": [1, 1],
        "timestamp": "2026-10-09T12:00:00+02:00",
    }
    assert errors(doc) == []


@pytest.mark.parametrize("example", EXAMPLES, ids=lambda p: p.name)
def test_examples_are_valid(example):
    assert errors(json.loads(example.read_text(encoding="utf-8"))) == []


def test_examples_exist():
    assert len(EXAMPLES) >= 2


def test_custom_types_are_valid_but_reported(doc):
    doc["nodes"][1]["type"] = "Requirement"
    doc["edges"][0]["type"] = "satisfies"
    assert errors(doc) == []
    found = find_custom_types(doc)
    assert found == [
        CustomType("$.nodes[1].type", "node", "Requirement"),
        CustomType("$.edges[0].type", "edge", "satisfies"),
    ]
    assert "Requirement" in found[0].message


def test_find_custom_types_ignores_malformed_input():
    assert find_custom_types({}) == []
    assert find_custom_types({"nodes": "x", "edges": [1, {"type": 2}]}) == []


def _set(document, path, value):
    *parents, last = path
    target = document
    for key in parents:
        target = target[key]
    if value is _DELETE:
        del target[last]
    else:
        target[last] = value


_DELETE = object()


@pytest.mark.parametrize(
    "path, value",
    [
        (["version"], "2"),
        (["nodes"], _DELETE),
        (["extra"], 1),
        (["nodes", 0, "id"], "a.py"),
        (["nodes", 0, "id"], "File:a.py"),
        (["nodes", 0, "id"], "file:"),
        (["nodes", 0, "type"], "file"),
        (["nodes", 0, "color"], "red"),
        (["nodes", 0, "attrs"], []),
        (["nodes", 0, "provenance"], _DELETE),
        (["nodes", 0, "provenance", "method"], "magia"),
        (["nodes", 0, "provenance", "extractor"], _DELETE),
        (["nodes", 0, "provenance", "confidence"], 1.5),
        (["nodes", 0, "provenance", "confidence"], -0.1),
        (["nodes", 0, "provenance", "lines"], [1, 2, 3]),
        (["nodes", 0, "provenance", "lines"], [0, 2]),
        (["nodes", 0, "provenance", "timestamp"], "09/10/2026"),
        (["nodes", 0, "provenance", "timestamp"], "2026-10-09T12:00:00"),
        (["nodes", 0, "provenance", "autor"], "x"),
        (["edges", 0, "target"], _DELETE),
        (["edges", 0, "source"], "a.py"),
        (["edges", 0, "type"], "Defines"),
    ],
)
def test_invalid_documents_are_rejected(doc, path, value):
    broken = copy.deepcopy(doc)
    _set(broken, path, value)
    assert errors(broken), f"should fail: {path} = {value!r}"


def test_cli_schema_prints_schema(capsys):
    assert main(["schema"]) == EXIT_OK
    assert json.loads(capsys.readouterr().out) == load_schema()


def test_cli_schema_path(capsys):
    assert main(["schema", "--path"]) == EXIT_OK
    assert capsys.readouterr().out.strip() == str(schema_path())


def test_cli_schema_json(capsys):
    assert main(["--json", "schema"]) == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["command"] == "schema"
    assert payload["result"]["schema"] == load_schema()
    assert payload["result"]["path"] == str(schema_path())
