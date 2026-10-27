# Experiment 2: gates G1–G3

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
