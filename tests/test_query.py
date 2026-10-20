import json

import pytest

from kg import analysis, store
from kg.cli import EXIT_OK, EXIT_USAGE, main
from kg.extract import extract_repo
from kg.update import update_store

PARSER = {"method": "parser", "extractor": "python-ast@0.1", "confidence": 1.0}
LLM = {"method": "llm", "extractor": "claude-code", "confidence": 0.7}


def graph_of(nodes, edges):
    return store.document_to_graph(
        {
            "version": "1",
            "nodes": [
                {"id": i, "type": t, "provenance": dict(PARSER), **extra}
                for i, t, extra in nodes
            ],
            "edges": [
                {"source": s, "target": d, "type": r, "provenance": dict(prov)}
                for s, d, r, prov in edges
            ],
        }
    )


@pytest.fixture
def graph():
    """app.core imports app.util; util defines helper and Box.size; a test,
    a document, a decision and a custom relation point at them."""
    return graph_of(
        [
            ("repo:demo", "Repo", {}),
            ("file:app/core.py", "File", {"attrs": {"digest": "sha256:1"}}),
            ("file:app/util.py", "File", {"attrs": {"digest": "sha256:2"}}),
            ("module:app.core", "Module", {"label": "core"}),
            (
                "module:app.util",
                "Module",
                {"label": "util", "description": "Small helpers for sizes."},
            ),
            ("function:app.util.helper", "Function", {"attrs": {"public": True}}),
            ("function:app.util._hidden", "Function", {"attrs": {"public": False}}),
            ("class:app.util.Box", "Class", {"attrs": {"public": True}}),
            ("function:app.util.Box.size", "Function", {"attrs": {"public": True}}),
            (
                "test:tests.test_util.test_helper",
                "Test",
                {"attrs": {"kind": "function"}},
            ),
            ("document:README.md", "Document", {}),
            ("decision:keep-it-small", "Decision", {}),
            ("requirement:fast", "Requirement", {}),
        ],
        [
            ("repo:demo", "file:app/core.py", "contains", PARSER),
            ("repo:demo", "file:app/util.py", "contains", PARSER),
            ("file:app/core.py", "module:app.core", "defines", PARSER),
            ("file:app/util.py", "module:app.util", "defines", PARSER),
            ("file:app/util.py", "function:app.util.helper", "defines", PARSER),
            ("file:app/util.py", "function:app.util._hidden", "defines", PARSER),
            ("file:app/util.py", "class:app.util.Box", "defines", PARSER),
            ("class:app.util.Box", "function:app.util.Box.size", "defines", PARSER),
            ("module:app.core", "module:app.util", "imports", PARSER),
            (
                "test:tests.test_util.test_helper",
                "function:app.util.helper",
                "tests",
                PARSER,
            ),
            ("document:README.md", "module:app.core", "documents", LLM),
            ("decision:keep-it-small", "module:app.core", "justifies", LLM),
            ("requirement:fast", "module:app.util", "affects", LLM),
        ],
    )


def ids(hits):
    return [h.id for h in hits]


# --- find ------------------------------------------------------------------------


def test_find_ranks_names_ids_then_descriptions(graph):
    found = analysis.find(graph, "util")
    assert found[0] == "module:app.util"  # exact label first
    assert found[1:3] == ["class:app.util.Box", "file:app/util.py"]  # ties by ID
    assert analysis.find(graph, "sizes") == ["module:app.util"]  # description only
    assert analysis.find(graph, "nothing") == []


def test_find_by_type_and_attribute(graph):
    assert analysis.find(graph, types=["Class"]) == ["class:app.util.Box"]
    found = analysis.find(graph, types=["Function"], attrs={"public": False})
    assert found == ["function:app.util._hidden"]


# --- neighbors ---------------------------------------------------------------------


def test_neighbors_in_both_directions(graph):
    hits = analysis.neighbors(graph, "module:app.core")
    assert ids(hits) == [
        "decision:keep-it-small",
        "document:README.md",
        "file:app/core.py",
        "module:app.util",
    ]
    assert all(h.depth == 1 for h in hits)


def test_neighbors_filtered_by_direction_relation_and_type(graph):
    out = analysis.neighbors(graph, "module:app.core", direction="out")
    assert ids(out) == ["module:app.util"]
    documents = analysis.neighbors(graph, "module:app.core", relations=["documents"])
    assert ids(documents) == ["document:README.md"]
    two = analysis.neighbors(graph, "module:app.core", depth=2, types=["Function"])
    assert ids(two) == []  # functions are 3 edges away
    three = analysis.neighbors(graph, "module:app.core", depth=3, types=["Function"])
    assert "function:app.util.helper" in ids(three)
    assert {h.depth for h in three} == {3}


# --- paths -------------------------------------------------------------------------


def test_path_prefers_the_direction_of_the_edges(graph):
    direction, steps = analysis.shortest_path(
        graph, "document:README.md", "module:app.util"
    )
    assert direction == "forward"
    assert [s.label for s in steps] == [
        "document:README.md -[documents]-> module:app.core",
        "module:app.core -[imports]-> module:app.util",
    ]
    direction, _ = analysis.shortest_path(
        graph, "module:app.util", "document:README.md"
    )
    assert direction == "backward"
    direction, steps = analysis.shortest_path(
        graph, "test:tests.test_util.test_helper", "class:app.util.Box"
    )
    assert direction == "mixed"
    assert len(steps) == 3


def test_path_with_relations_or_none(graph):
    assert (
        analysis.shortest_path(
            graph, "module:app.core", "function:app.util.helper", relations=["imports"]
        )
        is None
    )
    assert analysis.shortest_path(graph, "module:app.core", "module:app.core") == (
        "forward",
        [],
    )


def test_unknown_id_suggests_the_closest(graph):
    with pytest.raises(analysis.QueryError) as exc:
        analysis.impact(graph, "module:app.utl")
    assert exc.value.suggestion == 'Did you mean "module:app.util"?'


# --- impact ------------------------------------------------------------------------


def test_impact_through_the_defining_module(graph):
    hits = analysis.impact(graph, "function:app.util.helper")
    assert [(h.id, h.depth) for h in hits] == [
        ("module:app.util", 1),
        ("test:tests.test_util.test_helper", 1),
        ("module:app.core", 2),
        ("decision:keep-it-small", 3),
        ("document:README.md", 3),
    ]
    core = hits[2]
    assert [s.label for s in core.path] == [
        "file:app/util.py -[defines]-> function:app.util.helper",
        "file:app/util.py -[defines]-> module:app.util",
        "module:app.core -[imports]-> module:app.util",
    ]
    readme = hits[4]
    assert readme.confidence == 0.7  # the weakest link
    assert readme.methods == ["llm", "parser"]


def test_impact_of_a_method_reaches_its_class_then_its_module(graph):
    hits = analysis.impact(graph, "function:app.util.Box.size", depth=2)
    assert [(h.id, h.depth) for h in hits] == [
        ("class:app.util.Box", 1),
        ("module:app.util", 2),
    ]


def test_impact_options(graph):
    no_containment = analysis.impact(
        graph, "function:app.util.helper", containment=False
    )
    assert ids(no_containment) == ["test:tests.test_util.test_helper"]
    assert ids(analysis.impact(graph, "module:app.util", depth=1)) == [
        "module:app.core"
    ]
    # Custom relations only propagate when asked for
    assert "requirement:fast" not in ids(analysis.impact(graph, "module:app.util"))
    custom = analysis.impact(graph, "module:app.util", relations=["affects"])
    assert ids(custom) == ["requirement:fast"]


def test_impact_types_filter_the_results_not_the_walk(graph):
    hits = analysis.impact(graph, "function:app.util.helper", types=["Module"])
    assert [(h.id, h.depth) for h in hits] == [
        ("module:app.util", 1),
        ("module:app.core", 2),
    ]
    assert len(hits[1].path) == 3  # the path is kept
    # A Document is reached through modules that are not listed
    docs = analysis.impact(graph, "function:app.util.helper", types=["Document"])
    assert ids(docs) == ["document:README.md"]


def test_impact_never_returns_repo_or_file_nodes(graph):
    hits = analysis.impact(graph, "module:app.util", relations=["contains", "defines"])
    assert not [h for h in hits if h.type in ("Repo", "File")]


def test_impact_is_deterministic(graph):
    first = [h.to_dict() for h in analysis.impact(graph, "function:app.util.helper")]
    reordered = store.document_to_graph(
        {
            **store.graph_to_document(graph),
            "edges": list(reversed(store.graph_to_document(graph)["edges"])),
        }
    )
    second = [
        h.to_dict() for h in analysis.impact(reordered, "function:app.util.helper")
    ]
    assert first == second


# --- Predefined queries and limits --------------------------------------------------


def test_tested_and_untested_partition_the_code(graph):
    assert analysis.tested(graph) == {
        "function:app.util.helper": ["test:tests.test_util.test_helper"]
    }
    every = analysis.coverage(graph)
    untested = analysis.untested(graph)
    assert set(untested) | set(analysis.tested(graph)) == set(every)
    assert not set(untested) & set(analysis.tested(graph))
    assert "function:app.util._hidden" not in every
    assert "function:app.util._hidden" in analysis.coverage(graph, include_private=True)


def test_undocumented(graph):
    assert analysis.undocumented(graph, ["Module"]) == ["module:app.util"]
    assert "function:app.util._hidden" not in analysis.undocumented(graph)
    assert "function:app.util._hidden" in analysis.undocumented(
        graph, include_private=True
    )


def test_coverage_limits(graph):
    assert analysis.missing_relations(graph, ["imports", "calls"]) == ["calls"]
    assert analysis.unread_files(graph) == []
    del graph.nodes["file:app/core.py"]["attrs"]
    assert analysis.unread_files(graph) == ["app/core.py"]


# --- CLI on a real repo --------------------------------------------------------------


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "demo"
    (root / "app").mkdir(parents=True)
    (root / "app/__init__.py").write_text("")
    (root / "app/core.py").write_text(
        "from app.util import helper\n\n\ndef run():\n    return helper()\n"
    )
    (root / "app/util.py").write_text("def helper():\n    return 1\n")
    store.init_store(root / ".kg")
    update_store(root / ".kg", extract_repo(root))
    return root


def run(repo, capsys, *argv):
    capsys.readouterr()
    code = main(["--json", *argv, "--kg-dir", str(repo / ".kg")])
    return code, json.loads(capsys.readouterr().out)


def test_cli_impact_json(repo, capsys):
    code, out = run(repo, capsys, "impact", "function:app.util.helper")
    assert code == EXIT_OK
    result = out["result"]
    assert [(r["id"], r["depth"], r["direct"]) for r in result["results"]] == [
        ("module:app.util", 1, True),
        ("module:app.core", 2, False),
    ]
    assert set(result["results"][0]) == {
        "id",
        "type",
        "label",
        "depth",
        "direct",
        "confidence",
        "methods",
        "path",
    }
    codes = [limit["code"] for limit in result["limits"]]
    assert codes == ["missing_relations"]  # up to date, every file read


def test_cli_text_says_may_affect_and_shows_paths(repo, capsys):
    capsys.readouterr()
    main(["impact", "function:app.util.helper", "--kg-dir", str(repo / ".kg")])
    out = capsys.readouterr().out
    assert "may affect 2 elements" in out
    assert "module:app.core -[imports]-> module:app.util  [parser, 1]" in out


def test_cli_impact_with_no_result(repo, capsys):
    capsys.readouterr()
    main(["impact", "module:app.core", "--kg-dir", str(repo / ".kg")])
    assert "no relation found in the graph" in capsys.readouterr().out


def test_cli_reports_a_stale_graph(repo, capsys):
    (repo / "app/util.py").write_text("def helper():\n    return 2\n")
    _, out = run(repo, capsys, "query", "node", "module:app.util")
    [stale] = [x for x in out["result"]["limits"] if x["code"] == "stale_graph"]
    assert stale["files"] == ["app/util.py"]


def test_cli_store_outside_its_repo(repo, tmp_path, capsys):
    elsewhere = tmp_path / "elsewhere" / ".kg"
    elsewhere.parent.mkdir()
    store.init_store(elsewhere)
    update_store(elsewhere, extract_repo(repo))
    capsys.readouterr()
    main(["--json", "query", "untested", "--kg-dir", str(elsewhere)])
    limits = json.loads(capsys.readouterr().out)["result"]["limits"]
    assert "freshness_unknown" in [x["code"] for x in limits]


def test_cli_query_node_find_and_path(repo, capsys):
    code, out = run(
        repo, capsys, "query", "node", "module:app.core", "--direction", "out"
    )
    assert code == EXIT_OK
    assert out["result"]["node"]["type"] == "Module"
    assert [n["id"] for n in out["result"]["neighbors"]] == ["module:app.util"]

    _, out = run(repo, capsys, "query", "find", "help", "--type", "Function")
    assert [n["id"] for n in out["result"]["nodes"]] == ["function:app.util.helper"]

    _, out = run(repo, capsys, "query", "path", "module:app.core", "module:app.util")
    assert out["result"]["direction"] == "forward"
    assert len(out["result"]["path"]) == 1


def test_cli_untested_and_undocumented(repo, capsys):
    _, out = run(repo, capsys, "query", "untested")
    assert [n["id"] for n in out["result"]["nodes"]] == [
        "function:app.core.run",
        "function:app.util.helper",
    ]
    _, out = run(repo, capsys, "query", "undocumented", "--type", "Package")
    assert [n["id"] for n in out["result"]["nodes"]] == ["package:app"]


def test_cli_impact_type_filter_reports_what_it_left_out(repo, capsys):
    _, out = run(
        repo, capsys, "impact", "function:app.util.helper", "--type", "Package"
    )
    result = out["result"]
    assert result["results"] == []
    assert result["types"] == ["Package"]
    assert result["omitted"] == {"Module": 2}
    _, out = run(repo, capsys, "impact", "function:app.util.helper")
    assert out["result"]["omitted"] == {} and out["result"]["types"] is None
    capsys.readouterr()
    main(
        [
            "impact",
            "function:app.util.helper",
            "--type",
            "Package",
            "--kg-dir",
            str(repo / ".kg"),
        ]
    )
    assert "left out by --type: Module 2" in capsys.readouterr().out


def test_cli_tested_lists_the_tests_and_states_the_criterion(repo, capsys):
    (repo / "tests").mkdir()
    (repo / "tests/test_util.py").write_text(
        "from app.util import helper\n\n\ndef test_helper():\n    assert helper()\n"
    )
    update_store(repo / ".kg", extract_repo(repo))
    _, out = run(repo, capsys, "query", "tested", "--type", "Module,Function")
    nodes = {n["id"]: n["tests"] for n in out["result"]["nodes"]}
    assert nodes == {
        "function:app.util.helper": ["test:tests.test_util.test_helper"],
        "module:app.util": ["test:tests.test_util"],
    }
    assert "a test module imports it" in out["result"]["criterion"]
    _, out = run(repo, capsys, "query", "untested", "--type", "Module,Function")
    assert [n["id"] for n in out["result"]["nodes"]] == [
        "function:app.core.run",
        "module:app.core",
    ]
    assert out["result"]["criterion"]
    capsys.readouterr()
    main(["query", "tested", "--kg-dir", str(repo / ".kg")])
    text = capsys.readouterr().out
    assert "<-[tests]- test:tests.test_util.test_helper" in text
    assert "tested: a `tests` edge points to it" in text


def test_cli_query_node_depth_zero_is_the_node_alone(repo, capsys):
    code, out = run(repo, capsys, "query", "node", "module:app.core", "--depth", "0")
    assert code == EXIT_OK
    assert out["result"]["node"]["type"] == "Module"
    assert out["result"]["neighbors"] == []

    capsys.readouterr()
    args = ["query", "node", "module:app.core", "--depth", "0", "--brief"]
    main([*args, "--kg-dir", str(repo / ".kg")])
    text = capsys.readouterr().out
    assert text.startswith("module:app.core (Module)")
    assert "no neighbors" not in text


def test_cli_brief_node_is_a_card(repo, capsys):
    _, full = run(repo, capsys, "query", "node", "function:app.util.helper")
    _, brief = run(repo, capsys, "query", "node", "function:app.util.helper", "--brief")
    card = brief["result"]["node"]
    assert card["provenance"] == {
        "method": "parser",
        "source": "app/util.py",
        "lines": [1, 2],
    }
    assert card["attrs"]["signature"] == "()"
    assert brief["result"]["neighbors"] == ["<-[defines]- file:app/util.py"]
    assert brief["result"]["more"] == {}
    assert len(json.dumps(brief)) < len(json.dumps(full))
    capsys.readouterr()
    main(
        [
            "query",
            "node",
            "function:app.util.helper",
            "--brief",
            "--kg-dir",
            str(repo / ".kg"),
        ]
    )
    text = capsys.readouterr().out
    assert "at: app/util.py:1-2" in text and "[parser" not in text


def test_cli_brief_lists_are_capped_and_counted(repo, capsys, monkeypatch):
    import kg.cli

    monkeypatch.setattr(kg.cli, "BRIEF_LIMIT", 1)
    _, found = run(repo, capsys, "query", "find", "app", "--brief")
    assert len(found["result"]["nodes"]) == 1 and found["result"]["total"] > 1
    _, impact = run(repo, capsys, "impact", "function:app.util.helper", "--brief")
    result = impact["result"]
    assert result["total"] == 2 and len(result["results"]) == 1
    assert result["more"] == {"Module": 1}
    assert result["results"][0].startswith("module:app.util")
    _, path = run(
        repo, capsys, "query", "path", "module:app.core", "module:app.util", "--brief"
    )
    assert path["result"]["path"] == ["module:app.core -[imports]-> module:app.util"]


def test_cli_brief_marks_edges_that_are_not_the_parsers(repo, capsys, tmp_path):
    agent = tmp_path / "agent.json"
    agent.write_text(
        json.dumps(
            {
                "version": "1",
                "nodes": [
                    {
                        "id": "decision:keep",
                        "type": "Decision",
                        "description": "Keep it small.",
                        "provenance": {
                            "method": "llm",
                            "extractor": "t",
                            "confidence": 0.8,
                        },
                    }
                ],
                "edges": [
                    {
                        "source": "decision:keep",
                        "target": "module:app.util",
                        "type": "justifies",
                        "provenance": {
                            "method": "llm",
                            "extractor": "t",
                            "confidence": 0.8,
                        },
                    }
                ],
            }
        )
    )
    main(["add", str(agent), "--kg-dir", str(repo / ".kg")])
    _, out = run(repo, capsys, "query", "node", "module:app.util", "--brief")
    assert "<-[justifies]- decision:keep [llm, 0.8]" in out["result"]["neighbors"]
    _, card = run(repo, capsys, "query", "node", "decision:keep", "--brief")
    assert card["result"]["node"]["provenance"] == {"method": "llm", "confidence": 0.8}


@pytest.mark.parametrize(
    "argv",
    [
        ["impact", "function:app.util.helpr"],
        ["query", "node", "module:app.cor"],
        ["query", "path", "module:app.core", "nope"],
    ],
)
def test_cli_unknown_ids_are_usage_errors(repo, capsys, argv):
    code, out = run(repo, capsys, *argv)
    assert code == EXIT_USAGE
    assert out["error"]["details"]["suggestion"]


@pytest.mark.parametrize(
    "argv",
    [
        ["query"],
        ["query", "find"],
        ["impact", "x", "--depth", "0"],
        ["query", "node", "module:app.core", "--depth", "-1"],
    ],
)
def test_cli_usage_errors(repo, capsys, argv):
    assert main([*argv, "--kg-dir", str(repo / ".kg")]) == EXIT_USAGE
