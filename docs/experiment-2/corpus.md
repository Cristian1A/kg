# Experiment 2: the kg corpus

P0 of [experiment 2](requirements.md) (#71). The curated memory of kg's own
history (R2-01, R2-11 curated mode) that every retrieval strategy reads. It
lives in `bench/corpus/kg/`: **one file per session, in order**, each a kg
input document that `kg add` merges into one store (R2-08, R2-10).

```bash
kg init --kg-dir /tmp/mem/.kg
for f in bench/corpus/kg/*.json; do kg add "$f" --kg-dir /tmp/mem/.kg; done
```

Loading the first *n* files gives the memory as it stood after session *n*.
The questions pinned at `e066c56` read files 01–11; C2, pinned at `7dfd6ad`,
reads all 12.

## Contents

| | Count |
|---|---|
| Sessions | 12, from 2026-10-07 to 2026-10-25 |
| Memories | 78: 37 decisions, 14 tasks, 11 experiments, 11 issues, 5 constraints |
| Components | 12 |
| Evidence | 76: issues, PRs, comments, commits and files |
| Edges | 282 |

Of the memories, 53 end `active`, 11 `done`, 3 `superseded` and 11
`invalidated`; 3 `supersedes`, 4 `invalidated_by` and 3 `blocked_by` edges
carry those changes.

## Sessions

Each file is one Claude Code session of the project, cited by date and the
first eight characters of its ID, the same as in the
[questions](questions-draft.md). Session 12 is the start of this experiment,
up to `7dfd6ad`, and only C2 reads it.

| File | Session |
|------|---------|
| 01 | Requirements interview and repository set-up |
| 02 | Manual check of #1, samples folder, schema and validate |
| 03 | Store, kg add, and the move to English |
| 04 | Extractors, renderers, agent guide and MVP validation |
| 05 | v0.2 re-scoped to the evidence phase; CI, consistency and queries |
| 06 | First benchmark, the plan with scrapy, and node cards |
| 07 | The previous session was lost |
| 08 | Stale-graph reads, keeping the graph fresh, release 0.2.0 |
| 09 | The project site |
| 10 | Benchmark v3 proposal and the scrapy runs |
| 11 | Council, step 0, and closing kg |
| 12 | Experiment 2 opened |

## Format

The memory model of §4 maps onto kg's schema with no change to kg:

| §4 | In the corpus |
|----|---------------|
| memory types | node `type`: `Decision` and `Issue` from kg's catalog; `Component`, `Task`, `Experiment`, `Constraint`, `Evidence` and `Session` as custom types (valid, reported as notes) |
| title, body | `label`, `description` |
| creation time, session, status | `attrs.created`, `attrs.session`, `attrs.status` |
| provenance | `provenance.method: manual`, `extractor: exp2-curated@1` |
| relations | edge `type` in kg's snake_case: `decided_because`, `affects`, `supported_by`, `supersedes`, `invalidated_by`, `blocked_by`, `produced` |
| evidence anchor | `attrs.kind` (`issue`, `pr`, `comment`, `commit`, `file`), `attrs.ref` and, for files, `attrs.commit` and `provenance.source` |

- **Text follows Engram's formats** ([engram.md](engram.md)): a memory's
  `description` is *What / Why / Where / Learned*. A session's is *Goal /
  Instructions / Discoveries / Accomplished / Next steps / Relevant files*.
  The text is the same for every strategy; only the structure on top differs
  (R2-09).
- **Status changes are later writes.** When a session supersedes,
  invalidates or finishes an earlier memory, its file holds that node again
  with only the new `attrs.status`, and `kg add` merges it (the new value
  wins). A memory created and changed in the same session is written with
  its final status.
- **Evidence anchors are a path and a commit, not line ranges yet.** Suspect
  memories (§4.3) need lines. They are added in P1, with the staleness check.

## How it was written

- **Sources:** the 71 issues and PRs with their comments, the commits on
  `main`, the docs at `e066c56`, and the 11 reviewed sessions (dialogue only,
  paraphrased, never quoted raw; N2-06). Messages that looked like they held
  a credential were skipped.
- **One pass per session, in order:** what the session decided, found, tried,
  left pending or changed, with the PRs and issues it produced. Not one
  memory per question.
- **Left out on purpose:** facts that only a file holds and no session or PR
  discussed. D9 (Python version and dependencies) has no memory, so the
  direct lookups also measure what memory does not need to hold.
- **Checks** (`tests/test_bench.py`): the files merge in order into one store;
  every memory has a valid status and exactly the session that produced it;
  the relations are the closed catalog of §4.2; and every key point of the
  questions that only GitHub or a session can answer is in the corpus of
  their snapshot.

The JSON files are the source; edits go to them directly.

## Threats

- **Written after the questions, by the same model.** The memories could
  favour the answers the questions need. Against it: the pass is per session
  and covers every one, 30 of the 78 memories hold fewer than half the key
  points of any question, and the agent-written mode (R2-11) in P1 builds a
  second corpus with no sight of the questions. Results are reported for
  both.
- **The coverage check is lexical.** A key point found anywhere in the corpus
  does not prove that one memory, or one hop, holds the whole answer. Which
  strategy can put it together is what P1 and P2 measure.
- **Session 12 is the session that wrote this corpus.** Only C2 reads it,
  and only up to `7dfd6ad`, before the questions existed.
