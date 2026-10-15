# Benchmark report: does the graph help an agent? (v0.2)

The decision point of v0.2 ([roadmap.md](roadmap.md#exit), RNF-10, #39). An
agent answers questions about a repository, either by reading the code or by
querying the kg graph, and the answers are graded against references checked
in the code. How the benchmark works is in [bench/README.md](../bench/README.md);
the raw results are in `bench/results/`.

## Summary

**On these repos the graph does not answer better than the code, and it does
not answer more cheaply.** Reading the code scores 1.00 once a grading error
is corrected, and the graph scores 0.98, with the same tokens and about a
third more time. The graph has three real advantages: multi-hop questions
(impact, import chains) take fewer calls, every claim cites node IDs and
edges, and a stale graph says that it is stale instead of inventing answers.
It fails where the graph and the code disagree: it repeats a README that the
workflow files contradict, and a stale graph cannot answer about anything that
changed.

The repos are small, 4 to 104 files, where reading the code is cheap. What the
evidence does **not** cover is the case kg is designed for: a repo too large to
read. That is the first experiment of v0.3 (see *What this means for v0.3*).

## Setup

| | |
|---|---|
| Agent | A fresh Claude Code subagent per run (Claude Opus 5.5), no API key: `bench.subagent` |
| Strategies | `code`: list, read and search files. `graph`: read-only `kg query`, `kg impact`, `kg status`. `topic`: the same over a store of the question's topic |
| Limits | 25 tool calls per run; same prompt for every strategy except the tool section |
| Repos | `basic-python-cli` (4 files), `my_first_data_project` (22), `python-clean-architecture` (104), `kg` itself (100, at `1a342c4`), and `kg-stale` (the code of `1a342c4` with the graph of `ebd078d`) |
| Questions | 6 pilot, 17 main (`questions/main.json`), 6 stale (`questions/stale.json`): 29 in all. Reference answers come from an AST import graph independent of kg, or from reading the files |
| Graph | `kg extract` plus the committed agent layer (`examples/agent/<repo>.json`) |
| Grading | Mechanical: F1 over normalized names, or keyword groups. Traceability: the share of cited evidence that exists in the repo or the graph |

## Results

| Run | Questions | Score | Answered | Traceability | Tokens | Calls | Seconds |
|-----|-----------|-------|----------|--------------|--------|-------|---------|
| Pilot, code | 6 | 1.00 | 6/6 | 1.00 | 29 905 | 4.2 | 21 |
| Pilot, graph | 6 | 1.00 | 6/6 | 0.86 | 32 256 | 4.3 | 27 |
| Main, code | 17 | 0.94 (1.00 corrected) | 17/17 | 0.99 | 34 637 | 5.5 | 30 |
| Main, graph before #49 | 17 | 0.92 | 16/17 | 0.94 | 35 448 | 7.5 | 45 |
| Main, graph with #49 | 17 | 0.98 | 17/17 | 0.96 | 34 785 | 6.1 | 41 |
| Main, topic stores | 17 | 0.98 | 17/17 | 0.94 | 33 981 | 6.6 | 46 |
| Stale, code | 6 | 1.00 | 6/6 | 1.00 | 33 095 | 4.8 | 30 |
| Stale, graph | 6 | 0.63 | 6/6 | 0.59 | 33 458 | 5.7 | 44 |

- **Corrected:** `pca-presenter-impl` scored 0 for the code strategy because
  it named the modules without their `src.` prefix (`app.flask.presenters…`).
  The answer is right; the grader is too strict.
- **Tokens** are the totals the subagent reports, which include about 28 000
  tokens of Claude Code's own prompt in every run. The difference between
  strategies is a few thousand tokens at most.
- **#49** (`kg query tested`, `kg impact --type`, an explicit "tested"
  criterion) came out of the first main run: the graph agent had run out of
  calls listing untested modules one test at a time, and an impact answer was
  57 KB, 109 of its 125 results tests.

### By topic (main questions)

| Topic | Questions | Code | Graph (#49) | Topic stores |
|-------|-----------|------|-------------|--------------|
| development | 9 | 0.89 (1.00 corrected) | 0.99 | 1.00 |
| tests | 3 | 1.00 | 1.00 | 1.00 |
| documentation | 3 | 1.00 | 0.89 | 0.89 |
| decisions | 2 | 1.00 | 1.00 | 1.00 |

### Multi-hop questions

Where the graph earns its keep: the answer needs several hops that the graph
already holds.

| Question | Code calls | Graph calls | Code tokens | Graph tokens |
|----------|-----------|------------|-------------|--------------|
| `pca-impact-user` (19 modules, transitive) | 5 | 3 | 43 057 | 43 107 |
| `kg-impact-validation` (9 modules, transitive) | 9 | 4 | 34 820 | 31 743 |
| `mfdp-constants-impact` | 7 | 2 | 30 254 | 29 175 |
| `pca-path` (5-import chain) | 6 | 4 | 38 339 | 30 106 |
| `kg-path` | 5 | 4 | 32 413 | 29 676 |
| `pca-flask-deps` (packages through imports) | 8 | 9 | 40 919 | 35 775 |
| `kg-cli-deps` | 9 | 7 | 37 020 | 40 863 |

Both strategies are right on all seven. The graph uses fewer calls on six and
fewer tokens on five.

### Stale graph (`questions/stale.json`)

The graph is from `ebd078d`, before `kg.update` existed; the code is at
`1a342c4`.

| Question | Changed? | Code | Stale graph | Fresh graph |
|----------|----------|------|-------------|-------------|
| `kgs-path` | no | 1.00 | 1.00 | 1.00 |
| `kgs-decision-llm` | no | 1.00 | 1.00 | 1.00 |
| `kgs-cli-imports` | yes | 1.00 | 0.89 | – |
| `kgs-impact-validation` | yes | 1.00 | 0.88 | 0.94 |
| `kgs-tests-update` | yes | 1.00 | 0.00 | 1.00 |
| `kgs-update-functions` | yes | 1.00 | 0.00 | – |

Every stale answer mentions that the graph is stale (the `stale_graph` limit,
RF-77), and none claims what the graph cannot show. When something is
missing, the answer says so: "src/kg/cli.py is among the modified files … the
current file may import modules the graph does not show (e.g. kg.update or
kg.analysis)". When the element is new, the agent declines ("the graph has to
be re-extracted") instead of guessing. The cost is the answer itself: 0.63
against 1.00.

## Answers to the exit questions

1. **On which kinds of questions does the graph help, and on which not?**
   - **Development, multi-hop** (impact, import chains, packages reached
     through imports): same accuracy as the code, fewer calls. This is the
     only kind where it helps, and only in effort, not in accuracy.
   - **Tests:** after #49, the same as the code. Before #49 it failed.
   - **Documentation:** worse. On `mfdp-auto-workflows` the graph repeats the
     README ("flake8 is the only automatic workflow"). The CodeQL workflow
     also runs on a weekly cron, and the agent reading the YAML found it. The
     agent layer copies the docs, and `kg extract` does not read workflow
     triggers, so the graph cannot contradict the docs.
   - **Decisions:** the same as the code. The decisions sit in a README or a
     requirements file that the code agent finds with one search.
2. **Do topic-specific graphs beat the full graph?** No: the same score, 2%
   fewer tokens, more calls and more time. Since #49, `kg impact --type` and
   `kg query node --type` filter at query time, which removes most of the
   noise a topic store would remove.
3. **How much does a stale graph hurt?** It does not mislead, but it cannot
   answer about what changed: 1.00 on the controls, 0.00 to 0.89 on the
   changed questions, 0.63 overall. The RF-77 warning works as designed.
4. **Is `kg impact` precise enough with `imports` alone, or does it need
   `calls`?** For these questions, `imports` is enough: every impact
   question scored 1.00 with the graph, except one run that filtered out a
   `Package` with `--type Module`. The questions ask for modules, though; a
   question about which functions call a function would need `calls`
   (RF-13), and none was asked.

## What this means for v0.3

The roadmap says that if the graph does not help, v0.3 starts with a redesign
instead of following its table. The evidence is weaker than "does not help":
the graph is as accurate as the code, cites its evidence, saves calls on
multi-hop questions and is safe when stale. But it does not beat reading the
code on repos of this size. Our recommendation:

1. **First, a benchmark on a large repo** (hundreds of modules, where reading
   the code takes many calls), with the multi-hop and test questions. This
   tests the case kg is designed for. If the graph does not win there, the
   redesign starts.
2. **Move up: keeping the graph fresh** (hook and incremental extraction,
   RF-73, RF-78). A stale graph is safe but useless for anything that
   changed, so its value depends on being up to date.
3. **Move up: checking documents against code.** The documentation failure
   comes from copying the docs into the graph. Extracting workflow triggers
   and other configuration, and flagging where a document and the code
   disagree (CU-03), turns this weakness into a use case.
4. **Keep, conditional on step 1: the MCP server** (RF-23). It is the natural
   way for agents to use the graph if the graph pays off.
5. **Move down: topic views** (RF-44): question 2 found no gain. **Move down:
   `calls` relations** (RF-13): question 4 found no need, although no
   function-level question tested it.

## Update: context and graph-guided reading (#52, step 1)

The v0.2 runs could not show how much context each strategy loads: subagent
token totals include about 28 000 tokens of the coding agent's own prompt.
Every tool call now records the size of its result, so each answer reports
`context_chars`, the characters of every tool result it loaded. Earlier runs
were replayed where the tools have not changed since (code, the graph with
#49, stale). The first graph runs and the pilot graph runs came before #49,
so they cannot be replayed.

The new `hybrid` strategy is how kg is meant to be used: query the graph,
then read only what it cites. `read_file` opens only the files and line
ranges in the provenance of the nodes the graph returned in that run.

| Run | Questions | Score | Answered | Context (chars, mean / median) | Calls | Seconds |
|-----|-----------|-------|----------|--------------------------------|-------|---------|
| Main, code | 17 | 0.94 (1.00 corrected) | 17/17 | 11 974 / 7 385 | 5.5 | 30 |
| Main, graph (#49) | 17 | 0.98 | 17/17 | 14 640 / 11 998 | 6.1 | 41 |
| Main, hybrid | 17 | **1.00** | 17/17 | 14 888 / 9 758 | 7.1 | 44 |
| Pilot, code | 6 | 1.00 | 6/6 | 2 930 / 1 773 | 4.2 | 21 |
| Pilot, hybrid | 6 | 1.00 | 6/6 | 5 423 / 3 788 | 5.7 | 39 |
| Stale, code | 6 | 1.00 | 6/6 | 8 460 / 2 862 | 4.8 | 30 |
| Stale, graph | 6 | 0.63 | 6/6 | 9 161 / 6 470 | 5.7 | 44 |
| Stale, hybrid | 6 | 0.65 | 5/6 | 35 647 / 39 874 | 16.0 | 63 |

**What the hybrid strategy fixes.** It scores 1.00 on the main questions.
On `mfdp-auto-workflows`, where the graph alone repeated the README, it read
the workflow files the graph cites and found the CodeQL cron. On the stale
graph, `kgs-cli-imports` went from 0.89 to 1.00: the graph cites
`src/kg/cli.py`, and reading it shows the two imports the graph lacks.

**Where the context goes.** Reading what the graph cites is cheap: `read_file`
is 3.8% of the hybrid context, about 500 characters a read. **The other 96% is
the graph's own output**:

| Command | Share of the hybrid context | Mean characters a call |
|---------|-----------------------------|------------------------|
| `query node` | 36% | 2 430 |
| `query find` | 27% | 3 361 |
| `impact` (with and without `--type`) | 24% | 6 000–20 000 |
| `read_file` | 4% | 504 |

The JSON is about three times the size of the text output for the same node
(1 786 against 626 characters), mostly provenance repeated on every edge. So
the graph loads more context than reading the code, not less. It loses on
lookups (`pca-presenter-impl`: 31 897 against 1 438), and wins on paths and
documents (`pca-path`: 2 849 against 22 022; `kg-docs-merge`: 11 031 against
25 291).

**Two things the hybrid runs found:**
- **The agent layer can cite stale lines.** On `kg-decision-html` the decision
  cites `docs/requirements.md:279`, which at the benchmark commit is the
  heading "## 9. Out of scope": the store was built with an older agent layer.
  Only a strategy that reads what the graph cites can notice this, which is
  what step 2's quoted claims are for.
- **A stale graph hides the new files.** The citation rule only opens files a
  node cites, so a file added after the graph (`src/kg/update.py`) cannot be
  read even though `kg status` names it. Letting the files `kg status` lists
  as changed or added be read would let the hybrid strategy recover from a
  stale graph.

**What this means for step 2.** The lever is the size of the graph's answers,
not reading less code: node cards with the provenance once, neighbor counts
instead of lists, and a compact output for `find` and `impact`. If that cuts
the graph's output by about two thirds, as the text format suggests, the
hybrid strategy would load about half the context of reading the code, with
the same score.

## Limits of this evidence

- **Sample size.** 29 questions, one run each. A difference of one question
  moves a strategy's mean by 0.06; 0.98 against 1.00 is a tie.
- **Small repos.** The largest has 104 files. Reading code is cheap there.
- **Contamination.** The subagents run inside this repository and load its
  `AGENTS.md`, which describes kg. The kg questions may be easier for both
  strategies than they would be for a stranger's repo.
- **Who wrote the questions.** The same model family that answers them wrote
  the questions and references, and also the agent layer of each graph.
- **Tokens.** Only totals are known, dominated by Claude Code's own prompt;
  they cannot separate input from output.
- **Grading.** Mechanical: one known false negative (`src.` prefixes), and
  keyword questions reward wording. The answers in the result files were read
  to check the conclusions.
- **Prompt change.** The second graph run's tool description also lists
  `query tested` and `impact --type`, so part of its gain may come from the
  description.
- **The graph's agent layer was written with the code at hand.** The
  benchmark measures answering from a graph, not the cost of building one.
