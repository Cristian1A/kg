# Engram: what it does, and what experiment 2 takes from it

Phase P0 of [experiment 2](requirements.md) (#71). A study of
[Engram](https://github.com/Gentleman-Programming/engram) at `7192931`
(2026-10-25): Go, MIT, 1 225 commits since its first release on 2026-02-16.
It covers the docs (`README.md`, `DOCS.md`, `docs/ARCHITECTURE.md`,
`docs/COMPARISON.md`, `docs/intended-usage.md`), the memory protocol skill
(`skills/memory-protocol/SKILL.md`) and the store schema in
`internal/store/store.go`. Claims about the code were checked with `grep`; the
rest is what the docs say.

## In one paragraph

Engram is persistent memory for coding agents, exposed as an MCP server (27
tools), an HTTP API, a CLI and a TUI. **The agent decides what to remember**:
it calls `mem_save` with a structured summary instead of Engram capturing
every tool call. Memories ("observations") go into one SQLite file with an
FTS5 index. At the end of a session the agent writes a summary. In the next
session it recalls with `mem_context`, then `mem_search`, then
`mem_get_observation`. Its own comparison sets it against claude-mem, which
captures everything and compresses it with extra model calls into a vector
database.

## Data model

| Table | Holds |
|-------|-------|
| `sessions` | `id`, `project`, `directory`, `started_at`, `ended_at`, `summary` |
| `observations` | `type`, `title`, `content`, `project`, `scope`, `topic_key`, `revision_count`, `duplicate_count`, `pinned`, `review_after`, `expires_at`, `created_at`, `updated_at`, `deleted_at`, and three `embedding*` columns |
| `observations_fts` | FTS5 over `title`, `content`, `tool_name`, `type`, `project`, `topic_key` |
| `user_prompts` + `prompts_fts` | the user's prompts, searchable apart |
| `memory_relations` | a verdict between two observations: `relation`, `judgment_status`, reason, evidence, confidence |

The rest of the schema (about ten more tables) is sync to other machines and
to a cloud service, which experiment 2 leaves out.

- **Types:** `decision`, `architecture`, `bugfix`, `pattern`, `config`,
  `discovery`, `learning`, `preference`, plus `session_summary`.
- **Content format:** What / Why / Where / Learned.
- **Session summary:** Goal / Instructions / Discoveries / Accomplished /
  Next Steps / Relevant Files.
- **Scope:** `project` (default), `personal`, `global`.

## Writing

- **Selective.** The protocol asks for "verified knowledge that is durable and
  costly to reconstruct": decisions with rationale, non-obvious root causes,
  real constraints and pending work. Routine progress, speculation and raw
  dumps stay out.
- **Search before writing.** The agent looks for an existing memory on the
  same topic and updates it by ID rather than saving a duplicate.
- **`topic_key` makes a save an upsert.** The same `project + scope +
  topic_key` (`decision/database-choice`) updates the existing row in place
  and increments `revision_count`. An evolving decision stays in **one row
  holding the latest version**. The protocol asks the agent to "record
  superseded facts as history" inside the content.
- **Exact dedupe** over a rolling window (hash of project, scope, type, title)
  bumps `duplicate_count` instead of inserting.
- **Soft delete** by default.

## Reading

Progressive disclosure, to keep the context small:

1. `mem_search "auth middleware"`: compact results with IDs, previews capped
   at 300 characters.
2. `mem_timeline observation_id=42`: what happened before and after it in that
   session.
3. `mem_get_observation id=42`: the full content.

`mem_context` returns recent sessions, prompts, pinned and recent observations
for a project, with optional caps and a byte budget. The Claude Code plugin
can inject it at session start; bare MCP does not.

## Relations between memories

Relations exist, but only for **conflicts**. When `mem_save` finds FTS5
candidates that may contradict the new memory, it returns them with
`judgment_required: true`. The agent then calls `mem_judge` with one of
`related`, `compatible`, `scoped`, `conflicts_with`, `supersedes` or
`not_conflict`, a reason, optional evidence and a confidence. Search results
then show annotation lines such as `supersedes: #12 (title)` and
`superseded_by: #40 (title)`.

So Engram has a graph, but a sparse one: edges between observations only,
created when a write looks like a conflict. Retrieval shows them as
annotations on results; nothing in the docs follows them further.

## Staleness

Time-based, not evidence-based. Each type gets a `review_after`: 3 months for
`config` and `preference`, 6 months for `discovery`, `pattern` and
`decision`, 12 months for `architecture`, `bugfix` and `policy`. The docs say
these are "review prompts, not empirically calibrated expiration deadlines".
Overdue memories stay searchable with `state="needs_review"`, and
`mem_review` lists them or marks them reviewed.

## What it does not have

- **No semantic search.** The `embedding`, `embedding_model` and
  `embedding_created_at` columns are declared, but no Go code outside the
  schema uses them. Search is FTS5 only.
- **No evidence anchors.** "Where" and "Relevant Files" are free text. Nothing
  ties a memory to a file, a line range or a commit, so a code change cannot
  flag the memories that depend on it.
- **No typed edges to tasks, components or evidence.** Only
  observation-to-observation verdicts.
- **No traversal.** Retrieval is search plus a session timeline.

## Mapping to experiment 2's model

| Experiment 2 (§4) | Engram |
|-------------------|--------|
| `Decision`, `Constraint`, `Experiment`, `Issue` | observation with `type` `decision`, `architecture`, `bugfix`, `discovery`… |
| `Component` | none; at most a `topic_key` family |
| `Task`, `BLOCKED_BY` | none; pending work lives in a summary's "Next Steps" |
| `Evidence`, `SUPPORTED_BY` | none; free text in "Where" or "Relevant Files" |
| `Session`, `PRODUCED` | `sessions` and `observations.session_id` |
| `SUPERSEDES` | `memory_relations.relation = supersedes`, or a `topic_key` upsert that overwrites |
| `INVALIDATED_BY` | none; `review_after` is time, not change |
| `DECIDED_BECAUSE` | inside the content ("Why") |
| `AFFECTS` | none |

## What experiment 2 takes from it

1. **S2 copies Engram's retrieval.** FTS5 (BM25) over title, content, type and
   topic key, compact previews first and full content on request. Then S2 is
   a fair stand-in for a real, used system, not a weak baseline.
2. **Memory content uses its formats.** What / Why / Where / Learned for
   memories, and Goal / Discoveries / Accomplished / Next Steps / Relevant
   Files for session records (R2-02). The text is the same for every strategy;
   only the structure on top differs (R2-09).
3. **The agent-written mode (R2-11) uses its protocol.** "Durable and costly to
   reconstruct", search before writing, and update instead of duplicating.
   This gives the realistic pipeline a tested write policy instead of one we
   invent.
4. **H4 has a sharp version.** A `topic_key` upsert keeps one row with the
   latest version; our `SUPERSEDES` keeps both and links them. The
   supersession questions test whether keeping the old decision as a node,
   rather than as prose inside the new one, helps or only adds noise.
5. **H3 targets what Engram lacks.** Tasks, components, evidence anchors and
   invalidation by code change are the parts of §4 Engram does not model. If
   the graph wins, it should be on the rationale, blocked-work, staleness and
   multi-hop questions. If it does not win there, it wins nowhere.
6. **S5 has a model.** `mem_context` (recent sessions, pinned and recent
   memories, a byte budget) is the temporal strategy.

## Measuring Engram itself (P3)

Through `bench/`'s "measure your own tool" entry point, as an external
system:

- **Load:** `POST /sessions` and `POST /observations` with the corpus's
  sessions and memories, in order. `topic_key` is set where our corpus has a
  `SUPERSEDES` chain, so Engram uses its own mechanism for it.
- **Answer:** the agent gets Engram's MCP tools (`mem_context`, `mem_search`,
  `mem_timeline`, `mem_get_observation`) in place of ours, with the same
  budget and the same prompt.
- **Needs:** a Go toolchain to build it. There is none on this machine yet.
  The alternative is a release binary.
- **Caveat:** relations are created by `mem_judge` during writes, so loading
  curated memories gives Engram no relations unless the loader judges the
  candidates `mem_save` returns. The loader records the supersessions the
  corpus already knows and nothing more.
