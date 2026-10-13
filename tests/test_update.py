import json

import pytest

from kg import store
from kg.cli import EXIT_INTERNAL, EXIT_OK, EXIT_USAGE, main
from kg.extract import extract_repo
from kg.update import is_derived, prune, staleness, update_store

LLM = {"method": "llm", "extractor": "claude-code", "confidence": 0.8}


def write(root, files):
    for path, text in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "demo"
    write(
        root,
        {
            "app/__init__.py": "",
            "app/core.py": "from app.util import helper\n\n\ndef run():\n"
            "    return helper()\n",
            "app/util.py": "def helper():\n    return 1\n\n\ndef old():\n    pass\n",
            "tests/test_core.py": "from app.core import run\n\n\ndef test_run():\n"
            "    assert run()\n",
        },
    )
    store.init_store(root / ".kg")
    return root


def extract(root, *extra):
    return main(["extract", str(root), "--kg-dir", str(root / ".kg"), *extra])


def graph(root):
    return store.load_graph(root / ".kg")


def text(root):
    return store.graph_path(root / ".kg").read_text(encoding="utf-8")


def add_agent_knowledge(root):
    """A concept implemented by `old()`, plus an agent-only edge."""
    document = {
        "version": "1",
        "nodes": [
            {"id": "concept:legacy", "type": "Concept", "provenance": LLM},
            {"id": "document:README.md", "type": "Document", "provenance": LLM},
        ],
        "edges": [
            {
                "source": "function:app.util.old",
                "target": "concept:legacy",
                "type": "implements",
                "provenance": LLM,
            },
            {
                "source": "document:README.md",
                "target": "concept:legacy",
                "type": "documents",
                "provenance": LLM,
            },
        ],
    }
    path = root / "agent.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    assert main(["add", str(path), "--kg-dir", str(root / ".kg")]) == EXIT_OK


# --- Scenarios of #37 ----------------------------------------------------------


def test_extracting_twice_without_changes(repo, capsys):
    assert extract(repo) == EXIT_OK
    before = text(repo)
    capsys.readouterr()
    assert extract(repo) == EXIT_OK
    assert text(repo) == before
    assert capsys.readouterr().out.startswith("no changes")


def test_modified_function_and_dependencies(repo):
    extract(repo)
    write(repo, {"app/core.py": "import requests\n\n\ndef run():\n    return 2\n"})
    extract(repo)
    g = graph(repo)
    assert not g.has_edge("module:app.core", "module:app.util", key="imports")
    assert g.has_edge("module:app.core", "dependency:requests", key="imports")
    # The test no longer reaches helper() through run(); its own edge stays
    assert g.has_edge("test:tests.test_core.test_run", "function:app.core.run")


def test_deleted_function_is_removed_with_its_edges(repo):
    extract(repo)
    write(repo, {"app/util.py": "def helper():\n    return 1\n"})
    extract(repo)
    g = graph(repo)
    assert "function:app.util.old" not in g
    assert "function:app.util.helper" in g


def test_deleted_function_with_agent_edges_is_kept_and_reported(repo, capsys):
    extract(repo)
    add_agent_knowledge(repo)
    write(repo, {"app/util.py": "def helper():\n    return 1\n"})
    capsys.readouterr()
    assert extract(repo, "--json") == EXIT_OK
    removed = json.loads(capsys.readouterr().out)["result"]["removed"]
    assert removed["orphans"] == [
        {
            "id": "function:app.util.old",
            "edges": ["function:app.util.old -[implements]-> concept:legacy"],
        }
    ]
    g = graph(repo)
    assert "function:app.util.old" in g
    # The parser edge to it is gone; the agent's knowledge is intact
    assert not g.has_edge("file:app/util.py", "function:app.util.old")
    assert {"concept:legacy", "document:README.md"} <= set(g)
    assert g.has_edge("document:README.md", "concept:legacy", key="documents")


def test_orphan_is_removed_once_the_agent_edge_is_gone(repo):
    extract(repo)
    add_agent_knowledge(repo)
    write(repo, {"app/util.py": "def helper():\n    return 1\n"})
    extract(repo)
    kg_dir = str(repo / ".kg")
    edge = ["function:app.util.old", "implements", "concept:legacy"]
    assert main(["remove", "--edge", *edge, "--kg-dir", kg_dir]) == EXIT_OK
    extract(repo)
    assert "function:app.util.old" not in graph(repo)


def test_renamed_or_moved_file(repo):
    extract(repo)
    (repo / "app/util.py").rename(repo / "app/tools.py")
    write(repo, {"app/core.py": "from app.tools import helper\n"})
    extract(repo)
    g = graph(repo)
    old = {"file:app/util.py", "module:app.util", "function:app.util.helper"}
    new = {"file:app/tools.py", "module:app.tools", "function:app.tools.helper"}
    assert not old & set(g)
    assert new <= set(g)
    assert g.has_edge("module:app.core", "module:app.tools", key="imports")


def test_deleted_file(repo):
    extract(repo)
    (repo / "tests/test_core.py").unlink()
    extract(repo)
    g = graph(repo)
    assert not [n for n in g if "test_core" in n]
    assert not [e for e in g.edges(keys=True) if e[2] == "tests"]


def test_syntax_error_keeps_the_previous_elements_until_fixed(repo, capsys):
    extract(repo)
    good = (repo / "app/util.py").read_text(encoding="utf-8")
    write(repo, {"app/util.py": "def helper(:\n"})
    capsys.readouterr()
    extract(repo)
    out = capsys.readouterr().out
    assert "kept" in out and "skipped files" in out
    g = graph(repo)
    assert {"function:app.util.helper", "function:app.util.old"} <= set(g)
    # The broken file still counts as modified for `kg status`
    assert staleness(g, repo).modified == ["app/util.py"]

    write(repo, {"app/util.py": good.replace("def old", "def renamed")})
    extract(repo)
    g = graph(repo)
    assert "function:app.util.old" not in g
    assert "function:app.util.renamed" in g
    assert not staleness(g, repo).stale


def test_failed_extraction_leaves_the_store_unchanged(repo, monkeypatch):
    extract(repo)
    before = text(repo)
    write(repo, {"app/util.py": "def helper():\n    return 1\n"})

    def boom(root):
        raise RuntimeError("extractor crashed")

    monkeypatch.setattr("kg.extract.extract_repo", boom)
    assert extract(repo) == EXIT_INTERNAL
    assert text(repo) == before


def test_invalid_extraction_leaves_the_store_unchanged(repo):
    extract(repo)
    before = text(repo)
    extraction = extract_repo(repo)
    extraction.document["edges"].append(
        {
            "source": "module:app.core",
            "target": "module:missing",
            "type": "imports",
            "provenance": extraction.document["edges"][0]["provenance"],
        }
    )
    result = update_store(repo / ".kg", extraction)
    assert result.merge is None
    assert text(repo) == before


def test_dry_run_reports_without_saving(repo, capsys):
    extract(repo)
    before = text(repo)
    write(repo, {"app/util.py": "def helper():\n    return 1\n"})
    capsys.readouterr()
    assert extract(repo, "--dry-run", "--json") == EXIT_OK
    result = json.loads(capsys.readouterr().out)["result"]
    assert result["dry_run"] is True
    assert result["changed"] is True
    assert "function:app.util.old" in result["removed"]["nodes"]
    assert text(repo) == before


def test_digest_changes_are_not_conflicts(repo, capsys):
    extract(repo)
    write(repo, {"app/__init__.py": "# package\n"})
    capsys.readouterr()
    extract(repo, "--json")
    result = json.loads(capsys.readouterr().out)["result"]
    assert "file:app/__init__.py" in result["nodes"]["merged"]
    assert not [c for c in result["conflicts"] if c["field"] == "attrs.digest"]


# --- What is never removed ------------------------------------------------------


def test_other_extractors_and_manual_data_are_kept(repo):
    extract(repo)
    g = graph(repo)
    foreign = {"method": "parser", "extractor": "js-parser@1", "confidence": 1.0}
    manual = {"method": "manual", "extractor": "me", "confidence": 1.0}
    g.add_node("module:web.app", type="Module", provenance=foreign)
    g.add_node("concept:x", type="Concept", provenance=manual)
    store.save_graph(g, repo / ".kg")
    extract(repo)
    assert {"module:web.app", "concept:x"} <= set(graph(repo))


def test_store_with_another_repo_removes_nothing(repo, tmp_path, capsys):
    other = tmp_path / "other"
    write(other, {"lib.py": "def f():\n    pass\n"})
    main(["extract", str(other), "--kg-dir", str(repo / ".kg")])
    capsys.readouterr()
    extract(repo)
    out = capsys.readouterr().out
    assert "also holds the extraction of repo:other" in out
    assert "function:lib.f" in graph(repo)


def test_prune_keeps_elements_of_skipped_files():
    prov = {"method": "parser", "extractor": "python-ast@0.1", "confidence": 1.0}
    g = store.document_to_graph(
        {
            "version": "1",
            "nodes": [
                {"id": "repo:r", "type": "Repo", "provenance": prov | {"source": "."}},
                {
                    "id": "function:a.f",
                    "type": "Function",
                    "provenance": prov | {"source": "a.py"},
                },
                {
                    "id": "function:b.g",
                    "type": "Function",
                    "provenance": prov | {"source": "b.py"},
                },
            ],
            "edges": [],
        }
    )
    document = {"version": "1", "nodes": [{"id": "repo:r"}], "edges": []}
    pruned, report = prune(g, document, skipped={"a.py"})
    assert set(pruned) == {"repo:r", "function:a.f"}
    assert report.nodes == ["function:b.g"]
    assert report.kept_skipped == ["function:a.f"]


@pytest.mark.parametrize(
    ("provenance", "derived"),
    [
        ({"method": "parser", "extractor": "python-ast@0.1"}, True),
        ({"method": "parser", "extractor": "pyproject@0.2"}, True),
        ({"method": "parser", "extractor": "requirements@0.1"}, True),
        ({"method": "parser", "extractor": "js-parser@1"}, False),
        ({"method": "llm", "extractor": "python-ast@0.1"}, False),
        ({}, False),
    ],
)
def test_is_derived(provenance, derived):
    assert is_derived({"provenance": provenance}) is derived


# --- kg status (RF-77) -----------------------------------------------------------


def status(root, *extra):
    return main(["status", str(root), "--kg-dir", str(root / ".kg"), *extra])


def test_status_up_to_date(repo, capsys):
    extract(repo)
    capsys.readouterr()
    assert status(repo) == EXIT_OK
    out = capsys.readouterr().out
    assert "up to date" in out
    assert "parser" in out


def test_status_lists_modified_added_and_deleted_files(repo, capsys):
    write(repo, {"pyproject.toml": '[project]\nname = "demo"\n'})
    extract(repo)
    write(repo, {"app/core.py": "x = 2\n", "app/new.py": "", "pyproject.toml": "\n"})
    (repo / "app/util.py").unlink()
    capsys.readouterr()
    assert status(repo, "--json") == EXIT_OK
    result = json.loads(capsys.readouterr().out)["result"]
    assert result["stale"] is True
    assert result["modified"] == ["app/core.py", "pyproject.toml"]
    assert result["added"] == ["app/new.py"]
    assert result["deleted"] == ["app/util.py"]
    assert result["methods"] == {"parser": result["nodes"]}


def test_status_of_a_store_without_digests(repo, capsys):
    extract(repo)
    g = graph(repo)
    for _, data in g.nodes(data=True):
        data.pop("attrs", None)
    store.save_graph(g, repo / ".kg")
    capsys.readouterr()
    status(repo)
    out = capsys.readouterr().out
    assert "unknown" in out
    assert "run `kg extract" in out


def test_status_of_another_repo_is_a_usage_error(repo, tmp_path, capsys):
    extract(repo)
    other = tmp_path / "other"
    other.mkdir()
    capsys.readouterr()
    assert main(["status", str(other), "--kg-dir", str(repo / ".kg")]) == EXIT_USAGE
    assert "the store holds repo:demo, not repo:other" in capsys.readouterr().err


def test_status_of_an_empty_store(repo, capsys):
    assert status(repo) == EXIT_OK
    assert "added" in capsys.readouterr().out
