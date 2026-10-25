"""Experiment 2's harness (bench/memory.py), without calling any model."""

import json
import subprocess

import pytest

from bench import memory
from bench.tools import ToolError

PROV = {"method": "manual", "extractor": "test", "confidence": 1.0}


def _session(n, commit, nodes=(), edges=()):
    sid = f"session:2026-10-0{n}-s{n}"
    session = {
        "id": sid,
        "type": "Session",
        "label": f"Session {n}",
        "description": f"Goal: work {n}",
        "attrs": {"date": f"2026-10-0{n}", "commit": commit, "order": n},
        "provenance": PROV,
    }
    return {"version": "1", "nodes": [session, *nodes], "edges": list(edges)}


def _memory(mid, label, body, session, status="active"):
    return {
        "id": mid,
        "type": mid.split(":")[0].capitalize(),
        "label": label,
        "description": body,
        "attrs": {"created": "2026-10-01", "session": session, "status": status},
        "provenance": PROV,
    }


@pytest.fixture
def corpus(tmp_path):
    root = tmp_path / "corpus"
    root.mkdir()
    first = _session(
        1,
        "aaaaaaa",
        [
            _memory(
                "decision:use-sqlite",
                "Use SQLite for the index",
                "What: SQLite with FTS5.",
                "session:2026-10-01-s1",
            ),
            _memory(
                "issue:slow-reads",
                "Reads are slow",
                "What: every read validates the store.",
                "session:2026-10-01-s1",
            ),
        ],
        [
            {
                "source": "session:2026-10-01-s1",
                "target": "decision:use-sqlite",
                "type": "produced",
                "provenance": PROV,
            }
        ],
    )
    second = _session(2, "bbbbbbb")
    second["nodes"].append(
        {
            "id": "issue:slow-reads",
            "type": "Issue",
            "attrs": {"status": "invalidated"},
            "provenance": PROV,
        }
    )
    (root / "01-a.json").write_text(json.dumps(first))
    (root / "02-b.json").write_text(json.dumps(second))
    return root


def test_snapshot_stops_at_the_pinned_session(corpus):
    assert [p.name for p in memory.snapshot("aaaaaaa", corpus)] == ["01-a.json"]
    assert len(memory.snapshot("bbbbbbb", corpus)) == 2
    with pytest.raises(ValueError):
        memory.snapshot("ccccccc", corpus)


def test_later_sessions_change_status(corpus):
    before = memory.load_memory(memory.snapshot("aaaaaaa", corpus))
    after = memory.load_memory(memory.snapshot("bbbbbbb", corpus))
    assert before.nodes["issue:slow-reads"]["attrs"]["status"] == "active"
    assert after.nodes["issue:slow-reads"]["attrs"]["status"] == "invalidated"
    text = memory.render(after, "issue:slow-reads")
    assert text.startswith("[issue:slow-reads] Issue · invalidated · 2026-10-01")
    assert memory.memories(after) == [
        "decision:use-sqlite",
        "issue:slow-reads",
        "session:2026-10-01-s1",
        "session:2026-10-02-s2",
    ]


def test_fts_query_quotes_words_like_engram():
    assert (
        memory.fts_query('why "SQLite" AND kg?')
        == '"why" OR "SQLite" OR "AND" OR "kg?"'
    )
    assert memory.fts_query('say "hi"there') == '"say" OR "hi""there"'
    assert memory.fts_query("   ") == ""


def test_fts_search_ranks_title_matches_first(corpus):
    graph = memory.load_memory(memory.snapshot("aaaaaaa", corpus))
    conn = memory.fts_index(graph)
    # "sqlite" is in one title and one body; "validates" in one body only
    assert memory.fts_search(conn, "Why SQLite?")[0] == "decision:use-sqlite"
    assert memory.fts_search(conn, "who validates the store")[0] == "issue:slow-reads"
    assert memory.fts_search(conn, "nothing matches this") == []
    assert memory.fts_search(conn, "") == []


def test_context_is_empty_for_s0_and_deterministic_for_s2(corpus):
    graph = memory.load_memory(memory.snapshot("aaaaaaa", corpus))
    assert memory.context("s0", "Why SQLite?", graph) == ""
    first = memory.context("s2", "Why SQLite?", graph)
    assert first == memory.context("s2", "Why SQLite?", graph)
    assert first.startswith("[decision:use-sqlite] Decision · active")
    with pytest.raises(ValueError):
        memory.context("s9", "?", graph)


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()

    def git(*args):
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "T")
    (root / "a.py").write_text("x = 1\n")
    git("add", ".")
    git("commit", "-qm", "feat: add a\n\nWhy: a test.")
    (root / "docs").mkdir()
    (root / "docs/b.md").write_text("# B\n")
    git("add", ".")
    git("commit", "-qm", "docs: add b")
    return root


def test_git_log_filters_by_message_and_path(repo):
    out = memory.git_log(repo, {"grep": None, "path": None, "max_count": None})
    assert "docs: add b" in out.splitlines()[0] and "Why: a test." in out
    only = memory.git_log(repo, {"grep": "FEAT", "path": None, "max_count": None})
    assert "feat: add a" in only and "docs: add b" not in only
    by_path = memory.git_log(repo, {"grep": None, "path": "docs", "max_count": 5})
    assert "docs: add b" in by_path and "feat" not in by_path
    none = memory.git_log(repo, {"grep": "nothing", "path": None, "max_count": 1})
    assert none == "no commits match"
    with pytest.raises(ToolError):
        memory.git_log(repo, {"grep": "(", "path": None, "max_count": 1})


def test_a_session_runs_and_grades(corpus, repo, tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "prepare_repo", lambda commit: repo)
    question = {
        "id": "kg-X1",
        "commit": "aaaaaaa",
        "category": "rationale",
        "lives_in": ["session"],
        "question": "Why SQLite?",
        "expect": {"keywords": [["fts5"]]},
        "reference": "FTS5.",
    }
    session = tmp_path / "session"
    runs = memory.prepare_session([question], ["s0", "s2"], 2, session, corpus)
    assert [r.name for r in runs] == [
        "kg-X1.s0.1",
        "kg-X1.s0.2",
        "kg-X1.s2.1",
        "kg-X1.s2.2",
    ]
    s0, s2 = (runs[0] / "prompt.md").read_text(), (runs[2] / "prompt.md").read_text()
    assert "## Memory" not in s0 and "[decision:use-sqlite]" in s2
    assert "-m bench.memory call" in s2 and "git_log" in s2

    run = runs[2]
    assert "a.py" in memory.subagent.call(
        run, "list_files", '{"glob": "*"}', memory.run_tool
    )
    error = memory.subagent.call(run, "kg", '{"args": []}', memory.run_tool)
    assert error.startswith("Error: unknown tool")
    answer = {
        "answer": "SQLite with FTS5.",
        "items": [],
        "evidence": ["decision:use-sqlite"],
    }
    memory.subagent.call(run, "submit_answer", json.dumps(answer), memory.run_tool)

    records = memory.collect(session, {"kg-X1": question}, {})
    by_run = {(r["strategy"], r["repeat"]): r for r in records}
    assert by_run[("s2", 1)]["grade"]["score"] == 1.0
    assert by_run[("s2", 1)]["outcome"] == "answered"
    assert by_run[("s2", 1)]["context_chars"] > by_run[("s2", 1)]["memory_chars"] > 0
    assert by_run[("s0", 1)]["outcome"] == "no_answer"
    assert by_run[("s0", 1)]["memory_chars"] == 0


def test_the_kg_corpus_answers_its_questions_with_s2():
    """The real corpus and questions load, and S2 gives every question context."""
    questions = json.loads(memory.QUESTIONS.read_text(encoding="utf-8"))
    graphs = {}
    for q in questions:
        if q["commit"] not in graphs:
            graphs[q["commit"]] = memory.load_memory(memory.snapshot(q["commit"]))
        ids = memory.fts_search(memory.fts_index(graphs[q["commit"]]), q["question"])
        assert len(ids) == memory.TOP_K, q["id"]
