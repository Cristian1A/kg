# Benchmark: questions over code vs. over the knowledge graph

Measures whether a kg graph improves an agent's answers about a repository,
compared with an agent that reads the code (#39, RNF-10). The goal is not to
prove that the graph works. It is to find out **when it adds value and what it
costs**. A result where the graph does not help is a valid outcome.

It lives outside the `kg` package because it calls a model; `kg` itself calls
no LLM and needs no keys (RF-24).

## How it works

Each question is run once per **strategy**, with the same model, effort,
system prompt and turn limit:

| Strategy | Tools | Evidence it cites |
|----------|-------|-------------------|
| `code` (baseline) | `list_files`, `read_file`, `search` over the repo | `path:line` |
| `graph` | `kg` (read-only `kg query`, `kg impact`, `kg status`) over the repo's store | node IDs and edges |

Both end by calling `submit_answer` with `answer`, `items` and `evidence`.

- **Repos** (`repos.json`): the three repos of `docs/examples/`, each pinned
  to a commit. `prepare` clones them into `bench/.cache/` (ignored by git) and
  builds each store with `kg extract` plus the committed agent layer
  (`examples/agent/<repo>.json`), so the graph strategy needs no LLM to build
  its graph.
- **Questions** (`questions/*.json`): each has a `topic` (`development`,
  `tests`, `documentation`, `decisions`), a human-readable `reference` answer
  checked against the code, and an `expect` block for mechanical grading:
  - `items` plus `normalize` (`module`, `package` or `text`): scored with F1
    over the normalized names (`etl/utils.py`, `module:etl.utils` and
    `etl.utils` are the same module);
  - `keywords`: groups of alternatives the answer must mention; the score is
    the share of groups found.
- **Metrics** per run: score, traceability (share of `evidence` that exists in
  the repo or the graph), input and output tokens (cache reads and writes
  included), turns, tool calls, wall time, and the outcome (`answered`,
  `max_turns`, `refusal`, `max_tokens`). Quality and cost are reported
  separately.
- **Loop**: a manual tool-use loop (`agent.py`) so each request's usage is
  recorded and the turns are capped. The prompt prefix (tools and system) is
  stable and cached.
- **Same model for both strategies**: no fallback model is configured, so a
  refused request counts as a failure instead of being answered by another
  model.

## Running it

```bash
pip install -e ".[bench]"          # the Anthropic SDK, only for this
python -m bench.run --dry-run      # prepare the repos and exercise the tools; no model calls
export ANTHROPIC_API_KEY=...       # or `ant auth login`
python -m bench.run                # pilot: questions/pilot.json, both strategies
python -m bench.run --only mfdp-impact --strategies graph   # a subset
python -m bench.report bench/results/<file>.jsonl           # Markdown report
```

Options: `--questions`, `--strategies code,graph`, `--only ID1,ID2`,
`--model` (default `claude-opus-5-5`), `--effort` (default `medium`),
`--max-turns` (default 25), `--out`.

Each run appends one JSON line to `bench/results/<UTC time>.jsonl`, with the
answer, the grade, the metrics and the configuration needed to repeat it:
model, effort, turn limit, question file, repo commits, kg version and commit,
Python version and the system prompt. Commit the result files of runs that a
report relies on.

**Cost.** Every run calls the model. The pilot (6 questions × 2 strategies)
is small; measure its cost before scaling to 15–30 questions.

## Running it with subagents (no API key)

`bench.subagent` runs the same questions with the same confined tools, but
the agent is a subagent started by a coding agent (for example Claude Code's
Agent tool), so no API key is needed:

```bash
python -m bench.subagent prepare              # one prompt per question and strategy
# give each run directory's prompt.md to a fresh subagent
python -m bench.subagent collect bench/.cache/subagent/<session> --usage usage.json
python -m bench.report bench/results/<session>-subagent.jsonl
```

Each subagent's only tool is `python -m bench.subagent call <run dir> <tool>
<json>`, which runs the strategy's tool, logs it in `calls.jsonl`, caps the
calls at 25 and stores the `submit_answer` input. `--usage` maps each run
directory name to the `total_tokens`, `seconds` and `model` that the subagent
notification reports.

Differences from `bench.run`:

- The confinement is by instruction, not by sandbox: check `calls.jsonl` (and
  the subagent's transcript) to confirm it used only its tools.
- Only the total tokens are known, and they include the coding agent's own
  system prompt and tool definitions. Compare the strategies with each other,
  not with `bench.run` results. Effort is whatever the coding agent uses.

## Limits

- 15–30 questions guide decisions; they are not statistically conclusive,
  especially once split by topic or commit.
- Grading is mechanical: an answer that is right but names things differently
  than `normalize` expects scores lower. Read the answers in the results file
  before drawing conclusions.
- Strategies differ in context and tools by design; the token budget, turn
  limit, model and prompt are the same.
- The graph strategy sees the committed agent layer, which an agent wrote with
  access to the code and documents. The benchmark measures answering from a
  graph, not building one.

## Pilot (`questions/pilot.json`)

| ID | Repo | Topic | Reference |
|----|------|-------|-----------|
| `bpc-decisions` | basic-python-cli | decisions | No external dependencies; a single argument |
| `bpc-tests` | basic-python-cli | tests | No tests |
| `mfdp-impact` | my_first_data_project | development | Both ETL pipelines call `get_postgres_connection` |
| `mfdp-dependencies` | my_first_data_project | development | `azure`, `psycopg2` |
| `pca-sqlalchemy` | python-clean-architecture | development | Six non-test modules import SQLAlchemy |
| `pca-architecture` | python-clean-architecture | decisions | Clean Architecture; use cases in `src/interactor` |

Next: run the pilot, check the harness (prompts, grading, token counting),
then grow to 15–30 questions with the topic-specific graph and two-commit
variants described in #39.
