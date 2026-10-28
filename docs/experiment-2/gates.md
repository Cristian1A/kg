# Experiment 2: gates G1–G3

**Final result (2026-10-28, against the best of S2 and S3): G1, G2 and G3
pass as pre-registered, but the graph does not earn its place.** G1 passes on
exactly the two categories it needs: blocked rests on one question (kg-B1),
and S2r, plain FTS5 with each memory's relation lines indexed as text, scores
1.00 there too; rationale rests on evidence recall that S8 gets by listing
evidence in its prompt. Without kg-B1, G1 fails. G3 passes only because no
strategy made a staleness error. The graph does not lose the easy cases (G2).
[Final results](#final-results-with-s3) below; the first,
[provisional results](#results) against S2 alone are kept.

The gates are pre-registered in [requirements](requirements.md) §7. Two of
the metrics they use, evidence recall and staleness errors (§6.4), had a
definition but no procedure. The procedure below was written and committed
**before** either metric was computed for any run; only the mechanical
accuracy had been looked at (checkpoint, 2026-10-27).

## Runs compared

- S0 and S2: the G0 session `20261025T212002Z`.
- S4 and S8: session `20261026T154359Z`.
- Same 40 frozen questions, 3 repeats each, the same model and harness.
- **S3 had not run** for the [provisional results](#results), which
  compare against S2 alone. The [final results](#final-results-with-s3)
  add session `20261027T092553Z` (S1, S3, S2r).

## Metrics

**Accuracy** is the frozen keyword grade (`grade.score`). A run that did not
answer scores 0.

**Evidence recall** (§6.4: share of reference evidence the answer cites).
Each question's `evidence` list is the reference set. A reference item is
cited when the answer's text or its `evidence` list contains one of the
item's anchors (case does not matter):

- `#N`: the issue or PR number, written `#N`, `issue N`, `PR N`,
  `issues/N` or `pull/N`.
- a hexadecimal ID of 7 or more characters (a commit or a session): its
  first 7 characters.
- a path in backquotes: the path. `` `git log` `` and
  `` `git log -p …` `` instead count as cited when the answer cites any
  commit hash (7+ hexadecimal characters).
- `session … YYYY-MM-DD` with no ID: the word `session` and that date.

An item with no anchor is left out of the denominator. A run that did not
answer has recall 0. Memory IDs count only through the anchors they contain
(a session memory's ID holds its transcript ID); citing a memory that has no
anchor of the reference does not count. S8's prompt lists evidence and the
others do not, so this metric favours S8 by design: that is what S8 is for.

**Staleness errors** (§6.4: answers that assert a superseded or invalidated
memory as current). Judged by hand on the 8 questions where a fact changed:
staleness T1–T4 and supersession S1, S2, S4, S5. A run is an error when its
answer states the old claim (T) or the replaced plan or result (S) as still
true or current. Leaving out what changed, without asserting the old fact,
is not an error (the accuracy grade already counts it). The audit is blind:
the 96 answers of S2, S4, S8 and S0 are shuffled (seed 71), shown with the
question and reference answer but without strategy or repeat, judged, and
only then joined back to their runs. The judgments are stored in
`bench/results/memory/staleness-audit.tsv`.

**Time** is the subagent's seconds (`seconds`, from its transcript).

## Gate rules, as applied

- **G1.** For each of rationale, multi-hop, supersession, staleness and
  blocked work: the category passes if S4 − S2 or S8 − S2 is at least 0.10
  in mean accuracy, or in mean evidence recall. G1 passes with at least two
  categories.
- **G2.** On direct lookups, for S4 and for S8 separately: S2 − graph ≤ 0.03
  in mean accuracy, and mean seconds ≤ 1.30 × S2's.
- **G3.** Staleness errors of S4 and of S8 (count over the 8 questions × 3
  repeats) are each at most half of S2's. If S2 has none, G3 holds only if
  the graph strategy has none either.

Means are over runs (questions × repeats) in the category. Per-question
means and a question-level bootstrap (10,000 resamples, seed 71) are
reported next to each difference, as for G0.

## Final evaluation with S3 (procedure)

Fixed and committed on 2026-10-28, **before** any per-category value,
evidence recall or staleness judgment of the S1/S3/S2r session was
computed. Only the overall and hidden-question mechanical means had been
looked at (checkpoint: S3 0.920 / 0.824, below S2).

- **Runs added:** session `20261027T092553Z` (S1, S3, S2r; same 40
  questions, 3 repeats, model and harness).
- **Comparator.** §7 compares "per category, against the best non-graph
  strategy (S2 or S3)". For each category and each metric, the comparator
  is whichever of S2 and S3 has the higher mean in that category on that
  metric. S1 (whole memory in the prompt) and S2r (the R2-09 variant) are
  not comparators: §7 names only S2 and S3. Both are reported next to it.
- **G1.** A category passes if S4 or S8 minus the comparator is at least
  0.10 in mean accuracy, or in mean evidence recall. The bootstrap is over
  per-question differences to that same comparator.
- **G2.** Accuracy loss on direct lookups against the comparator; time
  against S2, as §7 says.
- **G3.** Staleness errors of S4 and of S8 against the fewer of S2's and
  S3's; with 0 errors in the comparator, the graph must have 0 too.
- **Staleness audit, extended.** The 72 answers of S1, S3 and S2r on the 8
  audited questions get a blind sheet of their own (same rules, shuffled
  with seed 71, codes `b001`…), judged before being joined back, and are
  appended to `staleness-audit.tsv`. The 96 earlier judgments are kept.
- **Also reported:** G1 without kg-B1 (the question blocked rested on),
  S2r on kg-B1 (does a relation indexed as text name the blocker, as the
  edge does?), and S1 and S2r per category.
- **Time outlier.** `kg-R6.s1.3` (17,822 s) was resumed after a session
  limit; its seconds are left out. S1 is in no time gate.

## Results

Computed on 2026-10-27 with

```bash
python -m bench.gates report bench/results/memory/20261025T212002Z.jsonl \
  bench/results/memory/20261026T154359Z.jsonl \
  --audit bench/results/memory/staleness-audit.tsv
```

### Per category

Mean accuracy / evidence recall / seconds, over 3 repeats of each question.

| Category | Qs | S0 | S2 | S4 | S8 |
|----------|----|----|----|----|----|
| direct | 8 | 0.88 / 0.56 / 37 | 1.00 / 0.58 / 24 | 1.00 / 0.67 / 29 | 1.00 / 0.56 / 26 |
| rationale | 6 | 0.40 / 0.50 / 67 | 1.00 / 0.81 / 29 | 0.96 / 0.67 / 28 | 0.96 / 0.92 / 27 |
| multi-hop | 6 | 0.72 / 0.67 / 62 | 0.99 / 0.89 / 28 | 0.93 / 0.90 / 28 | 0.93 / 0.89 / 35 |
| negative | 4 | 0.85 / 0.21 / 45 | 1.00 / 0.71 / 26 | 1.00 / 0.71 / 26 | 1.00 / 0.46 / 25 |
| supersession | 4 | 0.67 / 0.75 / 38 | 1.00 / 0.83 / 26 | 1.00 / 0.75 / 29 | 1.00 / 0.92 / 25 |
| staleness | 4 | 0.94 / 0.94 / 34 | 0.97 / 0.94 / 28 | 0.92 / 0.97 / 34 | 1.00 / 1.00 / 29 |
| blocked | 4 | 0.54 / 0.79 / 70 | 0.75 / 0.71 / 52 | 1.00 / 0.67 / 46 | 0.88 / 0.88 / 40 |
| continuation | 4 | 0.67 / 0.38 / 64 | 0.85 / 0.88 / 24 | 0.75 / 0.88 / 31 | 0.82 / 0.88 / 28 |

S2 is at or near the ceiling in accuracy on every category but blocked and
continuation, so a +0.10 accuracy gain over it was possible only there.

### G1 — passes on 2 of 5 categories (the minimum)

Difference to S2, with the question-level 95% bootstrap interval. A category
passes on +0.10 in accuracy or in evidence recall.

| Category | S4 accuracy | S4 recall | S8 accuracy | S8 recall | Passes |
|----------|-------------|-----------|-------------|-----------|--------|
| rationale | −0.04 [−0.11, 0] | −0.14 [−0.31, 0] | −0.04 [−0.11, 0] | **+0.11** [−0.06, +0.33] | yes (S8 recall) |
| multi-hop | −0.06 [−0.17, 0] | +0.01 [−0.06, +0.08] | −0.06 [−0.17, 0] | 0.00 | no |
| supersession | 0.00 | −0.08 [−0.17, 0] | 0.00 | +0.08 [0, +0.25] | no |
| staleness | −0.06 [−0.17, 0] | +0.03 [0, +0.08] | +0.03 [0, +0.08] | +0.06 [0, +0.11] | no |
| blocked | **+0.25** [0, +0.75] | −0.04 [−0.12, 0] | **+0.13** [0, +0.38] | **+0.17** [0, +0.50] | yes (S4, S8) |

Every interval includes 0: with 4–6 questions per category, no difference is
clearly above chance.

- **Blocked rests on kg-B1 alone.** On B2–B4 all three strategies score 1.00.
  On kg-B1 ("which store decision was left to revisit, and what was it
  waiting for?") S2 scores 0.00 in all three repeats, S4 1.00 and S8 0.50.
  The G0 hand audit called S2's zero a keyword false negative: it names the
  right decision and condition but not the blocker (RF-23, the MCP server).
  S4 and S8 name the blocker because the `blocked by task:mcp-server` edge
  brings that memory into the prompt. So the gain has the mechanism the graph
  is meant to have, but it is one question. **Without kg-B1, blocked shows no
  difference and G1 fails** (one category).
- **Rationale passes on evidence recall only.** S8's recall gain comes mostly
  from kg-R3 (1.00 against S2's 0.33) and kg-R7 (0.67 against 0.50): S8's
  prompt lists each memory's evidence (issues, commits), so its answers cite
  it. That is S8's design, not a better retrieval of the facts: in accuracy
  S8 is 0.04 below S2 (kg-R5, 0.78 against 1.00).
- **Where the graph was expected to win, it does not.** Multi-hop (H3) is
  0.06 *below* S2 for both graph strategies, with equal recall.

### G2 — passes

| Strategy | Accuracy loss on direct lookups (≤ 0.03) | Time vs S2 (≤ 1.30×) |
|----------|------------------------------------------|----------------------|
| S4 | 0.00 | 1.22× |
| S8 | 0.00 | 1.10× |

Every strategy scores 1.00 on the 8 direct lookups. S4 takes 22% more time,
within the margin.

### G3 — passes trivially

The blind audit found **no staleness error** in any of the 96 answers (S0,
S2, S4 and S8 on T1–T4, S1, S2, S4, S5). Every answer to a staleness question
says the old claim no longer holds and names the change; every answer to a
supersession question gives the current state. With S2 at 0 errors, "at most
half of S2's" can only hold as 0 = 0. The gate says nothing about H4: the 8
questions were too easy to make any strategy repeat obsolete knowledge,
including S0, which reads the current files.

Borderline answers, judged not errors and noted in the audit file:
`kg-S5.s0.*` say the template was not tried, without saying the criterion was
replaced (an incomplete answer, not an old claim); three answers to kg-S2
read "fails with every strategy" loosely but report the later lean result.

## Final results with S3

Computed on 2026-10-28, with the procedure fixed in
[Final evaluation with S3](#final-evaluation-with-s3-procedure), with

```bash
python -m bench.gates report bench/results/memory/20261025T212002Z.jsonl \
  bench/results/memory/20261026T154359Z.jsonl \
  bench/results/memory/20261027T092553Z.jsonl \
  --audit bench/results/memory/staleness-audit.tsv   # and --exclude kg-B1
```

### Per category

Mean accuracy / evidence recall, over 3 repeats of each question. S1 and S2r
are not comparators (§7) and are shown for reference.

| Category | S0 | S1 | S2 | S2r | S3 | S4 | S8 |
|----------|----|----|----|-----|----|----|----|
| direct | 0.88 / 0.56 | 1.00 / 0.65 | 1.00 / 0.58 | 1.00 / 0.67 | 0.97 / 0.70 | 1.00 / 0.67 | 1.00 / 0.56 |
| rationale | 0.40 / 0.50 | 0.99 / 0.67 | 1.00 / 0.81 | 0.93 / 0.78 | 0.88 / 0.75 | 0.96 / 0.67 | 0.96 / 0.92 |
| multi-hop | 0.72 / 0.67 | 0.96 / 0.93 | 0.99 / 0.89 | 1.00 / 0.89 | 1.00 / 0.92 | 0.93 / 0.90 | 0.93 / 0.89 |
| negative | 0.85 / 0.21 | 1.00 / 0.79 | 1.00 / 0.71 | 0.97 / 0.46 | 1.00 / 0.62 | 1.00 / 0.71 | 1.00 / 0.46 |
| supersession | 0.67 / 0.75 | 1.00 / 0.75 | 1.00 / 0.83 | 1.00 / 0.83 | 1.00 / 0.79 | 1.00 / 0.75 | 1.00 / 0.92 |
| staleness | 0.94 / 0.94 | 0.97 / 1.00 | 0.97 / 0.94 | 0.97 / 0.92 | 0.94 / 0.97 | 0.92 / 0.97 | 1.00 / 1.00 |
| blocked | 0.54 / 0.79 | 0.75 / 0.71 | 0.75 / 0.71 | 1.00 / 0.75 | 0.79 / 0.75 | 1.00 / 0.67 | 0.88 / 0.88 |
| continuation | 0.67 / 0.38 | 0.88 / 0.88 | 0.85 / 0.88 | 0.85 / 0.88 | 0.72 / 0.88 | 0.75 / 0.88 | 0.82 / 0.88 |

S3 (embeddings) is the comparator only where it beats S2: accuracy on
multi-hop (1.00 against 0.99) and blocked (0.79 against 0.75), recall on
multi-hop, staleness and blocked. Overall it is below S2 (0.920 against
0.956), weakest on rationale (kg-R6: 0.25) and continuation.

### G1 — passes on 2 of 5 categories; fails without kg-B1

Difference to the comparator (S2 or S3, per category and metric), with the
question-level 95% bootstrap interval.

| Category | Comparator (acc / rec) | S4 accuracy | S4 recall | S8 accuracy | S8 recall | Passes |
|----------|------------------------|-------------|-----------|-------------|-----------|--------|
| rationale | S2 / S2 | −0.04 [−0.11, 0] | −0.14 [−0.31, 0] | −0.04 [−0.11, 0] | **+0.11** [−0.06, +0.33] | yes (S8 recall) |
| multi-hop | S3 / S3 | −0.07 [−0.20, 0] | −0.02 [−0.06, 0] | −0.07 [−0.20, 0] | −0.03 [−0.08, 0] | no |
| supersession | S2 / S2 | 0.00 | −0.08 [−0.17, 0] | 0.00 | +0.08 [0, +0.25] | no |
| staleness | S2 / S3 | −0.06 [−0.17, 0] | 0.00 | +0.03 [0, +0.08] | +0.03 [0, +0.08] | no |
| blocked | S3 / S3 | **+0.21** [0, +0.62] | −0.08 [−0.25, 0] | +0.08 [0, +0.25] | **+0.13** [0, +0.38] | yes (S4 acc., S8 recall) |

Every interval includes 0. Without kg-B1, blocked shows no difference
(B2–B4 all at 1.00) and **G1 fails** with one category, as against S2.

- **The edge adds nothing its text could not (R2-09).** On kg-B1, S2r scores
  1.00 in all three repeats and names RF-23 and the MCP server, as S4 does
  (S2 0.00, S3 0.17, S8 0.50). S2r has no traversal: it only indexes and
  shows the relation line `blocked by: [task:mcp-server] MCP server (RF-23)`.
  So the one gain G1's blocked category rests on comes from the relation's
  text being retrievable and visible, not from walking the graph.
- **The whole memory does not help either.** S1, every memory in the prompt
  in S2's format (no relation lines), scores 0.00 on kg-B1, like S2. Having
  the blocker's memory in context is not enough; the link has to be stated.
- **Rationale is unchanged:** S8's recall gain over S2 (kg-R3, kg-R7) comes
  from listing evidence in its prompt; in accuracy it is 0.04 below S2.
- **Multi-hop** (H3), where the graph was expected to win, is 0.07 below S3
  for both graph strategies (kg-M1: S4 and S8 0.60, S2r and S3 1.00).

### G2 — passes

| Strategy | Accuracy loss on direct lookups (≤ 0.03, to S2) | Time vs S2 (≤ 1.30×) |
|----------|-------------------------------------------------|----------------------|
| S4 | 0.00 | 1.22× |
| S8 | 0.00 | 1.10× |

S2 is the comparator on direct lookups (S3 scores 0.97 there).

### G3 — passes trivially

The blind audit of the 72 answers of S1, S3 and S2r (codes `b001`–`b072`)
found no staleness error either: **0 errors in 168 answers**, every strategy.
Against the fewer of S2's and S3's (0), the graph's 0 passes. As before, the
gate says nothing about H4: the 8 questions do not make any strategy repeat
obsolete knowledge.

## What it means

The numbers clear the pre-registered bar, but they do not show that the
graph earns its place over FTS5 on this corpus. The final run with S3, S1
and S2r makes this firmer, not weaker:

1. G1's two passing categories rest on one question (kg-B1) and on S8 showing
   evidence in its prompt. Neither is strong enough to move kg forward as a
   product on those categories alone (§7: only where G1–G3 pass).
2. S2 is already at the ceiling on most categories. The curated corpus,
   written knowing the questions, makes each answer reachable by keywords, so
   there is little left for relations to add. The agent-written corpus
   (R2-11) and the Engram and pandas corpora are where a graph could show a
   difference, if there is one.
3. The cheapest test of the one real mechanism seen (a `blocked by` edge
   bringing in the blocker) is the R2-09 variant: S2 with relation targets
   indexed as text. If it also names RF-23 on kg-B1, the edge adds nothing
   that keywords could not. **It does** (S2r 1.00 on kg-B1, every repeat):
   on this corpus the useful part of the graph is its typed links written
   next to each memory, not traversal. S1 (every memory, no relation lines)
   scores 0.00 there, so what matters is that the link is stated.
4. S3 (embeddings) does not change the picture: it is below S2 overall and
   is the comparator only on multi-hop and blocked, where the graph does not
   beat it either once kg-B1 is set aside.

**Next:** the agent-written corpus (R2-11), the control for the curated
corpus having been written knowing the questions; then P3 (S7,
continuation tasks, the Engram and pandas corpora), where relations might
matter more than here.
