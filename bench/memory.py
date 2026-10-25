"""Experiment 2 (#71): answer questions about a project's history, with memory.

Every strategy gets the same tools as S0, the repository at the question's
commit plus its git log, and differs only in the memory context its prompt
carries (N2-01). The context is a function of the question and the store
(R2-12), the same on every run (N2-03):

- `s0`: no memory.
- `s2`: the K best memories by SQLite FTS5 (BM25) over the question's words,
  as Engram ranks them: each word quoted, joined by OR, title weighted 5 and
  content 1 (`docs/experiment-2/engram.md`).

The store is the curated corpus (`corpus/kg/`, one kg document per session)
merged in order up to the session pinned at the question's commit. Runs use
subagents, as `bench.subagent` does:

    python -m bench.memory prepare --strategies s0,s2 --repeat 3
    python -m bench.memory call <run dir> <tool> '<JSON>'
    python -m bench.memory collect <session> --usage usage.json
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import networkx as nx

from bench import subagent
from bench.grading import grade
from bench.run import CACHE, REPO_ROOT, ROOT, _run
from bench.tools import CODE_TOOLS, SUBMIT, ToolError, _clip, list_files, read_file
from bench.tools import search as search_files

CORPUS = ROOT / "corpus/kg"
QUESTIONS = ROOT / "questions/memory/kg.json"
SESSIONS = CACHE.parent / "memory"
STRATEGIES = ("s0", "s2")
MEMORY_TYPES = ("Decision", "Task", "Experiment", "Issue", "Constraint", "Session")
TOP_K = 8
# Engram's BM25 column weights (internal/store/store.go): title 5, content 1
FTS_WEIGHTS = {"id": 0.0, "title": 5.0, "content": 1.0, "type": 0.0}
MAX_LOG = 200  # commits per git_log call

SYSTEM = """You answer questions about the history of a software project, kg:
what was decided and why, what was tried, what changed and what is pending.

{hint}

Answer only from what you are given and what the tools return; do not guess
from general knowledge. When you are done, call `submit_answer` once with:
- `answer`: the answer in a few sentences;
- `items`: an empty list, unless the question asks for a list;
- `evidence`: what supports the answer: file paths with lines, commits, issue
  or PR numbers, memory IDs."""

REPO_HINT = (
    "You can list, read and search the repository's files at its current "
    "commit, and read its git log."
)
HINTS = {
    "s0": REPO_HINT + " There is no record of the project's past work sessions.",
    "s2": REPO_HINT
    + " The project also keeps a memory: records of its past work sessions and "
    "what they decided, tried and left pending. A full-text search of that "
    "memory with your question returned the memories below. They may be "
    "incomplete, and each says its status: a superseded or invalidated memory "
    "no longer holds.",
}

GIT_LOG = {
    "name": "git_log",
    "description": "The repository's commit history up to its current commit, "
    f"newest first, at most {MAX_LOG} commits per call: hash, date, subject and "
    "body. `grep` keeps the commits whose message matches it (case-insensitive "
    "regular expression); `path` keeps those that touch a file or directory; "
    "null for no filter.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "grep": {"type": ["string", "null"]},
            "path": {"type": ["string", "null"]},
            "max_count": {"type": ["integer", "null"]},
        },
        "required": ["grep", "path", "max_count"],
        "additionalProperties": False,
    },
}
TOOLS = [*CODE_TOOLS[:3], GIT_LOG, SUBMIT]


# --- store -------------------------------------------------------------------------


def snapshot(commit: str, corpus: Path = CORPUS) -> list[Path]:
    """The session files up to the one pinned at `commit`, in order."""
    files = sorted(corpus.glob("*.json"))
    for n, path in enumerate(files, start=1):
        doc = json.loads(path.read_text(encoding="utf-8"))
        session = next(x for x in doc["nodes"] if x["type"] == "Session")
        if session["attrs"]["commit"] == commit:
            return files[:n]
    raise ValueError(f"no session of {corpus} is pinned at {commit}")


def load_memory(files: list[Path]) -> nx.MultiDiGraph:
    """Merge the session files in order into a fresh kg store and load it."""
    from kg import store
    from kg.merge import add_to_store

    with tempfile.TemporaryDirectory() as tmp:
        kg_dir = Path(tmp) / ".kg"
        store.init_store(kg_dir)
        for path in files:
            result = add_to_store(kg_dir, path.read_text(encoding="utf-8"))
            if not result.validation.ok:
                raise ValueError(f"{path.name} is not valid")
        return store.load_graph(kg_dir)


def memories(graph: nx.MultiDiGraph) -> list[str]:
    """IDs of the memories, sessions included, in ID order."""
    return sorted(n for n, d in graph.nodes(data=True) if d["type"] in MEMORY_TYPES)


def render(graph: nx.MultiDiGraph, node: str) -> str:
    """A memory as the agent sees it: a header line, its title and its body."""
    d = graph.nodes[node]
    attrs = d.get("attrs", {})
    if d["type"] == "Session":
        head = f"[{node}] Session · {attrs['date']} · commit {attrs['commit']}"
    else:
        head = (
            f"[{node}] {d['type']} · {attrs['status']} · {attrs['created']} · "
            f"{attrs['session']}"
        )
    return "\n".join([head, d.get("label", ""), d.get("description", "")])


def fts_index(graph: nx.MultiDiGraph) -> sqlite3.Connection:
    """An in-memory FTS5 index of the memories' text, derived from the store."""
    conn = sqlite3.connect(":memory:")
    conn.execute(f"CREATE VIRTUAL TABLE memories USING fts5({', '.join(FTS_WEIGHTS)})")
    conn.executemany(
        "INSERT INTO memories VALUES (?, ?, ?, ?)",
        [
            (
                n,
                graph.nodes[n].get("label", ""),
                graph.nodes[n].get("description", ""),
                graph.nodes[n]["type"],
            )
            for n in memories(graph)
        ],
    )
    return conn


def fts_query(text: str) -> str:
    """Engram's candidate query: every word quoted, joined by OR."""
    words = dict.fromkeys(w.strip('"') for w in text.split())
    return " OR ".join('"' + w.replace('"', '""') + '"' for w in words if w)


def fts_search(conn: sqlite3.Connection, text: str, k: int = TOP_K) -> list[str]:
    """The IDs of the `k` best memories for `text`, best first."""
    query = fts_query(text)
    if not query:
        return []
    weights = ", ".join(str(w) for w in FTS_WEIGHTS.values())
    rows = conn.execute(
        f"SELECT id FROM memories WHERE memories MATCH ? "
        f"ORDER BY bm25(memories, {weights}), id LIMIT ?",
        (query, k),
    )
    return [r[0] for r in rows]


def context(strategy: str, question: str, graph: nx.MultiDiGraph) -> str:
    """The memory context a strategy puts in the prompt ('' for S0)."""
    if strategy == "s0":
        return ""
    if strategy == "s2":
        ids = fts_search(fts_index(graph), question)
        return "\n\n".join(render(graph, n) for n in ids)
    raise ValueError(f"unknown strategy {strategy!r}")


# --- repository and tools -----------------------------------------------------------


def prepare_repo(commit: str) -> Path:
    """A clone of this repository at `commit`, with no other branch or remote.

    The agent sees the files and the history up to `commit`, nothing later.
    """
    path = SESSIONS / "repos" / commit
    if not (path / ".git").is_dir():
        path.parent.mkdir(parents=True, exist_ok=True)
        _run(["git", "clone", "--quiet", "--no-checkout", str(REPO_ROOT), str(path)])
        _run(["git", "-C", str(path), "checkout", "--quiet", "--detach", commit])
        _run(["git", "-C", str(path), "remote", "remove", "origin"])
        branches = _run(
            [
                "git",
                "-C",
                str(path),
                "for-each-ref",
                "--format=%(refname:short)",
                "refs/heads",
            ]
        )
        for branch in branches.split():
            _run(["git", "-C", str(path), "branch", "--quiet", "-D", branch])
    head = _run(["git", "-C", str(path), "rev-parse", "--short=7", "HEAD"]).strip()
    if head != commit[:7]:
        raise SystemExit(f"{path} is at {head}, expected {commit}")
    return path


def git_log(repo: Path, args: dict[str, Any]) -> str:
    count = min(max(1, args.get("max_count") or MAX_LOG), MAX_LOG)
    cmd = [
        "git",
        "-C",
        str(repo),
        "log",
        "HEAD",
        f"-n{count}",
        "--date=short",
        "--format=%h %ad %s%n%b",
    ]
    if args.get("grep"):
        cmd += ["-i", "-E", f"--grep={args['grep']}"]
    if args.get("path"):
        cmd += ["--", args["path"]]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
    if proc.returncode:
        raise ToolError(proc.stderr.strip() or "git log failed")
    return proc.stdout.strip() or "no commits match"


HANDLERS = {
    "list_files": list_files,
    "read_file": read_file,
    "search": search_files,
    "git_log": git_log,
}


def run_tool(
    run_dir: Path, meta: dict[str, Any], tool: str, args: dict[str, Any]
) -> str:
    """A `bench.subagent.call` runner for the memory strategies' tools."""
    if tool not in HANDLERS:
        raise ToolError(f"unknown tool {tool!r}")
    return _clip(HANDLERS[tool](Path(meta["repo_path"]), args))


# --- runs ---------------------------------------------------------------------------


def prompt(question: dict[str, Any], strategy: str, run_dir: Path, memory: str) -> str:
    system = SYSTEM.format(hint=HINTS[strategy])
    if memory:
        system += "\n\n## Memory\n\n" + memory
    tools = "\n".join(
        f"- `{t['name']}` {json.dumps(t['input_schema']['properties'])}: "
        f"{t['description']}"
        for t in TOOLS
    )
    return subagent.PROMPT.replace("bench.subagent", "bench.memory").format(
        system=system.replace("call `submit_answer`", "call the `submit_answer` tool"),
        cwd=REPO_ROOT,
        python=Path(sys.executable).relative_to(REPO_ROOT, walk_up=True),
        run_dir=run_dir.relative_to(REPO_ROOT, walk_up=True),
        tools=tools,
        max_turns=subagent.MAX_TURNS,
        question=question["question"],
    )


def prepare_session(
    questions: list[dict[str, Any]],
    strategies: list[str],
    repeat: int,
    session: Path,
    corpus: Path = CORPUS,
) -> list[Path]:
    """One run directory (`run.json`, `prompt.md`) per question, strategy and repeat."""
    graphs: dict[str, nx.MultiDiGraph] = {}
    runs = []
    for q in questions:
        if q["commit"] not in graphs:
            graphs[q["commit"]] = load_memory(snapshot(q["commit"], corpus))
        repo = prepare_repo(q["commit"])
        for strategy in strategies:
            memory = context(strategy, q["question"], graphs[q["commit"]])
            for n in range(1, repeat + 1):
                run_dir = session / f"{q['id']}.{strategy}.{n}"
                run_dir.mkdir(parents=True, exist_ok=False)
                meta = {
                    "question": q["id"],
                    "strategy": strategy,
                    "repeat": n,
                    "repo_path": str(repo),
                    "commit": q["commit"],
                    "category": q["category"],
                    "memory_chars": len(memory),
                }
                (run_dir / "run.json").write_text(json.dumps(meta, indent=2) + "\n")
                (run_dir / "prompt.md").write_text(prompt(q, strategy, run_dir, memory))
                runs.append(run_dir)
    return runs


def collect(
    session: Path, questions: dict[str, dict[str, Any]], usage: dict[str, Any]
) -> list[dict[str, Any]]:
    """One result record per run, in the fields `bench.report` reads."""
    records = []
    for run_dir in sorted(p for p in session.iterdir() if (p / "run.json").is_file()):
        meta = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        q = questions[meta["question"]]
        answer_file = run_dir / "answer.json"
        answer = json.loads(answer_file.read_text()) if answer_file.exists() else None
        log = run_dir / "calls.jsonl"
        calls = [
            json.loads(x)
            for x in (log.read_text().splitlines() if log.exists() else [])
        ]
        if answer is not None:
            outcome = "answered"
        elif len(calls) >= subagent.MAX_TURNS:
            outcome = "max_turns"
        else:
            outcome = "no_answer"
        own = usage.get(run_dir.name, {})
        span = calls[-1]["time"] - calls[0]["time"] if calls else 0.0
        records.append(
            {
                "question": meta["question"],
                "strategy": meta["strategy"],
                "repeat": meta["repeat"],
                "model": own.get("model"),
                "effort": None,
                "answer": answer,
                "outcome": outcome,
                "turns": len(calls),
                "tool_calls": sum(c["tool"] != "submit_answer" for c in calls),
                "tool_errors": sum("error" in c for c in calls),
                "memory_chars": meta["memory_chars"],
                "context_chars": meta["memory_chars"]
                + sum(c.get("chars", 0) for c in calls),
                "seconds": own.get("seconds", round(span, 2)),
                "usage": {"total_tokens": own.get("total_tokens")},
                "repo": "kg",
                "topic": "decisions",
                "category": q["category"],
                "lives_in": q["lives_in"],
                "grade": grade(q["expect"], answer).to_dict(),
                "traceability": None,
                "calls": [c["tool"] for c in calls],
            }
        )
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m bench.memory",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare", help="write the prompts of a new session")
    p.add_argument("--questions", type=Path, default=QUESTIONS)
    p.add_argument("--strategies", default=",".join(STRATEGIES))
    p.add_argument("--only", help="question IDs, comma-separated")
    p.add_argument("--repeat", type=int, default=3, help="runs per question (R2-15)")
    c = sub.add_parser("call", help="run one tool call for a subagent")
    c.add_argument("run_dir", type=Path)
    c.add_argument("tool")
    c.add_argument("json", nargs="?", help="JSON arguments (default: stdin)")
    k = sub.add_parser("collect", help="grade a session and write result lines")
    k.add_argument("session", type=Path)
    k.add_argument("--usage", type=Path, help="as for `bench.subagent collect`")
    k.add_argument("--out", type=Path, help="JSONL file (default: results/memory/)")
    args = parser.parse_args(argv)

    if args.command == "call":
        raw = args.json if args.json is not None else sys.stdin.read()
        print(subagent.call(args.run_dir, args.tool, raw, run_tool))
        return 0

    if args.command == "prepare":
        strategies = [s for s in args.strategies.split(",") if s]
        if unknown := set(strategies) - set(STRATEGIES):
            parser.error(f"unknown strategies: {', '.join(sorted(unknown))}")
        questions = json.loads(args.questions.read_text(encoding="utf-8"))
        if args.only:
            questions = [q for q in questions if q["id"] in set(args.only.split(","))]
        session = SESSIONS / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}"
        runs = prepare_session(questions, strategies, args.repeat, session)
        config = {
            "runner": "subagent",
            "experiment": 2,
            "max_turns": subagent.MAX_TURNS,
            "strategies": strategies,
            "repeat": args.repeat,
            "top_k": TOP_K,
            "questions": str(args.questions.resolve().relative_to(REPO_ROOT)),
            "corpus": str(CORPUS.relative_to(REPO_ROOT)),
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
    path = REPO_ROOT / config["questions"]
    questions = {q["id"]: q for q in json.loads(path.read_text(encoding="utf-8"))}
    usage = json.loads(args.usage.read_text()) if args.usage else {}
    out = args.out or ROOT / "results/memory" / f"{args.session.name}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for record in collect(args.session, questions, usage):
            f.write(json.dumps({**record, "config": config}, ensure_ascii=False) + "\n")
            print(
                f"{record['question']:<8} {record['strategy']:<3} {record['repeat']} "
                f"{record['outcome']:<10} score {record['grade']['score']:.2f}  "
                f"calls {record['turns']}"
            )
    print(f"results: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
