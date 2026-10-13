import io
import json
from pathlib import Path

import pytest

from kg.cli import EXIT_OK, EXIT_USAGE, EXIT_VALIDATION, main
from kg.schema.validation import (
    Issue,
    validate_document,
    validate_path,
    validate_text,
)

EXAMPLES = sorted((Path(__file__).parents[1] / "examples").glob("*.json"))
# What agents added to real repos; edges point to extracted nodes outside them
AGENT_EXAMPLES = sorted((Path(__file__).parents[1] / "examples/agent").glob("*.json"))

PROV = {"method": "parser", "extractor": "python-ast@0.1", "confidence": 1.0}


def node(id_, type_, **extra):
    return {"id": id_, "type": type_, "provenance": dict(PROV), **extra}


def edge(source, target, type_="defines", **extra):
    return {
        "source": source,
        "target": target,
        "type": type_,
        "provenance": dict(PROV),
        **extra,
    }


def document(nodes=(), edges=()):
    return {"version": "1", "nodes": list(nodes), "edges": list(edges)}


@pytest.fixture
def valid():
    return document(
        [node("file:a.py", "File"), node("function:a.f", "Function")],
        [edge("file:a.py", "function:a.f")],
    )


def only_error(report) -> Issue:
    assert len(report.errors) == 1, [i.to_text() for i in report.errors]
    return report.errors[0]


# --- Normal and edge cases ------------------------------------------------------


def test_valid_document_has_no_issues(valid):
    report = validate_document(valid)
    assert report.ok
    assert report.errors == report.warnings == []
    assert (report.nodes, report.edges) == (2, 1)
    assert report.summary("a.json") == "a.json is valid (2 nodes, 1 edge)"


def test_empty_graph_is_valid():
    report = validate_document(document())
    assert report.ok
    assert report.summary("x") == "x is valid (0 nodes, 0 edges)"


@pytest.mark.parametrize("example", EXAMPLES, ids=lambda p: p.name)
def test_examples_have_no_errors(example):
    assert validate_path(example).ok


@pytest.mark.parametrize("value", [[], "texto", 3, None])
def test_non_object_document(value):
    issue = only_error(validate_document(value))
    assert issue.code == "wrong_type"
    assert issue.path == "$"
    assert issue.expected == "object"


def test_every_error_is_actionable():
    broken = document(
        [{"id": "x", "type": 1, "extra": True}, node("file:a.py", "file")],
        [edge("file:a.py", "file:nada", "Defines")],
    )
    report = validate_document(broken)
    assert not report.ok
    for issue in report.errors:
        assert issue.path.startswith("$")
        assert issue.message and issue.expected and issue.suggestion
        assert issue.severity == "error"


# --- Error messages (RNF-07) -------------------------------------------------


def test_invalid_json_reports_position():
    issue = only_error(validate_text('{"version": "1",\n "nodes": [}'))
    assert issue.code == "invalid_json"
    assert issue.path == "$"
    assert issue.received == "line 2, column 12"


def test_missing_required_field(valid):
    del valid["nodes"][0]["provenance"]
    issue = only_error(validate_document(valid))
    assert issue.code == "required"
    assert issue.path == "$.nodes[0].provenance"
    assert issue.received is None
    assert issue.expected.startswith("field `provenance`")
    assert '"method": "parser"' in issue.suggestion


def test_missing_top_level_lists():
    report = validate_document({"version": "1"})
    assert [(i.code, i.path) for i in report.errors] == [
        ("required", "$.nodes"),
        ("required", "$.edges"),
    ]
    assert report.errors[0].suggestion == 'Add `"nodes": []` even if it is empty.'


def test_unknown_field_suggests_close_name(valid):
    valid["nodes"][0]["lable"] = "a"
    issue = only_error(validate_document(valid))
    assert issue.code == "unknown_field"
    assert issue.path == "$.nodes[0].lable"
    assert issue.received == '"a"'
    assert 'Did you mean "label"?' in issue.suggestion
    assert "`attrs`" in issue.suggestion


def test_unknown_provenance_field(valid):
    prov = valid["edges"][0]["provenance"]
    prov["metod"] = prov.pop("method")
    codes = {(i.code, i.path) for i in validate_document(valid).errors}
    assert codes == {
        ("required", "$.edges[0].provenance.method"),
        ("unknown_field", "$.edges[0].provenance.metod"),
    }


def test_enum_value(valid):
    valid["nodes"][0]["provenance"]["method"] = "Parser"
    issue = only_error(validate_document(valid))
    assert issue.code == "not_allowed"
    assert issue.received == '"Parser"'
    assert issue.expected == 'one of "parser", "llm", "manual"'
    assert issue.suggestion == 'Use "parser".'


def test_version_const(valid):
    valid["version"] = 1
    issue = only_error(validate_document(valid))
    assert (issue.code, issue.path, issue.received) == ("not_allowed", "$.version", "1")
    assert issue.suggestion == 'Use "1".'


@pytest.mark.parametrize("value", [1.5, -0.1])
def test_confidence_out_of_range(valid, value):
    valid["nodes"][0]["provenance"]["confidence"] = value
    issue = only_error(validate_document(valid))
    assert issue.code == "out_of_range"
    assert issue.path == "$.nodes[0].provenance.confidence"
    assert issue.expected == "a number between 0 and 1"


def test_wrong_type_shows_received_type(valid):
    valid["nodes"][0]["provenance"]["confidence"] = "alta"
    issue = only_error(validate_document(valid))
    assert issue.code == "wrong_type"
    assert issue.received == '"alta" (string)'
    assert issue.expected == "number"


def test_lines_length(valid):
    valid["nodes"][0]["provenance"]["lines"] = [3]
    issue = only_error(validate_document(valid))
    assert issue.code == "wrong_length"
    assert issue.received == "[3] (1 item)"
    assert issue.expected == "exactly 2 items"


def test_timestamp_format(valid):
    valid["nodes"][0]["provenance"]["timestamp"] = "2026-10-09 12:00"
    issue = only_error(validate_document(valid))
    assert issue.code == "invalid_timestamp"
    assert "2026-10-09T12:00:00Z" in issue.expected


@pytest.mark.parametrize(
    "id_, hint",
    [
        ("a.py", '"file:a.py"'),
        ("File:a.py", '"file:a.py"'),
        ("file:", "`file:src/app/main.py`"),
    ],
)
def test_invalid_id_suggests_fixed_id(valid, id_, hint):
    valid["nodes"][0]["id"] = id_
    valid["edges"] = []
    issue = only_error(validate_document(valid))
    assert issue.code == "invalid_id"
    assert issue.path == "$.nodes[0].id"
    assert hint in issue.suggestion


@pytest.mark.parametrize(
    "path, value, suggestion",
    [
        (("nodes", 0), "file", 'Use the standard type "File".'),
        (("edges", 0), "Defines", 'Use the standard type "defines".'),
    ],
)
def test_invalid_type_name_suggests_standard(valid, path, value, suggestion):
    valid[path[0]][path[1]]["type"] = value
    report = validate_document(valid)
    issue = only_error(report)
    assert issue.code == "invalid_type_name"
    assert issue.suggestion.startswith(suggestion)
    assert report.warnings == []  # not duplicated as a custom type


def test_long_values_are_truncated(valid):
    valid["nodes"][0]["lable"] = "x" * 500
    issue = only_error(validate_document(valid))
    assert len(issue.received) == 80
    assert issue.received.endswith("…")


def test_issue_to_text():
    issue = Issue("required", "$.a", "missing", None, "field `a`", "Add it.")
    assert issue.to_text() == (
        "error: $.a: missing\n"
        "  received:   (missing)\n"
        "  expected:   field `a`\n"
        "  suggestion: Add it."
    )


# --- Semantic checks (RF-05) and warnings (RF-02) ------------------------------


def test_duplicate_ids(valid):
    valid["nodes"].append(node("file:a.py", "File"))
    issue = only_error(validate_document(valid))
    assert issue.code == "duplicate_id"
    assert issue.path == "$.nodes[2].id"
    assert "$.nodes[0]" in issue.message


def test_broken_reference_suggests_close_id(valid):
    valid["edges"][0]["target"] = "function:a.g"
    issue = only_error(validate_document(valid))
    assert issue.code == "broken_reference"
    assert issue.path == "$.edges[0].target"
    assert 'Did you mean "function:a.f"?' in issue.suggestion


def test_broken_references_on_both_ends(valid):
    valid["edges"].append(edge("file:x.py", "file:y.py", "contains"))
    paths = [i.path for i in validate_document(valid).errors]
    assert paths == ["$.edges[1].source", "$.edges[1].target"]


def test_custom_types_are_warnings_not_errors(valid):
    valid["nodes"].append(node("requirement:rf-01", "Requirement"))
    valid["edges"].append(edge("function:a.f", "requirement:rf-01", "satisfies"))
    report = validate_document(valid)
    assert report.ok
    assert [(w.code, w.path) for w in report.warnings] == [
        ("custom_type", "$.nodes[2].type"),
        ("custom_type", "$.edges[1].type"),
    ]
    assert all(w.severity == "warning" for w in report.warnings)
    assert "1 warning" not in report.summary("x")
    assert "2 warnings" in report.summary("x")


def test_id_prefix_mismatch_is_warning(valid):
    valid["nodes"][1]["id"] = "file:a.f"
    valid["edges"][0]["target"] = "file:a.f"
    report = validate_document(valid)
    assert report.ok
    warning = report.warnings[0]
    assert (warning.code, warning.path) == ("id_prefix_mismatch", "$.nodes[1].id")
    assert '"function:a.f"' in warning.suggestion


LLM = {"method": "llm", "extractor": "claude-code", "confidence": 0.8}


@pytest.mark.parametrize(
    ("extra", "warned"),
    [
        ({}, True),
        ({"description": "   "}, True),
        ({"description": "Why the CLI has no dependencies."}, False),
    ],
)
def test_agent_nodes_need_a_description(extra, warned):
    report = validate_document(
        document([{"id": "decision:x", "type": "Decision", "provenance": LLM, **extra}])
    )
    assert report.ok  # a warning, not an error
    codes = [(w.code, w.path) for w in report.warnings]
    assert codes == ([("missing_description", "$.nodes[0].description")] * warned)


def test_parser_and_manual_nodes_need_no_description(valid):
    manual = {"method": "manual", "extractor": "me", "confidence": 1.0}
    valid["nodes"].append({"id": "concept:x", "type": "Concept", "provenance": manual})
    assert validate_document(valid).warnings == []


@pytest.mark.parametrize("example", EXAMPLES + AGENT_EXAMPLES, ids=lambda p: p.name)
def test_examples_describe_every_agent_node(example):
    codes = [w.code for w in validate_path(example).warnings]
    assert "missing_description" not in codes


def test_cli_add_warns_about_missing_descriptions(tmp_path, capsys):
    kg_dir = tmp_path / ".kg"
    assert main(["init", "--kg-dir", str(kg_dir)]) == EXIT_OK
    path = tmp_path / "agent.json"
    nodes = [{"id": "concept:x", "type": "Concept", "provenance": LLM}]
    path.write_text(json.dumps(document(nodes)), encoding="utf-8")
    capsys.readouterr()
    assert main(["add", str(path), "--kg-dir", str(kg_dir), "--json"]) == EXIT_OK
    result = json.loads(capsys.readouterr().out)["result"]
    assert [w["code"] for w in result["warnings"]] == ["missing_description"]


def test_issues_follow_document_order():
    broken = document(
        [node("file:a.py", "File", extra=1), node("file:a.py", "File")],
        [edge("file:a.py", "file:nada")],
    )
    broken["version"] = "2"
    paths = [i.path for i in validate_document(broken).errors]
    assert paths == [
        "$.version",
        "$.nodes[0].extra",
        "$.nodes[1].id",
        "$.edges[0].target",
    ]


# --- CLI ---------------------------------------------------------------------


@pytest.fixture
def write(tmp_path):
    def _write(content, name="g.json"):
        path = tmp_path / name
        text = content if isinstance(content, str) else json.dumps(content)
        path.write_text(text, encoding="utf-8")
        return str(path)

    return _write


def test_cli_valid_file(valid, write, capsys):
    path = write(valid)
    assert main(["validate", path]) == EXIT_OK
    captured = capsys.readouterr()
    assert captured.out.strip() == f"{path} is valid (2 nodes, 1 edge)"
    assert captured.err == ""


def test_cli_warnings_exit_0(valid, write, capsys):
    valid["nodes"][0]["type"] = "Fichero"
    valid["nodes"][0]["id"] = "fichero:a.py"
    valid["edges"][0]["source"] = "fichero:a.py"
    assert main(["validate", write(valid)]) == EXIT_OK
    assert "warning: $.nodes[0].type" in capsys.readouterr().out


def test_cli_errors_exit_1(valid, write, capsys):
    valid["edges"][0]["target"] = "function:nada"
    path = write(valid)
    assert main(["validate", path]) == EXIT_VALIDATION
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith(f"error: {path} is not valid: 1 error\n")
    assert "error: $.edges[0].target" in captured.err


def test_cli_json_success(valid, write, capsys):
    valid["nodes"].append(node("requirement:x", "Requirement"))
    path = write(valid)
    assert main(["--json", "validate", path]) == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    result = payload["result"]
    assert result["file"] == path
    assert result["valid"] is True
    assert result["errors"] == []
    assert result["warnings"][0]["code"] == "custom_type"


def test_cli_json_errors(valid, write, capsys):
    del valid["nodes"][0]["provenance"]["extractor"]
    assert main(["validate", write(valid), "--json"]) == EXIT_VALIDATION
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["error"]["code"] == EXIT_VALIDATION
    assert payload["error"]["type"] == "ValidationError"
    details = payload["error"]["details"]
    assert details["valid"] is False
    assert details["errors"] == [
        {
            "code": "required",
            "path": "$.nodes[0].provenance.extractor",
            "message": "missing required field",
            "received": None,
            "expected": "field `extractor`: Tool and version that produced it.",
            "suggestion": "Add the field `extractor`.",
            "severity": "error",
        }
    ]


def test_cli_invalid_json_exit_1(write, capsys):
    assert main(["validate", write("{nope")]) == EXIT_VALIDATION
    assert "malformed JSON" in capsys.readouterr().err


def test_cli_invalid_encoding_exit_1(tmp_path, capsys):
    path = tmp_path / "latin1.json"
    path.write_bytes('{"a": "ñ"}'.encode("latin-1"))
    assert main(["validate", str(path)]) == EXIT_VALIDATION
    assert "UTF-8" in capsys.readouterr().err


def test_cli_missing_file_is_usage_error(tmp_path, capsys):
    assert main(["validate", str(tmp_path / "no.json")]) == EXIT_USAGE
    assert "file not found" in capsys.readouterr().err


def test_cli_directory_is_usage_error(tmp_path, capsys):
    assert main(["validate", str(tmp_path)]) == EXIT_USAGE
    assert "cannot read" in capsys.readouterr().err


def test_cli_reads_stdin(valid, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(valid)))
    assert main(["validate", "-"]) == EXIT_OK
    assert capsys.readouterr().out.startswith("stdin is valid")


def test_cli_does_not_touch_store(valid, write, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = write(valid)
    before = sorted(p.name for p in tmp_path.iterdir())
    assert main(["validate", path, "--kg-dir", str(tmp_path / ".kg")]) == EXIT_OK
    assert sorted(p.name for p in tmp_path.iterdir()) == before
    assert not (tmp_path / ".kg").exists()
