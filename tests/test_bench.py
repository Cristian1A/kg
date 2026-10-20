"""The benchmark harness (bench/), without calling any model."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from bench import report, subagent
from bench.agent import run_question
from bench.grading import grade, normalize, traceability, verifiable
from bench.run import ROOT, load_questions, load_repos
from bench.tools import STRATEGY_HINTS, TOOLS, Citations, ToolError, run_tool
from bench.topics import TOPIC_TYPES, build_topic_stores, topic_graph
from kg import store
from kg.extract import extract_repo
from kg.update import update_store


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "demo"
    (root / "app").mkdir(parents=True)
    (root / "app/__init__.py").write_text("")
    (root / "app/core.py").write_text("import requests\n\n\ndef run():\n    return 1\n")
    (root / "README.md").write_text("# Demo\n")
    store.init_store(root / ".kg")
    update_store(root / ".kg", extract_repo(root))
    return root


# --- Questions --------------------------------------------------------------------


@pytest.mark.parametrize("path", sorted((ROOT / "questions").glob("*.json")))
def test_question_files_are_consistent(path):
    questions = load_questions(path)
    assert questions
    assert {q["topic"] for q in questions} <= {
        "development",
        "tests",
        "documentation",
        "decisions",
    }
    for q in questions:
        assert q["reference"], q["id"]  # a human-readable reference answer


def test_question_categories_are_checked(tmp_path, monkeypatch):
    path = tmp_path / "q.json"
    base = {
        "id": "q1",
        "repo": "kg",
        "topic": "tests",
        "question": "?",
        "expect": {"items": []},
        "reference": "None.",
    }
    path.write_text(json.dumps([{**base, "category": "multi-hop"}]))
    assert load_questions(path)[0]["category"] == "multi-hop"
    path.write_text(json.dumps([base]))  # the category is optional
    assert load_questions(path)
    path.write_text(json.dumps([{**base, "category": "trivia"}]))
    with pytest.raises(SystemExit, match="unknown category"):
        load_questions(path)


def test_repos_are_pinned_to_a_commit():
    for repo in load_repos():
        assert len(repo["commit"]) >= 7
        assert (ROOT.parent / repo["agent"]).is_file()


# --- Grading ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "kind", "expected"),
    [
        ("etl/utils.py", "module", "etl.utils"),
        ("module:etl.utils", "module", "etl.utils"),
        ("`etl.utils`", "module", "etl.utils"),
        ("app/__init__.py", "module", "app"),
        ("azure-storage-blob", "package", "azure"),
        ("azure.identity", "package", "azure"),
        ("psycopg2-binary", "package", "psycopg2"),
        ("dependency:requests", "package", "requests"),
        ("requests>=2", "package", "requests"),
        ("config:.github/workflows/ci.yml", "file", "ci.yml"),
        ("docs/store.md:12", "file", "store.md"),
    ],
)
def test_normalize(name, kind, expected):
    assert normalize(name, kind) == expected


def test_grade_items_with_precision_and_recall():
    expect = {"items": ["a.b", "a.c"], "normalize": "module"}
    perfect = grade(expect, {"items": ["a/b.py", "module:a.c"]})
    assert perfect.score == 1.0
    partial = grade(expect, {"items": ["a.b", "a.x"]})
    assert (partial.precision, partial.recall) == (0.5, 0.5)
    assert partial.missing == ("a.c",) and partial.extra == ("a.x",)
    assert grade(expect, None).score == 0.0


def test_grade_an_expected_empty_list():
    expect = {"items": [], "normalize": "module"}
    assert grade(expect, {"items": []}).score == 1.0
    assert grade(expect, {"items": ["x"]}).score == 0.0


def test_grade_keywords():
    expect = {"keywords": [["clean architecture"], ["interactor", "use cases"]]}
    assert grade(expect, {"answer": "It follows Clean Architecture."}).score == 0.5
    full = grade(expect, {"answer": "Clean architecture", "items": ["src.interactor"]})
    assert full.score == 1.0


def test_traceability(repo):
    graph = store.load_graph(repo / ".kg")
    assert verifiable("app/core.py:4", repo, graph)
    assert verifiable("app/core.py:1-5", repo, graph)
    assert not verifiable("app/core.py:99", repo, graph)
    assert not verifiable("../outside.py", repo, graph)
    assert verifiable("module:app.core", repo, graph)
    assert verifiable("module:app.core -[imports]-> dependency:requests", repo, graph)
    assert not verifiable("module:app.core -[imports]-> module:nope", repo, graph)
    assert verifiable("module:app.core (the only importer)", repo, graph)
    assert verifiable("app/core.py:1 (import)", repo, graph)
    assert not verifiable("(module:app.core)", repo, graph)
    assert traceability(["app/core.py", "made/up.py"], repo, graph) == 0.5
    assert traceability([], repo, graph) is None


# --- Tools ------------------------------------------------------------------------


def test_code_tools(repo):
    assert run_tool("code", repo, "list_files", {"glob": "app/*.py"}) == (
        "app/__init__.py\napp/core.py"
    )
    read = run_tool(
        "code",
        repo,
        "read_file",
        {"path": "app/core.py", "start_line": 4, "end_line": None},
    )
    assert read.splitlines()[0].strip() == "4  def run():"
    found = run_tool("code", repo, "search", {"pattern": r"^import", "glob": "**/*.py"})
    assert found == "app/core.py:1: import requests"


@pytest.mark.parametrize("path", ["../secret", ".kg/graph.json", "/etc/passwd"])
def test_code_tools_stay_inside_the_repo(repo, path):
    with pytest.raises(ToolError):
        run_tool(
            "code",
            repo,
            "read_file",
            {"path": path, "start_line": None, "end_line": None},
        )


def test_graph_tool_runs_read_only_kg_commands(repo):
    out = json.loads(run_tool("graph", repo, "kg", {"args": ["query", "find", "core"]}))
    assert out["result"]["nodes"][0]["id"] == "module:app.core"
    status = json.loads(run_tool("graph", repo, "kg", {"args": ["status"]}))
    assert status["result"]["stale"] is False
    for args in (["add", "x.json"], ["query", "node", "x", "--kg-dir", "/tmp"], []):
        with pytest.raises(ToolError):
            run_tool("graph", repo, "kg", {"args": args})


def test_strategies_cannot_use_each_others_tools(repo):
    with pytest.raises(ToolError):
        run_tool("graph", repo, "read_file", {"path": "README.md"})
    assert [t["name"] for t in TOOLS["graph"]] == ["kg", "submit_answer"]


def test_tool_schemas_are_strict():
    for tools in TOOLS.values():
        for tool in tools:
            schema = tool["input_schema"]
            assert tool["strict"] and schema["additionalProperties"] is False
            assert set(schema["required"]) == set(schema["properties"])


# --- Agent loop, with a fake client --------------------------------------------------


def block(type_, **fields):
    return SimpleNamespace(type=type_, **fields)


def response(*content, stop_reason="tool_use", tokens=(100, 10)):
    usage = SimpleNamespace(
        input_tokens=tokens[0],
        output_tokens=tokens[1],
        cache_creation_input_tokens=0,
        cache_read_input_tokens=50,
    )
    return SimpleNamespace(content=list(content), stop_reason=stop_reason, usage=usage)


class FakeClient:
    """Replays canned responses and records every request."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []
        self.messages = self

    def create(self, **kwargs):
        self.requests.append(json.loads(json.dumps(kwargs, default=vars)))
        return self.responses.pop(0)


QUESTION = {"id": "q", "repo": "demo", "question": "Which modules import requests?"}


def test_agent_loop_runs_tools_and_records_usage(repo):
    client = FakeClient(
        response(
            block(
                "tool_use",
                id="t1",
                name="search",
                input={"pattern": "requests", "glob": "*"},
            )
        ),
        response(
            block(
                "tool_use",
                id="t2",
                name="submit_answer",
                input={
                    "answer": "app.core",
                    "items": ["app.core"],
                    "evidence": ["app/core.py:1"],
                },
            )
        ),
    )
    run = run_question(client, QUESTION, "code", repo, "claude-opus-5-5", "medium")
    assert run.outcome == "answered"
    assert run.answer["items"] == ["app.core"]
    assert (run.turns, run.tool_calls, run.tool_errors) == (2, 1, 0)
    assert run.usage.input_tokens == 200 and run.usage.cache_read_input_tokens == 100
    # The second request carries the tool result, after the assistant's turn
    last = client.requests[1]["messages"]
    assert [m["role"] for m in last] == ["user", "assistant", "user"]
    assert last[2]["content"][0]["content"] == "app/core.py:1: import requests"
    first = client.requests[0]
    assert first["model"] == "claude-opus-5-5"
    assert first["output_config"] == {"effort": "medium"}
    assert "line numbers" in first["system"]  # the code strategy's hint
    assert "cannot read the files" not in first["system"]  # not the graph's


def test_agent_loop_reports_tool_errors_to_the_model(repo):
    client = FakeClient(
        response(block("tool_use", id="t1", name="kg", input={"args": ["add", "x"]})),
        response(
            block(
                "tool_use",
                id="t2",
                name="submit_answer",
                input={"answer": "", "items": [], "evidence": []},
            )
        ),
    )
    run = run_question(client, QUESTION, "graph", repo, "m", "low")
    assert run.tool_errors == 1
    result = client.requests[1]["messages"][2]["content"][0]
    assert result["is_error"] is True


@pytest.mark.parametrize(
    ("responses", "outcome"),
    [
        ([response(block("text", text="no"), stop_reason="refusal")], "refusal"),
        ([response(block("text", text="..."), stop_reason="max_tokens")], "max_tokens"),
        (
            [
                response(
                    block("tool_use", id=str(i), name="list_files", input={"glob": "*"})
                )
                for i in range(3)
            ],
            "max_turns",
        ),
    ],
)
def test_agent_loop_outcomes(repo, responses, outcome):
    run = run_question(
        FakeClient(*responses), QUESTION, "code", repo, "m", "low", max_turns=3
    )
    assert run.outcome == outcome
    assert run.answer is None


def test_agent_is_reminded_to_submit(repo):
    client = FakeClient(
        response(block("text", text="It is app.core."), stop_reason="end_turn"),
        response(
            block(
                "tool_use",
                id="t",
                name="submit_answer",
                input={"answer": "a", "items": [], "evidence": []},
            )
        ),
    )
    run = run_question(client, QUESTION, "code", repo, "m", "low")
    assert run.outcome == "answered"
    assert "submit_answer" in client.requests[1]["messages"][-1]["content"]


# --- Topic stores -----------------------------------------------------------------


def test_topic_graphs_keep_their_types_and_what_freshness_needs(repo):
    graph = store.load_graph(repo / ".kg")
    for topic in TOPIC_TYPES:
        sub = topic_graph(graph, topic)
        types = {d["type"] for _, d in sub.nodes(data=True)}
        assert {"Repo", "File"} <= types
        assert types <= {"Repo", "File", "Config", *TOPIC_TYPES[topic]}
        for u, v in sub.edges():
            assert graph.has_edge(u, v)
    assert "dependency:requests" in topic_graph(graph, "development")
    assert "dependency:requests" not in topic_graph(graph, "tests")


def test_topic_strategy_queries_its_topic_store(repo):
    build_topic_stores(repo)
    tests = json.loads(run_tool("topic", repo, "kg", {"args": ["status"]}, "tests"))
    assert tests["ok"] and tests["result"]["stale"] is False
    found = run_tool(
        "topic", repo, "kg", {"args": ["query", "find", "requests"]}, "tests"
    )
    assert json.loads(found)["result"]["nodes"] == []
    found = run_tool(
        "topic", repo, "kg", {"args": ["query", "find", "requests"]}, "development"
    )
    assert json.loads(found)["result"]["nodes"]
    # The code strategy never sees the stores
    listed = run_tool("code", repo, "list_files", {"glob": "**"})
    assert ".kg" not in listed
    with pytest.raises(ToolError):
        run_tool("code", repo, "read_file", {"path": ".kg-tests/graph.json"})


# --- Hybrid strategy --------------------------------------------------------------


def test_citations_come_from_provenance_not_node_ids():
    cited = Citations()
    cited.add_from(
        json.dumps(
            {
                "result": {
                    "node": {
                        "provenance": {
                            "method": "parser",
                            "source": "app/core.py",
                            "lines": [4, 5],
                        }
                    },
                    "path": [
                        {
                            "source": "module:app.core",
                            "target": "module:app.util",
                            "type": "imports",
                        }
                    ],
                    "neighbors": [
                        {"provenance": {"method": "parser", "source": "app/util.py"}}
                    ],
                }
            }
        )
    )
    cited.add_from("not json")
    assert cited.ranges == {"app/core.py": [[4, 5]], "app/util.py": None}
    assert cited.window("app/core.py", None, None) == (4, 5)
    assert cited.window("app/core.py", 4, 4) == (4, 4)
    assert cited.window("app/util.py", None, None) == (1, None)
    with pytest.raises(ToolError, match="lines 4-5"):
        cited.window("app/core.py", 1, 9)
    with pytest.raises(ToolError, match="not been cited"):
        cited.window("README.md", None, None)


def test_hybrid_reads_only_what_the_graph_cited(repo):
    cited = Citations()
    args = {"path": "app/core.py", "start_line": None, "end_line": None}
    with pytest.raises(ToolError, match="not been cited"):
        run_tool("hybrid", repo, "read_file", args, citations=cited)
    run_tool(
        "hybrid",
        repo,
        "kg",
        {"args": ["query", "node", "function:app.core.run"]},
        citations=cited,
    )
    assert cited.ranges["app/core.py"] == [[4, 5]]
    out = run_tool("hybrid", repo, "read_file", args, citations=cited)
    assert out.splitlines()[0].strip().startswith("4") and "return 1" in out
    assert "import requests" not in out  # line 1 was not cited
    with pytest.raises(ToolError):
        run_tool(
            "hybrid", repo, "search", {"pattern": "x", "glob": ""}, citations=cited
        )
    assert [t["name"] for t in TOOLS["hybrid"]] == ["kg", "read_file", "submit_answer"]


@pytest.mark.parametrize(
    "args",
    [["status"], ["query", "node", "function:app.core.run"]],
    ids=["status", "stale-limit"],
)
def test_hybrid_reads_the_files_a_stale_graph_reports(repo, args):
    (repo / "app/new.py").write_text("def added():\n    return 2\n")
    core = repo / "app/core.py"
    core.write_text(core.read_text() + "\n\ndef changed():\n    return 3\n")
    cited = Citations()
    read = {"path": "app/new.py", "start_line": None, "end_line": None}
    with pytest.raises(ToolError, match="not been cited"):
        run_tool("hybrid", repo, "read_file", read, citations=cited)
    run_tool("hybrid", repo, "kg", {"args": args}, citations=cited)
    # Added and modified files are read whole, even where a node cites lines
    assert cited.ranges["app/new.py"] is None and cited.ranges["app/core.py"] is None
    assert "return 2" in run_tool("hybrid", repo, "read_file", read, citations=cited)
    whole = {**read, "path": "app/core.py"}
    assert "return 3" in run_tool("hybrid", repo, "read_file", whole, citations=cited)


def test_cards_strategy_adds_brief_and_still_cites(repo):
    cited = Citations()
    out = run_tool(
        "cards",
        repo,
        "kg",
        {"args": ["query", "node", "function:app.core.run"]},
        citations=cited,
    )
    assert json.loads(out)["result"]["node"]["provenance"]["source"] == "app/core.py"
    assert cited.ranges["app/core.py"] == [[4, 5]]
    assert "return 1" in run_tool(
        "cards",
        repo,
        "read_file",
        {"path": "app/core.py", "start_line": None, "end_line": None},
        citations=cited,
    )
    status = json.loads(run_tool("cards", repo, "kg", {"args": ["status"]}))
    assert status["ok"]  # commands without --brief run as usual


def test_companion_has_the_code_tools_and_brief_kg(repo):
    names = [t["name"] for t in TOOLS["companion"]]
    assert names == ["list_files", "read_file", "search", "kg", "submit_answer"]
    out = run_tool(
        "companion", repo, "kg", {"args": ["query", "node", "function:app.core.run"]}
    )
    assert "neighbors" in json.loads(out)["result"]  # brief: a card, not a dump
    assert "at" not in json.loads(out)["result"]["node"]
    search = {"pattern": "return 1", "glob": "**/*.py"}
    assert "app/core.py:5" in run_tool("companion", repo, "search", search)
    read = {"path": "README.md", "start_line": None, "end_line": None}
    assert "# Demo" in run_tool("companion", repo, "read_file", read)  # uncited


def test_lean_is_code_with_the_companion_line(repo):
    assert TOOLS["lean"] == TOOLS["code"]
    line = "Use whichever gets the answer with fewer calls."
    assert line in STRATEGY_HINTS["companion"] and line in STRATEGY_HINTS["lean"]
    assert STRATEGY_HINTS["lean"].startswith(STRATEGY_HINTS["code"])
    search = {"pattern": "return 1", "glob": "**/*.py"}
    assert run_tool("lean", repo, "search", search) == run_tool(
        "code", repo, "search", search
    )
    with pytest.raises(ToolError):
        run_tool("lean", repo, "kg", {"args": ["status"]})


# --- Subagent runner --------------------------------------------------------------

SUB_QUESTION = {
    **QUESTION,
    "topic": "development",
    "expect": {"items": ["app.core"], "normalize": "module"},
    "reference": "Only app.core imports it.",
}


@pytest.fixture
def session(repo, tmp_path):
    runs = subagent.prepare_session(
        [SUB_QUESTION], ["code", "graph"], {"demo": repo}, tmp_path / "session"
    )
    return tmp_path / "session", {r.name: r for r in runs}


def test_subagent_prompt_names_only_the_strategy_tools(session):
    _, runs = session
    code = (runs["q.code"] / "prompt.md").read_text()
    graph = (runs["q.graph"] / "prompt.md").read_text()
    assert "`read_file`" in code and "`kg`" not in code
    assert "`kg`" in graph and "`read_file`" not in graph
    assert "Which modules import requests?" in code
    assert SUB_QUESTION["reference"] not in code  # the reference is not leaked
    assert "bench.subagent call" in code and str(runs["q.code"].name) in code


def test_subagent_call_runs_the_strategy_tools_and_logs_them(session):
    _, runs = session
    out = subagent.call(runs["q.code"], "search", '{"pattern": "requests", "glob": ""}')
    assert "app/core.py:1" in out
    out = subagent.call(runs["q.code"], "kg", '{"args": ["status"]}')
    assert out.startswith("Error:")  # a graph tool is not a code tool
    assert subagent.call(runs["q.code"], "read_file", "{oops").startswith("Error:")
    calls = (runs["q.code"] / "calls.jsonl").read_text().splitlines()
    assert [json.loads(c)["tool"] for c in calls] == ["search", "kg", "read_file"]
    assert sum("error" in json.loads(c) for c in calls) == 2


def test_subagent_submits_once_and_is_graded(session):
    root, runs = session
    answer = {
        "answer": "Only app.core.",
        "items": ["app/core.py"],
        "evidence": ["app/core.py:1"],
    }
    assert "submitted" in subagent.call(
        runs["q.code"], "submit_answer", json.dumps(answer)
    )
    again = subagent.call(runs["q.code"], "submit_answer", json.dumps(answer))
    assert "already submitted" in again
    bad = subagent.call(runs["q.graph"], "submit_answer", '{"answer": "x"}')
    assert bad.startswith("Error:")
    usage = {"q.code": {"total_tokens": 1234, "seconds": 9.5}}
    records = {
        r["strategy"]: r for r in subagent.collect(root, {"q": SUB_QUESTION}, usage)
    }
    code, graph = records["code"], records["graph"]
    assert code["outcome"] == "answered" and code["grade"]["score"] == 1.0
    assert code["traceability"] == 1.0 and code["usage"] == {"total_tokens": 1234}
    assert code["seconds"] == 9.5 and code["turns"] == 1 and code["tool_calls"] == 0
    assert graph["outcome"] == "no_answer" and graph["tool_errors"] == 1
    assert graph["usage"] == {"total_tokens": None}
    assert code["category"] is None  # SUB_QUESTION has no category


def test_subagent_records_context_and_replays_old_logs(repo, tmp_path):
    runs = subagent.prepare_session(
        [SUB_QUESTION], ["hybrid"], {"demo": repo}, tmp_path / "h"
    )
    run_dir = runs[0]
    blocked = subagent.call(
        run_dir,
        "read_file",
        '{"path": "app/core.py", "start_line": null, "end_line": null}',
    )
    assert blocked.startswith("Error:")
    node = subagent.call(
        run_dir, "kg", '{"args": ["query", "node", "function:app.core.run"]}'
    )
    read = subagent.call(
        run_dir,
        "read_file",
        '{"path": "app/core.py", "start_line": null, "end_line": null}',
    )
    assert "return 1" in read  # the citation survived between calls
    calls = [
        json.loads(line) for line in (run_dir / "calls.jsonl").read_text().splitlines()
    ]
    assert [c["chars"] for c in calls] == [len(blocked), len(node), len(read)]
    meta = json.loads((run_dir / "run.json").read_text())
    total = subagent.context_chars(meta, calls)
    assert total == len(blocked) + len(node) + len(read)
    # A log from before `chars` was recorded is replayed to the same total
    old = [{k: v for k, v in c.items() if k != "chars"} for c in calls]
    assert subagent.context_chars(meta, old) == total


def test_subagent_turns_are_capped(session, monkeypatch):
    _, runs = session
    monkeypatch.setattr(subagent, "MAX_TURNS", 2)
    for _ in range(2):
        subagent.call(runs["q.graph"], "kg", '{"args": ["status"]}')
    out = subagent.call(
        runs["q.graph"], "submit_answer", '{"answer": "", "items": [], "evidence": []}'
    )
    assert "limit" in out and not (runs["q.graph"] / "answer.json").exists()


def test_report_reads_subagent_records(tmp_path):
    rec = {
        "question": "q1",
        "topic": "tests",
        "strategy": "graph",
        "outcome": "answered",
        "grade": {"score": 1.0},
        "traceability": None,
        "usage": {"total_tokens": 5000},
        "turns": 3,
        "seconds": 20.0,
    }
    path = tmp_path / "r.jsonl"
    path.write_text(json.dumps(rec))
    text = report.markdown(report.load([path]))
    assert (
        "| q1 | tests | graph | answered | 1.00 | – | – | – | 5000 | – | 3 | 20.0 |"
        in text
    )
    assert "| graph | 1 | 1 | 1.00 | – | – | – | 5000 | – |" in text


# --- Report -----------------------------------------------------------------------


def _record(question, strategy, score, chars, category=None):
    return {
        "question": question,
        "topic": "development",
        "category": category,
        "strategy": strategy,
        "outcome": "answered",
        "grade": {"score": score},
        "traceability": 1.0,
        "usage": {"total_tokens": 1000},
        "context_chars": chars,
        "turns": 2,
        "seconds": 1.0,
    }


def test_report_by_category_and_repeated_runs(tmp_path):
    records = [
        _record("q1", "code", 1.0, 900, "multi-hop"),
        _record("q1", "code", 0.5, 1100, "multi-hop"),  # a repeated run
        _record("q1", "cards", 1.0, 300, "multi-hop"),
        _record("q2", "code", 0.0, 50, "uncertainty"),
        _record("q3", "code", 1.0, 10),  # no category: left out of that table
    ]
    rows = {(r["category"], r["strategy"]): r for r in report.by_category(records)}
    assert set(rows) == {
        ("multi-hop", "code"),
        ("multi-hop", "cards"),
        ("uncertainty", "code"),
    }
    assert rows["multi-hop", "code"]["runs"] == 2
    assert rows["multi-hop", "code"]["score"] == 0.75
    assert rows["multi-hop", "code"]["context_chars"] == 1000
    (spread,) = report.spread(records)
    assert spread["question"] == "q1" and spread["strategy"] == "code"
    assert spread["score"] == (0.5, 1.0) and spread["context_chars"] == (900, 1100)
    text = report.markdown(records)
    assert "| multi-hop | cards | 1 | 1.00 | 300 |" in text
    assert "| q1 | code | 2 | 0.50–1.00 | 900–1100 |" in text


def test_report_omits_empty_category_and_spread_tables():
    text = report.markdown([_record("q1", "code", 1.0, 10)])
    assert "Per category" not in text and "Repeated runs" not in text


def test_report_counts_the_runs_that_call_kg():
    records = [
        _record("q1", "companion", 1.0, 10) | {"calls": ["kg", "search", "kg"]},
        _record("q2", "companion", 1.0, 10)
        | {"calls": ["search", "read_file", "submit_answer"]},
        _record("q1", "cards", 1.0, 10) | {"calls": ["kg"]},  # no choice: left out
    ]
    (row,) = report.kg_use(records)
    assert row == {
        "strategy": "companion",
        "runs": 2,
        "with_kg": 1,
        "kg_calls": 2,
        "calls": 5,
    }
    assert "| companion | 2 | 1 | 2 | 5 |" in report.markdown(records)
    assert "Use of the graph" not in report.markdown(records[2:])


def test_report_separates_quality_and_cost(tmp_path):
    def record(strategy, score, tokens):
        return {
            "question": "q1",
            "topic": "development",
            "strategy": strategy,
            "outcome": "answered",
            "grade": {"score": score},
            "traceability": 1.0,
            "usage": {
                "input_tokens": tokens,
                "output_tokens": 10,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
            },
            "turns": 2,
            "seconds": 1.5,
        }

    path = tmp_path / "r.jsonl"
    path.write_text(
        "\n".join(
            json.dumps(r)
            for r in (record("code", 0.5, 1000), record("graph", 1.0, 300))
        )
    )
    rows = {r["strategy"]: r for r in report.summary(report.load([path]))}
    assert rows["graph"]["score"] == 1.0 and rows["graph"]["input_tokens"] == 300
    text = report.markdown(report.load([path]))
    assert "| graph | 1 | 1 | 1.00 |" in text
    assert "not to be statistically conclusive" in text


@pytest.mark.parametrize("path", sorted((ROOT / "questions").glob("*.json")))
def test_reference_answers_score_full_marks(path):
    """The reference answers themselves pass the grader (a sanity check)."""
    for q in load_questions(path):
        expect = q["expect"]
        if "items" in expect:
            answer = {"answer": q["reference"], "items": expect["items"]}
        else:
            answer = {"answer": " ".join(g[0] for g in expect["keywords"]), "items": []}
        assert grade(expect, answer).score == 1.0, q["id"]


def test_bench_does_not_need_the_sdk():
    # The harness imports anthropic lazily, only to call the model
    source = Path(ROOT / "agent.py").read_text() + Path(ROOT / "tools.py").read_text()
    assert "import anthropic" not in source
