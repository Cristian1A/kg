# Experiment 2: the harness

P1 of [experiment 2](requirements.md) (#71). `bench/memory.py` runs the
[questions](questions-draft.md) against the [kg corpus](corpus.md) with
Claude Code subagents, never an API key (R2-16).

```bash
python -m bench.memory prepare --strategies s0,s2 --repeat 3   # prompts
python -m bench.memory call <run dir> <tool> '<JSON>'          # a subagent's only tool
python -m bench.memory collect <session> --usage usage.json    # grade
python -m bench.report bench/results/memory/<session>.jsonl    # report
```

## One variable: the memory in the prompt

Every strategy gets **the same tools as S0** and the same prompt. Only the
lines that describe the memory, and the memory itself, differ (N2-01):

- **Tools:** `list_files`, `read_file` and `search` from experiment 1, plus
  `git_log` (hash, date, subject and body; filter by message or path), over a
  clone of this repository at the question's commit.
- **The clone holds nothing later than that commit.** Other branches and the
  remote are removed, so neither the files nor the log can show the
  experiment's own questions or corpus.
- **The memory is context, not a tool.** Each strategy is a function of the
  question and the store (R2-12) whose result goes into the prompt under
  `## Memory`. It is the same on every run (N2-03). Letting the agent query
  the memory itself is S7's job, not S2's.
- **Status is shown by every strategy.** Each memory's header gives its type,
  status, date and session, so a superseded or invalidated memory is labelled
  wherever it appears (§4.3). Relations are not shown: they are the graph's
  structure, the variable of S4 (R2-09).

Adding memory to S0's tools, rather than replacing them, is the realistic
case: an agent with a memory still has the repository. It also means a
memory strategy can only gain on what the files lack, which is what H1 and
G0 are about.

## The strategies

| ID | Context | Notes |
|----|---------|-------|
| `s0` | none | the repository and its log only |
| `s2` | the 8 best memories by FTS5 | as Engram ranks them |

**S2 follows Engram** ([engram.md](engram.md)) as far as a fixed query
allows:

- **Index.** One FTS5 table over each memory's ID, title, body and type,
  sessions included (Engram indexes session summaries too). It is derived
  from the store on every run and never saved (R2-10).
- **Ranking.** `bm25` with Engram's column weights: title 5, body 1, the
  others 0.
- **Query.** Each word of the question quoted and joined by `OR`, as Engram's
  candidate search does. Its interactive search joins words by AND, which on
  a whole question returns nothing.
- **Left out:** Engram's recency and pinned boosts. The corpus has no pinned
  memories, and recency against the time of the run would make the context
  depend on the day.
- **K = 8**, about 4 to 8 KB of context: the full memories, not 300-character
  previews, since there is no second call to open them.

## Results

`collect` writes the fields `bench.report` reads, plus `repeat`,
`memory_chars` (the context in the prompt) and `lives_in`. `context_chars`
counts the memory and every tool result. Grading is the key points of each
question (R2-07); evidence recall and staleness errors (§6.4) are computed
from the same records in P2.
