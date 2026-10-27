"""Experiment 2 (#71): gates G1–G3 over the result files of several sessions.

The procedure is fixed in `docs/experiment-2/gates.md`: accuracy is the frozen
keyword grade, evidence recall matches the anchors of each reference item,
staleness errors come from a blind hand audit, time is the subagent's seconds.

    python -m bench.gates sheet <results.jsonl>...  > sheet.tsv
    python -m bench.gates report <results.jsonl>... --audit staleness-audit.tsv
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from bench.memory import QUESTIONS

SEED = 71
GRAPH = ("s4", "s8")
BASELINE = "s2"
G1_CATEGORIES = ("rationale", "multi-hop", "supersession", "staleness", "blocked")
G1_MARGIN = 0.10
G2_ACCURACY = 0.03
G2_TIME = 1.30
STALE_CATEGORIES = ("staleness", "supersession")
AUDITED = ("s0", "s2", "s4", "s8")
RESAMPLES = 10_000

HEX = re.compile(r"\b[0-9a-f]{7,40}\b")
COMMIT = re.compile(r"(?<![-\w])[0-9a-f]{7,40}\b")
NUMBER = re.compile(r"#(\d+)")
QUOTED = re.compile(r"`([^`]+)`")
DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")


def anchors(item: str) -> list[tuple[str, str]]:
    """The (kind, value) anchors of one reference evidence item."""
    found = [("number", n) for n in NUMBER.findall(item)]
    found += [("hex", h[:7]) for h in HEX.findall(item.lower())]
    for span in QUOTED.findall(item):
        if span.startswith("git log"):
            found.append(("commit", ""))
        elif not HEX.fullmatch(span.lower()):
            found.append(("path", span.lower()))
    if not found and "session" in item.lower():
        found += [("session", d) for d in DATE.findall(item)]
    return found


def _matches(kind: str, value: str, text: str) -> bool:
    if kind == "number":
        return bool(
            re.search(rf"(#|\bissues?\s+|\bpr\s+|issues/|pull/){value}\b", text)
        )
    if kind == "hex":
        return value in text
    if kind == "commit":  # not a session memory's ID (`session:<date>-<hex>`)
        return bool(COMMIT.search(text))
    if kind == "path":
        return value in text
    return "session" in text and value in text


def cited_text(answer: dict[str, Any] | None) -> str:
    """The answer and its evidence list, lowercased, as one string."""
    if not answer:
        return ""
    parts = [str(answer.get("answer", ""))] + [
        str(e) for e in answer.get("evidence", [])
    ]
    return "\n".join(parts).lower()


def evidence_recall(
    reference: list[str], answer: dict[str, Any] | None
) -> float | None:
    """Share of the anchored reference items the answer cites (None: no anchors)."""
    items = [a for a in map(anchors, reference) if a]
    if not items:
        return None
    text = cited_text(answer)
    hit = sum(any(_matches(k, v, text) for k, v in item) for item in items)
    return hit / len(items)


def load(paths: list[Path]) -> list[dict[str, Any]]:
    """Every result record of the given JSONL files."""
    return [
        json.loads(line)
        for path in paths
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def audit_sheet(
    records: list[dict[str, Any]],
    questions: dict[str, dict[str, Any]],
    seed: int = SEED,
) -> list[dict[str, str]]:
    """The blind staleness-audit rows: shuffled, without strategy or repeat."""
    picked = [
        r
        for r in records
        if r["category"] in STALE_CATEGORIES and r["strategy"] in AUDITED
    ]
    picked.sort(key=lambda r: (r["question"], r["strategy"], r["repeat"]))
    random.Random(seed).shuffle(picked)
    rows = []
    for n, r in enumerate(picked, 1):
        q = questions[r["question"]]
        rows.append(
            {
                "code": f"a{n:03d}",
                "run": f"{r['question']}.{r['strategy']}.{r['repeat']}",
                "question": q["question"],
                "reference": q["reference"],
                "answer": (r["answer"] or {}).get("answer", "(no answer)"),
            }
        )
    return rows


def read_audit(path: Path) -> dict[str, bool]:
    """Run name → staleness error, from the audit TSV (columns run, error)."""
    with path.open(encoding="utf-8", newline="") as f:
        return {
            row["run"]: row["error"] == "1" for row in csv.DictReader(f, delimiter="\t")
        }


def _mean(values: list[float]) -> float:
    return statistics.mean(values) if values else float("nan")


def bootstrap(
    diffs: list[float], seed: int = SEED, n: int = RESAMPLES
) -> tuple[float, float]:
    """95% interval of the mean of per-question differences."""
    rng = random.Random(seed)
    means = sorted(statistics.mean(rng.choices(diffs, k=len(diffs))) for _ in range(n))
    return means[int(0.025 * n)], means[int(0.975 * n) - 1]


def table(
    records: list[dict[str, Any]], questions: dict[str, dict[str, Any]]
) -> dict[str, dict[str, dict[str, Any]]]:
    """category → strategy → accuracy, recall, seconds and per-question values."""
    out: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in records:
        groups[(r["category"], r["strategy"])].append(r)
    for (category, strategy), rows in groups.items():
        recalls = [
            (
                r["question"],
                evidence_recall(questions[r["question"]]["evidence"], r["answer"]),
            )
            for r in rows
        ]
        per_q: dict[str, dict[str, list[float]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for r, (_, rec) in zip(rows, recalls, strict=True):
            per_q[r["question"]]["accuracy"].append(r["grade"]["score"])
            if rec is not None:
                per_q[r["question"]]["recall"].append(rec)
        out[category][strategy] = {
            "runs": len(rows),
            "accuracy": _mean([r["grade"]["score"] for r in rows]),
            "recall": _mean([rec for _, rec in recalls if rec is not None]),
            "seconds": _mean(
                [r["seconds"] for r in rows if r.get("seconds") is not None]
            ),
            "per_question": {
                q: {k: _mean(v) for k, v in m.items()} for q, m in sorted(per_q.items())
            },
        }
    return out


def _diffs(cell: dict[str, Any], base: dict[str, Any], metric: str) -> list[float]:
    return [
        cell["per_question"][q][metric] - base["per_question"][q][metric]
        for q in sorted(base["per_question"])
        if metric in base["per_question"][q]
        and metric in cell["per_question"].get(q, {})
    ]


def gates(
    records: list[dict[str, Any]],
    questions: dict[str, dict[str, Any]],
    audit: dict[str, bool] | None,
) -> dict[str, Any]:
    """The verdict of G1, G2 and G3, with the numbers behind each."""
    t = table(records, questions)
    g1 = {}
    for category in G1_CATEGORIES:
        base = t[category][BASELINE]
        rows = {}
        for s in GRAPH:
            cell = t[category][s]
            d_acc = cell["accuracy"] - base["accuracy"]
            d_rec = cell["recall"] - base["recall"]
            rows[s] = {
                "accuracy": d_acc,
                "recall": d_rec,
                "accuracy_ci": bootstrap(_diffs(cell, base, "accuracy")),
                "recall_ci": bootstrap(_diffs(cell, base, "recall")),
                "pass": d_acc >= G1_MARGIN or d_rec >= G1_MARGIN,
            }
        g1[category] = {
            "strategies": rows,
            "pass": any(r["pass"] for r in rows.values()),
        }
    passed = [c for c, v in g1.items() if v["pass"]]

    direct = t["direct"]
    g2 = {}
    for s in GRAPH:
        loss = direct[BASELINE]["accuracy"] - direct[s]["accuracy"]
        ratio = direct[s]["seconds"] / direct[BASELINE]["seconds"]
        g2[s] = {
            "loss": loss,
            "time_ratio": ratio,
            "pass": loss <= G2_ACCURACY and ratio <= G2_TIME,
        }

    g3: dict[str, Any] | None = None
    if audit is not None:
        errors = {s: 0 for s in AUDITED}
        judged = {s: 0 for s in AUDITED}
        for r in records:
            name = f"{r['question']}.{r['strategy']}.{r['repeat']}"
            if r["category"] in STALE_CATEGORIES and name in audit:
                judged[r["strategy"]] += 1
                errors[r["strategy"]] += audit[name]
        g3 = {
            "errors": errors,
            "judged": judged,
            "pass": {
                s: errors[s] <= errors[BASELINE] / 2
                if errors[BASELINE]
                else errors[s] == 0
                for s in GRAPH
            },
        }
    return {
        "table": t,
        "g1": {"categories": g1, "passed": passed, "pass": len(passed) >= 2},
        "g2": {"strategies": g2, "pass": all(v["pass"] for v in g2.values())},
        "g3": g3,
    }


def _print_report(result: dict[str, Any]) -> None:
    t = result["table"]
    strategies = sorted({s for cells in t.values() for s in cells})
    print("category       " + "".join(f"{s:>16}" for s in strategies))
    print("               " + "".join(f"{'acc  rec  sec':>16}" for _ in strategies))
    for category in sorted(t):
        cells = t[category]
        line = f"{category:<15}"
        for s in strategies:
            c = cells.get(s)
            line += (
                f"{c['accuracy']:>6.3f}{c['recall']:>5.2f}{c['seconds']:>5.0f}"
                if c
                else " " * 16
            )
        print(line)
    print()
    g1 = result["g1"]
    print(
        f"G1: {'PASS' if g1['pass'] else 'FAIL'} ({len(g1['passed'])} categories: "
        f"{', '.join(g1['passed']) or 'none'})"
    )
    for category, v in g1["categories"].items():
        for s, r in v["strategies"].items():
            print(
                f"  {category:<13} {s} − s2: accuracy {r['accuracy']:+.3f} "
                f"[{r['accuracy_ci'][0]:+.2f}, {r['accuracy_ci'][1]:+.2f}], "
                f"recall {r['recall']:+.3f} "
                f"[{r['recall_ci'][0]:+.2f}, {r['recall_ci'][1]:+.2f}]"
                f"{'  pass' if r['pass'] else ''}"
            )
    g2 = result["g2"]
    print(f"G2: {'PASS' if g2['pass'] else 'FAIL'}")
    for s, r in g2["strategies"].items():
        print(
            f"  {s}: accuracy loss {r['loss']:+.3f}, time × {r['time_ratio']:.2f}"
            f"{'  pass' if r['pass'] else '  fail'}"
        )
    g3 = result["g3"]
    if g3 is None:
        print("G3: not evaluated (no --audit)")
    else:
        ok = all(g3["pass"].values())
        print(f"G3: {'PASS' if ok else 'FAIL'}")
        for s in AUDITED:
            print(f"  {s}: {g3['errors'][s]} errors in {g3['judged'][s]} runs")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m bench.gates",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name, help_ in (
        ("sheet", "write the blind staleness-audit sheet (TSV) to stdout"),
        ("report", "print the per-category table and the G1–G3 verdicts"),
    ):
        p = sub.add_parser(name, help=help_)
        p.add_argument("results", type=Path, nargs="+")
        p.add_argument("--questions", type=Path, default=QUESTIONS)
        if name == "report":
            p.add_argument(
                "--audit", type=Path, help="staleness audit TSV (run, error)"
            )
            p.add_argument("--json", action="store_true", help="print JSON instead")
    args = parser.parse_args(argv)
    questions = {
        q["id"]: q for q in json.loads(args.questions.read_text(encoding="utf-8"))
    }
    records = load(args.results)
    if args.command == "sheet":
        rows = audit_sheet(records, questions)
        writer = csv.DictWriter(
            sys.stdout,
            fieldnames=["code", "question", "reference", "answer"],
            delimiter="\t",
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)
        return 0
    audit = read_audit(args.audit) if args.audit else None
    result = gates(records, questions, audit)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True, default=list))
    else:
        _print_report(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
