# Experiment 2: checkpoint

Where the work stands, so a new session can resume it without this one's
conversation. **Update this file whenever the state below changes.**

Last update: 2026-10-27, G0 passed; P2: S4/S8 run done; G1–G3 pass weakly
(provisional until S3), see [gates.md](gates.md).

## State

| Phase | State |
|-------|-------|
| P0 | done: [questions](questions-draft.md) frozen (`bench/questions/memory/kg.json`), [corpus](corpus.md) (`bench/corpus/kg/`), gates in [requirements](requirements.md) §7 |
| P1 | harness done ([harness.md](harness.md), `bench/memory.py`, S0 and S2); **G0 done and passed** ([g0.md](g0.md)) |
| P2 | in progress: S1, S4 and S8 implemented ([harness.md](harness.md)); **S4/S8 run done; G1–G3 pass weakly** ([gates.md](gates.md), provisional until S3) |
| P3–P4 | not started |

Branch `experiment-2/agent-context-memory`; issue #71 tracks the checklist.

## The G0 run in progress

- **Session:** `bench/.cache/memory/20261025T212002Z/` (git-ignored, on this
  machine only): 240 runs = 40 questions × `s0`, `s2` × 3 repeats.
- **Order:** `order.txt` in the session, shuffled with seed 71. Runs are
  launched in that order, in batches of about 20.
- **Pilot:** 4 runs in `bench/.cache/memory/20261025T211107Z/`, not part of
  the results (D2 and R1, both strategies, once).

### Resume

From the repo root, with `source env/bin/activate`:

```bash
S=bench/.cache/memory/20261025T212002Z
python -m bench.memory status $S          # done / pending runs
```

A run is **done** when it has `answer.json` or used its 25 calls. For each
pending run, in the order of `order.txt`, start one Claude Code subagent
(Agent tool, `general-purpose`, model `opus`) with exactly this prompt:

```text
Read the file /home/cris/networkx/<S>/<run>/prompt.md and follow its instructions exactly. Reading that one prompt file is allowed; after that, the only command you may run is the one it describes.
```

- Launch about 20 at a time in the background, wait for the notifications,
  then the next batch. Never an API key.
- **A run that has `calls.jsonl` but is not done** was cut off (session
  limit, crash). It cannot be resumed as is. Ask the user before resetting
  it (deleting its `calls.jsonl`), then launch it again.

### When every run is done

```bash
# tokens and seconds of every run, from the subagents' transcripts
python -m bench.memory usage $S ~/.claude/projects/-home-cris-networkx/<session id>/subagents
python -m bench.memory collect $S          # -> bench/results/memory/20261025T212002Z.jsonl
python -m bench.report bench/results/memory/20261025T212002Z.jsonl
```

- The subagents' transcripts live under the Claude Code session that launched
  them: `8c8f5c90-4496-4460-8c26-1107a306f8e4` for the runs started on
  2026-10-25, `c97e654c-8c88-4590-8da9-24580c3cd0b5` for those started on
  2026-10-26 (batches 5–9), `23eb9334-2b4d-4205-9750-5e558d746c9e` for
  batch 10 on. Runs launched from a later session have their transcripts under
  that session's ID, so run `usage` once per session directory; it merges
  into `usage.json`.
- **G0** (requirements §7): on the 15 questions that only GitHub or a session
  can answer (`lives_in` without `file` or `git-log`), the best memory
  strategy must beat S0 by at least 0.15 in mean score. Otherwise the
  experiment stops and the result is reported.

```bash
python - <<'EOF'
import json, statistics
rows = [json.loads(l) for l in open("bench/results/memory/20261025T212002Z.jsonl")]
hidden = [r for r in rows if not {"file", "git-log"} & set(r["lives_in"])]
for s in ("s0", "s2"):
    print(s, round(statistics.mean(r["grade"]["score"] for r in hidden if r["strategy"] == s), 3))
EOF
```

- Commit the results file and a short write-up of G0 (mean, spread, per
  category), then update #71 and this file.

## Notes from the run

- **Protocol violations** are listed in `violations.tsv` in the session
  (run, what happened). Report each result with and without them.
  So far: `kg-M6.s0.3` ran shell helpers on the tool output.
- **The keyword grader is lenient with abstentions.** `kg-R3.s0.2` said the
  repo does not record why the repos were dropped, guessed licensing, and
  scored 1.00 because it named "license" and "MIT". This favours S0, so it
  makes G0 harder to pass, not easier. The grader stays frozen. After the
  run, audit by hand the answers to the 15 hidden questions and report the
  number of answers that admit not knowing, next to the mechanical score.
- After batches 1 and 2 (40 runs, 2026-10-25): every run answered except
  none; `kg-R6` scored 0.00 in all three S0 runs and 1.00 with S2.
- Batch 4 (positions 61–80 of `order.txt`) was cut off at 22:27 on
  2026-10-25 when the session ran out of tokens: 19 runs had 1–3 calls and
  no answer. With the user's approval (2026-10-26) their `calls.jsonl` was
  deleted and they were launched again in batch 6. No subagent had seen a
  full answer, so the reset does not bias the result.
- Batch 5 (positions 81–100): `kg-R1.s0.1` used its 25 calls without
  answering (scores 0, as decided). It had chained several calls per shell
  command; it used only the allowed command, so it is not a violation.
- Batch 7 (positions 101–120): `kg-R5.s0.3` and `kg-B1.s0.2` also used their
  25 calls without answering, the same way (loops and chained calls in one
  shell command). Three S0 runs so far, none with S2. Report this pattern
  next to G0: S0 spends more calls searching for what is not in the repo.
- Batch 8 (positions 121–140): every run answered. `kg-S2.s2.3` piped the
  tool output through grep (logged in `violations.tsv`, the first S2 one).
- Done after batch 8: 141 of 240.
- Batch 9 (positions 141–160) was stopped on 2026-10-26 at the user's request
  (tokens running out): 15 runs answered, 5 were cut off with 9–12 calls
  (`kg-B2.s0.3`, `kg-D7.s0.1`, `kg-M7.s0.1`, `kg-M7.s0.2`, `kg-N3.s0.2`).
  **Next session:** ask the user before deleting their `calls.jsonl`, launch
  them again, then continue from position 161. Done: 156 of 240.
- Batch 10 (2026-10-26, session `23eb9334`): with the user's approval the
  five cut-off runs of batch 9 had their `calls.jsonl` deleted and were
  launched again, together with the 15 pending runs of positions 161–176
  (161 was already done). Every run answered; none used its 25 calls
  (`kg-R5.s0.1` came closest with 20) and no subagent reported a violation.
  Done after batch 10: 176 of 240.
- Batch 11 (positions 177–196, session `23eb9334`): every run answered;
  none used its 25 calls (`kg-C4.s0.2` came closest with 20) and no
  subagent reported a violation. Done after batch 11: 196 of 240.
- Batch 12 (positions 197–218, 22 runs, session `23eb9334`): every run
  answered; none used its 25 calls (`kg-C4.s0.3` and `kg-M6.s0.1` came
  closest with 21) and no subagent reported a violation. Only 20 subagents
  can run at once, so the last two were launched as the first finished.
  Done after batch 12: 218 of 240.
- Batch 13 (positions 219–240, the last 22, session `23eb9334`): 21 runs
  answered. `kg-R1.s0.3` used its 25 calls without answering (scores 0),
  the same way as earlier S0 runs (several calls chained per shell
  command). `collect` counts six such S0 runs in all (`kg-R1.s0.2` and
  `kg-R5.s0.2` had not been noted per batch), none with S2. `kg-B1.s0.3` piped tool
  output through grep/cut/head (logged in `violations.tsv`, three in all).
- **Every run is done: 240 of 240** (2026-10-26). `usage` was run for the
  three sessions (240 runs with usage; `kg-C5.s2.2` has 0 tokens recorded),
  `collect` wrote `bench/results/memory/20261025T212002Z.jsonl`.
- **G0 passes.** On the 15 hidden questions: S0 0.387, S2 0.916, difference
  +0.529 (+0.520 without the three violations; question-level bootstrap
  95% CI 0.32–0.73, seed 71). The write-up is [g0.md](g0.md).
- **Hand audit done** (2026-10-26, in [g0.md](g0.md)): 18 of 45 S0 answers
  abstain (they got 7.0 points), none of S2. Scoring them 0 gives +0.684.
  The three `kg-B1.s2` runs are a keyword false negative (right decision,
  no RF-23), not a retrieval failure. #71 updated with the result.
  **Next:** P2 (S4, S8, then S1, S3; gates G1–G3) and the agent-written
  corpus (R2-11).

## P2

- **2026-10-26: S1, S4 and S8 implemented** in `bench/memory.py`, with
  tests; the design is in [harness.md](harness.md) (FTS5 seeds, relations to
  depth 2 for S4 and 1 for S8, 8 memories, S8 adds evidence). Not run yet.
- **Decided with the user (2026-10-26):** S1 stays (R2-13 requires it once
  H1 holds, and it is the control for "the whole memory fits in the
  prompt"), run separately after S4/S8. S0 and S2 are not run again: G1–G3
  compare against the G0 session.

### The S4/S8 run in progress

- **Session:** `bench/.cache/memory/20261026T154359Z/` (git-ignored, this
  machine only): 240 runs = 40 questions × `s4`, `s8` × 3 repeats, prepared
  at `3410487`. `order.txt` is shuffled with seed 71 the same way as G0's
  (`random.Random(71).shuffle` of the sorted run names).
- **Resume and launch exactly as for G0** (section "Resume" above), with
  `S=bench/.cache/memory/20261026T154359Z`: the same subagent prompt, about
  20 at a time (at most 20 subagents run at once), ask before resetting a
  cut-off run.
- **Transcripts:** runs launched from session
  `61399e93-a7ac-4b50-8057-5f667d54c9ae` (batch 1 on). Session `23eb9334`
  marked batch 1 as launched, but no run had any calls on 2026-10-26, so it
  never started; nothing to reset.
- Batch 1 (positions 1–20, session `61399e93`): every run answered; none
  used its 25 calls (`kg-R6.s8.3` came closest with 12) and no subagent
  reported a violation. Done after batch 1: 20 of 240.
- Batch 2 (positions 21–40, session `61399e93`): every run answered; none
  used its 25 calls (`kg-B4.s4.3` came closest with 10) and no subagent
  reported a violation. Done after batch 2: 40 of 240.
- Batch 3 (positions 41–60, session `61399e93`): every run answered; none
  used its 25 calls (`kg-B2.s8.3` came closest with 11) and no subagent
  reported a violation. Done after batch 3: 60 of 240.
- Batch 4 (positions 61–80, session `61399e93`): every run answered; none
  used its 25 calls (`kg-B2.s8.2` came closest with 10) and no subagent
  reported a violation. Done after batch 4: 80 of 240.
- Batch 5 (positions 81–100, session `61399e93`): every run answered; none
  used its 25 calls (`kg-B4.s4.2` came closest with 14) and no subagent
  reported a violation. Done after batch 5: 100 of 240.
- Batch 6 (positions 101–120, session `61399e93`): 19 runs answered; none
  used its 25 calls and no subagent reported a violation. `kg-R6.s8.1` was
  still running (8 calls) when batch 7 was launched.
- Batch 7 (positions 121–140, session `61399e93`): every run answered,
  including `kg-R6.s8.1` from batch 6 (11 calls, the most); none used its 25
  calls and no subagent reported a violation. Checked on 2026-10-27: no
  run was cut off, nothing to reset. Done after batch 7: 140 of 240.
- Batch 8 (positions 141–160, session `25cb3c1f-27f9-41c3-9fd3-1e8c7a84b257`,
  which holds the transcripts of batch 8 on): every run answered; none used
  its 25 calls (`kg-B2.s4.3` came closest with 8) and no subagent reported a
  violation. Done after batch 8: 160 of 240.
- Batch 9 (positions 161–180, session `25cb3c1f`): every run answered;
  none used its 25 calls (`kg-C2.s8.3` came closest with 8) and no subagent
  reported a violation. `kg-T2.s4.3` said after submitting that its answer
  also claims `--depth 0` is still rejected for `kg impact`, citing a test
  it never read; check it in the hand audit. Done after batch 9: 180 of 240.
- Batch 10 (positions 181–200, session `25cb3c1f`): every run answered;
  none used its 25 calls (`kg-M4.s8.1` and `kg-M6.s4.1` came closest with
  6) and no subagent reported a violation. Done after batch 10: 200 of 240.
- Batch 11 (positions 201–220, session `25cb3c1f`): every run answered;
  none used its 25 calls (`kg-B2.s4.2` and `kg-B2.s8.1` came closest with
  8) and no subagent reported a violation. Done after batch 11: 220 of 240.
- Batch 12 (positions 221–240, the last 20, session `25cb3c1f`): every run
  answered; none used its 25 calls (`kg-B4.s8.2` came closest with 11) and
  no subagent reported a violation. For two runs (`kg-S4.s4.1`,
  `kg-S5.s4.1`) the auto-mode safety classifier was unavailable; their
  transcripts were checked by hand: only the prompt read and the allowed
  `bench.memory call` command.
- **Every run is done: 240 of 240** (2026-10-27). No S4/S8 run used its 25
  calls in the whole run (the most was 14) and `violations.tsv` is empty.
  `usage` was run for sessions `61399e93` and `25cb3c1f` (240 runs with
  usage, none empty); `collect` wrote
  `bench/results/memory/20261026T154359Z.jsonl`.
- First look, mechanical score (not yet the gates): all 40 questions S0
  0.711, S2 0.956, S4 0.951, S8 0.954; the 15 hidden questions S0 0.387,
  S2 0.916, S4 0.932, S8 0.912. **Next:** evaluate G1–G3 as pre-registered
  in [requirements](requirements.md) §7 against the G0 session, write it
  up, update #71; then the S1 run.
### G1–G3 (2026-10-27)

- Procedure fixed and committed **before** computing evidence recall or
  staleness errors: [gates.md](gates.md) (`d614cf5`). Code: `bench/gates.py`
  with `tests/test_bench_gates.py` (`6b3e18f`).
- Blind staleness audit done: `bench/results/memory/staleness-audit.tsv`
  (96 answers, S0/S2/S4/S8 on T1–T4 and S1, S2, S4, S5). **No staleness
  error in any strategy.**
- Report: `python -m bench.gates report bench/results/memory/20261025T212002Z.jsonl
  bench/results/memory/20261026T154359Z.jsonl --audit
  bench/results/memory/staleness-audit.tsv`. Mechanical verdict:
  - **G1 passes on 2 categories**, the minimum: rationale (S8 evidence
    recall +0.111, CI −0.06 to +0.33) and blocked (S4 accuracy +0.250,
    S8 +0.125 and recall +0.167). Fragile: blocked is likely driven by
    kg-B1, where S2 scores 0 by a known keyword false negative (g0.md hand
    audit). Check per question, and report with and without kg-B1.
  - **G2 passes:** no accuracy loss on direct lookups; time ×1.22 (S4) and
    ×1.10 (S8) of S2.
  - **G3 passes trivially:** 0 errors everywhere (S2 has none, so the graph
    could not halve them). Uninformative: a ceiling effect.
  - All provisional until S3 runs (gates compare to the best of S2 and S3).
- **Done:** the write-up is in [gates.md](gates.md) §Results. Per question,
  blocked's gain is all kg-B1 (S2 0.00, S4 1.00, S8 0.50; B2–B4 tie at
  1.00): without it G1 fails. Rationale's is S8's evidence recall (kg-R3,
  kg-R7), from the evidence its prompt lists. Multi-hop is 0.06 *below* S2.
  Every bootstrap interval includes 0.
- **Next:** update #71 (ask the user first), then S3 (makes the gates
  final), S1, the R2-09 variant (S2 with relation targets indexed as text,
  the test of the kg-B1 mechanism), the agent-written corpus.
- **S3** waits until the S4/S8 run is done (the user's decision,
  2026-10-26). Runtime: `sentence-transformers` with `all-MiniLM-L6-v2`, as
  an optional extra (N2-02, Q2-03).

## Decisions already taken (do not reopen)

- Subagents only, never an API key. Everything versioned in English.
- Every strategy has S0's tools; only the memory in the prompt differs.
- S2 follows Engram's FTS5 ranking with OR over the question's words, K = 8.
- A run that uses its 25 calls without answering scores 0, as in
  experiment 1.
- S4 was corrected after freezing, before any scored run (questions draft,
  open point 5). Nothing else changes in the frozen questions.

## Next after G0

If G0 passes: P2, strategies S4 (graph traversal) and S8 (hybrid), then S1
and S3, and gates G1–G3. The agent-written corpus (R2-11) is still to build;
it is the control for the corpus having been written after the questions.
