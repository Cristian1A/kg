"""The tools each strategy gives the agent, confined to one repo (#39).

- `code`: list, read and search the repo's files (the baseline).
- `graph`: run `kg query` / `kg impact` / `kg status` on the repo's store.
- `topic`: the same, on the store of the question's topic (`.kg-<topic>`,
  see `bench.topics`).
- `hybrid`: `kg`, plus `read_file` limited to the files and line ranges the
  graph has cited so far in the run (`Citations`), and to the files it reports
  as changed since it was built (`kg status`, or a `stale_graph` limit).
- `cards`: `hybrid` with brief answers: `--brief` is added to every command
  that takes it.
- `companion`: the `code` tools plus `kg` with brief answers: the graph next
  to search, not instead of it (#67).

Both get `submit_answer`, which ends the run. Tool definitions are strict
JSON Schemas and their order is fixed, so the prompt prefix caches well.
"""

from __future__ import annotations

import fnmatch
import json
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

MAX_OUTPUT = 20_000  # characters per tool result
MAX_LINES = 400  # lines per read_file call
MAX_MATCHES = 200  # matches per search call
_HIDDEN = (".git", ".kg")  # and the topic stores, `.kg-<topic>`

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
        '["query", "tested", "--type", "Module"], ["query", "undocumented"], '
        '["impact", "function:app.run", "--type", "Module,Package"], ["status"]. '
        'Run ["query", "--help"] or ["impact", "--help"] for '
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

READ_CITED = {
    **CODE_TOOLS[1],
    "description": f"Read lines of a file the graph has cited, at most {MAX_LINES} "
    "lines per call. Only the files in the `source` of a node the `kg` tool "
    "returned (e.g. with `kg query node <id>`) can be read, and only within its "
    "`lines` when it gives them; null reads the whole cited range. Files the "
    "graph reports as changed or added since it was built (`kg status`, or a "
    "`stale_graph` limit) can be read whole.",
}

TOOLS = {
    "code": CODE_TOOLS,
    "graph": GRAPH_TOOLS,
    "topic": GRAPH_TOOLS,
    "hybrid": [GRAPH_TOOLS[0], READ_CITED, SUBMIT],
    "cards": [GRAPH_TOOLS[0], READ_CITED, SUBMIT],
    "companion": [*CODE_TOOLS[:3], GRAPH_TOOLS[0], SUBMIT],
}

STRATEGY_HINTS = {
    "code": "You can list, read and search the repository's files. Cite evidence "
    "as file paths with line numbers (`path:line` or `path:start-end`).",
    "graph": "You cannot read the files. You can query the repository's knowledge "
    "graph, built by kg from its code and documents, with the `kg` tool. Cite "
    "evidence as graph node IDs or edges (`source -[type]-> target`) from the "
    "tool output.",
}
STRATEGY_HINTS["topic"] = STRATEGY_HINTS["graph"]
STRATEGY_HINTS["hybrid"] = (
    "You can query the repository's knowledge graph, built by kg from its code "
    "and documents, with the `kg` tool, and read the files it cites with "
    "`read_file`: only the `source` file and `lines` of the nodes it returns "
    "(`kg query node <id>` shows them). If the graph is stale, `kg status` "
    "lists the files changed or added since it was built: read those whole. "
    "Cite evidence as graph node IDs, edges (`source -[type]-> target`) or "
    "`path:line`."
)
STRATEGY_HINTS["cards"] = STRATEGY_HINTS["hybrid"]
STRATEGY_HINTS["companion"] = (
    "You can list, read and search the repository's files, and query its "
    "knowledge graph, built by kg from its code and documents, with the `kg` "
    "tool. Use whichever gets the answer with fewer calls. Cite evidence as "
    "`path:line`, graph node IDs or edges (`source -[type]-> target`)."
)
# The commands that take `--brief`: `cards` and `companion` always add it
_BRIEF = ("cards", "companion")
_BRIEF_COMMANDS = {("query", "node"), ("query", "find"), ("query", "path"), ("impact",)}


class Citations:
    """Files and line ranges the graph has cited in a run: what `hybrid` reads.

    `ranges` maps a repo path to `[start, end]` pairs; `None` means the whole
    file (a node with a `source` and no `lines`, such as a module, or a file
    the graph reports as changed since it was built).
    """

    def __init__(self, ranges: dict[str, list[list[int]] | None] | None = None):
        self.ranges: dict[str, list[list[int]] | None] = dict(ranges or {})

    def add_from(self, output: str) -> None:
        """Record every `source` (with its `lines`) in a `kg --json` output.

        Files the graph does not match are recorded whole: `modified` and
        `added` in `kg status`, and the `files` of a `stale_graph` limit.
        """
        try:
            data = json.loads(output)
        except json.JSONDecodeError:
            return
        stack = [data]
        while stack:
            item = stack.pop()
            if isinstance(item, list):
                stack.extend(item)
            elif isinstance(item, dict):
                source = item.get("source")
                # A provenance block; a path step's `source` is a node ID
                if isinstance(source, str) and (
                    "method" in item or "extractor" in item
                ):
                    self._add(source, item.get("lines"))
                for path in _stale_files(item):
                    self.ranges[path] = None
                stack.extend(item.values())

    def _add(self, path: str, lines: Any) -> None:
        if not (isinstance(lines, list) and len(lines) == 2):
            self.ranges[path] = None
        elif self.ranges.get(path, []) is not None:
            pair = [int(lines[0]), int(lines[1])]
            if pair not in self.ranges.setdefault(path, []):
                self.ranges[path].append(pair)

    def window(
        self, path: str, start: int | None, end: int | None
    ) -> tuple[int, int | None]:
        """The lines `read_file` may return, or a `ToolError` that says why not."""
        if path not in self.ranges:
            raise ToolError(
                f"{path} has not been cited by the graph; query a node whose "
                "`source` is that file first (`kg query node <id>`)"
            )
        allowed = self.ranges[path]
        if allowed is None:
            return start or 1, end
        for low, high in allowed:
            if start is None and end is None:
                return low, high
            if low <= (start or low) and (end or high) <= high:
                return start or low, end or high
        cited = ", ".join(f"{low}-{high}" for low, high in sorted(allowed))
        raise ToolError(f"outside what the graph cited for {path}: lines {cited}")


def _stale_files(item: dict[str, Any]) -> list[str]:
    """The files a `kg status` result or a `stale_graph` limit says changed."""
    if item.get("code") == "stale_graph":
        files = item.get("files", [])
    elif "stale" in item and "modified" in item:
        files = [*item.get("modified", []), *item.get("added", [])]
    else:
        return []
    return [f for f in files if isinstance(f, str)]


class ToolError(Exception):
    """A tool call that cannot run; its message goes back to the agent."""


def run_tool(
    strategy: str,
    repo: Path,
    name: str,
    args: dict[str, Any],
    topic: str = "",
    citations: Citations | None = None,
) -> str:
    """Run one tool call of `strategy` on `repo` and return its text result.

    `topic` picks the store of the `topic` strategy; `citations` holds what
    the graph has cited so far in a `hybrid` run, and is updated.
    """
    kg_dir = repo / (f".kg-{topic}" if strategy == "topic" else ".kg")
    cited = citations if citations is not None else Citations()

    def kg(repo: Path, args: dict[str, Any]) -> str:
        argv = [str(a) for a in args["args"]]
        if strategy in _BRIEF and (
            tuple(argv[:2]) in _BRIEF_COMMANDS or tuple(argv[:1]) in _BRIEF_COMMANDS
        ):
            argv = [*argv, "--brief"] if "--brief" not in argv else argv
        output = run_kg(repo, {"args": argv}, kg_dir)
        if strategy in ("hybrid", "cards"):
            cited.add_from(output)
        return output

    def read_cited(repo: Path, args: dict[str, Any]) -> str:
        start, end = cited.window(
            args["path"], args.get("start_line"), args.get("end_line")
        )
        return read_file(repo, {**args, "start_line": start, "end_line": end})

    handlers: dict[str, Callable[[Path, dict[str, Any]], str]] = {
        "code": {"list_files": list_files, "read_file": read_file, "search": search},
        "hybrid": {"kg": kg, "read_file": read_cited},
        "cards": {"kg": kg, "read_file": read_cited},
        "companion": {
            "list_files": list_files,
            "read_file": read_file,
            "search": search,
            "kg": kg,
        },
    }.get(strategy, {"kg": kg})
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
        if p.is_file() and not _hidden(p.relative_to(root).parts)
    )


def _inside(repo: Path, rel: str) -> Path:
    path = (repo / rel).resolve()
    if not path.is_relative_to(repo.resolve()) or _hidden(Path(rel).parts):
        raise ToolError(f"outside the repo: {rel}")
    return path


def _hidden(parts: tuple[str, ...]) -> bool:
    return any(p in _HIDDEN or p.startswith(".kg-") for p in parts)


# --- graph -------------------------------------------------------------------------

_KG_COMMANDS = ("query", "impact", "status")


def run_kg(repo: Path, args: dict[str, Any], kg_dir: Path | None = None) -> str:
    argv = [str(a) for a in args["args"]]
    if not argv or argv[0] not in _KG_COMMANDS:
        raise ToolError(
            f"only these kg commands are allowed: {', '.join(_KG_COMMANDS)}"
        )
    if any(a.startswith("--kg-dir") for a in argv):
        raise ToolError("--kg-dir is set by the benchmark")
    if argv[0] == "status":
        argv = ["status", str(repo)]
    # The interpreter running the benchmark, so kg need not be on PATH
    cmd = [sys.executable, "-m", "kg", *argv, "--kg-dir", str(kg_dir or repo / ".kg")]
    if "--help" not in argv and "-h" not in argv:
        cmd.append("--json")
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
    return proc.stdout or proc.stderr


def _clip(text: str) -> str:
    if len(text) <= MAX_OUTPUT:
        return text
    return text[:MAX_OUTPUT] + f"\n… output cut at {MAX_OUTPUT} characters"
