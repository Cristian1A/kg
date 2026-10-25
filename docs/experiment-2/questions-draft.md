# Experiment 2: question draft for the kg corpus

**Status: draft for review.** P0 of [experiment 2](requirements.md) (#71).
Once the questions are reviewed, they move to `bench/questions/` in the
benchmark's JSON format, and are frozen in a commit with the gates before
the first scored run (N2-04).

39 questions about kg's own history, in the shares of R2-04. Each has a
reference answer, its evidence, and **where the answer lives**:

| Code | Source | Visible to S0 (no memory)? |
|------|--------|----------------------------|
| `F` | a file of the repository at the pinned commit | yes |
| `G` | a commit message (`git log`) | yes |
| `I` | an issue, PR or comment on GitHub only | no |
| `T` | a Claude Code session only (reviewed transcript, Q2-02; cited by date and session ID prefix) | no |

The questions marked only `I` or `T` are the ones R2-06 is about (at least a
third). **Here they are 13 of 39 (33%)**: R1, R3, R5, N3 and B1 from GitHub,
and D7, R6, R7, M7, M8, N4, C4 and C5 from the sessions. M4, M6 and C1 depend
on them in part. The pinned commit is `e066c56` (main after
#70) unless a question says otherwise.

## Summary

| Category | IDs | Count | Share | Target |
|----------|-----|-------|-------|--------|
| Direct lookup | D1–D5, D7 | 6 | 15% | 20% |
| Rationale | R1–R7 | 7 | 18% | 15% |
| Multi-hop | M1–M8 | 8 | 21% | 15% |
| Negative knowledge | N1–N4 | 4 | 10% | 10% |
| Supersession | S1, S2, S4 | 3 | 8% | 10% |
| Staleness | T1–T3 | 3 | 8% | 10% |
| Blocked work | B1–B3 | 3 | 8% | 10% |
| Continuation | C1–C5 | 5 | 13% | 10% |

D6 and S3 were dropped after the transcript review: they repeated R3 and M5.

---

## Direct lookup

| ID | Question | Reference answer | Evidence | Lives in |
|----|----------|------------------|----------|----------|
| D1 | Which model answered experiment 1's benchmark questions, and with what tool-call limit? | A fresh Claude Code subagent on Claude Opus 5.5 per question and strategy, at most 25 tool calls | `docs/report.md` §How it was measured | F |
| D2 | Which version and commit of scrapy did the large-repo benchmark use? | 2.19.0, commit `8026dee` | `docs/report.md`; `samples/README.md` | F |
| D3 | Which JavaScript library does the interactive HTML embed, and which version? | vis-network 9.1.2, bundled to work offline | `docs/requirements.md` PA-03 | F |
| D4 | How long did one `kg query` on scrapy take before and after the fast-reads work? | 4.9 s before, 0.8 s after | `docs/report.md` §With kg fast | F |
| D5 | Where does kg cache that a store was already validated, and what is the cache keyed by? | `$XDG_CACHE_HOME/kg/validated/`, keyed by the SHA-256 of the contents, kg's version and the schema | `docs/store.md`; `src/kg/store.py`; PR #68 | F |
| D7 | What review came before the step-0 experiment, and on what terms was it run? | An unofficial "council" on 2026-10-20, set up after Karpathy's llm-council: subagents as experts researched similar tools and what kg could borrow or add, then cross-reviewed and synthesised. It was explicitly unofficial: nothing went to the repo until there was a good idea, which then became #67 | session 2026-10-20 (`84137a84`); `docs/roadmap.md` only says "unofficial review" | T |

## Rationale

| ID | Question | Reference answer | Evidence | Lives in |
|----|----------|------------------|----------|----------|
| R1 | Why does kg not commit its own `.kg/graph.json`, so the CI freshness template does not run on kg itself? | Merge conflicts: two PRs that touch code both change `graph.json`, so the second conflicts almost every time, and PR diffs grow about sixfold. Every contributor has kg and rebuilds the whole graph in about 2 s, so committing it does not pay off. Size (1.17 MB) is not the problem | #59 closing comment | I |
| R2 | Why does the HTML renderer embed vis-network itself instead of using pyvis? | pyvis's template lacks filters, search and the details panel, and pyvis pulls in ipython | `docs/requirements.md` PA-03; #10 | F |
| R3 | Why were two of the first candidate repos for the MVP validation dropped? | They declared no license, and the examples were going to be published, so they risked licensing problems. Three MIT repos replaced them | #12, second comment | I |
| R4 | Why was v0.2 re-scoped on 2026-10-13? | External feedback asked for a short, bounded phase to get evidence that kg solves a problem. The old v0.2 was too broad (deduplication, export, hooks and history, MCP, `calls`, a Dockerfile) and lacked what the plan needed (stale-graph detection, coverage limits, CI, the benchmark as success criterion) | #43; `docs/requirements.md` PA-05 and change log 1.2 | F, I |
| R5 | Why were #35 and #55 to be done together? | They touch the same code and the same decisions: which nodes are visible at start, how hidden nodes are shown, and a layout precomputed in Python. One design chooses the initial view once and lays it out once | #35 and #55, comments of 2026-10-15 | I |
| R6 | When the step-0 gate failed, which options were weighed, and which was chosen? | Option 1, close and publish the negative result (report, a reusable harness, close v0.3), against option 3, take the string edges to an existing tool (risks: the council was only about 50% sure the idea is new, acceptance depends on others, and it was never measured). Option 1 was chosen on 2026-10-20. Option 2 is not in the session text (it was in the report draft) | session 2026-10-20 (`84137a84`); PR #70 names option 1 | I, T |
| R7 | Why was #40 (a reproducible demo) closed with a README section instead of a separate demo? | The user judged it unnecessary: the repo and the published example graphs already show how to apply kg to any repo, so a separate tutorial adds nothing. The README's *Ask the graph* took its place | session 2026-10-15 (`4381279d`); the outcome alone is in the `docs/requirements.md` change log | T |

## Multi-hop

| ID | Question | Reference answer | Evidence | Lives in |
|----|----------|------------------|----------|----------|
| M1 | Which experiments led to closing kg, and what did each one show? | (1) 17 questions on small repos: a tie (code 1.00, graph 0.98, hybrid 1.00). (2) 6 on a stale graph: safe but not useful (0.63; 0.83 once it read changed files). (3) 16 on scrapy: code 0.99, graph 0.93, slower. (4) Step 0, `companion`: 0.96 against 0.98, +45% time, gate failed. (5) `lean` control: the prompt line explains the saving where kg was not used | `docs/report.md`; #52; #67 | F |
| M2 | What was step 0's gate, who fixed it when, and which criterion failed? | Score within 0.03 of `code`, at most +15% context, at most +30% time, set in #67 before the run. Score (−0.02) and context (−40%) passed; time failed (+45%) | #67 body and first comment; `docs/report.md` | F, I |
| M3 | Which facts missing from the graph explain the accuracy losses on scrapy, and which question did each cost? | Imports under `if TYPE_CHECKING:` (job runtime impact), inheritance kept as strings (manager subclasses), settings and classes loaded from strings (download delay) | #67 body; `docs/report.md` §On a large repo | F, I |
| M4 | Which problems of kg's own implementation did the review of the scrapy run find, and which commit fixed each? | Every read re-validated the store (fixed in `7947ba7`, validate once); every command imported matplotlib (lazy loading of `kg.render`, PR #68); `--depth 0` was rejected (`97f3741`) | #67 body; `git log` | I, G |
| M5 | Which requirements and issues trace "keep the graph consistent with the code", and how is a stale graph detected today? | RF-72 and RF-77, #37 then #59. A full rebuild of the parser layer keeps agent knowledge; content digests and `kg status` detect changes, not git commits; `kg status --check` and pre-commit hooks guard it | `docs/requirements.md` RF-72, RF-77; `docs/extract.md`; `docs/store.md`; #37; #59 | F |
| M6 | What triggered the single-language rule for agent-written text, and where is it stated now? | The basic-python-cli graph mixed Spanish and English labels (#11 comment, 2026-10-12); the rule is in the agent guide (`kg guide`, `src/kg/agents/guide.md`) | #11; `src/kg/agents/guide.md` | I + F |
| M7 | Where did the council suggest taking the string-edges idea, and how sure was it that the idea is new? | To existing tools with users rather than inside kg: code-review-graph, codebase-memory-mcp, or libraries such as grimp or import-linter, as a plugin, PR or small library. It was about 50% sure nothing does it yet, after a short search | session 2026-10-20 (`84137a84`) | T |
| M8 | What led from the small-repo results to scrapy and node cards, and who chose each? | After the small repos tied (2026-10-15), the user and Claude agreed a larger repo was needed and the user chose scrapy. The user also proposed more descriptive nodes (provenance, where in the docs a fact comes from, links to files) to save context, which became node cards (`--brief`, #57) | session 2026-10-15 (`3c0f074e`); #52 | T |

## Negative knowledge

| ID | Question | Reference answer | Evidence | Lives in |
|----|----------|------------------|----------|----------|
| N1 | Which ways of giving the agent the graph were tried and did not beat reading the code? | `graph`, `topic`, `hybrid`, `cards` and `companion`. `lean` was the control, not a graph strategy | `docs/report.md` strategies table | F |
| N2 | Did letting the agent read the files a stale graph reports solve the stale-graph problem? | Partly: 0.63 → 0.83, still below the code's 1.00, at three to four times the code's context | `docs/report.md` §A stale graph | F |
| N3 | Why can a user not edit or delete nodes from the interactive HTML? | A self-contained offline HTML cannot write back to the store; editing went to the CLI instead (`kg remove`, `kg edit`, #28) | #10 comment; #28 | I |
| N4 | Why did Claude not merge PR #68 itself? | Claude Code's permission classifier blocked the merge through the API as an unreviewed merge; Claude did not try to get around it, and the user merged it from GitHub | session 2026-10-20 (`84137a84`) | T |

## Supersession

| ID | Question | Reference answer | Evidence | Lives in |
|----|----------|------------------|----------|----------|
| S1 | The first step-0 result said `companion`'s context saving was not kg's. What did the later control change in that conclusion? | The `lean` control confirmed it only where kg was not called (the prompt line explains all the saving there). Where the agent called kg, the graph did halve the context (−56%) at the same score, at +35% time | #67, both comments; `docs/report.md` §What is the graph's | F, I |
| S2 | Does `scr-impact-job-runtime` fail with every strategy? | It was first reported so (#67, first comment). The later `lean` control scored 1.00 on it (104 s); `companion` scored 0.50 | #67 comments; `docs/report.md` | F, I |
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
| C4 | On the evening of 2026-10-15 the session was lost. What plan did the next one resume from, and how was it recovered? | The user pasted Claude's last message by hand. The plan, by impact: (1) let `hybrid` read the files a stale graph reports, (2) the rest of step 2 (document sections, quoted claims), (3) step 3, scrapy with 15–20 questions, (4) #55; tags still to confirm (v0.1.0 retroactive on `8b9d7b2`). Claude recommended 1, then scrapy | sessions 2026-10-15 (`735af7cf`, `4381279d`) | T |
| C5 | On 2026-10-19 work stopped at the session limit. What was in progress, and was the hand-over saved? | The scrapy repetitions of #52, to be followed by the report. The user asked for a `checkpoint.md` for the next session, but the limit hit first: no checkpoint was written. The next session, on 2026-10-20, began with the council instead | session 2026-10-19 (`4578caf8`); no `checkpoint.md` in the repo | T |

---

## Open points

1. **R2-06 is met, just.** 13 of 39 is a third. kg wrote most of its
   decisions into its docs, so most session-only knowledge is about *why*,
   *who* and *what happened to the work*, not about the code.
2. **Shares drift from R2-04** by up to 6 points (multi-hop 21% against 15%,
   direct 15% against 20%), because the sessions mostly add rationale and
   continuation. Before freezing, either add two direct lookups and one
   staleness question, or set R2-04's tolerance at ±5 points.
3. **Transcript review.** Twelve sessions (2026-10-06 to 2026-10-20) were read
   as dialogue only, without tool output. Reference answers paraphrase them in
   English; nothing is quoted raw. One user message held what looks like a
   credential; it was skipped and is not in any file. The current session
   (2026-10-25) was left out, since it is the one writing the questions.
4. **Overlap.** S1 and M1 share evidence. Kept on
   purpose: one asks *what*, the other *why* or *what changed*, which is the
   difference the experiment measures.
5. **C2 is about this experiment.** It is pinned to a later commit than the
   rest and needs its own corpus snapshot.
6. **Grading.** D1–D5, N1, B3 and T1–T3 can be graded on names or keyword
   groups. R1–R7, M1, M7, M8, S1, C4 and C5 need a rubric of key points (R2-07).
7. **Engram and pandas questions** come after these are reviewed, with the
   same categories, from their PRs, issues and generated sessions (R2-02).
