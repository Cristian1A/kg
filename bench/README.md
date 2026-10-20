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
| `topic` | the same `kg` tool, over a store of the question's topic (`bench/topics.py`) | node IDs and edges |
| `hybrid` | `kg`, plus `read_file` limited to the files and line ranges the graph has cited in the run, and to the files it reports as changed or added since it was built (`kg status`, or a `stale_graph` limit), read whole | node IDs, edges and `path:line` |
| `cards` | `hybrid`, with `--brief` added to every `kg` command that takes it (node cards) | node IDs, edges and `path:line` |
| `companion` | the `code` tools plus `kg`, with `--brief` as in `cards`: the graph next to search, not instead of it (#67). The report counts the runs that call `kg` | `path:line`, node IDs and edges |

All end by calling `submit_answer` with `answer`, `items` and `evidence`.

- **Repos** (`repos.json`): the three repos of `docs/examples/` and `kg`
  itself, each pinned to a commit. `kg-stale` has `graph_commit`: its store is
  built at that older commit, then the repo is checked out at `commit`, so the
  graph is stale (`questions/stale.json`). `prepare` clones them into `bench/.cache/` (ignored by git) and
  builds each store with `kg extract` plus the committed agent layer
  (`examples/agent/<repo>.json`), so the graph strategy needs no LLM to build
  its graph. It also writes the topic stores, `.kg-<topic>`: the types a topic
  needs plus `Repo`, `File` and `Config`, so freshness and containment still
  work.
- **Questions** (`questions/*.json`): each has a `topic` (`development`,
  `tests`, `documentation`, `decisions`), a human-readable `reference` answer
  checked against the code, and an `expect` block for mechanical grading:
  - `items` plus `normalize` (`module`, `package` or `text`): scored with F1
    over the normalized names (`etl/utils.py`, `module:etl.utils` and
    `etl.utils` are the same module);
  - `keywords`: groups of alternatives the answer must mention; the score is
    the share of groups found.
- **Metrics** per run: the characters of every tool result (`context_chars`,
  the context the answer loaded), score, traceability (share of `evidence` that exists in
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

A short bootstrap prompt is enough: tell the subagent to `cat` its
`prompt.md` once and follow it. Claude Code runs at most 20 subagents at a
time, so a larger session goes in batches.

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

## Results

The report, with the answers to the v0.2 exit questions, is
[docs/benchmark.md](../docs/benchmark.md). Result files:

| File | Run |
|------|-----|
| `results/20261015T092017Z-subagent.jsonl` | Pilot, `code` and `graph` |
| `results/20261015T093425Z-subagent.jsonl` | `questions/main.json`, `code` and `graph` |
| `results/20261015T094923Z-subagent-graph-49.jsonl` | `questions/main.json`, `graph`, with `kg query tested` and `kg impact --type` (#49) |
| `results/20261015T095721Z-subagent-topic.jsonl` | `questions/main.json`, `topic` |
| `results/20261015T095733Z-subagent-stale.jsonl` | `questions/stale.json`, `code` and `graph` |
| `results/20261015T154218Z-subagent-hybrid-pilot.jsonl` | `questions/pilot.json`, `hybrid` (#52) |
| `results/20261015T154220Z-subagent-hybrid.jsonl` | `questions/main.json`, `hybrid` (#52) |
| `results/20261015T154222Z-subagent-hybrid-stale.jsonl` | `questions/stale.json`, `hybrid` (#52) |
| `results/20261015T160303Z-subagent-cards.jsonl` | `questions/main.json`, `cards` (#52) |
| `results/20261015T160309Z-subagent-cards-stale.jsonl` | `questions/stale.json`, `cards` (#52) |
| `results/20261019T213916Z-subagent-scrapy.jsonl` | `questions/scrapy.json`, `code`, `graph`, `hybrid` and `cards` (#52) |
| `results/20261020T090411Z-subagent-scrapy-step0.jsonl` | `questions/scrapy.json`, `companion`, `cards` and `code`, on the faster kg (#67) |
| `results/20261020T090412Z-subagent-scrapy-step0.jsonl` | `questions/scrapy.json`, `companion` and `cards`, second run (#67) |
