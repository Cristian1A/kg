"""Run the benchmark with coding-agent subagents instead of the API (#39).

`bench.run` drives the model through the API. This module runs the same
questions with the same confined tools, but the agent is a subagent started by
a coding agent (e.g. Claude Code's Agent tool), so no API key is needed:

1. `python -m bench.subagent prepare` writes one prompt per question and
   strategy into a session directory and prints the run directories.
2. Each subagent gets one prompt. Its only tool is
   `python -m bench.subagent call <run dir> <tool> [<json>]`, which runs the
   strategy's tool (`bench.tools.run_tool`), logs the call, caps the turns and
   stores the `submit_answer` input.
3. `python -m bench.subagent collect <session>` grades the answers and writes
   result lines in the format `bench.report` reads. Tokens and time come from
   the subagent notifications, passed with `--usage`.

The tool confinement is by instruction, not by sandbox: the call log lets the
person running the benchmark check that each subagent used only its tools.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bench.agent import SYSTEM
from bench.grading import grade, traceability
from bench.run import (
    CACHE,
    REPO_ROOT,
    ROOT,
    STRATEGIES,
    _run,
    load_questions,
    load_repos,
    prepare,
)
from bench.tools import STRATEGY_HINTS, TOOLS, Citations, ToolError, run_tool

SESSIONS = CACHE.parent / "subagent"
MAX_TURNS = 25

PROMPT = """You are an agent in a benchmark. {system}

## Tools

Your only tool is this shell command, run from `{cwd}`:

    {python} -m bench.subagent call {run_dir} <tool> '<JSON arguments>'

For long arguments, pass the JSON on standard input instead:

    {python} -m bench.subagent call {run_dir} submit_answer <<'EOF'
    {{"answer": "...", "items": [...], "evidence": [...]}}
    EOF

The tools and their JSON arguments:

{tools}

Rules:
- Use only that command. Do not read, list or search any file yourself, do
  not run any other command and do not use the web: the benchmark measures
  what these tools give you.
- You have at most {max_turns} calls, `submit_answer` included. Call
  `submit_answer` exactly once, at the end; it ends the run.
- After submitting, reply with one line: `submitted`.

## Question

{question}
"""


def prompt(question: dict[str, Any], strategy: str, run_dir: Path) -> str:
    """The prompt a subagent gets for one question and strategy."""
    system = SYSTEM.format(repo=question["repo"], hint=STRATEGY_HINTS[strategy])
    tools = "\n".join(
        f"- `{t['name']}` {json.dumps(t['input_schema']['properties'])}: "
        f"{t['description']}"
        for t in TOOLS[strategy]
    )
    return PROMPT.format(
        system=system.replace("call `submit_answer`", "call the `submit_answer` tool"),
        cwd=REPO_ROOT,
        python=Path(sys.executable).relative_to(REPO_ROOT, walk_up=True),
        run_dir=run_dir.relative_to(REPO_ROOT, walk_up=True),
        tools=tools,
        max_turns=MAX_TURNS,
        question=question["question"],
    )


def prepare_session(
    questions: list[dict[str, Any]],
    strategies: list[str],
    paths: dict[str, Path],
    session: Path,
) -> list[Path]:
    """Write one run directory (`run.json`, `prompt.md`) per question and strategy."""
    runs = []
    for q in questions:
        for strategy in strategies:
            run_dir = session / f"{q['id']}.{strategy}"
            run_dir.mkdir(parents=True, exist_ok=False)
            meta = {
                "question": q["id"],
                "strategy": strategy,
                "repo": q["repo"],
                "repo_path": str(paths[q["repo"]]),
                "topic": q["topic"],
                "category": q.get("category"),
            }
            (run_dir / "run.json").write_text(json.dumps(meta, indent=2) + "\n")
            (run_dir / "prompt.md").write_text(prompt(q, strategy, run_dir))
            runs.append(run_dir)
    return runs


def call(run_dir: Path, tool: str, raw: str) -> str:
    """Run one tool call for a subagent and log it in `calls.jsonl`."""
    meta = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    log = run_dir / "calls.jsonl"
    calls = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    if (run_dir / "answer.json").exists():
        return "Error: the answer was already submitted; the run is over."
    entry: dict[str, Any] = {"time": time.time(), "tool": tool}
    try:
        if len(calls) >= MAX_TURNS:
            raise ToolError(f"the limit of {MAX_TURNS} calls is reached")
        try:
            args = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ToolError(f"the arguments are not valid JSON: {e}") from e
        entry["args"] = args
        if tool == "submit_answer":
            answer = {k: args.get(k) for k in ("answer", "items", "evidence")}
            if not isinstance(answer["answer"], str) or not all(
                isinstance(answer[k], list) for k in ("items", "evidence")
            ):
                raise ToolError("submit_answer needs answer (text), items and evidence")
            (run_dir / "answer.json").write_text(json.dumps(answer, indent=2) + "\n")
            result = "Answer submitted. Reply `submitted`."
        else:
            cited_file = run_dir / "citations.json"
            cited = Citations(
                json.loads(cited_file.read_text()) if cited_file.exists() else None
            )
            result = run_tool(
                meta["strategy"],
                Path(meta["repo_path"]),
                tool,
                args,
                meta["topic"],
                cited,
            )
            if meta["strategy"] in ("hybrid", "cards"):
                cited_file.write_text(json.dumps(cited.ranges) + "\n")
    except ToolError as e:
        entry["error"] = str(e)
        result = f"Error: {e}"
    entry["chars"] = len(result)
    with log.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return result


def collect(
    session: Path, questions: dict[str, dict[str, Any]], usage: dict[str, Any]
) -> list[dict[str, Any]]:
    """One result record per run directory, graded like `bench.run` does."""
    from kg import store

    records = []
    for run_dir in sorted(p for p in session.iterdir() if (p / "run.json").is_file()):
        meta = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        q = questions[meta["question"]]
        repo = Path(meta["repo_path"])
        answer_file = run_dir / "answer.json"
        answer = json.loads(answer_file.read_text()) if answer_file.exists() else None
        log = run_dir / "calls.jsonl"
        calls = [
            json.loads(line)
            for line in (log.read_text().splitlines() if log.exists() else [])
        ]
        if answer is not None:
            outcome = "answered"
        elif len(calls) >= MAX_TURNS:
            outcome = "max_turns"
        else:
            outcome = "no_answer"
        own = usage.get(run_dir.name, {})
        span = calls[-1]["time"] - calls[0]["time"] if calls else 0.0
        evidence = (answer or {}).get("evidence") or []
        records.append(
            {
                "question": meta["question"],
                "strategy": meta["strategy"],
                "model": own.get("model"),
                "effort": None,
                "answer": answer,
                "outcome": outcome,
                "turns": len(calls),
                "tool_calls": sum(c["tool"] != "submit_answer" for c in calls),
                "tool_errors": sum("error" in c for c in calls),
                "context_chars": context_chars(meta, calls),
                "seconds": own.get("seconds", round(span, 2)),
                "usage": {"total_tokens": own.get("total_tokens")},
                "repo": meta["repo"],
                "topic": q["topic"],
                "category": q.get("category"),
                "grade": grade(q["expect"], answer).to_dict(),
                "traceability": traceability(
                    evidence, repo, store.load_graph(repo / ".kg")
                ),
                "calls": [c["tool"] for c in calls],
            }
        )
    return records


def context_chars(meta: dict[str, Any], calls: list[dict[str, Any]]) -> int:
    """Characters of every tool result of a run: the context it loaded.

    Runs logged before `chars` was recorded are replayed: the tools are
    deterministic over a pinned repo and its store.
    """
    if all("chars" in c for c in calls):
        return sum(c["chars"] for c in calls)
    cited, total = Citations(), 0
    for c in calls:
        if "chars" in c:
            total += c["chars"]
        elif c["tool"] == "submit_answer" or "args" not in c:
            total += len(f"Error: {c['error']}") if "error" in c else 0
        else:
            try:
                total += len(
                    run_tool(
                        meta["strategy"],
                        Path(meta["repo_path"]),
                        c["tool"],
                        c["args"],
                        meta.get("topic", ""),
                        cited,
                    )
                )
            except ToolError as e:
                total += len(f"Error: {e}")
    return total


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m bench.subagent",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare", help="write the prompts of a new session")
    p.add_argument("--questions", type=Path, default=ROOT / "questions/pilot.json")
    p.add_argument("--strategies", default=",".join(STRATEGIES))
    p.add_argument("--only", help="question IDs, comma-separated")
    c = sub.add_parser("call", help="run one tool call for a subagent")
    c.add_argument("run_dir", type=Path)
    c.add_argument("tool")
    c.add_argument("json", nargs="?", help="JSON arguments (default: stdin)")
    k = sub.add_parser("collect", help="grade a session and write result lines")
    k.add_argument("session", type=Path)
    k.add_argument(
        "--usage",
        type=Path,
        help='JSON {"<run dir name>": {"total_tokens": n, "seconds": s, "model": m}}',
    )
    k.add_argument(
        "--out", type=Path, help="JSONL file (default: results/<time>.jsonl)"
    )
    args = parser.parse_args(argv)

    if args.command == "call":
        raw = args.json if args.json is not None else sys.stdin.read()
        print(call(args.run_dir, args.tool, raw))
        return 0

    if args.command == "prepare":
        strategies = [s for s in args.strategies.split(",") if s]
        if unknown := set(strategies) - set(STRATEGIES):
            parser.error(f"unknown strategies: {', '.join(sorted(unknown))}")
        questions = load_questions(args.questions)
        if args.only:
            questions = [q for q in questions if q["id"] in set(args.only.split(","))]
        repos = {r["name"]: r for r in load_repos()}
        paths = {n: prepare(repos[n]) for n in sorted({q["repo"] for q in questions})}
        session = SESSIONS / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}"
        runs = prepare_session(questions, strategies, paths, session)
        config = {
            "runner": "subagent",
            "max_turns": MAX_TURNS,
            "strategies": strategies,
            "questions": str(args.questions.resolve().relative_to(REPO_ROOT)),
            "repos": {n: r["commit"] for n, r in sorted(repos.items())},
            "kg": _run(["kg", "--version"]).strip(),
            "kg_commit": _run(
                ["git", "-C", str(REPO_ROOT), "rev-parse", "--short", "HEAD"]
            ).strip(),
        }
        (session / "config.json").write_text(json.dumps(config, indent=2) + "\n")
        print(f"session: {session}")
        for run_dir in runs:
            print(run_dir / "prompt.md")
        return 0

    config = json.loads((args.session / "config.json").read_text(encoding="utf-8"))
    questions = {q["id"]: q for q in load_questions(REPO_ROOT / config["questions"])}
    usage = json.loads(args.usage.read_text()) if args.usage else {}
    out = args.out or ROOT / "results" / f"{args.session.name}-subagent.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for record in collect(args.session, questions, usage):
            f.write(json.dumps({**record, "config": config}, ensure_ascii=False) + "\n")
            print(
                f"{record['question']:<22} {record['strategy']:<6} "
                f"{record['outcome']:<10} score {record['grade']['score']:.2f}  "
                f"calls {record['turns']}"
            )
    print(f"results: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
