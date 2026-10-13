"""The tools each strategy gives the agent, confined to one repo (#39).

- `code`: list, read and search the repo's files (the baseline).
- `graph`: run `kg query` / `kg impact` / `kg status` on the repo's store.

Both get `submit_answer`, which ends the run. Tool definitions are strict
JSON Schemas and their order is fixed, so the prompt prefix caches well.
"""

from __future__ import annotations

import fnmatch
import re
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

MAX_OUTPUT = 20_000  # characters per tool result
MAX_LINES = 400  # lines per read_file call
MAX_MATCHES = 200  # matches per search call
_HIDDEN = (".git", ".kg")

SUBMIT = {
    "name": "submit_answer",
    "description": (
        "Submit your final answer. Call it exactly once, when you are done. "
        "`items` is the list the question asks for (empty if it asks for none or "
        "the answer is none); `evidence` lists what supports the answer."
    ),
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "answer": {"type": "string", "description": "The answer, in prose."},
            "items": {"type": "array", "items": {"type": "string"}},
            "evidence": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["answer", "items", "evidence"],
        "additionalProperties": False,
    },
}

CODE_TOOLS = [
    {
        "name": "list_files",
        "description": "List the repo's files whose path matches a glob "
        "(e.g. `**/*.py`, `src/**`). Paths are relative to the repo root.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"glob": {"type": "string"}},
            "required": ["glob"],
            "additionalProperties": False,
        },
    },
    {
        "name": "read_file",
        "description": f"Read a file with line numbers, at most {MAX_LINES} lines "
        "per call. Lines are 1-indexed; null reads from the start or to the end.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "start_line": {"type": ["integer", "null"]},
                "end_line": {"type": ["integer", "null"]},
            },
            "required": ["path", "start_line", "end_line"],
            "additionalProperties": False,
        },
    },
    {
        "name": "search",
        "description": "Search the repo's files for a regular expression. Returns "
        "`path:line: text` for each match, in files whose path matches `glob`.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"pattern": {"type": "string"}, "glob": {"type": "string"}},
            "required": ["pattern", "glob"],
            "additionalProperties": False,
        },
    },
    SUBMIT,
]

GRAPH_TOOLS = [
    {
        "name": "kg",
        "description": "Run a read-only kg command on the repo's knowledge graph "
        "and get its JSON output. `args` are the command line after `kg`, e.g. "
        '["query", "find", "utils"], ["query", "node", "module:app.core", '
        '"--depth", "2"], ["query", "path", "A", "B"], ["query", "untested"], '
        '["query", "undocumented"], ["impact", "function:app.run", "--depth", '
        '"2"], ["status"]. Run ["query", "--help"] or ["impact", "--help"] for '
        "every option.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"args": {"type": "array", "items": {"type": "string"}}},
            "required": ["args"],
            "additionalProperties": False,
        },
    },
    SUBMIT,
]

TOOLS = {"code": CODE_TOOLS, "graph": GRAPH_TOOLS}

STRATEGY_HINTS = {
    "code": "You can list, read and search the repository's files. Cite evidence "
    "as file paths with line numbers (`path:line` or `path:start-end`).",
    "graph": "You cannot read the files. You can query the repository's knowledge "
    "graph, built by kg from its code and documents, with the `kg` tool. Cite "
    "evidence as graph node IDs or edges (`source -[type]-> target`) from the "
    "tool output.",
}


class ToolError(Exception):
    """A tool call that cannot run; its message goes back to the agent."""


def run_tool(strategy: str, repo: Path, name: str, args: dict[str, Any]) -> str:
    """Run one tool call of `strategy` on `repo` and return its text result."""
    handlers: dict[str, Callable[[Path, dict[str, Any]], str]] = (
        {"list_files": list_files, "read_file": read_file, "search": search}
        if strategy == "code"
        else {"kg": run_kg}
    )
    if name not in handlers:
        raise ToolError(f"unknown tool {name!r} for strategy {strategy!r}")
    return _clip(handlers[name](repo, args))


# --- code ------------------------------------------------------------------------


def list_files(repo: Path, args: dict[str, Any]) -> str:
    paths = [p for p in _files(repo) if fnmatch.fnmatch(p, args["glob"])]
    return "\n".join(paths) if paths else "no files match"


def read_file(repo: Path, args: dict[str, Any]) -> str:
    path = _inside(repo, args["path"])
    if not path.is_file():
        raise ToolError(f"not a file: {args['path']}")
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    start = max(1, args.get("start_line") or 1)
    end = min(len(lines), args.get("end_line") or len(lines), start + MAX_LINES - 1)
    if start > len(lines):
        return f"{args['path']} has {len(lines)} lines"
    body = [f"{n:>5}  {lines[n - 1]}" for n in range(start, end + 1)]
    more = f"\n… {len(lines) - end} more lines" if end < len(lines) else ""
    return "\n".join(body) + more


def search(repo: Path, args: dict[str, Any]) -> str:
    try:
        pattern = re.compile(args["pattern"])
    except re.error as e:
        raise ToolError(f"invalid regular expression: {e}") from e
    matches = []
    for rel in _files(repo):
        if not fnmatch.fnmatch(rel, args["glob"] or "*"):
            continue
        text = (repo / rel).read_text(encoding="utf-8", errors="replace")
        for n, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                matches.append(f"{rel}:{n}: {line.strip()}")
                if len(matches) >= MAX_MATCHES:
                    return "\n".join(matches) + "\n… more matches; narrow the search"
    return "\n".join(matches) if matches else "no matches"


def _files(repo: Path) -> list[str]:
    root = repo.resolve()
    return sorted(
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_file() and not set(p.relative_to(root).parts) & set(_HIDDEN)
    )


def _inside(repo: Path, rel: str) -> Path:
    path = (repo / rel).resolve()
    if not path.is_relative_to(repo.resolve()) or set(Path(rel).parts) & set(_HIDDEN):
        raise ToolError(f"outside the repo: {rel}")
    return path


# --- graph -------------------------------------------------------------------------

_KG_COMMANDS = ("query", "impact", "status")


def run_kg(repo: Path, args: dict[str, Any]) -> str:
    argv = [str(a) for a in args["args"]]
    if not argv or argv[0] not in _KG_COMMANDS:
        raise ToolError(
            f"only these kg commands are allowed: {', '.join(_KG_COMMANDS)}"
        )
    if any(a.startswith("--kg-dir") for a in argv):
        raise ToolError("--kg-dir is set by the benchmark")
    if argv[0] == "status":
        argv = ["status", str(repo)]
    cmd = ["kg", *argv, "--kg-dir", str(repo / ".kg")]
    if "--help" not in argv and "-h" not in argv:
        cmd.append("--json")
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
    return proc.stdout or proc.stderr


def _clip(text: str) -> str:
    if len(text) <= MAX_OUTPUT:
        return text
    return text[:MAX_OUTPUT] + f"\n… output cut at {MAX_OUTPUT} characters"
