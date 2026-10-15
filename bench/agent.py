"""One benchmark run: an agent answers one question with one strategy's tools.

A manual tool-use loop rather than the SDK's tool runner, so every request's
token usage is recorded and the number of turns is capped. The history is
append-only (`response.content` is sent back unchanged), as the current
models require for their thinking blocks.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from bench.tools import STRATEGY_HINTS, TOOLS, Citations, ToolError, run_tool

SYSTEM = """You answer questions about a software repository named {repo}.

{hint}

Answer only from what the tools return; do not guess from general knowledge.
When you are done, call `submit_answer` once with:
- `answer`: the answer in a few sentences;
- `items`: the list the question asks for, written as the project names them
  (dotted module names such as `app.core`, import names of packages, or
  function names), or an empty list if the answer is none;
- `evidence`: the references that support the answer."""


@dataclass
class Usage:
    """Tokens summed over every request of a run."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    def add(self, usage: Any) -> None:
        for name in asdict(self):
            setattr(self, name, getattr(self, name) + (getattr(usage, name, 0) or 0))


@dataclass
class Run:
    """What happened in one run; `answer` is `None` if none was submitted."""

    question: str
    strategy: str
    model: str
    effort: str
    answer: dict[str, Any] | None = None
    outcome: str = (
        "no_answer"  # answered | no_answer | max_turns | refusal | max_tokens
    )
    turns: int = 0
    tool_calls: int = 0
    tool_errors: int = 0
    context_chars: int = 0  # characters of every tool result
    seconds: float = 0.0
    usage: Usage = field(default_factory=Usage)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_question(
    client: Any,
    question: dict[str, Any],
    strategy: str,
    repo: Path,
    model: str,
    effort: str,
    max_turns: int = 25,
) -> Run:
    """Run the agent on one question until it submits an answer or gives up."""
    run = Run(question["id"], strategy, model, effort)
    system = SYSTEM.format(repo=question["repo"], hint=STRATEGY_HINTS[strategy])
    messages: list[dict[str, Any]] = [{"role": "user", "content": question["question"]}]
    cited = Citations()
    started = time.monotonic()
    try:
        while run.turns < max_turns:
            run.turns += 1
            response = client.messages.create(
                model=model,
                max_tokens=16000,
                system=system,
                tools=TOOLS[strategy],
                messages=messages,
                output_config={"effort": effort},
                cache_control={"type": "ephemeral"},
            )
            run.usage.add(response.usage)
            if response.stop_reason in ("refusal", "max_tokens"):
                run.outcome = response.stop_reason
                return run
            calls = [b for b in response.content if b.type == "tool_use"]
            submitted = [c for c in calls if c.name == "submit_answer"]
            if submitted:
                run.answer = dict(submitted[0].input)
                run.outcome = "answered"
                return run
            if not calls:  # ended its turn without answering: remind it once more
                messages.append({"role": "assistant", "content": response.content})
                messages.append(
                    {
                        "role": "user",
                        "content": "Call `submit_answer` with your answer.",
                    }
                )
                continue
            messages.append({"role": "assistant", "content": response.content})
            messages.append(
                {
                    "role": "user",
                    "content": [
                        _execute(
                            run, strategy, repo, c, question.get("topic", ""), cited
                        )
                        for c in calls
                    ],
                }
            )
        run.outcome = "max_turns"
        return run
    finally:
        run.seconds = round(time.monotonic() - started, 2)


def _execute(
    run: Run,
    strategy: str,
    repo: Path,
    call: Any,
    topic: str = "",
    cited: Citations | None = None,
) -> dict[str, Any]:
    run.tool_calls += 1
    result: dict[str, Any] = {"type": "tool_result", "tool_use_id": call.id}
    try:
        result["content"] = run_tool(
            strategy, repo, call.name, dict(call.input), topic, cited
        )
    except ToolError as e:
        run.tool_errors += 1
        result |= {"content": f"Error: {e}", "is_error": True}
    run.context_chars += len(result["content"])
    return result
