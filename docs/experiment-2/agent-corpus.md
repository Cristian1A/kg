# Experiment 2: the agent-written corpus (R2-11)

The curated corpus ([corpus.md](corpus.md)) was written by hand, knowing the
questions. G0 and the gates measured retrieval from it. This corpus is the
control: an agent writes the memory session by session, as a real pipeline
would, **without seeing the questions or the curated corpus**. If the results
hold on it, they are not an artefact of a memory written for the questions.

This document fixes the design and the analysis **before** any writer or run
(2026-10-28). Results are added below when they exist.

## Design

Agreed with the user on 2026-10-28.

- **Sessions:** the same 12 as the curated corpus, in order, with the same
  IDs and pinned commits (only that metadata is read from the curated files).
- **Sources per session** (`python -m bench.memory_write sources`, git-ignored
  under `bench/.cache/memory/writers/`):
  - the session's dialogue: the user's and the assistant's text, no tool
    calls, tool output or thinking; lines that look like a credential are
    dropped (N2-06);
  - GitHub issues and PRs opened, closed or merged, and issue comments, dated
    after the previous session's pinned commit and up to this one's. Bodies
    are taken **as they stood at the end of that window**, from GitHub's edit
    history: a body edited later (such as #71's checklist) would leak the
    future;
  - the commits reachable from `7dfd6ad` in the same window: message and
    files.
  - Session 12's dialogue is cut at `7dfd6ad` (2026-10-25 13:41:58 +01:00),
    before the questions existed, as the curated corpus does.
- **Writer:** one Claude Code subagent (`general-purpose`, Opus) per
  session, in order. Its prompt (`python -m bench.memory_write prompt`) gives
  Engram's protocol (record what is durable and costly to reconstruct; check
  before writing; update instead of duplicating; keep superseded and
  invalidated memories, linked), the curated corpus's format (same node
  types, statuses and closed relation catalog; status changes as later
  writes), an example from another project, and the list of every memory
  written so far. It may read only its sources file and run only `show` (an
  earlier memory in full) and `submit`.
- **Submit** checks the document (one Session node with the fixed ID; known
  types and statuses; every new memory with its session, date and a
  `produced` edge; closed relation catalog; no dangling edge), merges it
  after the earlier sessions with kg's validation, and stores it in
  `bench/corpus/kg-agent/` with provenance `llm`, `exp2-agent@1`.
- **Blindness check:** after the 12 sessions, every writer's transcript is
  checked for any read or command beyond its sources file, `show` and
  `submit`. A writer that read the questions, the curated corpus or
  docs/experiment-2 is reported, and its session is written again.

### Simplifications

- The writer is not the agent that worked in the session: it reads the
  session's dialogue afterwards. It sees what was said, not what the tools
  showed, so facts only visible in tool output are missing, as they would be
  for an agent that summarises its own session from memory.
- "Check before writing" is a list of every memory's ID, type, status and
  title, with `show` for the full text, not Engram's search. With under 100
  memories the list fits; a larger store would need search.

## Runs

- **S2, S2r and S4** on the agent corpus: 40 frozen questions × 3 strategies
  × 3 repeats = 360 runs, the same harness, model and subagent prompt as
  before (`bench.memory prepare --corpus bench/corpus/kg-agent`).
- **S0 is not re-run:** its prompt holds no memory, so the G0 session's S0
  runs (`20261025T212002Z`) are its baseline.
- The same strategies on the curated corpus come from the earlier sessions
  (S2: `20261025T212002Z`, S4: `20261026T154359Z`, S2r: `20261027T092553Z`).

## Analysis (fixed before the runs)

1. **The corpus:** memories by type and status, relations by type, evidence
   items, against the curated corpus.
2. **Coverage:** for the 15 hidden questions (`lives_in` without `file` or
   `git-log`), the share of their keyword groups found anywhere in the agent
   corpus of their snapshot, with the same lexical check the curated corpus
   passes at 100% (`tests/test_bench.py`).
3. **G0 on the agent corpus:** on the 15 hidden questions, the best of S2,
   S2r and S4 minus S0 in mean accuracy, with the question-level bootstrap
   (10,000 resamples, seed 71). The pre-registered bar is +0.15. Below it,
   the curated result does not carry over to an agent-written memory.
4. **Curated against agent-written:** for S2, S2r and S4, mean accuracy on
   all 40 and on the 15 hidden questions, and per category, in both corpora.
   The drop is what writing the memory for the questions was worth.
5. **The graph on the agent corpus:** per G1 category, S4 minus the better
   of S2 and S2r, in accuracy and in evidence recall (gates.md's
   definitions). S3 is not run here, so this is not the gate itself.
6. **kg-B1:** whether the agent corpus records the blocker (a `blocked_by`
   relation or the blocker named in text) and each strategy's score on it.
7. **Hand audit** of the hidden answers, as in [g0.md](g0.md): how many
   abstain, and the score with abstentions set to 0.
8. **Cost:** the writers' tokens (summed over every request) and the runs'.

Protocol violations (`violations.tsv`) are reported with and without them.
