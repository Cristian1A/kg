"""Experiment 2 (#71), R2-11: the agent-written corpus.

An agent records the project's memory at the end of each session, in order,
without seeing the questions or the curated corpus. Each session gets a
sources file (its dialogue, and the GitHub activity and commits since the
previous session) and a prompt; one subagent per session writes a kg input
document and submits it, which validates it and merges it after the earlier
sessions (`corpus/kg-agent/`). Design: `docs/experiment-2/agent-corpus.md`.

    set -a; source .env; set +a
    python -m bench.memory_write fetch               # GitHub, read-only
    python -m bench.memory_write sources             # every session
    python -m bench.memory_write prompt 01-2026-10-07-9f063e5d
    python -m bench.memory_write show <session> <memory ID>
    python -m bench.memory_write submit <session> <file>
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

import networkx as nx

from bench.memory import CORPUS, MEMORY_TYPES, SESSIONS, load_memory, render
from bench.run import REPO_ROOT, ROOT, _run

AGENT_CORPUS = ROOT / "corpus/kg-agent"
WRITERS = SESSIONS / "writers"
GITHUB = SESSIONS / "github"
TRANSCRIPTS = Path.home() / ".claude/projects/-home-cris-networkx"
# The last commit any source may come from: the questions came after it.
LAST_COMMIT = "7dfd6ad"
PROVENANCE = {"method": "llm", "extractor": "exp2-agent@1", "confidence": 1.0}
NODE_TYPES = {*MEMORY_TYPES, "Component", "Evidence"}
STATUSES = ("active", "superseded", "invalidated", "done")
RELATIONS = {
    "decided_because": "Decision → Constraint / Experiment / Evidence: the reason",
    "affects": "Task / Decision / Issue → Component: the part it touches",
    "supported_by": "any memory → Evidence: where it can be checked",
    "supersedes": "new Decision → old Decision: the old one no longer holds",
    "invalidated_by": "any memory → Evidence of a change that made it obsolete",
    "blocked_by": "Task → Task / Issue / Constraint: what stops it",
    "produced": "Session → every memory it created",
}
CREDENTIAL = re.compile(
    r"(ghp_|github_pat_|sk-ant-|sk-[A-Za-z0-9]{16}|xox[bp]-|AKIA)[A-Za-z0-9_\-]{8,}"
    r"|(?i:token|password|secret|api[_-]?key)\s*[=:]\s*\S{8,}"
)
REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
TAG = re.compile(r"<(local-command-\w+|command-message|command-args)>.*?</\1>", re.S)
COMMAND = re.compile(r"<command-name>(.*?)</command-name>")


# --- sessions -----------------------------------------------------------------------


def sessions() -> list[dict[str, Any]]:
    """The sessions to write, in order: ID, date, pinned commit, transcript.

    Only the curated corpus's Session metadata is read, never its text.
    """
    out = []
    for path in sorted(CORPUS.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        node = next(n for n in doc["nodes"] if n["type"] == "Session")
        out.append({"id": node["id"], "stem": path.stem, **node["attrs"]})
    return out


def session(stem: str) -> dict[str, Any]:
    for s in sessions():
        if s["stem"] == stem:
            return s
    raise SystemExit(f"unknown session: {stem}")


def commit_time(commit: str) -> datetime:
    return datetime.fromisoformat(
        _run(
            ["git", "-C", str(REPO_ROOT), "show", "-s", "--format=%cI", commit]
        ).strip()
    )


def windows() -> dict[str, tuple[datetime | None, datetime]]:
    """Each session's sources window: after the previous pinned commit, to its own."""
    out, previous = {}, None
    for s in sessions():
        end = commit_time(s["commit"])
        out[s["stem"]] = (previous, end)
        previous = end
    return out


def _within(when: str | None, window: tuple[datetime | None, datetime]) -> bool:
    if not when:
        return False
    t = datetime.fromisoformat(when.replace("Z", "+00:00"))
    return (window[0] is None or t > window[0]) and t <= window[1]


# --- sources ------------------------------------------------------------------------


def clean(text: str) -> str:
    """Text without harness tags, and without lines that look like credentials."""
    text = REMINDER.sub("", text)
    text = TAG.sub("", text)
    text = COMMAND.sub(lambda m: m.group(1), text)
    text = re.sub(r"</?command-[\w-]+>", "", text)
    lines = [
        "[line dropped: it looked like a credential]" if CREDENTIAL.search(ln) else ln
        for ln in text.splitlines()
    ]
    return "\n".join(lines).strip()


def dialogue(path: Path, until: datetime | None = None) -> str:
    """The user's and the assistant's text of a transcript, without tool output."""
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        e = json.loads(line)
        if e.get("type") not in ("user", "assistant") or e.get("isSidechain"):
            continue
        if e.get("isMeta") or e.get("isCompactSummary"):
            continue
        stamp = e.get("timestamp")
        if (
            until
            and stamp
            and datetime.fromisoformat(stamp.replace("Z", "+00:00")) > until
        ):
            break
        content = e["message"].get("content")
        if isinstance(content, str):
            parts = [content]
        else:
            parts = [
                c.get("text", "") for c in content or [] if c.get("type") == "text"
            ]
        text = clean("\n".join(parts))
        if text:
            who = "USER" if e["type"] == "user" else "ASSISTANT"
            out.append(f"[{e.get('timestamp', '')[:16]}] {who}: {text}")
    return "\n\n".join(out)


def _transcript(prefix: str) -> Path:
    found = sorted(TRANSCRIPTS.glob(f"{prefix}*.jsonl"))
    if len(found) != 1:
        raise SystemExit(f"transcript {prefix}: {len(found)} matches")
    return found[0]


def commits(window: tuple[datetime | None, datetime]) -> str:
    """The commits reachable from LAST_COMMIT in the window: message and files."""
    log = _run(
        [
            "git",
            "-C",
            str(REPO_ROOT),
            "log",
            LAST_COMMIT,
            "--reverse",
            "--format=%h%x1f%cI%x1f%B%x1e",
        ]
    )
    out = []
    for entry in log.split("\x1e"):
        if not entry.strip():
            continue
        sha, when, body = entry.strip("\n").split("\x1f", 2)
        if not _within(when, window):
            continue
        files = _run(
            ["git", "-C", str(REPO_ROOT), "show", "--name-only", "--format=", sha]
        ).split()
        out.append(
            f"commit {sha} ({when[:16]})\n{clean(body)}\nfiles: {', '.join(files)}"
        )
    return "\n\n".join(out)


def github(window: tuple[datetime | None, datetime]) -> str:
    """Issues and PRs opened, closed or merged, and comments, in the window."""
    issues = json.loads((GITHUB / "issues.json").read_text(encoding="utf-8"))
    comments = json.loads((GITHUB / "comments.json").read_text(encoding="utf-8"))
    merged = {
        p["number"]: p.get("merged_at")
        for p in json.loads((GITHUB / "pulls.json").read_text(encoding="utf-8"))
    }
    edits = {
        int(k): v
        for k, v in json.loads(
            (GITHUB / "edits.json").read_text(encoding="utf-8")
        ).items()
    }
    titles = {i["number"]: i["title"] for i in issues}
    events = []
    for i in issues:
        kind = "PR" if "pull_request" in i else "issue"
        n = i["number"]
        if _within(i["created_at"], window):
            body = clean(body_at(i, edits.get(n, []), window[1]))
            events.append(
                (i["created_at"], f"{kind} #{n} opened: {i['title']}\n{body}".strip())
            )
        if kind == "PR" and _within(merged.get(n), window):
            events.append((merged[n], f"PR #{n} merged: {i['title']}"))
        elif _within(i.get("closed_at"), window):
            reason = i.get("state_reason") or "closed"
            events.append(
                (i["closed_at"], f"{kind} #{n} closed ({reason}): {i['title']}")
            )
    for c in comments:
        if _within(c["created_at"], window):
            n = int(c["issue_url"].rsplit("/", 1)[1])
            events.append(
                (
                    c["created_at"],
                    f"comment on #{n} ({titles.get(n, '')}):\n"
                    + clean(c.get("body") or ""),
                )
            )
    events.sort(key=lambda e: e[0])
    return "\n\n".join(f"[{t[:16]}] {text}" for t, text in events)


def body_at(issue: dict[str, Any], edits: list[dict[str, str]], when: datetime) -> str:
    """An issue's or PR's body as it stood at `when`, from its edit history.

    GitHub keeps each edit's full text (the first is the original); a body
    never edited is the current one.
    """
    if not edits:
        return issue.get("body") or ""
    before = [
        e
        for e in edits
        if datetime.fromisoformat(e["editedAt"].replace("Z", "+00:00")) <= when
    ]
    if not before:
        return ""
    return max(before, key=lambda e: e["editedAt"])["diff"] or ""


def write_sources(stem: str) -> Path:
    """`writers/<session>/sources.md`: GitHub activity, commits, then the dialogue."""
    s = session(stem)
    window = windows()[stem]
    until = window[1] if s["commit"] == LAST_COMMIT else None
    text = "\n\n".join(
        [
            f"# Sources of session {s['id']} ({s['date']})",
            "Everything below happened after the previous session and up to this "
            f"session's last commit ({s['commit']}), in time order within each part.",
            "## GitHub: issues, pull requests and comments",
            github(window) or "(none)",
            "## Commits",
            commits(window) or "(none)",
            "## The session's dialogue (the user and the assistant, no tool output)",
            dialogue(_transcript(s["transcript"]), until) or "(empty)",
        ]
    )
    out = WRITERS / stem / "sources.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text + "\n", encoding="utf-8")
    return out


def fetch() -> None:
    """Every issue, PR and issue comment of the repository (GET only)."""
    owner, repo = os.environ["GITHUB_OWNER"], os.environ["GITHUB_REPO"]
    headers = {
        "Authorization": f"token {os.environ['GITHUB_TOKEN']}",
        "Accept": "application/vnd.github+json",
    }
    GITHUB.mkdir(parents=True, exist_ok=True)
    for name, path in (
        ("issues", "issues?state=all"),
        ("comments", "issues/comments?"),
        ("pulls", "pulls?state=all"),
    ):
        items, page = [], 1
        while True:
            url = (
                f"https://api.github.com/repos/{owner}/{repo}/{path}"
                f"&per_page=100&page={page}"
            )
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req) as r:
                batch = json.load(r)
            items += batch
            if len(batch) < 100:
                break
            page += 1
        (GITHUB / f"{name}.json").write_text(json.dumps(items, indent=1))
        print(f"{name}: {len(items)}")
    edits = {}
    for kind in ("issues", "pullRequests"):
        query = (
            "query($o:String!,$r:String!){repository(owner:$o,name:$r){"
            f"{kind}(first:100){{nodes{{number lastEditedAt "
            "userContentEdits(first:100){nodes{editedAt diff}}}}}}"
        )
        req = urllib.request.Request(
            "https://api.github.com/graphql",
            data=json.dumps(
                {"query": query, "variables": {"o": owner, "r": repo}}
            ).encode(),
            headers={"Authorization": f"bearer {os.environ['GITHUB_TOKEN']}"},
        )
        with urllib.request.urlopen(req) as r:
            nodes = json.load(r)["data"]["repository"][kind]["nodes"]
        for node in nodes:
            if node["lastEditedAt"]:
                edits[node["number"]] = node["userContentEdits"]["nodes"]
    (GITHUB / "edits.json").write_text(json.dumps(edits, indent=1))
    print(f"edited bodies: {len(edits)}")


# --- the memory so far --------------------------------------------------------------


def earlier(stem: str) -> list[Path]:
    """The agent corpus files of the sessions before `stem`; all must exist."""
    order = [s["stem"] for s in sessions()]
    before = order[: order.index(stem)]
    missing = [b for b in before if not (AGENT_CORPUS / f"{b}.json").exists()]
    if missing:
        raise SystemExit(f"write these sessions first: {', '.join(missing)}")
    return [AGENT_CORPUS / f"{b}.json" for b in before]


def memory_so_far(stem: str) -> nx.MultiDiGraph:
    files = earlier(stem)
    return load_memory(files) if files else nx.MultiDiGraph()


def listing(graph: nx.MultiDiGraph) -> str:
    """One line per memory, component and evidence item, for the writer."""
    groups: dict[str, list[str]] = {"memories": [], "components": [], "evidence": []}
    for node, d in sorted(graph.nodes(data=True)):
        attrs = d.get("attrs", {})
        if d["type"] == "Component":
            groups["components"].append(f"- [{node}] {d.get('label', '')}")
        elif d["type"] == "Evidence":
            groups["evidence"].append(f"- [{node}] {d.get('label', '')}")
        elif d["type"] == "Session":
            groups["memories"].append(f"- [{node}] Session · {d.get('label', '')}")
        else:
            groups["memories"].append(
                f"- [{node}] {d['type']} · {attrs.get('status')} · {d.get('label', '')}"
            )
    return "\n\n".join(
        f"### {name.capitalize()} ({len(lines)})\n" + ("\n".join(lines) or "(none)")
        for name, lines in groups.items()
    )


def show(stem: str, node: str) -> str:
    graph = memory_so_far(stem)
    if node not in graph:
        return f"no memory {node} before this session"
    d = graph.nodes[node]
    text = (
        render(graph, node)
        if d["type"] in MEMORY_TYPES
        else f"[{node}] {d['type']}\n{d.get('label', '')}\n{d.get('description', '')}"
        f"\n{json.dumps(d.get('attrs', {}))}"
    )
    links = [f"→ {t} [{v}]" for _, v, t in graph.out_edges(node, keys=True)]
    links += [f"← {t} [{u}]" for u, _, t in graph.in_edges(node, keys=True)]
    return text.strip() + ("\nrelations:\n" + "\n".join(links) if links else "")


# --- submit -------------------------------------------------------------------------


def check(stem: str, doc: dict[str, Any], graph: nx.MultiDiGraph) -> list[str]:
    """What is wrong with a session's document, given the memory before it."""
    s = session(stem)
    errors = []
    nodes = doc.get("nodes", [])
    ids = {n.get("id") for n in nodes}
    sess = [n for n in nodes if n.get("type") == "Session"]
    if [n.get("id") for n in sess] != [s["id"]]:
        errors.append(f"exactly one Session node, with id {s['id']}")
    produced = {
        e.get("target")
        for e in doc.get("edges", [])
        if e.get("type") == "produced" and e.get("source") == s["id"]
    }
    for n in nodes:
        nid, kind, attrs = n.get("id"), n.get("type"), n.get("attrs", {})
        if kind not in NODE_TYPES:
            errors.append(f"{nid}: type {kind} is not one of {sorted(NODE_TYPES)}")
            continue
        if kind == "Session":
            continue
        new = nid not in graph
        if new and "label" not in n:
            errors.append(f"{nid}: a new node needs a label")
        if kind in MEMORY_TYPES:
            if attrs.get("status") not in STATUSES:
                errors.append(f"{nid}: status must be one of {', '.join(STATUSES)}")
            if new:
                if attrs.get("session") != s["id"] or attrs.get("created") != s["date"]:
                    errors.append(
                        f"{nid}: a new memory needs attrs.session {s['id']} "
                        f"and attrs.created {s['date']}"
                    )
                if nid not in produced:
                    errors.append(
                        f"{nid}: a new memory needs a produced edge from {s['id']}"
                    )
            elif graph.nodes[nid]["type"] != kind:
                errors.append(f"{nid}: already a {graph.nodes[nid]['type']}")
    for e in doc.get("edges", []):
        if e.get("type") not in RELATIONS:
            errors.append(
                f"edge type {e.get('type')} is not one of {sorted(RELATIONS)}"
            )
        for end in (e.get("source"), e.get("target")):
            if end not in ids and end not in graph:
                errors.append(
                    f"edge {e.get('source')} → {e.get('target')}: no node {end}"
                )
    return errors


def normalize(stem: str, doc: dict[str, Any]) -> dict[str, Any]:
    """The document as stored: fixed Session attrs and the agent's provenance."""
    s = session(stem)
    for n in doc["nodes"]:
        n["provenance"] = dict(PROVENANCE)
        if n["type"] == "Session":
            n["attrs"] = {k: s[k] for k in ("date", "commit", "transcript", "order")}
    for e in doc["edges"]:
        e["provenance"] = dict(PROVENANCE)
    return {"version": "1", "nodes": doc["nodes"], "edges": doc["edges"]}


def submit(stem: str, path: Path) -> tuple[bool, str]:
    """Validate a session's document and store it in the agent corpus."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"cannot read {path}: {exc}"
    if not isinstance(doc, dict) or not isinstance(doc.get("nodes"), list):
        return False, "the document needs a list of nodes (and of edges)"
    doc.setdefault("edges", [])
    files = earlier(stem)
    graph = load_memory(files) if files else nx.MultiDiGraph()
    if errors := check(stem, doc, graph):
        return False, "not accepted:\n" + "\n".join(f"- {e}" for e in errors)
    doc = normalize(stem, doc)
    text = json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
    from kg import store
    from kg.merge import add_to_store

    with tempfile.TemporaryDirectory() as tmp:
        kg_dir = Path(tmp) / ".kg"
        store.init_store(kg_dir)
        for f in files:
            add_to_store(kg_dir, f.read_text(encoding="utf-8"))
        result = add_to_store(kg_dir, text)
        if not result.validation.ok:
            issues = "\n".join(f"- {i.to_text()}" for i in result.validation.errors)
            return False, f"not accepted, kg validation:\n{issues}"
    AGENT_CORPUS.mkdir(parents=True, exist_ok=True)
    (AGENT_CORPUS / f"{stem}.json").write_text(text, encoding="utf-8")
    kinds: dict[str, int] = {}
    for n in doc["nodes"]:
        kinds[n["type"]] = kinds.get(n["type"], 0) + 1
    summary = ", ".join(f"{v} {k}" for k, v in sorted(kinds.items()))
    return True, f"accepted: {summary}; {len(doc['edges'])} edges"


# --- prompt -------------------------------------------------------------------------

PROMPT = """\
# Write the project memory for one session

You keep the long-term memory of a software project, **kg** (a Python CLI that
turns a project's knowledge into a graph). Other agents will read this memory
in later sessions to recover context they cannot easily get back: why things
were decided, what was tried and failed, what was left pending and what blocks
it, what changed. You write it at the end of session **{id}** ({date}).

## What you may do

1. Read `{sources}`: everything that happened since the previous session
   (GitHub issues, PRs and comments; commits) and this session's dialogue
   between the user and the assistant. **It is the only file you may read.**
   Do not open, list or search any other file or directory of the repository.
2. Run only these commands, from `{repo}`:
   - `env/bin/python -m bench.memory_write show {stem} <memory ID>`: one
     earlier memory in full, with its relations.
   - `env/bin/python -m bench.memory_write submit {stem} <your JSON file>`:
     validate and store your document. If it is not accepted, fix what it
     says and submit again.
3. Write your document to `{out}`.

When it is accepted, reply with only `submitted`.

## What to record (Engram's protocol)

- Record what is **durable and costly to reconstruct**: decisions and their
  reasons, approaches tried and why they failed, constraints, results of
  experiments, problems found, pending work and what blocks it, and what
  replaced what. Not what a file or `git log` shows in a second.
- **Check before writing.** The memory so far is listed below. If something
  is already there, update it instead of writing a duplicate: re-emit the
  node with its ID and the new fields (they replace the old ones), or change
  only its status.
- **Keep the history.** When a decision is replaced, write the new one with a
  `supersedes` edge to the old one and set the old one's status to
  `superseded`. When a change makes a memory obsolete, set its status to
  `invalidated` with an `invalidated_by` edge to the evidence of the change.
  Finished tasks become `done`.
- Paraphrase; do not paste the dialogue. Leave out anything that looks like a
  credential. Write in English.

## Format

A kg input document: `{{"version": "1", "nodes": [...], "edges": [...]}}`.

**Node types:** `Decision`, `Task`, `Experiment`, `Issue`, `Constraint` (the
memories), `Component` (a part of the project), `Evidence` (where a claim can
be checked) and one `Session` (this session).

- **IDs:** `<type>:<kebab-case-slug>` for new nodes, e.g. `decision:use-sqlite`;
  evidence by anchor, e.g. `evidence:issue-12`, `evidence:pr-30`,
  `evidence:commit-1a2b3c4`, `evidence:file-docs-store-md`.
- **A memory** has `label` (its title), `description` and `attrs`:
  `status` (`active`, `superseded`, `invalidated` or `done`), `session`
  (`{id}`) and `created` (`{date}`). Its description follows
  *What / Why / Where / Learned*, one line each.
- **The session node** has the ID `{id}`, a `label` (what the session was
  about) and a `description` in *Goal / Instructions / Discoveries /
  Accomplished / Next steps / Relevant files*. Its attrs are set for you.
- **A component** has `label` and `description`. **Evidence** has `label` and
  `attrs` `kind` (`issue`, `pr`, `comment`, `commit` or `file`) and `ref` (the
  number, hash or path); for a file, also `commit`.
- **A status change** of an earlier memory: `{{"id": ..., "type": ...,
  "attrs": {{"status": "superseded"}}}}`.

**Edges** `{{"source": ..., "target": ..., "type": ...}}`, only these types:

{relations}

Every new memory needs a `produced` edge from `{id}`. Edges may point to
earlier nodes.

## A small example (another project)

```json
{example}
```

## The memory so far

{listing}
"""

EXAMPLE = {
    "version": "1",
    "nodes": [
        {
            "id": "session:2026-01-05-0a1b2c3d",
            "type": "Session",
            "label": "Cache layer and the Redis question",
        },
        {
            "id": "decision:in-process-cache",
            "type": "Decision",
            "label": "Cache in process instead of Redis",
            "description": "What: an LRU cache inside the API process.\n"
            "Why: one instance only; Redis adds an operational dependency.\n"
            "Where: api/cache.py\nLearned: revisit if the API scales out.",
            "attrs": {
                "status": "active",
                "session": "session:2026-01-05-0a1b2c3d",
                "created": "2026-01-05",
            },
        },
        {
            "id": "decision:redis-cache",
            "type": "Decision",
            "attrs": {"status": "superseded"},
        },
        {"id": "component:api", "type": "Component", "label": "api"},
        {
            "id": "evidence:pr-14",
            "type": "Evidence",
            "label": "Add an in-process cache",
            "attrs": {"kind": "pr", "ref": "14"},
        },
    ],
    "edges": [
        {
            "source": "session:2026-01-05-0a1b2c3d",
            "target": "decision:in-process-cache",
            "type": "produced",
        },
        {
            "source": "decision:in-process-cache",
            "target": "decision:redis-cache",
            "type": "supersedes",
        },
        {
            "source": "decision:in-process-cache",
            "target": "component:api",
            "type": "affects",
        },
        {
            "source": "decision:in-process-cache",
            "target": "evidence:pr-14",
            "type": "supported_by",
        },
    ],
}


def write_prompt(stem: str) -> Path:
    s = session(stem)
    folder = WRITERS / stem
    text = PROMPT.format(
        id=s["id"],
        date=s["date"],
        stem=stem,
        repo=REPO_ROOT,
        sources=folder / "sources.md",
        out=folder / "memory.json",
        relations="\n".join(f"- `{k}`: {v}" for k, v in RELATIONS.items()),
        example=json.dumps(EXAMPLE, indent=2),
        listing=listing(memory_so_far(stem)),
    )
    out = folder / "prompt.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m bench.memory_write",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("fetch", help="download issues, PRs and comments (read-only)")
    sub.add_parser("sources", help="write every session's sources.md")
    p = sub.add_parser("prompt", help="write a session's prompt.md")
    p.add_argument("stem")
    s = sub.add_parser("show", help="print an earlier memory")
    s.add_argument("stem")
    s.add_argument("node")
    u = sub.add_parser("submit", help="validate and store a session's document")
    u.add_argument("stem")
    u.add_argument("file", type=Path)
    args = parser.parse_args(argv)
    if args.command == "fetch":
        fetch()
    elif args.command == "sources":
        for s_ in sessions():
            path = write_sources(s_["stem"])
            print(f"{path}  {path.stat().st_size // 1024} KB")
    elif args.command == "prompt":
        print(write_prompt(args.stem))
    elif args.command == "show":
        print(show(args.stem, args.node))
    else:
        ok, message = submit(args.stem, args.file)
        print(message)
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
