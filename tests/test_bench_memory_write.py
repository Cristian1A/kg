"""The agent-written corpus of experiment 2 (R2-11): sources, checks, submit."""

import json
from datetime import UTC, datetime

import pytest

from bench import memory_write as mw

S1 = {
    "id": "session:2026-01-01-aaaa0001",
    "stem": "01-2026-01-01-aaaa0001",
    "date": "2026-01-01",
    "commit": "1111111",
    "transcript": "aaaa0001",
    "order": 1,
}
S2 = {
    "id": "session:2026-01-02-bbbb0002",
    "stem": "02-2026-01-02-bbbb0002",
    "date": "2026-01-02",
    "commit": "2222222",
    "transcript": "bbbb0002",
    "order": 2,
}


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    monkeypatch.setattr(mw, "sessions", lambda: [S1, S2])
    monkeypatch.setattr(mw, "AGENT_CORPUS", tmp_path / "kg-agent")
    return tmp_path


def _memory(nid, session, status="active", **extra):
    return {
        "id": nid,
        "type": "Decision",
        "label": nid,
        "description": "What: x",
        "attrs": {
            "status": status,
            "session": session["id"],
            "created": session["date"],
        },
        **extra,
    }


def _doc(session, nodes, edges=()):
    return {
        "version": "1",
        "nodes": [{"id": session["id"], "type": "Session", "label": "s"}, *nodes],
        "edges": list(edges),
    }


def _produced(session, nid):
    return {"source": session["id"], "target": nid, "type": "produced"}


def test_clean_drops_tags_and_credential_lines():
    text = (
        "keep this\n<system-reminder>hidden</system-reminder>"
        "<command-name>/init</command-name>\nexport GITHUB_TOKEN=ghp_abcdefghijklmnop\n"
        "password: hunter2hunter2"
    )
    out = mw.clean(text)
    assert "hidden" not in out and "/init" in out and "keep this" in out
    assert "ghp_" not in out and "hunter2" not in out
    assert out.count("looked like a credential") == 2


def test_dialogue_keeps_text_only_and_stops_at_the_cut(tmp_path):
    events = [
        {
            "type": "user",
            "timestamp": "2026-01-01T10:00:00Z",
            "message": {"content": "Hola"},
        },
        {
            "type": "assistant",
            "timestamp": "2026-01-01T10:00:05Z",
            "message": {
                "content": [
                    {"type": "thinking", "thinking": "secret plan"},
                    {"type": "text", "text": "Hello"},
                    {"type": "tool_use", "name": "Bash", "input": {}},
                ]
            },
        },
        {
            "type": "user",
            "timestamp": "2026-01-01T10:00:06Z",
            "message": {"content": [{"type": "tool_result", "content": "output"}]},
        },
        {
            "type": "user",
            "timestamp": "2026-01-01T10:00:07Z",
            "isMeta": True,
            "message": {"content": "meta"},
        },
        {
            "type": "user",
            "timestamp": "2026-01-01T11:00:00Z",
            "message": {"content": "Later"},
        },
    ]
    path = tmp_path / "t.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in events))
    text = mw.dialogue(path)
    assert "USER: Hola" in text and "ASSISTANT: Hello" in text and "USER: Later" in text
    assert "secret plan" not in text and "output" not in text and "meta" not in text
    cut = mw.dialogue(path, until=datetime(2026, 1, 1, 10, 30, tzinfo=UTC))
    assert "Later" not in cut and "Hello" in cut


def test_body_at_returns_the_body_as_it_stood():
    edits = [
        {"editedAt": "2026-01-03T00:00:00Z", "diff": "edited"},
        {"editedAt": "2026-01-01T00:00:00Z", "diff": "original"},
    ]
    issue = {"body": "edited"}
    assert mw.body_at(issue, edits, datetime(2026, 1, 2, tzinfo=UTC)) == "original"
    assert mw.body_at(issue, edits, datetime(2026, 1, 4, tzinfo=UTC)) == "edited"
    assert mw.body_at(
        {"body": "never edited"}, [], datetime(2026, 1, 1, tzinfo=UTC)
    ) == ("never edited")


def test_submit_checks_order_and_content(corpus):
    path = corpus / "doc.json"
    # session 2 needs session 1 first
    path.write_text(json.dumps(_doc(S2, [])))
    with pytest.raises(SystemExit, match="write these sessions first"):
        mw.submit(S2["stem"], path)
    # a new memory without its produced edge, and an unknown edge type
    bad = _doc(
        S1,
        [_memory("decision:a", S1)],
        [{"source": "decision:a", "target": "decision:a", "type": "relates_to"}],
    )
    path.write_text(json.dumps(bad))
    ok, message = mw.submit(S1["stem"], path)
    assert not ok and "produced edge" in message and "relates_to" in message
    good = _doc(S1, [_memory("decision:a", S1)], [_produced(S1, "decision:a")])
    good["nodes"][0]["attrs"] = {"order": 99}
    path.write_text(json.dumps(good))
    ok, message = mw.submit(S1["stem"], path)
    assert ok, message
    stored = json.loads((mw.AGENT_CORPUS / f"{S1['stem']}.json").read_text())
    session = next(n for n in stored["nodes"] if n["type"] == "Session")
    assert session["attrs"]["order"] == 1 and session["attrs"]["commit"] == "1111111"
    assert all(n["provenance"]["extractor"] == "exp2-agent@1" for n in stored["nodes"])


def test_later_session_updates_and_supersedes(corpus):
    path = corpus / "doc.json"
    path.write_text(
        json.dumps(_doc(S1, [_memory("decision:a", S1)], [_produced(S1, "decision:a")]))
    )
    assert mw.submit(S1["stem"], path)[0]
    assert "[decision:a] Decision · active" in mw.listing(mw.memory_so_far(S2["stem"]))
    assert "decision:a" in mw.show(S2["stem"], "decision:a")
    later = _doc(
        S2,
        [
            _memory("decision:b", S2),
            {"id": "decision:a", "type": "Decision", "attrs": {"status": "superseded"}},
        ],
        [
            _produced(S2, "decision:b"),
            {"source": "decision:b", "target": "decision:a", "type": "supersedes"},
        ],
    )
    path.write_text(json.dumps(later))
    ok, message = mw.submit(S2["stem"], path)
    assert ok, message
    # an update may not claim a memory is new in this session with another type
    wrong = _doc(
        S2, [{"id": "decision:a", "type": "Task", "attrs": {"status": "done"}}]
    )
    path.write_text(json.dumps(wrong))
    ok, message = mw.submit(S2["stem"], path)
    assert not ok and "already a Decision" in message
