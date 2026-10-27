"""Experiment 2 (#71): answer questions about a project's history, with memory.

Every strategy gets the same tools as S0, the repository at the question's
commit plus its git log, and differs only in the memory context its prompt
carries (N2-01). The context is a function of the question and the store
(R2-12), the same on every run (N2-03):

- `s0`: no memory.
- `s1`: every memory, oldest first: the upper bound on recall.
- `s2`: the K best memories by SQLite FTS5 (BM25) over the question's words,
  as Engram ranks them: each word quoted, joined by OR, title weighted 5 and
  content 1 (`docs/experiment-2/engram.md`).
- `s2r`: S2 where each memory's text also holds its relations, written as
  S4 shows them (R2-09): it tells what the graph adds beyond keywords.
- `s3`: the K memories nearest the question by cosine similarity of
  `all-MiniLM-L6-v2` embeddings of title and body (needs the `memory` extra).
- `s4`: graph traversal. The 3 best FTS5 memories are seeds; the typed
  relations of the store are followed to depth 2, the closest and most
  telling links first, up to K memories, each shown with its relations.
- `s8`: hybrid. The 4 best FTS5 memories are seeds; their neighbours at
  depth 1 fill the K, in FTS5 order, each shown with its relations and its
  evidence (issues, PRs, commits, files).

The store is the curated corpus (`corpus/kg/`, one kg document per session)
merged in order up to the session pinned at the question's commit. Runs use
subagents, as `bench.subagent` does:

    python -m bench.memory prepare --strategies s0,s2 --repeat 3
    python -m bench.memory call <run dir> <tool> '<JSON>'
    python -m bench.memory status <session>
    python -m bench.memory usage <session> ~/.claude/projects/<project>/<id>/subagents
    python -m bench.memory collect <session>
"""

from __future__ import annotations

import argparse
import functools
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
STRATEGIES = ("s0", "s1", "s2", "s2r", "s3", "s4", "s8")
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
MEMORY_TYPES = ("Decision", "Task", "Experiment", "Issue", "Constraint", "Session")
TOP_K = 8
# Engram's BM25 column weights (internal/store/store.go): title 5, content 1
FTS_WEIGHTS = {"id": 0.0, "title": 5.0, "content": 1.0, "type": 0.0}
MAX_LOG = 200  # commits per git_log call
# S4 and S8: FTS5 seeds, then the store's relations up to a depth (R2-12)
SEEDS = {"s4": 3, "s8": 4}
DEPTH = {"s4": 2, "s8": 1}
# Relations between two memories a traversal follows, as (link, priority):
# a recorded reason, replacement or block first, then a shared issue, PR,
# commit or file, then the session that produced a memory. Components are
# not followed: one is shared by up to 19 memories, so it links nearly all.
DIRECT = ("supersedes", "blocked_by", "decided_because")
ANCHORS = ("supported_by", "invalidated_by")
PRIORITY = {"direct": 0, "evidence": 1, "session": 2}
# How an edge reads from its source and from its target
SHOWN = {
    "supersedes": ("supersedes", "superseded by"),
    "blocked_by": ("blocked by", "blocks"),
    "decided_because": ("decided because of", "reason for"),
    "invalidated_by": ("invalidated by", "invalidates"),
    "affects": ("affects", "affected by"),
}

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
}
MEMORY_HINT = (
    " The project also keeps a memory: records of its past work sessions and "
    "what they decided, tried and left pending. {how} They may be incomplete, "
    "and each says its status: a superseded or invalidated memory no longer "
    "holds."
)
HOW = {
    "s1": "The whole memory is below, oldest first.",
    "s2": "A full-text search of that memory with your question returned the "
    "memories below.",
    "s2r": "A full-text search of that memory with your question returned the "
    "memories below. Under each memory are its relations: what it supersedes, "
    "what blocks it, what it was decided because of, what it affects.",
    "s3": "A semantic search of that memory with your question returned the "
    "memories below, the closest in meaning first.",
    "s4": "A full-text search of that memory with your question found the first "
    "memories below; the rest are linked to them by the memory's recorded "
    "relations. Under each memory are its relations: what it supersedes, what "
    "blocks it, what it was decided because of, what it affects.",
    "s8": "A full-text search of that memory with your question found the first "
    "memories below; the rest are linked to them by the memory's recorded "
    "relations. Under each memory are its relations and its evidence: the "
    "issues, PRs, commits and files that support it.",
}
HINTS.update({s: REPO_HINT + MEMORY_HINT.format(how=h) for s, h in HOW.items()})

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


def fts_index(
    graph: nx.MultiDiGraph, with_relations: bool = False
) -> sqlite3.Connection:
    """An in-memory FTS5 index of the memories' text, derived from the store.

    With `with_relations` (S2r), a memory's content also holds its relation
    lines, so the relation targets' IDs and titles are searchable as text.
    """
    conn = sqlite3.connect(":memory:")
    conn.execute(f"CREATE VIRTUAL TABLE memories USING fts5({', '.join(FTS_WEIGHTS)})")
    rows = []
    for n in memories(graph):
        content = graph.nodes[n].get("description", "")
        if with_relations:
            content = "\n".join([content, *relations(graph, n)])
        rows.append(
            (n, graph.nodes[n].get("label", ""), content, graph.nodes[n]["type"])
        )
    conn.executemany("INSERT INTO memories VALUES (?, ?, ?, ?)", rows)
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


@functools.cache
def _embedding_model() -> Any:
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(EMBEDDING_MODEL, device="cpu")


def embed(texts: list[str]) -> Any:
    """Unit-length `all-MiniLM-L6-v2` embeddings of `texts`, one row each."""
    return _embedding_model().encode(
        texts, normalize_embeddings=True, convert_to_numpy=True
    )


def semantic_search(
    graph: nx.MultiDiGraph, text: str, k: int = TOP_K, encode: Any = None
) -> list[str]:
    """The IDs of the `k` memories nearest `text` by cosine similarity (S3).

    A memory is embedded as its title and body. Ties go to the smaller ID, so
    the result is the same on every run (N2-03). `encode` replaces `embed` in
    tests.
    """
    ids = memories(graph)
    if not ids:
        return []
    texts = [
        f"{graph.nodes[n].get('label', '')}\n{graph.nodes[n].get('description', '')}"
        for n in ids
    ]
    vectors = (encode or embed)([text, *texts])
    query, rows = vectors[0], vectors[1:]
    scores = [
        round(float(sum(a * b for a, b in zip(query, r, strict=True))), 6) for r in rows
    ]
    ranked = sorted(zip(ids, scores, strict=True), key=lambda x: (-x[1], x[0]))
    return [n for n, _ in ranked[:k]]


def is_memory(graph: nx.MultiDiGraph, node: str) -> bool:
    return graph.nodes[node]["type"] in MEMORY_TYPES


def linked(graph: nx.MultiDiGraph, node: str) -> dict[str, int]:
    """The memories one link from `node`, each with its best link's priority."""
    found: dict[str, int] = {}

    def add(other: str, link: str) -> None:
        if other != node and is_memory(graph, other):
            found[other] = min(found.get(other, PRIORITY[link]), PRIORITY[link])

    for u, v, d in [
        *graph.out_edges(node, data=True),
        *graph.in_edges(node, data=True),
    ]:
        other = v if u == node else u
        if d["type"] in DIRECT:
            add(other, "direct")
        elif d["type"] == "produced":
            add(other, "session")
        elif d["type"] in ANCHORS and graph.nodes[other]["type"] == "Evidence":
            for w, _, e in graph.in_edges(other, data=True):
                if e["type"] in ANCHORS:
                    add(w, "evidence")
    return found


def traverse(
    graph: nx.MultiDiGraph, seeds: list[str], depth: int
) -> dict[str, tuple[int, int, int]]:
    """Memories within `depth` links of the seeds: (hops, priority, seed rank).

    Each memory keeps its shortest path, and among those its best link and
    then the best-ranked seed it was reached from.
    """
    found = {s: (0, 0, rank) for rank, s in enumerate(seeds)}
    frontier = list(seeds)
    for hop in range(1, depth + 1):
        reached: dict[str, tuple[int, int, int]] = {}
        for node in frontier:
            for other, priority in linked(graph, node).items():
                if other not in found:
                    path = (hop, priority, found[node][2])
                    reached[other] = min(reached.get(other, path), path)
        found.update(reached)
        frontier = sorted(reached)
    return found


def relations(graph: nx.MultiDiGraph, node: str) -> list[str]:
    """A memory's typed relations, as lines under it (S4, S8)."""
    lines = []
    edges = [(d["type"], 0, v) for _, v, d in graph.out_edges(node, data=True)]
    edges += [(d["type"], 1, u) for u, _, d in graph.in_edges(node, data=True)]
    for kind, side, other in sorted(edges):
        if kind in SHOWN:
            label = graph.nodes[other].get("label", "")
            lines.append(f"- {SHOWN[kind][side]}: [{other}] {label}".rstrip())
    return lines


def evidence(graph: nx.MultiDiGraph, node: str) -> list[str]:
    """The evidence a memory is anchored to, as lines under it (S8)."""
    lines = []
    for _, v, d in sorted(graph.out_edges(node, data=True), key=lambda e: e[1]):
        if d["type"] == "supported_by" and graph.nodes[v]["type"] == "Evidence":
            attrs = graph.nodes[v].get("attrs", {})
            anchor = " ".join(
                str(attrs[k]) for k in ("kind", "ref", "commit") if attrs.get(k)
            )
            lines.append(f"- evidence: {anchor}: {graph.nodes[v].get('label', '')}")
    return lines


def by_age(graph: nx.MultiDiGraph, node: str) -> tuple[str, str]:
    attrs = graph.nodes[node].get("attrs", {})
    return (attrs.get("created") or attrs.get("date") or "", node)


def context(strategy: str, question: str, graph: nx.MultiDiGraph) -> str:
    """The memory context a strategy puts in the prompt ('' for S0)."""
    if strategy == "s0":
        return ""
    if strategy == "s1":
        ids = sorted(memories(graph), key=lambda n: by_age(graph, n))
        return "\n\n".join(render(graph, n) for n in ids)
    if strategy == "s2":
        ids = fts_search(fts_index(graph), question)
        return "\n\n".join(render(graph, n) for n in ids)
    if strategy == "s2r":
        ids = fts_search(fts_index(graph, with_relations=True), question)
        return "\n\n".join(
            "\n".join([render(graph, n), *relations(graph, n)]) for n in ids
        )
    if strategy == "s3":
        ids = semantic_search(graph, question)
        return "\n\n".join(render(graph, n) for n in ids)
    if strategy in ("s4", "s8"):
        conn = fts_index(graph)
        seeds = fts_search(conn, question, SEEDS[strategy])
        found = traverse(graph, seeds, DEPTH[strategy])
        if strategy == "s4":
            # the graph alone orders the rest: closest, then most telling link
            ids = sorted(found, key=lambda n: (*found[n], n))[:TOP_K]
        else:
            # text relevance orders the neighbours; unmatched ones go last
            text = {n: r for r, n in enumerate(fts_search(conn, question, len(graph)))}
            ids = sorted(
                found,
                key=lambda n: (found[n][0], text.get(n, len(text)), *found[n][1:], n),
            )[:TOP_K]
        parts = []
        for n in ids:
            lines = [render(graph, n), *relations(graph, n)]
            if strategy == "s8":
                lines += evidence(graph, n)
            parts.append("\n".join(lines))
        return "\n\n".join(parts)
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


def usage_from_transcripts(session: Path, transcripts: Path) -> dict[str, Any]:
    """Tokens, seconds and model of each run, read from the subagents' transcripts.

    A Claude Code subagent's transcript (`subagents/agent-*.jsonl`) starts with
    the message that names its run's `prompt.md`. Tokens are those of its last
    request, as the subagent notification reports them; seconds go from its
    first event to its last. Runs with no transcript are left out.
    """
    usage = {}
    for path in sorted(transcripts.glob("*.jsonl")):
        events = [json.loads(line) for line in path.read_text().splitlines() if line]
        first = next((e for e in events if e.get("type") == "user"), None)
        if first is None or not isinstance(first["message"].get("content"), str):
            continue
        text = first["message"]["content"]
        name = next(
            (
                p.parent.name
                for p in map(Path, text.split())
                if p.name == "prompt.md" and p.parent.parent == session
            ),
            None,
        )
        replies = [e["message"] for e in events if e.get("type") == "assistant"]
        if name is None or not replies:
            continue
        u = replies[-1]["usage"]
        times = sorted(
            datetime.fromisoformat(e["timestamp"].replace("Z", "+00:00"))
            for e in events
            if e.get("timestamp")
        )
        usage[name] = {
            "total_tokens": u["input_tokens"]
            + u["cache_creation_input_tokens"]
            + u["cache_read_input_tokens"]
            + u["output_tokens"],
            "seconds": round((times[-1] - times[0]).total_seconds(), 2),
            "model": replies[-1]["model"],
        }
    return usage


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
    u = sub.add_parser("usage", help="write <session>/usage.json from the transcripts")
    u.add_argument("session", type=Path)
    u.add_argument("transcripts", type=Path, help="a directory of agent-*.jsonl")
    s = sub.add_parser("status", help="which runs of a session are done")
    s.add_argument("session", type=Path)
    args = parser.parse_args(argv)

    if args.command == "usage":
        session = args.session.resolve()
        out = session / "usage.json"
        usage = json.loads(out.read_text()) if out.exists() else {}
        usage.update(usage_from_transcripts(session, args.transcripts))
        out.write_text(json.dumps(usage, indent=2, sort_keys=True) + "\n")
        print(f"{len(usage)} runs with usage: {out}")
        return 0

    if args.command == "status":
        done, pending = [], []
        for run_dir in sorted(p for p in args.session.iterdir() if p.is_dir()):
            log = run_dir / "calls.jsonl"
            calls = len(log.read_text().splitlines()) if log.exists() else 0
            finished = (run_dir / "answer.json").exists() or calls >= subagent.MAX_TURNS
            (done if finished else pending).append(f"{run_dir.name} ({calls} calls)")
        print(f"done {len(done)}, pending {len(pending)}")
        for line in pending:
            print(f"pending: {line}")
        return 0

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
            "seeds": SEEDS,
            "depth": DEPTH,
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
    default_usage = args.session / "usage.json"
    usage_file = args.usage or (default_usage if default_usage.exists() else None)
    usage = json.loads(usage_file.read_text()) if usage_file else {}
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
