# Experiment 2: gates G1–G3

**Result (provisional until S3 runs): G1, G2 and G3 pass as pre-registered,
but weakly.** G1 passes on exactly the two categories it needs, and each
rests on little: blocked on one question (kg-B1), rationale on evidence
recall that S8 gets by showing evidence in its prompt. G3 passes only
because no strategy made a staleness error. The graph does not lose the easy
cases (G2). [Results](#results) below.

The gates are pre-registered in [requirements](requirements.md) §7. Two of
the metrics they use, evidence recall and staleness errors (§6.4), had a
definition but no procedure. The procedure below was written and committed
**before** either metric was computed for any run; only the mechanical
accuracy had been looked at (checkpoint, 2026-10-27).

## Runs compared

- S0 and S2: the G0 session `20261025T212002Z`.
- S4 and S8: session `20261026T154359Z`.
- Same 40 frozen questions, 3 repeats each, the same model and harness.
- **S3 has not run.** §7 compares against the best non-graph strategy (S2
  or S3), so for now the comparison is against S2 alone. A gate that fails
  against S2 fails for good (the best of S2 and S3 is at least S2); a gate
  that passes must be checked again once S3 has run.

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

## What it means

The numbers clear the pre-registered bar, but they do not show that the
graph earns its place over FTS5 on this corpus:

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
   that keywords could not.

**Next:** S3 (to make the comparison final), S1, the R2-09 text-with-relations
variant, then the agent-written corpus.
