# Requirements — Experiment 2: memory that carries an agent across sessions

| Field | Value |
|-------|-------|
| Document version | 1.0 |
| Date | 2026-10-25 |
| Status | Approved by the client (2026-10-25). Open questions (§11) pending |
| Issue | #71 |
| Branch | `experiment-2/agent-context-memory` |
| Previous experiment | `experiment-1/code-graph-negative-result` ([report](../report.md)) |
| Reference implementation | [Engram](https://github.com/Gentleman-Programming/engram), studied, not a dependency |

> **Note on IDs.** This experiment has its own ID space so it cannot be
> confused with kg's `RF-xx`: `H` = hypothesis, `R2-xx` = functional
> requirement, `N2-xx` = non-functional requirement, `Q2-xx` = open question.

---

## 1. Why a second experiment

Experiment 1 asked whether a graph of **how the code is built** (modules,
imports, tests) helps an agent answer questions about a repository. It did
not: on scrapy, reading the code scored 0.98 and the graph next to search
scored 0.96, 45% slower. Most of the graph's facts could be rediscovered with
one `search`, because the code itself is the source of truth and is always
there to read.

Experiment 2 moves the graph to knowledge the code does **not** hold, and that
an agent otherwise has to rediscover each session:

| | Experiment 1: code graph | Experiment 2: context graph |
|---|---|---|
| Represents | how the software is built | what an agent needs to know to work on it |
| Example | `main.py` → calls `process_data()` → uses `Database` | Decision: keep SQLite · because: MVP simplicity · evidence: `docs/architecture.md` |
| Example question | "Which functions depend on this class?" | "Why did we choose SQLite, and what would have to change to reconsider it?" |
| Source of truth | the code (always readable) | sessions, decisions, experiments (often only in transcripts, PRs or heads) |

The graph is an **index of knowledge**; files, commits and lines are the
**evidence** it points to. The graph never replaces the evidence.

### 1.1 Lessons from experiment 1 that bind this design

1. **The strongest control is "no tool".** In experiment 1 the agent reading
   the code beat every graph strategy. Here, an agent with the repo and its
   git history but no memory store is a mandatory baseline (S0).
2. **Control the prompt.** The `lean` control showed a prompt line, not the
   graph, explained part of a gain. Strategies differ only in retrieval
   (N2-01).
3. **Time counts.** A strategy that ties on score and is 45% slower loses.
4. **The question mix decides the result.** 14 of 16 scrapy questions were
   one-hop lookups, which favour grep. The mix is fixed and published before
   any run (R2-12).
5. **Pre-register the gate.** The pass/fail criteria are written before the
   first run (§7), as the scrapy gate was.

---

## 2. Hypothesis and research question

**H.** Representing explicitly what an agent knows about a project improves
its ability to recover the relevant context across sessions, without
rediscovering it each time.

**Research question.** On which kinds of task, and under which conditions,
does a **relational** memory (a graph) improve the continuity of coding
agents over **textual** search and **semantic** retrieval?

**Sub-hypotheses**, each tied to a question category (§5):

| ID | Claim | Expected winner |
|----|-------|-----------------|
| H1 | Any memory store beats rediscovering from the repo (S0) on questions whose answer is not in the files | every memory strategy |
| H2 | Full-text search is enough for direct lookups | S2 (FTS) ties or wins |
| H3 | Following relations wins on questions that chain several memories (why → evidence → component) | S4 (graph) |
| H4 | Explicit supersession and invalidation edges reduce answers that repeat obsolete knowledge | S4, S5 |
| H5 | Embeddings win when the question is phrased unlike the memory | S3 |
| H6 | Letting the agent drive retrieval pays off only on complex questions, and costs time on simple ones | S7 |

H1 failing ends the experiment: if memory does not beat the repo, the
retrieval architecture does not matter.

---

## 3. Scope

### 3.1 In scope
- A shared memory store and a set of interchangeable **retrieval strategies**
  over it.
- A corpus: a repository plus a controlled set of prior sessions.
- A frozen question set with reference answers and reference evidence.
- A second, smaller **continuation task** evaluation (R2-14).
- A report in the style of experiment 1's, positive or negative.

### 3.2 Out of scope
- Building a product or another Engram. kg becomes a product only for the
  cases where the experiment shows the graph wins.
- Multi-user or networked memory, sync, authentication.
- Memory of code structure (that was experiment 1).
- Fine-tuning or training models.

---

## 4. Memory model

### 4.1 Memory types (nodes)

Start from units of knowledge that survive sessions, not from code symbols.

| Type | Example |
|------|---------|
| `Decision` | SQLite was chosen over PostgreSQL |
| `Component` | parser, API, storage |
| `Task` | Move the parser to a common interface |
| `Experiment` | The graph did not improve the initial benchmark |
| `Constraint` | No heavy dependencies |
| `Issue` | The index goes stale when files are deleted |
| `Evidence` | a file and line range, a section, a commit, a PR or a code fragment |
| `Session` | what was done and what was left pending |

Every memory has: a stable ID, a title, a body, a creation time, the session
that produced it, a status (`active`, `superseded`, `invalidated`, `done`)
and provenance (who wrote it: `curated`, `agent`, `parser`).

### 4.2 Relations (edges)

| Relation | From → to | Meaning |
|----------|-----------|---------|
| `DECIDED_BECAUSE` | Decision → Constraint / Experiment / Evidence | the reason behind a decision |
| `AFFECTS` | Task / Decision / Issue → Component | what part of the project it touches |
| `SUPPORTED_BY` | any claim → Evidence | where it can be checked |
| `SUPERSEDES` | new Decision → old Decision | the old one no longer holds |
| `INVALIDATED_BY` | any memory → Evidence (a change) | a change made it obsolete |
| `BLOCKED_BY` | Task → Task / Issue / Constraint | what stops it |
| `PRODUCED` | Session → any memory | when and where it was learned |

The catalog is closed for the experiment so strategies stay comparable.
Custom types are a kg feature, not an experimental variable.

### 4.3 Evidence and staleness

- `Evidence` anchors to a path, a line range and the commit it was read at.
- When the anchored lines change after that commit, every memory
  `SUPPORTED_BY` it is **suspect** until checked. This reuses kg's staleness
  check (`kg status`).
- A strategy may return suspect or invalidated memories, but must label them.
  Asserting them as current is graded as a staleness error (§6).

---

## 5. Corpus and questions

### 5.1 Corpus

- **R2-01.** The primary corpus is **this repository's own history**: about
  70 PRs, their issues, the docs, the benchmark runs and the decisions of
  experiment 1, including decisions that were later superseded (the v0.2
  re-scope) and approaches that failed (`graph`, `topic`, `cards`).
- **R2-02.** Sessions are reconstructed as a controlled, ordered sequence of
  session records (what was done, decided, found and left pending), each
  pinned to a commit. The same sequence feeds every strategy.
- **R2-03.** A second corpus on a repository the model family did not write
  (candidate: Engram or a sample in `samples/`), so the result is not only
  about our own history (Q2-01).

### 5.2 Question categories

- **R2-04.** At least 30 questions, with a fixed share per category:

| Category | Example | Share |
|----------|---------|-------|
| Direct lookup | "Which model answered the benchmark?" | 20% |
| Rationale | "Why was v0.2 re-scoped to the evidence phase?" | 15% |
| Multi-hop | "Which experiments support the decision to close kg, and what did each measure?" | 15% |
| Negative knowledge | "Which approaches were already shown not to work?" | 10% |
| Supersession | "What is the current plan for v0.3, and what did it replace?" | 10% |
| Staleness | "Which recorded facts depend on code changed since they were written?" | 10% |
| Blocked work | "Which tasks are still blocked, and by what?" | 10% |
| Continuation | "What must I recover before resuming yesterday's work on X?" | 10% |

- **R2-05.** Every question has a reference answer **and** a set of reference
  evidence (paths, commits, PRs), both checked by hand.
- **R2-06.** At least a third of the questions must have answers that are
  **not** stated in any file of the repository at the pinned commit (only in
  sessions, PRs or issues). These are the ones H1 is about.
- **R2-07.** Grading is mechanical where possible (F1 over names, keyword
  groups, as in experiment 1). Open answers use a rubric fixed in advance.

---

## 6. Functional requirements

### 6.1 Store

- **R2-08.** One store holds every memory and relation. All strategies read
  the same store; none has data the others lack.
- **R2-09.** The store keeps text and structure apart: title and body are
  text; relations and status are structured fields. Text strategies index the
  text; the graph strategy uses the structure. A variant where text indexing
  also sees the relation targets as text is run, to tell what the graph adds
  beyond keywords.
- **R2-10.** The store has a deterministic on-disk form, diffable in git,
  in the spirit of `.kg/graph.json`. Indexes (FTS5, vectors) are derived and
  rebuildable from it.
- **R2-11.** Writing memory is a separate step from answering. Two write
  modes: **curated** (reference memories written by hand, to measure
  retrieval alone) and **agent-written** (an agent records memories at the end
  of each session, to measure the realistic pipeline).

### 6.2 Retrieval strategies

- **R2-12.** Each strategy is a function `(question, store, budget) → context`
  behind one interface, so the harness swaps them without other changes:

| ID | Strategy | How it retrieves | May win on |
|----|----------|------------------|------------|
| S0 | No memory | repo + git log + search tools only | anything in the files |
| S1 | Full dump | the whole store in context, while it fits | upper bound on recall |
| S2 | Text top-K | SQLite FTS5 (BM25), K best memories | direct lookups |
| S3 | Semantic top-K | embeddings, K nearest memories | rephrased questions |
| S4 | Graph traversal | find seed memories, follow typed relations to depth d | multi-hop, rationale |
| S5 | Temporal | recency and status first (latest active, then superseded) | continuation, supersession |
| S6 | Hierarchical | project → component → memory → evidence | large stores |
| S7 | Iterative | the agent searches, inspects, finds gaps and queries again | complex questions |
| S8 | Hybrid | text seeds, graph expansion, evidence attached | mixed questions |

- **R2-13.** Priority: S0, S2, S4 and S8 are required. S1, S3 and S7 are
  required if H1 holds. S5 and S6 are optional.

### 6.3 Evaluation

- **R2-14.** **Continuation task.** Besides the questions, at least 5 tasks
  that resume interrupted work ("continue the parser change from session 12").
  Measured: tool calls and context spent before the first useful action, and
  whether the agent repeats work or an approach already shown to fail.
- **R2-15.** Each (question, strategy) pair runs at least 3 times. Results
  report the mean and the spread.
- **R2-16.** The harness reuses `bench/`: subagents, never an API key, the
  same graders and result files, and its "measure your own tool" entry point
  for external systems such as Engram.

### 6.4 Metrics

| Metric | Definition |
|--------|------------|
| Accuracy | graded score per question (0–1) |
| Evidence recall | share of reference evidence the answer cites |
| Evidence precision | share of cited evidence that is in the reference set |
| Staleness errors | answers that assert a superseded or invalidated memory as current |
| Context | characters of retrieved context and of all tool results |
| Tool calls | per answer |
| Wall time | seconds per answer |
| Write cost | tokens and seconds an agent spends recording memory per session |
| Maintenance | memories that needed a manual fix after each session |

---

## 7. Gates (pre-registered)

Set before the first run. Per category, against the best non-graph strategy
(S2 or S3):

- **G0 — memory is worth having.** On the questions of R2-06, the best memory
  strategy beats S0 by at least 0.15 in accuracy. Otherwise stop and report.
- **G1 — the graph earns its place.** S4 or S8 beats the best non-graph
  strategy by at least 0.10 in accuracy, or in evidence recall, on at least
  two of: rationale, multi-hop, supersession, staleness, blocked work.
- **G2 — it does not cost the easy cases.** On direct lookups the graph
  strategy loses no more than 0.03 in accuracy and takes no more than 30%
  more time than S2.
- **G3 — it ages well.** Staleness errors with S4/S8 are at most half those
  of S2.

kg moves forward as a product only on the categories where G1–G3 pass. A
failure is published like experiment 1's.

---

## 8. Non-functional requirements

- **N2-01. One variable at a time.** Same model, same prompt apart from the
  tool or context description, same tool-call and token budget, same store.
  Any prompt line one strategy gets, a control gets too.
- **N2-02. Local and offline.** SQLite (stdlib `sqlite3` with FTS5) and
  NetworkX. Embeddings run locally; their dependency is justified and declared
  in `pyproject.toml` as an optional extra (Q2-03).
- **N2-03. Deterministic.** Same store and question give the same retrieved
  context for S0–S6 and S8. Only S7, which the agent drives, may vary.
- **N2-04. Reproducible.** Corpus, store, questions, references and results
  are committed. Questions and gates are frozen in a commit before the first
  scored run.
- **N2-05. Language.** Code, docs and results in English, as in the rest of
  the repo.
- **N2-06. Privacy.** No secret, `.env` content or private transcript enters
  the corpus without review. Reconstructed sessions are written for the
  corpus, not copied raw.

---

## 9. Plan

| Phase | Output | Exit criterion |
|-------|--------|----------------|
| P0 | corpus, 30+ questions with references, gates frozen | questions reviewed and committed |
| P1 | store, write modes, S0 and S2 | G0 measured |
| P2 | S4 and S8; S1 and S3 if G0 passes | G1–G3 measured |
| P3 | S7, continuation tasks, second corpus | results replicated on corpus 2 |
| P4 | report | published, whatever the result |

G0 failing after P1 ends the experiment early, with a report.

---

## 10. Threats to validity

- **One model family** writes the sessions, the questions, the references and
  the answers. Mitigation: hand-checked references, a second corpus.
- **Self-knowledge.** The answering model may recall this project from
  training or context. Mitigation: questions about details that only the
  sessions hold, and S0 as the floor.
- **Curated memory flatters retrieval.** Mitigation: the agent-written mode.
- **Small samples.** 30 questions and 3 runs make a 0.03 difference a tie.
  Only gate margins count.
- **Graph built for the questions.** Relations are written with the
  memories, before the questions are seen, or by an agent that never sees
  them.

---

## 11. Open questions

| ID | Question |
|----|----------|
| Q2-01 | Which repository is the second corpus? |
| Q2-02 | Do we reconstruct sessions from PRs and issues only, or also from reviewed Claude Code transcripts? |
| Q2-03 | Which local embedding model (size, dependency weight) for S3? |
| Q2-04 | Does the store reuse kg's `.kg/` format and schema, or start a new one? |
| Q2-05 | Is Engram run as an external system through the harness, or only studied? |
