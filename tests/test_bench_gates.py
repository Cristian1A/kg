"""Experiment 2's gates (bench/gates.py), on hand-made result records."""

import pytest

from bench import gates


def test_anchors_of_each_reference_kind():
    assert gates.anchors("#35 and #55, comments") == [
        ("number", "35"),
        ("number", "55"),
    ]
    assert gates.anchors("`docs/report.md` §How") == [("path", "docs/report.md")]
    assert gates.anchors("`git log -p README.md`") == [("commit", "")]
    assert gates.anchors("session 2026-10-20 (`84137a84`)") == [("hex", "84137a8")]
    assert gates.anchors("session of 2026-10-15") == [("session", "2026-10-15")]
    assert gates.anchors("the outcome alone") == []


def test_evidence_recall_matches_anchors():
    ref = ["#67", "`git log`", "`src/kg/cli.py`", "nothing to anchor"]
    answer = {"answer": "See issue 67.", "evidence": ["commit 97f3741"]}
    assert gates.evidence_recall(ref, answer) == 2 / 3
    assert gates.evidence_recall(ref, None) == 0.0
    assert gates.evidence_recall(["no anchor"], answer) is None


def test_number_and_commit_are_not_partial_matches():
    assert gates.evidence_recall(["#5"], {"answer": "#59", "evidence": []}) == 0.0
    session_id = {"answer": "", "evidence": ["memory session:2026-10-15-735af7cf"]}
    assert gates.evidence_recall(["`git log`"], session_id) == 0.0
    assert gates.evidence_recall(["session 2026-10-15 (`735af7cf`)"], session_id) == 1.0


def _questions():
    out = {}
    for qid, category in (("kg-D1", "direct"), ("kg-T1", "staleness")):
        out[qid] = {
            "id": qid,
            "category": category,
            "question": f"{qid}?",
            "reference": "ref",
            "evidence": ["#1"],
        }
    for category in gates.G1_CATEGORIES:
        if category != "staleness":
            qid = f"kg-{category}"
            out[qid] = {
                "id": qid,
                "category": category,
                "question": "?",
                "reference": "ref",
                "evidence": ["#1"],
            }
    return out


def _record(qid, category, strategy, score, cites, seconds=10.0, repeat=1):
    return {
        "question": qid,
        "category": category,
        "strategy": strategy,
        "repeat": repeat,
        "grade": {"score": score},
        "answer": {"answer": "x", "evidence": ["#1"] if cites else []},
        "seconds": seconds,
    }


def test_gates_verdicts():
    questions = _questions()
    records = []
    for qid, q in questions.items():
        graph_better = q["category"] in ("rationale", "multi-hop")
        records.append(_record(qid, q["category"], "s2", 0.5, False))
        for s in gates.GRAPH:
            records.append(_record(qid, q["category"], s, 0.5, graph_better))
    # direct lookups: S4 is slower than 1.30 × S2, S8 is not
    records = [
        {**r, "seconds": 14.0}
        if r["question"] == "kg-D1" and r["strategy"] == "s4"
        else r
        for r in records
    ]
    audit = {"kg-T1.s2.1": True, "kg-T1.s4.1": False, "kg-T1.s8.1": True}
    result = gates.gates(records, questions, audit)
    assert result["g1"]["passed"] == ["rationale", "multi-hop"]
    assert result["g1"]["pass"]
    assert not result["g2"]["strategies"]["s4"]["pass"]
    assert result["g2"]["strategies"]["s8"]["pass"]
    assert result["g3"]["pass"] == {"s4": True, "s8": False}


def test_audit_sheet_is_blind_and_deterministic():
    questions = _questions()
    records = [
        _record("kg-T1", "staleness", s, 1.0, True, repeat=n)
        for s in ("s0", "s2", "s4", "s8")
        for n in (1, 2, 3)
    ] + [_record("kg-D1", "direct", "s2", 1.0, True)]
    rows = gates.audit_sheet(records, questions)
    assert len(rows) == 12
    assert rows == gates.audit_sheet(records, questions)
    assert [r["code"] for r in rows] == [f"a{n:03d}" for n in range(1, 13)]
    assert sorted(r["run"] for r in rows) == sorted(
        f"kg-T1.{s}.{n}" for s in ("s0", "s2", "s4", "s8") for n in (1, 2, 3)
    )


def test_comparator_is_the_best_of_s2_and_s3_per_category_and_metric():
    questions = _questions()
    records = []
    for qid, q in questions.items():
        s3_better = q["category"] == "rationale"
        records.append(_record(qid, q["category"], "s2", 0.5, False))
        records.append(
            _record(qid, q["category"], "s3", 0.9 if s3_better else 0.4, True)
        )
        for s in gates.GRAPH:
            records.append(_record(qid, q["category"], s, 0.6, False))
    audit = {"kg-T1.s2.1": True, "kg-T1.s3.1": False, "kg-T1.s4.1": False}
    result = gates.gates(records, questions, audit)
    rationale = result["g1"]["categories"]["rationale"]
    # S3 is best in accuracy on rationale; S3 cites #1, so it is best in recall
    assert rationale["baseline"] == {"accuracy": "s3", "recall": "s3"}
    assert rationale["strategies"]["s4"]["accuracy"] == pytest.approx(-0.3)
    multi = result["g1"]["categories"]["multi-hop"]
    assert multi["baseline"]["accuracy"] == "s2"
    assert multi["strategies"]["s4"]["accuracy"] == pytest.approx(0.1)
    # G3 compares against the fewer errors of S2 and S3 (S3: 0)
    assert result["g3"]["baseline"] == "s3"
    assert result["g3"]["pass"] == {"s4": True, "s8": True}


def test_audit_sheet_of_other_strategies_and_seconds_outlier():
    questions = _questions()
    records = [
        _record("kg-T1", "staleness", s, 1.0, True, repeat=n)
        for s in ("s1", "s2", "s3")
        for n in (1, 2, 3)
    ]
    rows = gates.audit_sheet(records, questions, strategies=("s1", "s3"), prefix="b")
    questions["kg-R6"] = {**questions["kg-rationale"], "id": "kg-R6"}
    assert [r["code"] for r in rows] == [f"b{n:03d}" for n in range(1, 7)]
    assert not any(".s2." in r["run"] for r in rows)
    slow = _record("kg-R6", "rationale", "s1", 1.0, True, seconds=17822.0, repeat=3)
    fast = _record("kg-R6", "rationale", "s1", 1.0, True, seconds=20.0)
    assert gates.table([slow, fast], questions)["rationale"]["s1"]["seconds"] == 20.0
