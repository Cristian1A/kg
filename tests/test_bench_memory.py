"""Experiment 2's harness (bench/memory.py), without calling any model."""

import json
import subprocess
from pathlib import Path

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


def _edge(source, target, kind):
    return {"source": source, "target": target, "type": kind, "provenance": PROV}


@pytest.fixture
def linked_store(tmp_path):
    """A seed decision with a chain of relations and a shared piece of evidence.

    decision:seed (matches "parser") is blocked by task:block, which supersedes
    task:old; decision:seed and decision:twin cite the same issue; the session
    produced decision:seed and decision:far.
    """
    s1 = "session:2026-10-01-s1"
    doc = _session(
        1,
        "aaaaaaa",
        [
            _memory("decision:seed", "Rewrite the parser", "What: a new parser.", s1),
            _memory("task:block", "Wait for the lexer", "What: a lexer.", s1),
            _memory(
                "task:old", "Old plan", "What: an earlier lexer.", s1, "superseded"
            ),
            _memory("decision:twin", "Keep the CLI", "What: through the rewrite.", s1),
            _memory("decision:far", "Unrelated", "What: about the parser docs.", s1),
            {
                "id": "evidence:issue-7",
                "type": "Evidence",
                "label": "The rewrite issue",
                "attrs": {"kind": "issue", "ref": "#7"},
                "provenance": PROV,
            },
        ],
        [
            _edge("decision:seed", "task:block", "blocked_by"),
            _edge("task:block", "task:old", "supersedes"),
            _edge("decision:seed", "evidence:issue-7", "supported_by"),
            _edge("decision:twin", "evidence:issue-7", "supported_by"),
            _edge(s1, "decision:seed", "produced"),
            _edge(s1, "decision:far", "produced"),
        ],
    )
    root = tmp_path / "linked"
    root.mkdir()
    (root / "01-a.json").write_text(json.dumps(doc))
    return memory.load_memory(memory.snapshot("aaaaaaa", root))


def _ids(text):
    return [line[1:].split("]")[0] for line in text.splitlines() if line[:1] == "["]


def test_traversal_follows_relations_to_its_depth(linked_store, monkeypatch):
    monkeypatch.setitem(memory.SEEDS, "s4", 1)
    monkeypatch.setitem(memory.SEEDS, "s8", 1)
    found = memory.traverse(linked_store, ["decision:seed"], 2)
    assert found["task:block"] == (1, 0, 0)  # a direct relation
    assert found["decision:twin"] == (1, 1, 0)  # through the shared issue
    assert found["task:old"] == (2, 0, 0)
    assert found["session:2026-10-01-s1"] == (1, 2, 0)
    assert "decision:far" in found  # a sibling through the session, two links away

    s4 = memory.context("s4", "parser rewrite", linked_store)
    assert _ids(s4)[:4] == [
        "decision:seed",
        "task:block",
        "decision:twin",
        "session:2026-10-01-s1",
    ]
    assert "task:old" in _ids(s4)
    assert "- blocked by: [task:block] Wait for the lexer" in s4
    assert "- supersedes: [task:old] Old plan" in s4
    assert "evidence:" not in s4

    s8 = memory.context("s8", "parser rewrite", linked_store)
    # depth 1, and the neighbour the question's words match comes first
    assert _ids(s8) == [
        "decision:seed",
        "decision:twin",
        "task:block",
        "session:2026-10-01-s1",
    ]
    assert "- evidence: issue #7: The rewrite issue" in s8
    assert s8 == memory.context("s8", "parser rewrite", linked_store)


def test_s2r_searches_and_shows_relations_as_text(linked_store):
    # "lexer" is only in task:block's text and in decision:seed's relation line
    plain = memory.fts_search(memory.fts_index(linked_store), "lexer")
    rich = memory.fts_search(
        memory.fts_index(linked_store, with_relations=True), "lexer"
    )
    assert "decision:seed" not in plain
    assert "decision:seed" in rich
    text = memory.context("s2r", "lexer", linked_store)
    assert "- blocked by: [task:block] Wait for the lexer" in text
    assert "evidence:" not in text
    assert text == memory.context("s2r", "lexer", linked_store)


def _fake_encode(texts):
    """Bag-of-words vectors over a tiny vocabulary, unit length."""
    vocab = ["parser", "lexer", "cli", "plan"]
    rows = []
    for t in texts:
        v = [float(t.lower().count(w)) for w in vocab]
        norm = sum(x * x for x in v) ** 0.5 or 1.0
        rows.append([x / norm for x in v])
    return rows


def test_s3_ranks_by_cosine_and_breaks_ties_by_id(linked_store, monkeypatch):
    ids = memory.semantic_search(linked_store, "the lexer", 3, encode=_fake_encode)
    # task:block and task:old both mention only "lexer": a tie, ID order
    assert ids[:2] == ["task:block", "task:old"]
    monkeypatch.setattr(memory, "embed", _fake_encode)
    text = memory.context("s3", "the lexer", linked_store)
    assert _ids(text)[:2] == ["task:block", "task:old"]
    assert len(_ids(text)) == min(memory.TOP_K, len(memory.memories(linked_store)))
    assert "- blocked by" not in text  # S3 shows memories alone, as S2 does


def test_s1_holds_every_memory_oldest_first(linked_store):
    text = memory.context("s1", "anything", linked_store)
    assert sorted(_ids(text)) == memory.memories(linked_store)
    assert _ids(text)[0] == "decision:far"  # same date: ID order


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
        for strategy in ("s4", "s8"):
            text = memory.context(strategy, q["question"], graphs[q["commit"]])
            assert 0 < len(_ids(text)) <= memory.TOP_K, (q["id"], strategy)
            assert _ids(text)[: memory.SEEDS[strategy]] == ids[: memory.SEEDS[strategy]]


def test_usage_comes_from_the_subagent_transcripts(tmp_path, capsys):
    session = tmp_path / "session"
    (session / "kg-X1.s2.1").mkdir(parents=True)
    (session / "kg-X1.s0.1").mkdir()
    (session / "kg-X1.s0.1" / "answer.json").write_text("{}")
    transcripts = tmp_path / "subagents"
    transcripts.mkdir()
    prompt = session / "kg-X1.s2.1" / "prompt.md"
    events = [
        {
            "type": "user",
            "timestamp": "2026-10-25T10:00:00Z",
            "message": {"content": f"Read the file {prompt} and follow it."},
        },
        {
            "type": "assistant",
            "timestamp": "2026-10-25T10:00:30.5Z",
            "message": {
                "model": "claude-opus-5-5",
                "usage": {
                    "input_tokens": 2,
                    "cache_creation_input_tokens": 100,
                    "cache_read_input_tokens": 30000,
                    "output_tokens": 50,
                },
            },
        },
    ]
    lines = "\n".join(json.dumps(e) for e in events)
    (transcripts / "agent-1.jsonl").write_text(lines + "\n")
    (transcripts / "agent-2.jsonl").write_text(json.dumps(events[1]) + "\n")
    assert memory.usage_from_transcripts(session, transcripts) == {
        "kg-X1.s2.1": {
            "total_tokens": 30152,
            "seconds": 30.5,
            "model": "claude-opus-5-5",
            "started": "2026-10-25T10:00:00+00:00",
        }
    }
    assert memory.main(["usage", str(session), str(transcripts)]) == 0
    assert (
        json.loads((session / "usage.json").read_text())["kg-X1.s2.1"]["seconds"]
        == 30.5
    )
    assert memory.main(["status", str(session)]) == 0
    out = capsys.readouterr().out
    assert "done 1, pending 1" in out and "pending: kg-X1.s2.1 (0 calls)" in out


def _transcript(prompt: Path, start: str, replies: list[tuple[str, str, int]]) -> str:
    """A subagent transcript: the launch message, then (time, model, tokens) replies."""
    events = [
        {"type": "user", "timestamp": start, "message": {"content": f"Read {prompt}"}}
    ]
    for time, model, tokens in replies:
        events.append(
            {
                "type": "assistant",
                "timestamp": time,
                "message": {
                    "model": model,
                    "usage": {
                        "input_tokens": tokens,
                        "cache_creation_input_tokens": 0,
                        "cache_read_input_tokens": 0,
                        "output_tokens": 0,
                    },
                },
            }
        )
    return "\n".join(json.dumps(e) for e in events) + "\n"


def test_usage_skips_session_limit_notices_and_keeps_the_relaunch(tmp_path):
    session = tmp_path / "session"
    for run in ("kg-X1.s3.1", "kg-X2.s1.1"):
        (session / run).mkdir(parents=True)
    transcripts = tmp_path / "subagents"
    transcripts.mkdir()
    # Answered, then the session limit hit: the notice has no usage.
    (transcripts / "agent-a.jsonl").write_text(
        _transcript(
            session / "kg-X1.s3.1" / "prompt.md",
            "2026-10-28T08:00:00Z",
            [
                ("2026-10-28T08:00:20Z", "claude-opus-5-5", 40000),
                ("2026-10-28T08:00:21Z", "<synthetic>", 0),
            ],
        )
    )
    # Launched, cut off at once, launched again later: the relaunch counts,
    # whichever file name sorts first.
    prompt = session / "kg-X2.s1.1" / "prompt.md"
    (transcripts / "agent-z.jsonl").write_text(
        _transcript(
            prompt,
            "2026-10-27T09:28:00Z",
            [
                ("2026-10-27T09:28:05Z", "claude-opus-5-5", 9000),
                ("2026-10-27T09:28:06Z", "<synthetic>", 0),
            ],
        )
    )
    (transcripts / "agent-b.jsonl").write_text(
        _transcript(
            prompt,
            "2026-10-27T13:42:00Z",
            [("2026-10-27T13:42:30Z", "claude-opus-5-5", 50000)],
        )
    )
    usage = memory.usage_from_transcripts(session, transcripts)
    assert usage["kg-X1.s3.1"]["total_tokens"] == 40000
    assert usage["kg-X1.s3.1"]["model"] == "claude-opus-5-5"
    assert usage["kg-X2.s1.1"]["total_tokens"] == 50000
    assert usage["kg-X2.s1.1"]["seconds"] == 30.0
    # An older transcript read later (another session) does not overwrite it.
    old = tmp_path / "older"
    old.mkdir()
    (old / "agent-z.jsonl").write_text((transcripts / "agent-z.jsonl").read_text())
    assert memory.main(["usage", str(session), str(transcripts)]) == 0
    assert memory.main(["usage", str(session), str(old)]) == 0
    saved = json.loads((session / "usage.json").read_text())
    assert saved["kg-X2.s1.1"]["total_tokens"] == 50000
