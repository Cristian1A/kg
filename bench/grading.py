"""Mechanical grading of benchmark answers: no LLM judge (#39).

An answer is `{"answer": text, "items": [...], "evidence": [...]}`. Questions
expect either a list of `items` (scored by precision and recall after
normalizing names) or `keywords` (groups of alternatives the text must
mention). Traceability is the share of `evidence` that can be checked
against the repo or its graph.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import networkx as nx


@dataclass(frozen=True)
class Grade:
    """Score in [0, 1]; precision and recall only for item questions."""

    score: float
    precision: float | None = None
    recall: float | None = None
    missing: tuple[str, ...] = ()
    extra: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize(name: str, kind: str) -> str:
    """Canonical form of a module, package or plain name.

    `module`: `etl/utils.py`, `module:etl.utils` and `etl.utils` all become
    `etl.utils`. `package`: the top-level import name (`azure-storage-blob`
    and `azure.identity` become `azure`; `psycopg2-binary` becomes
    `psycopg2`). `file`: the file name (`config:.github/workflows/ci.yml`
    and `ci.yml` are the same).
    """
    text = name.strip().strip("`'\"").lower()
    text = re.sub(r"^[a-z_]+:", "", text)  # a graph ID prefix
    text = re.sub(r":\d+(-\d+)?$", "", text)  # a line reference
    if kind == "module":
        text = text.removesuffix(".py").replace("/", ".")
        return text.removesuffix(".__init__")
    if kind == "file":
        return text.rsplit("/", 1)[-1]
    if kind == "package":
        text = text.replace("-binary", "")
        return re.split(r"[.\-\[ <>=]", text)[0]
    return text


def grade(expect: dict[str, Any], answer: dict[str, Any] | None) -> Grade:
    """Grade an answer against a question's `expect` block."""
    if answer is None:
        return Grade(0.0)
    if "keywords" in expect:
        return _grade_keywords(expect["keywords"], answer)
    return _grade_items(expect["items"], expect.get("normalize", "text"), answer)


def _grade_items(expected: list[str], kind: str, answer: dict[str, Any]) -> Grade:
    want = {normalize(i, kind) for i in expected}
    got = {normalize(str(i), kind) for i in answer.get("items") or []}
    if not want:
        score = 1.0 if not got else 0.0
        return Grade(score, None, None, (), tuple(sorted(got)))
    hits = want & got
    precision = len(hits) / len(got) if got else 0.0
    recall = len(hits) / len(want)
    f1 = 2 * precision * recall / (precision + recall) if hits else 0.0
    return Grade(
        round(f1, 4),
        round(precision, 4),
        round(recall, 4),
        tuple(sorted(want - got)),
        tuple(sorted(got - want)),
    )


def _grade_keywords(groups: list[list[str]], answer: dict[str, Any]) -> Grade:
    text = " ".join(
        [str(answer.get("answer") or ""), *map(str, answer.get("items") or [])]
    ).lower()
    found = [any(alt.lower() in text for alt in group) for group in groups]
    missing = tuple(group[0] for group, ok in zip(groups, found, strict=True) if not ok)
    return Grade(round(sum(found) / len(groups), 4), missing=missing)


# --- Traceability --------------------------------------------------------------------

_EDGE = re.compile(r"^(?P<source>\S+) -\[(?P<type>[^\]]+)\]-> (?P<target>\S+)$")
_FILE_LINE = re.compile(r"^(?P<path>[^:\s]+?)(?::(?P<start>\d+)(?:-(?P<end>\d+))?)?$")


def verifiable(evidence: str, repo: Path, graph: nx.MultiDiGraph | None) -> bool:
    """Whether a piece of evidence points to something that exists.

    Accepted: a graph node ID, a graph edge (`a -[type]-> b`), or a repo file
    path with optional `:line` or `:start-end` within the file. A trailing
    note in parentheses is ignored (`a -[imports]-> b (a test)`).
    """
    text = re.sub(r"\s+\([^()]*\)$", "", evidence.strip()).strip("`")
    if graph is not None:
        if text in graph:
            return True
        edge = _EDGE.match(text)
        if edge and graph.has_edge(edge["source"], edge["target"], key=edge["type"]):
            return True
    match = _FILE_LINE.match(text)
    if not match:
        return False
    path = (repo / match["path"]).resolve()
    if not path.is_relative_to(repo.resolve()) or not path.is_file():
        return False
    if match["start"] is None:
        return True
    try:
        lines = len(path.read_text(encoding="utf-8", errors="replace").splitlines())
    except OSError:
        return False
    start = int(match["start"])
    end = int(match["end"] or start)
    return 1 <= start <= end <= lines


def traceability(
    evidence: list[str], repo: Path, graph: nx.MultiDiGraph | None
) -> float | None:
    """Share of verifiable evidence, `None` if the answer gives none."""
    if not evidence:
        return None
    ok = sum(verifiable(str(e), repo, graph) for e in evidence)
    return round(ok / len(evidence), 4)
