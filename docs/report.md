# Does a knowledge graph help an agent answer questions about code?

**No, not on the questions we tested.** On a 489-file repository, an agent
with kg's graph next to its search tools answered as well as one that only
read the code (0.96 against 0.98). It took 45% longer. Where the agent
chose to use the graph, the graph halved the text the agent had to read, but
it never made an answer more accurate. On the one question about type-only
imports, it did worse.

This is the write-up of kg's benchmark (October 2026, #39, #52, #67). Each
run, in the order it happened, is in [benchmark.md](benchmark.md). The raw
results are in [`bench/results/`](../bench/results/). The harness can measure
other tools too ([bench/README.md](../bench/README.md#measure-your-own-tool)).

## The question

kg turns a Python repository into a knowledge graph stored next to the code,
as plain JSON. The deterministic layer holds modules, classes, functions,
imports, dependencies and tests, each with its file and line. Agents add a
second layer: documents, decisions and concepts. Queries (`kg query`,
`kg impact`) answer questions like "what depends on this module", "how is A
connected to B" or "which tests cover this".

The bet was that an agent answering questions about a project would do
better with the graph than with grep and file reads: more accurate, or the
same for less.

## How it was measured

- **Agent.** A fresh Claude Code subagent (Claude Opus 5.5) per question and
  strategy, at most 25 tool calls, the same prompt apart from the tools.
- **Questions.** 45, each with a reference answer checked in the code and
  graded mechanically (F1 over names, or keyword groups):
  - 6 pilot and 17 main questions on four small repos (4 to 104 files);
  - 6 on a stale graph, built from an older commit than the code;
  - 16 on [scrapy](https://github.com/scrapy/scrapy) at `8026dee`, 489 Python
    files.
- **Cost.** Context is measured as the characters of every tool result an
  answer loaded. Token totals are dominated by the coding agent's own prompt
  (about 28 000 tokens a run). Seconds are wall time.
- **Strategies.** Seven, from the graph alone to the graph next to search:

| Strategy | Tools | What it tests |
|----------|-------|---------------|
| `code` | list, read and search files | the baseline |
| `graph` | `kg query`, `kg impact`, `kg status` only | the graph instead of the code |
| `topic` | the same, on a store of the question's topic | whether smaller graphs help |
| `hybrid` | `kg`, then read only the lines the graph cites | the graph as a map to the code |
| `cards` | `hybrid` with compact answers (`--brief`) | how much of the cost is output size |
| `companion` | the `code` tools plus `kg --brief` | the graph next to search |
| `lean` | the `code` tools plus `companion`'s prompt line | the control for that line |

## What we found

### On small repos, the graph tied

On the 17 main questions, reading the code scored 1.00 (after correcting
one grading error). The graph alone scored 0.98 and graph-guided reading
scored 1.00 ([report](benchmark.md#results)).

Compact node cards then cut the context to 4 411 characters, against
11 974 for the code, at the same score
([node cards](benchmark.md#update-node-cards-52-step-2)). That looked like
a win, but on repos this small reading the code is cheap either way.

Multi-hop questions (impact, import chains) took fewer calls with the graph
on six of seven, at the same accuracy
([multi-hop](benchmark.md#multi-hop-questions)).

### A stale graph is safe, not useful

Over a graph older than the code, the agent always said the graph was stale,
and never claimed what it could not show. It still could not answer about
what had changed: 0.63, against 1.00 for the code. Once it could read the
files `kg status` reported as changed, it reached 0.83. It then loaded three
to four times the code's context
([stale reads](benchmark.md#update-reading-what-a-stale-graph-reports-52)).

### On a large repo, reading the code won

scrapy was the case kg was designed for: too large to read whole. Each
strategy ran once per question
([scrapy](benchmark.md#update-a-large-repo-scrapy-52-67)):

| Strategy | Score | Context (chars) | Seconds |
|----------|-------|-----------------|---------|
| code | 0.99 | 9 638 | 29 |
| cards | 0.98 | 17 516 | 92 |
| hybrid | 0.97 | 48 704 | 85 |
| graph | 0.93 | 28 638 | 115 |

Part of the time was kg itself, not the graph. Every query re-validated the
11.5 MB store against its schema, which took 5 to 10 seconds. The accuracy
losses were facts the graph does not hold:

- imports under `if TYPE_CHECKING:`, which exist only for type checkers;
- inheritance, since base classes are kept as plain strings;
- settings, and classes loaded from strings in them.

### With kg fast and next to search, the graph cost time

We fixed the latency: a query on scrapy went from 4.9 s to 0.8 s. We then
gave the agent the code tools plus kg (`companion`), as agents are actually
used. Each strategy ran 32 times:

| Strategy | Score | Context (chars, mean) | Seconds (mean) |
|----------|-------|-----------------------|----------------|
| code | 0.98 | 8 731 | 31.8 |
| lean (control) | 0.99 | 8 955 | 34.7 |
| companion | 0.96 | 5 199 | 46.0 |
| cards | 0.95 | 19 166 | 50.4 |

`lean` ran 16 times. The gate set before the run was a score within 0.03 of
`code`, no more than 15% more context and no more than 30% more time.
`companion` passed on score and context, and failed on time (+45%).

### What is the graph's and what is the prompt's

`companion`'s prompt says "use whichever gets the answer with fewer calls".
The `lean` control gives the code tools that same line:

| Questions | `lean` | `companion` |
|-----------|--------|-------------|
| 8 where `companion` never called kg | 1.00 · 2 851 chars · 25.7 s | 0.99 · 2 851 chars · 30.3 s |
| 7 where it did (decision, impact, path, tests) | 0.99 · 9 816 chars · 35.1 s | 0.98 · 4 299 chars · 47.4 s |
| `scr-impact-job-runtime` | 1.00 · 104 s | 0.50 · 163 s |

On the questions answered without the graph, the prompt line explains the
whole saving, to the character. On the questions where the agent reached for
the graph, the graph cut the reading by 56% at the same score. It cost 35%
more time.

On the hardest question, which modules a change to `scrapy/utils/job.py`
could affect at runtime, it got in the way. `kg impact` listed 261 modules where the answer has 11, because it
does not tell type-only imports apart.

## What the graph is good and bad at

**Good at:**
- **Less reading on structural questions.** Impact, paths and the tests of a
  module take about half the context.
- **Traceable answers.** Every claim cites a node, an edge or a line.
- **Saying what it cannot see.** A stale or incomplete graph says so,
  instead of guessing.

**Bad at:**
- **Speed.** Answers that use the graph take longer, even once each query
  takes under a second.
- **Facts the parser does not extract.** Type-only imports, inheritance and
  string-based wiring all cost answers.
- **Lookups.** A single `search` already finds most answers. Most of
  scrapy's questions were of this kind.

**Neutral:** accuracy. No strategy beat reading the code.

The same shape appears in published work.
[RepoGraph](https://arxiv.org/abs/2410.14684) reports about two points on
SWE-bench Lite. [LocAgent](https://arxiv.org/abs/2503.09089) finds its gains
come from entity search rather than graph traversal.
[Codebase-Memory](https://arxiv.org/abs/2603.27277) reports 83% with a graph
against 92% for file exploration, at ten times fewer tokens.

## Limits of this evidence

- **Small sample.** 16 scrapy questions, one or two runs per strategy. A
  difference of 0.02 in score is a tie.
- **Noisy times.** They are the wall time of subagents run 20 at a time.
- **One model family.** The same family answered the questions, wrote them,
  wrote the references and wrote each graph's agent layer.
- **Questions that favour grep.** 14 of the 16 scrapy questions are
  one-hop lookups. A frozen set of hard impact questions was planned but
  not run.
- **Building cost not measured.** The benchmark measures answering from a
  graph, not the cost of writing its agent layer.

## An open idea: edges from strings

Python projects often wire code through strings rather than imports. In
scrapy, `RetryMiddleware` is never imported. A settings dict names it, and
`load_object` loads it at runtime:

```python
DOWNLOADER_MIDDLEWARES_BASE = {
    "scrapy.downloadermiddlewares.retry.RetryMiddleware": 550,
}
```

Django's `INSTALLED_APPS` and `MIDDLEWARE` work the same way, and so do
plugin entry points. No import graph sees these links; grep finds the string
but not what it means.

An edge from the setting to the class it loads, with its line and a
confidence below 1, would answer "which setting turns this on". It would
also answer "what configuration does a change to this class touch". About
five of scrapy's 16 questions turned on it.

We found no tool that extracts it, but the search was short. Nor did we
measure whether it helps an agent. It would fit better as a contribution to
an existing code-graph tool than as a reason to keep kg going.

## What stays

kg still works as a library and CLI: deterministic extraction, a validated
and versioned store, queries, impact, staleness checks, rendering and an
agent guide. Version 0.2 is released, and `main` has the faster reads. The
benchmark harness, its 45 questions and every result file are committed.
New strategies and new repos can be added to them.
