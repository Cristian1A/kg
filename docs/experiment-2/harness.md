# Experiment 2: the harness

P1 of [experiment 2](requirements.md) (#71). `bench/memory.py` runs the
[questions](questions-draft.md) against the [kg corpus](corpus.md) with
Claude Code subagents, never an API key (R2-16).

```bash
python -m bench.memory prepare --strategies s4,s8 --repeat 3   # prompts
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
| `s1` | every memory, oldest first | the upper bound on recall, about 37 KB |
| `s2` | the 8 best memories by FTS5 | as Engram ranks them |
| `s4` | 3 FTS5 seeds, relations to depth 2, 8 memories | each with its relations |
| `s8` | 4 FTS5 seeds, relations to depth 1, 8 memories | each with its relations and evidence |

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

**S4 and S8 add the store's structure** (P2), with the same budget of 8
memories and the same text as S2, so what changes is which memories are
chosen and what is shown under each (R2-09):

- **Seeds.** Both start from S2's FTS5 ranking: the top 3 for S4, the top 4
  for S8. A traversal needs somewhere to start; using S2's keeps the
  comparison to one variable.
- **Links between memories.** A traversal moves from one memory to another
  through a recorded relation (`supersedes`, `blocked_by`,
  `decided_because`, in either direction), through a shared piece of
  evidence (the same issue, PR, commit or file), or through the session that
  produced both. Components are not followed: `component:bench` alone is
  shared by 19 memories, so it would link nearly everything.
- **S4 orders by the graph.** Seeds first, then by number of links from a
  seed, then by the kind of link (relation, then evidence, then session),
  then by the seed it came from. Depth 2.
- **S8 orders by the text.** Seeds first, then its depth-1 neighbours in
  FTS5 order (neighbours the question's words do not match go last). It can
  return fewer than 8 when the seeds have few neighbours.
- **What is shown.** Under each memory, S4 and S8 list its relations
  (`supersedes`, `blocked by`, `decided because of`, `invalidated by`,
  `affects`, and their reverse) with the other end's ID and title. S8 also
  lists the evidence it is supported by (kind, reference, commit, title).
- **Size.** About 3.9 KB for S2, 4.7 KB for S4 and 5.3 KB for S8 on the 40
  questions. S4 brings 4 memories S2 does not have, and S8 brings 3.

**S1** puts every memory of the snapshot in the prompt, oldest first, in
S2's format (about 37 KB). It bounds what retrieval can gain.

**S2r** is the R2-09 variant: S2 with each memory's relation lines (as S4
shows them: kind, the other end's ID and title) appended to its indexed
content and shown under it. Same FTS5 query, weights and K = 8; no traversal,
so a related memory is named but not brought in. If S2r matches S4 where S4
beats S2 (kg-B1: the `blocked by task:mcp-server` line), the edge adds
nothing that its text could not.

**S3** ranks the memories by cosine similarity between the question and each
memory's title and body, embedded with `sentence-transformers/all-MiniLM-L6-v2`
on CPU (N2-02, Q2-03; the `memory` extra). K = 8, ties by ID, shown in S2's
format. Embeddings are computed when the session is prepared, so every repeat
gets the same context (N2-03).

## Results

`collect` writes the fields `bench.report` reads, plus `repeat`,
`memory_chars` (the context in the prompt) and `lives_in`. `context_chars`
counts the memory and every tool result. Grading is the key points of each
question (R2-07); evidence recall and staleness errors (§6.4) are computed
from the same records in P2.
