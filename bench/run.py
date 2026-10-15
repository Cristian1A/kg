"""Run the benchmark: `python -m bench.run --help` (see `bench/README.md`).

Prepares each repo (a clone at a fixed commit plus its kg store), runs every
question with every strategy, grades the answers and appends one JSON line
per run to the results file. `--dry-run` does everything except calling the
model: it checks the questions, prepares the repos and exercises each tool.
"""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bench.agent import SYSTEM, run_question
from bench.grading import grade, traceability
from bench.tools import TOOLS, run_tool
from bench.topics import build_topic_stores

ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent
CACHE = ROOT / ".cache" / "repos"
DEFAULT_MODEL = "claude-opus-5-5"
STRATEGIES = ("code", "graph", "topic", "hybrid", "cards")


def load_questions(path: Path) -> list[dict[str, Any]]:
    """The questions of a file, checked against `repos.json`."""
    questions = json.loads(path.read_text(encoding="utf-8"))
    repos = {r["name"] for r in load_repos()}
    ids = [q["id"] for q in questions]
    if len(ids) != len(set(ids)):
        raise SystemExit(f"{path}: duplicate question IDs")
    for q in questions:
        if q["repo"] not in repos:
            raise SystemExit(f"{path}: {q['id']}: unknown repo {q['repo']!r}")
        if ("items" in q["expect"]) == ("keywords" in q["expect"]):
            raise SystemExit(f"{path}: {q['id']}: expect needs items or keywords")
    return questions


def load_repos() -> list[dict[str, Any]]:
    return json.loads((ROOT / "repos.json").read_text(encoding="utf-8"))


def prepare(repo: dict[str, Any]) -> Path:
    """Clone the repo at its commit and build its stores, once.

    With `graph_commit`, the store is built at that commit and the repo is
    then checked out at `commit`: a stale graph of the current code.
    """
    path = CACHE / repo["name"]
    if not (path / ".git").is_dir():
        CACHE.mkdir(parents=True, exist_ok=True)
        _run(["git", "clone", "--quiet", repo["url"], str(path)])
        _run(["git", "-C", str(path), "checkout", "--quiet", repo["commit"]])
    if not (path / ".kg").is_dir():
        kg_dir = str(path / ".kg")
        if graph_commit := repo.get("graph_commit"):
            _run(["git", "-C", str(path), "checkout", "--quiet", graph_commit])
        _run(["kg", "init", "--kg-dir", kg_dir])
        _run(["kg", "extract", str(path), "--kg-dir", kg_dir])
        _run(["kg", "add", str(REPO_ROOT / repo["agent"]), "--kg-dir", kg_dir])
        _run(["git", "-C", str(path), "checkout", "--quiet", repo["commit"]])
    build_topic_stores(path)
    head = _run(["git", "-C", str(path), "rev-parse", "--short=7", "HEAD"]).strip()
    if head != repo["commit"][:7]:
        raise SystemExit(f"{path} is at {head}, expected {repo['commit']}")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m bench.run", description=__doc__)
    parser.add_argument("--questions", type=Path, default=ROOT / "questions/pilot.json")
    parser.add_argument("--strategies", default=",".join(STRATEGIES))
    parser.add_argument("--only", help="question IDs to run, comma-separated")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--effort", default="medium")
    parser.add_argument("--max-turns", type=int, default=25)
    parser.add_argument(
        "--out", type=Path, help="JSONL file (default: results/<time>.jsonl)"
    )
    parser.add_argument("--dry-run", action="store_true", help="do not call the model")
    args = parser.parse_args(argv)

    strategies = [s for s in args.strategies.split(",") if s]
    if unknown := set(strategies) - set(STRATEGIES):
        parser.error(f"unknown strategies: {', '.join(sorted(unknown))}")
    questions = load_questions(args.questions)
    if args.only:
        wanted = set(args.only.split(","))
        questions = [q for q in questions if q["id"] in wanted]
    repos = {r["name"]: r for r in load_repos()}
    paths = {
        name: prepare(repos[name]) for name in sorted({q["repo"] for q in questions})
    }

    if args.dry_run:
        return _dry_run(questions, strategies, paths)

    import anthropic  # only needed to call the model: pip install -e ".[bench]"

    client = anthropic.Anthropic()
    out = args.out or ROOT / "results" / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    config = _config(args, strategies, repos)
    with out.open("a", encoding="utf-8") as f:
        for q in questions:
            for strategy in strategies:
                run = run_question(
                    client,
                    q,
                    strategy,
                    paths[q["repo"]],
                    args.model,
                    args.effort,
                    args.max_turns,
                )
                record = _record(q, run, paths[q["repo"]], config)
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                f.flush()
                usage = run.usage
                read = usage.input_tokens + usage.cache_read_input_tokens
                print(
                    f"{q['id']:<22} {strategy:<6} {run.outcome:<10} "
                    f"score {record['grade']['score']:.2f}  "
                    f"tokens {read}+{usage.output_tokens}  {run.seconds}s"
                )
    print(f"results: {out}")
    return 0


def _record(
    q: dict[str, Any], run: Any, repo: Path, config: dict[str, Any]
) -> dict[str, Any]:
    from kg import store

    graph = store.load_graph(repo / ".kg")
    evidence = (run.answer or {}).get("evidence") or []
    return {
        **run.to_dict(),
        "repo": q["repo"],
        "topic": q["topic"],
        "grade": grade(q["expect"], run.answer).to_dict(),
        "traceability": traceability(evidence, repo, graph),
        "config": config,
    }


def _config(
    args: argparse.Namespace, strategies: list[str], repos: dict
) -> dict[str, Any]:
    """Everything needed to repeat a run."""
    kg_version = _run(["kg", "--version"]).strip()
    return {
        "model": args.model,
        "effort": args.effort,
        "max_turns": args.max_turns,
        "strategies": strategies,
        "questions": str(args.questions.relative_to(REPO_ROOT)),
        "repos": {n: r["commit"] for n, r in sorted(repos.items())},
        "kg": kg_version,
        "kg_commit": _run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "--short", "HEAD"]
        ).strip(),
        "python": platform.python_version(),
        "system_prompt": SYSTEM,
    }


def _dry_run(
    questions: list[dict], strategies: list[str], paths: dict[str, Path]
) -> int:
    samples = {
        "code": ("list_files", {"glob": "*.md"}),
        "graph": ("kg", {"args": ["query", "find", "--type", "Repo"]}),
        "topic": ("kg", {"args": ["status"]}),
        "hybrid": ("kg", {"args": ["query", "find", "--type", "Repo"]}),
        "cards": ("kg", {"args": ["query", "find", "--type", "Repo"]}),
    }
    for name, path in paths.items():
        for strategy in strategies:
            tool, tool_args = samples[strategy]
            result = run_tool(strategy, path, tool, tool_args, "tests")
            print(f"{name} [{strategy}] {tool}: {len(result)} characters")
    tools = {s: [t["name"] for t in TOOLS[s]] for s in strategies}
    print(f"{len(questions)} questions × {len(strategies)} strategies; tools: {tools}")
    print("dry run: the model was not called")
    return 0


def _run(cmd: list[str]) -> str:
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise SystemExit(f"{' '.join(cmd)} failed:\n{proc.stderr}")
    return proc.stdout


if __name__ == "__main__":
    sys.exit(main())
