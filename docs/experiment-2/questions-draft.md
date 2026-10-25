# Experiment 2: question draft for the kg corpus

**Status: draft for review.** P0 of [experiment 2](requirements.md) (#71).
Once the questions are reviewed, they move to `bench/questions/` in the
benchmark's JSON format, and are frozen in a commit with the gates before
the first scored run (N2-04).

32 questions about kg's own history, in the shares of R2-04. Each has a
reference answer, its evidence, and **where the answer lives**:

| Code | Source | Visible to S0 (no memory)? |
|------|--------|----------------------------|
| `F` | a file of the repository at the pinned commit | yes |
| `G` | a commit message (`git log`) | yes |
| `I` | an issue, PR or comment on GitHub only | no |
| `T` | a Claude Code session only (transcript; to be checked when transcripts are reviewed, Q2-02) | no |

The questions marked only `I` or `T` are the ones R2-06 is about (at least a
third). **Here they are only 5 of 32** (R1, R3, R5, N3, B1), plus 2 that
depend on them in part (M4, C1). That is short of the target; see
[Open points](#open-points). The pinned commit is `e066c56` (main after
#70) unless a question says otherwise.

## Summary

| Category | IDs | Count | Share | Target |
|----------|-----|-------|-------|--------|
| Direct lookup | D1–D6 | 6 | 19% | 20% |
| Rationale | R1–R5 | 5 | 16% | 15% |
| Multi-hop | M1–M5 | 5 | 16% | 15% |
| Negative knowledge | N1–N3 | 3 | 9% | 10% |
| Supersession | S1–S4 | 4 | 13% | 10% |
| Staleness | T1–T3 | 3 | 9% | 10% |
| Blocked work | B1–B3 | 3 | 9% | 10% |
| Continuation | C1–C3 | 3 | 9% | 10% |


---

## Direct lookup

| ID | Question | Reference answer | Evidence | Lives in |
|----|----------|------------------|----------|----------|
| D1 | Which model answered experiment 1's benchmark questions, and with what tool-call limit? | A fresh Claude Code subagent on Claude Opus 5.5 per question and strategy, at most 25 tool calls | `docs/report.md` §How it was measured | F |
| D2 | Which version and commit of scrapy did the large-repo benchmark use? | 2.19.0, commit `8026dee` | `docs/report.md`; `samples/README.md` | F |
| D3 | Which JavaScript library does the interactive HTML embed, and which version? | vis-network 9.1.2, bundled to work offline | `docs/requirements.md` PA-03 | F |
| D4 | How long did one `kg query` on scrapy take before and after the fast-reads work? | 4.9 s before, 0.8 s after | `docs/report.md` §With kg fast | F |
| D5 | Where does kg cache that a store was already validated, and what is the cache keyed by? | `$XDG_CACHE_HOME/kg/validated/`, keyed by the SHA-256 of the contents, kg's version and the schema | `docs/store.md`; `src/kg/store.py`; PR #68 | F |
| D6 | Which three repositories validated the MVP, and under which license? | basic-python-cli, my_first_data_project, python-clean-architecture; all MIT | `samples/README.md`; `docs/mvp-validation.md`; #12 | F |

## Rationale

| ID | Question | Reference answer | Evidence | Lives in |
|----|----------|------------------|----------|----------|
| R1 | Why does kg not commit its own `.kg/graph.json`, so the CI freshness template does not run on kg itself? | Merge conflicts: two PRs that touch code both change `graph.json`, so the second conflicts almost every time, and PR diffs grow about sixfold. Every contributor has kg and rebuilds the whole graph in about 2 s, so committing it does not pay off. Size (1.17 MB) is not the problem | #59 closing comment | I |
| R2 | Why does the HTML renderer embed vis-network itself instead of using pyvis? | pyvis's template lacks filters, search and the details panel, and pyvis pulls in ipython | `docs/requirements.md` PA-03; #10 | F |
| R3 | Why were two of the first candidate repos for the MVP validation dropped? | They declared no license, and the examples were going to be published, so they risked licensing problems. Three MIT repos replaced them | #12, second comment | I |
| R4 | Why was v0.2 re-scoped on 2026-10-13? | External feedback asked for a short, bounded phase to get evidence that kg solves a problem. The old v0.2 was too broad (deduplication, export, hooks and history, MCP, `calls`, a Dockerfile) and lacked what the plan needed (stale-graph detection, coverage limits, CI, the benchmark as success criterion) | #43; `docs/requirements.md` PA-05 and change log 1.2 | F, I |
| R5 | Why were #35 and #55 to be done together? | They touch the same code and the same decisions: which nodes are visible at start, how hidden nodes are shown, and a layout precomputed in Python. One design chooses the initial view once and lays it out once | #35 and #55, comments of 2026-10-15 | I |

## Multi-hop

| ID | Question | Reference answer | Evidence | Lives in |
|----|----------|------------------|----------|----------|
| M1 | Which experiments led to closing kg, and what did each one show? | (1) 17 questions on small repos: a tie (code 1.00, graph 0.98, hybrid 1.00). (2) 6 on a stale graph: safe but not useful (0.63; 0.83 once it read changed files). (3) 16 on scrapy: code 0.99, graph 0.93, slower. (4) Step 0, `companion`: 0.96 against 0.98, +45% time, gate failed. (5) `lean` control: the prompt line explains the saving where kg was not used | `docs/report.md`; #52; #67 | F |
| M2 | What was step 0's gate, who fixed it when, and which criterion failed? | Score within 0.03 of `code`, at most +15% context, at most +30% time, set in #67 before the run. Score (−0.02) and context (−40%) passed; time failed (+45%) | #67 body and first comment; `docs/report.md` | F, I |
| M3 | Which facts missing from the graph explain the accuracy losses on scrapy, and which question did each cost? | Imports under `if TYPE_CHECKING:` (job runtime impact), inheritance kept as strings (manager subclasses), settings and classes loaded from strings (download delay) | #67 body; `docs/report.md` §On a large repo | F, I |
| M4 | Which problems of kg's own implementation did the review of the scrapy run find, and which commit fixed each? | Every read re-validated the store (fixed in `7947ba7`, validate once); every command imported matplotlib (lazy loading of `kg.render`, PR #68); `--depth 0` was rejected (`97f3741`) | #67 body; `git log` | I, G |
| M5 | Which requirements and issues trace "keep the graph consistent with the code", and how is a stale graph detected today? | RF-72 and RF-77, #37 then #59. A full rebuild of the parser layer keeps agent knowledge; content digests and `kg status` detect changes, not git commits; `kg status --check` and pre-commit hooks guard it | `docs/requirements.md` RF-72, RF-77; `docs/extract.md`; `docs/store.md`; #37; #59 | F |

## Negative knowledge

| ID | Question | Reference answer | Evidence | Lives in |
|----|----------|------------------|----------|----------|
| N1 | Which ways of giving the agent the graph were tried and did not beat reading the code? | `graph`, `topic`, `hybrid`, `cards` and `companion`. `lean` was the control, not a graph strategy | `docs/report.md` strategies table | F |
| N2 | Did letting the agent read the files a stale graph reports solve the stale-graph problem? | Partly: 0.63 → 0.83, still below the code's 1.00, at three to four times the code's context | `docs/report.md` §A stale graph | F |
| N3 | Why can a user not edit or delete nodes from the interactive HTML? | A self-contained offline HTML cannot write back to the store; editing went to the CLI instead (`kg remove`, `kg edit`, #28) | #10 comment; #28 | I |

## Supersession

| ID | Question | Reference answer | Evidence | Lives in |
|----|----------|------------------|----------|----------|
| S1 | The first step-0 result said `companion`'s context saving was not kg's. What did the later control change in that conclusion? | The `lean` control confirmed it only where kg was not called (the prompt line explains all the saving there). Where the agent called kg, the graph did halve the context (−56%) at the same score, at +35% time | #67, both comments; `docs/report.md` §What is the graph's | F, I |
| S2 | Does `scr-impact-job-runtime` fail with every strategy? | It was first reported so (#67, first comment). The later `lean` control scored 1.00 on it (104 s); `companion` scored 0.50 | #67 comments; `docs/report.md` | F, I |
| S3 | How does kg detect a stale graph: by git commits? | No. It was first planned with git commits; #37 replaced that with content digests and `kg status` | `docs/requirements.md` change log 1.2 | F |
| S4 | What is the current plan for v0.3? | There is none: v0.3 ended on 2026-10-20 after the gate failed; #35, #55, #60 and #66 were closed as not planned. Work moved to experiment 2 | `docs/roadmap.md` §How v0.3 ended; this branch's `docs/experiment-2/` | F |

## Staleness

Each quotes a claim that was true when written and checks it against the code
at the pinned commit.

| ID | Question | Reference answer | Evidence | Lives in |
|----|----------|------------------|----------|----------|
| T1 | #67 says every `kg query` re-validates scrapy's 11.5 MB store, 5–10 s per call. Is it still true? | No. Since `7947ba7` a store is validated once and the result cached by content hash | #67; `src/kg/store.py`; `docs/store.md` | I + F |
| T2 | #67 says `kg query node X --depth 0` gives a usage error. Is it still true? | No. `97f3741` shows a node alone with `--depth 0` | #67; `git log`; `src/kg/cli.py` | I + G |
| T3 | The status comment on #52 (2026-10-19) says scrapy is not in `bench/repos.json` and has no questions. Is it still true? | No. `bench/repos.json` lists scrapy and `bench/questions/scrapy.json` has its 16 questions | #52 comment; `bench/repos.json`; `bench/questions/scrapy.json` | I + F |

## Blocked work

| ID | Question | Reference answer | Evidence | Lives in |
|----|----------|------------------|----------|----------|
| B1 | Which decision about the store was left to revisit, and what was it waiting for? | Committing kg's own graph and running the CI template on it, to revisit when the MCP server (RF-23) lands and agents should query kg's graph without building it. RF-23 moved to v0.3 and was never started | #59 closing comment; `docs/requirements.md` | I |
| B2 | Which parts of #52's step 2 were left open? | `Section` nodes for documents, quoted claims in the agent layer, and extracting CI workflow triggers (CU-03) | #52 comment of 2026-10-19; `docs/benchmark.md` | F, I |
| B3 | Which v0.3 items were never started, and why? | MCP (RF-23), export (RF-60–61), `calls` (RF-13), deduplication (RF-31–33), hook and history (RF-73–74), the Dockerfile, plus #35, #55, #60 and #66: the gate failed and kg was closed (#69) | `docs/roadmap.md`; `docs/requirements.md` 1.2 | F, I |

## Continuation

| ID | Question | Reference answer | Evidence | Lives in |
|----|----------|------------------|----------|----------|
| C1 | I want to measure a new tool with the benchmark harness. What do I read first, which strategies do I compare it with, and how must the runs be launched? | `bench/README.md` "Measure your own tool"; compare with `code` and `lean`; run with Claude Code subagents (`python -m bench.subagent prepare`, then `collect --usage`), never with an API key | `bench/README.md`; session of 2026-10-15 | F, T |
| C2 | Resume experiment 2 (pinned at `7dfd6ad`). What is done and what comes next? | Requirements 1.1 approved, open questions answered, Engram and pandas cloned in `samples/`. Next is P0: study Engram, write the questions, freeze them with the gates | `docs/experiment-2/requirements.md`; #71 | F, I |
| C3 | Someone wants to pick up experiment 1's open idea. What is it, how much did it matter, and where should it go? | Edges from dotted-path strings (settings → the class `load_object` loads), with a line and a confidence below 1. About 5 of scrapy's 16 questions turned on it. Better as a contribution to an existing code-graph tool than as a reason to keep kg going | `docs/report.md` §An open idea | F |

---

## Candidates to reach a third not in files

Three more questions whose answers S0 cannot see, or can see only in part:

| ID | Category | Question | Reference answer | Lives in |
|----|----------|----------|------------------|----------|
| D7 | Direct lookup | What review led to the step-0 experiment before closing kg? | An unofficial "council" review: independent analyses, cross-review and a synthesis, run with subagents | T (the roadmap only says "unofficial review") |
| R6 | Rationale | When the gate failed, which options were weighed, and which was chosen? | Option 1, "close and publish", was chosen (PR #70 names it); the others are to be read from the session | I, T |
| M6 | Multi-hop | What triggered the single-language rule for agent-written text, and where is it enforced now? | The basic-python-cli graph mixed Spanish and English labels (#11 comment); the rule is in the agent guide (`kg guide`) | I + F |

## Open points

1. **Too few questions S0 cannot answer.** Even with D7 and R6, 7 of 35 (20%)
   live only in issues or sessions, against the third R2-06 asks for. kg
   wrote most of its decisions into its docs, so the files already hold them.
   About 5 more are needed, and the likely source is the transcripts: dead
   ends, options weighed and reasons that never reached a PR. They are
   written after the transcripts are reviewed (Q2-02). The alternative,
   relaxing R2-06, would weaken H1's test, so the draft keeps it.
2. **Overlap.** R3 and D6 share evidence, and so do S1 and M1. Kept on
   purpose: one asks *what*, the other *why* or *what changed*, which is the
   difference the experiment measures.
3. **C2 is about this experiment.** It is pinned to a later commit than the
   rest and needs its own corpus snapshot.
4. **Grading.** D1–D6, N1, B3 and T1–T3 can be graded on names or keyword
   groups. R1–R5, M1 and S1 need a rubric of key points (R2-07).
5. **Engram and pandas questions** come after these are reviewed, with the
   same categories, from their PRs, issues and generated sessions (R2-02).
