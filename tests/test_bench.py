"""The benchmark harness (bench/), without calling any model."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from bench import report
from bench.agent import run_question
from bench.grading import grade, normalize, traceability, verifiable
from bench.run import ROOT, load_questions, load_repos
from bench.tools import TOOLS, ToolError, run_tool
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


# --- Report -----------------------------------------------------------------------


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


def test_reference_answers_score_full_marks():
    """The reference answers themselves pass the grader (a sanity check)."""
    for q in load_questions(ROOT / "questions/pilot.json"):
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
