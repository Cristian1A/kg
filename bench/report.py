"""Summarize benchmark results: `python -m bench.report results/<file>.jsonl`.

Prints a Markdown report: one table per question and strategy, a summary
per strategy, the score and context per question category, the spread of
questions run more than once, and how often a strategy that can choose between
the files and the graph calls `kg`. Quality (score, traceability, answered) and cost
(tokens, time, turns) are reported separately.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

from bench.tools import TOOLS


def load(paths: list[Path]) -> list[dict[str, Any]]:
    records = []
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(json.loads(line))
    return records


def tokens(record: dict[str, Any]) -> tuple[int | None, int | None]:
    """Input tokens (cached reads and writes included) and output tokens.

    `None` when unknown: a subagent run (`bench.subagent`) only records its
    total.
    """
    u = record["usage"]
    if "input_tokens" not in u:
        return None, None
    read = u["input_tokens"] + u["cache_read_input_tokens"]
    return read + u["cache_creation_input_tokens"], u["output_tokens"]


def total_tokens(record: dict[str, Any]) -> int | None:
    """Input plus output tokens, or a subagent's reported total."""
    tin, tout = tokens(record)
    if tin is not None:
        return tin + tout
    return record["usage"].get("total_tokens")


def summary(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per strategy: means over its runs."""
    rows = []
    for strategy in sorted({r["strategy"] for r in records}):
        runs = [r for r in records if r["strategy"] == strategy]
        traced = [r["traceability"] for r in runs if r["traceability"] is not None]
        rows.append(
            {
                "strategy": strategy,
                "runs": len(runs),
                "answered": sum(r["outcome"] == "answered" for r in runs),
                "score": _mean(r["grade"]["score"] for r in runs),
                "traceability": _mean(traced) if traced else None,
                "input_tokens": _mean(tokens(r)[0] for r in runs),
                "output_tokens": _mean(tokens(r)[1] for r in runs),
                "total_tokens": _mean(total_tokens(r) for r in runs),
                "context_chars": _mean(r.get("context_chars") for r in runs),
                "seconds": _mean(r["seconds"] for r in runs),
                "turns": _mean(r["turns"] for r in runs),
            }
        )
    return rows


def by_category(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Mean score and context per category and strategy, for categorized runs."""
    rows = []
    keys = {(r["category"], r["strategy"]) for r in records if r.get("category")}
    for category, strategy in sorted(keys):
        runs = [
            r
            for r in records
            if r.get("category") == category and r["strategy"] == strategy
        ]
        rows.append(
            {
                "category": category,
                "strategy": strategy,
                "runs": len(runs),
                "score": _mean(r["grade"]["score"] for r in runs),
                "context_chars": _mean(r.get("context_chars") for r in runs),
            }
        )
    return rows


def kg_use(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """For strategies with both `search` and `kg`: how often runs call `kg`."""
    rows = []
    for strategy in sorted({r["strategy"] for r in records}):
        names = {t["name"] for t in TOOLS.get(strategy, [])}
        if not {"search", "kg"} <= names:
            continue
        runs = [r for r in records if r["strategy"] == strategy]
        kg_calls = [r.get("calls", []).count("kg") for r in runs]
        rows.append(
            {
                "strategy": strategy,
                "runs": len(runs),
                "with_kg": sum(n > 0 for n in kg_calls),
                "kg_calls": sum(kg_calls),
                "calls": sum(
                    len([c for c in r.get("calls", []) if c != "submit_answer"])
                    for r in runs
                ),
            }
        )
    return rows


def spread(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Range of score and context for each question and strategy run more than once."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in records:
        groups.setdefault((r["question"], r["strategy"]), []).append(r)
    rows = []
    for (question, strategy), runs in sorted(groups.items()):
        if len(runs) < 2:
            continue
        scores = [r["grade"]["score"] for r in runs]
        chars = [r["context_chars"] for r in runs if r.get("context_chars") is not None]
        rows.append(
            {
                "question": question,
                "strategy": strategy,
                "runs": len(runs),
                "score": (min(scores), max(scores)),
                "context_chars": (min(chars), max(chars)) if chars else None,
            }
        )
    return rows


def markdown(records: list[dict[str, Any]]) -> str:
    lines = [
        "## Per question",
        "",
        _header("Question", "Topic", "Strategy", "Outcome", *_METRICS),
    ]
    for r in sorted(records, key=lambda r: (r["question"], r["strategy"])):
        tin, tout = tokens(r)
        lines.append(
            f"| {r['question']} | {r['topic']} | {r['strategy']} | {r['outcome']} | "
            f"{r['grade']['score']:.2f} | {_fmt(r['traceability'])} | "
            f"{_int(tin)} | {_int(tout)} | {_int(total_tokens(r))} | "
            f"{_int(r.get('context_chars'))} | {r['turns']} | {r['seconds']} |"
        )
    lines += [
        "",
        "## Per strategy (means)",
        "",
        _header("Strategy", "Runs", "Answered", *_METRICS),
    ]
    for s in summary(records):
        lines.append(
            f"| {s['strategy']} | {s['runs']} | {s['answered']} | {s['score']:.2f} | "
            f"{_fmt(s['traceability'])} | {_int(s['input_tokens'])} | "
            f"{_int(s['output_tokens'])} | {_int(s['total_tokens'])} | "
            f"{_int(s['context_chars'])} | {s['turns']:.1f} | {s['seconds']:.1f} |"
        )
    if categories := by_category(records):
        lines += [
            "",
            "## Per category (means)",
            "",
            _header("Category", "Strategy", "Runs", "Score", "Context"),
        ]
        for c in categories:
            lines.append(
                f"| {c['category']} | {c['strategy']} | {c['runs']} | "
                f"{c['score']:.2f} | {_int(c['context_chars'])} |"
            )
    if choices := kg_use(records):
        lines += [
            "",
            "## Use of the graph (strategies that can also search the files)",
            "",
            _header("Strategy", "Runs", "Runs that call kg", "kg calls", "All calls"),
        ]
        for c in choices:
            lines.append(
                f"| {c['strategy']} | {c['runs']} | {c['with_kg']} | "
                f"{c['kg_calls']} | {c['calls']} |"
            )
    if repeated := spread(records):
        lines += [
            "",
            "## Repeated runs (min–max)",
            "",
            _header("Question", "Strategy", "Runs", "Score", "Context"),
        ]
        for s in repeated:
            low, high = s["score"]
            chars = s["context_chars"]
            context = "–" if chars is None else f"{chars[0]}–{chars[1]}"
            lines.append(
                f"| {s['question']} | {s['strategy']} | {s['runs']} | "
                f"{low:.2f}–{high:.2f} | {context} |"
            )
    n = len({r["question"] for r in records})
    lines += [
        "",
        f"{n} questions: enough to guide decisions, not to be statistically "
        "conclusive.",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m bench.report", description=__doc__)
    parser.add_argument("results", type=Path, nargs="+")
    args = parser.parse_args(argv)
    print(markdown(load(args.results)))
    return 0


_METRICS = (
    "Score",
    "Traceability",
    "Input tok.",
    "Output tok.",
    "Total tok.",
    "Context",
    "Turns",
    "Seconds",
)


def _header(*names: str) -> str:
    return f"| {' | '.join(names)} |\n|{'---|' * len(names)}"


def _mean(values: Any) -> float | None:
    """Mean of the known values; `None` if every value is unknown."""
    values = [v for v in values if v is not None]
    return statistics.fmean(values) if values else None


def _int(value: float | None) -> str:
    return "–" if value is None else f"{value:.0f}"


def _fmt(value: float | None) -> str:
    return "–" if value is None else f"{value:.2f}"


if __name__ == "__main__":
    sys.exit(main())
