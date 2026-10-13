# Functional Requirements — `kg` (working name)

| Field | Value |
|-------|-------|
| Document version | 1.2 (draft) |
| Date | 2026-10-13 |
| Status | 1.1 approved by the client (2026-10-07). **1.2 pending approval** (#43): re-scopes v0.2 and adds v0.3, see the [change log](#11-change-log) |
| Source | Requirements interview, blocks 1–4 (summary: [discovery.md](discovery.md)) |

> **Note on IDs.** Requirement and decision IDs keep their original Spanish
> prefixes so that existing issues, PRs and commits stay traceable:
> `RF` = functional requirement, `RNF` = non-functional requirement,
> `CU` = use case, `S` = assumption, `PA` = resolved open question.

---

## 1. Introduction

### 1.1 Purpose
`kg` is a command-line tool that turns knowledge about a software project (code, dependencies, documentation, tests, decisions…) into a **knowledge graph** that can be queried, visualized and exported.

It is meant for both **people** and **AI agents**. The goal is for developers and stakeholders to understand what a project is about and how it is built, and for an agent to reason about it with reliable data.

### 1.2 Scope
- The main domain is **software repositories**. The model is extensible to any domain.
- Input comes from two paths:
  1. **Deterministic extraction**: parsing code and configuration files. Python first.
  2. **Extraction assisted by an external agent**: the agent reads the repo or a text and produces JSON that conforms to the schema.
- The output is a graph stored inside the repo itself, with visualization (PNG/SVG, interactive HTML) and export to other formats.

### 1.3 Context
An exploratory project intended as a publishable side project (MIT license). First tests will run on small Python repos.

### 1.4 Glossary
| Term | Definition |
|------|------------|
| **Entity / node** | An element of the project: file, function, dependency, document… |
| **Relation / edge** | A directed, typed link between two entities (`imports`, `tests`…) |
| **Standard catalog** | Minimum set of entity and relation types defined by the tool, which agents should consider |
| **Custom type** | An entity or relation type not in the catalog, defined by the user or the agent |
| **Provenance** | Metadata about where a piece of data comes from: source, file/lines, method (parser/LLM) and confidence |
| **Store** | The `.kg/` folder inside the analyzed repo that holds the graph |
| **External agent** | An AI assistant (Claude Code or another) that uses `kg` as a tool |

---

## 2. Users and use cases

### 2.1 Profiles
| Profile | Need | How they interact |
|---------|------|-------------------|
| **Developer** | Understand the structure, the impact of a change and test coverage | CLI, interactive HTML, questions to an agent |
| **Non-technical stakeholder** | See at a glance what the project is about | Generated image or HTML |
| **AI agent** | Build the graph and query it to answer questions | CLI with `--json`, MCP server |

### 2.2 Main use cases
| ID | Use case | Actor | Summary flow |
|----|----------|-------|--------------|
| CU-01 | **Map a repo** | Developer / agent | `kg init` → `kg extract .` → the agent adds docs and decisions with `kg add` → `kg render --html` |
| CU-02 | **Which tests are missing?** | Agent | Finds code entities with no incoming `tests` relation and proposes tests |
| CU-03 | **Is the documentation in line with the code?** | Agent | Compares what `Document` nodes say (`documents` relations, LLM provenance) with what the parser extracted. Flags references to non-existent elements and undocumented public code |
| CU-04 | **How do I extend the project with these N requirements?** | Agent | Reads the graph's modules, responsibilities, dependencies and decisions, and reasons about where and how the requirements fit |
| CU-05 | **Impact of a change** | Developer / agent | `kg impact <node>` lists everything that transitively depends on the node |
| CU-06 | **Share the map** | Developer | `kg render` or `kg export --format mermaid` to include it in a README or a presentation |

> Open-ended questions (CU-02, CU-03 and CU-04) are answered by an **external agent** reasoning over the graph. `kg` does not embed any LLM. What it guarantees is that the graph holds the necessary data and that structured queries work.

---

## 3. Data model

### 3.1 Principles
- **Hybrid schema.** A mandatory standard catalog serves as a guide, and custom entity and relation types are allowed.
- **No redundancy.** Each real entity appears in a single node. To achieve this, each entity has a **stable ID** derived from its nature; for example `file:src/app/main.py` or `function:app.main.run`.
- **Traceability.** Every node and every relation records its provenance.
- **Directed, with attributes.** The graph is a directed multigraph (`nx.MultiDiGraph`) with free-form attributes on nodes and edges.

### 3.2 Standard entity catalog
| Type | Description | Typical origin |
|------|-------------|----------------|
| `Repo` | Project root | Parser |
| `Package` / `Module` | Code package or module | Parser |
| `File` | File in the repo | Parser |
| `Class` | Class | Parser |
| `Function` | Function or method | Parser |
| `Dependency` | External dependency (pyproject, requirements) | Parser |
| `Test` | Test file or function | Parser |
| `Document` | Document (README, docs/, relevant docstrings) | Parser + LLM |
| `Config` | Configuration (pyproject, .env.example, CI) | Parser |
| `Service` / `Endpoint` | Exposed service or endpoint | Parser + LLM |
| `Person` | Contributor or author | git / LLM |
| `Issue` | Issue or task | LLM / future |
| `Decision` | Design decision (ADR or explained in the docs) | LLM |
| `Concept` | Domain concept | LLM |

### 3.3 Standard relation catalog
`contains`, `imports`, `depends_on`, `defines`, `calls`, `documents`, `tests`, `configures`, `authored_by`, `implements`, `justifies` (Decision → entity).

### 3.4 Provenance (per node and per relation)
| Field | Example |
|-------|---------|
| `source` | `src/app/main.py` |
| `lines` | `[12, 40]` |
| `method` | `parser` \| `llm` \| `manual` |
| `extractor` | `python-ast@0.1`, `claude-code` |
| `confidence` | `1.0` (parser), `0.0–1.0` (LLM) |
| `timestamp` | ISO-8601 |

---

## 4. Functional requirements

Priorities:
- **MVP**: v0.1.
- **v0.2**: evidence phase. A short, bounded iteration to measure whether the graph helps (see section 7 and [roadmap.md](roadmap.md)).
- **v0.3**: iteration after v0.2. Its scope is reviewed with the v0.2 results.
- **Future**: improvement with no date.

### 4.1 Schema and validation
| ID | Requirement | Priority |
|----|-------------|----------|
| RF-01 | There is an official, published **JSON Schema** for the input format (`nodes`, `edges`, attributes and provenance) that an agent can read | MVP |
| RF-02 | The schema includes the **standard catalog** and accepts **custom types**; a non-standard type produces a *warning*, not an error | MVP |
| RF-03 | `kg validate <json>` validates without modifying the store | MVP |
| RF-04 | Validation errors are **clear and actionable**: JSON path of the failure, received value, expected value and a suggestion. Available as text and as JSON (`--json`) so an agent can self-correct | MVP |
| RF-05 | Validation detects broken references (an edge pointing to a non-existent node) and duplicate IDs in the same file | MVP |

### 4.2 Extraction
| ID | Requirement | Priority |
|----|-------------|----------|
| RF-10 | `kg extract <path>` deterministically analyzes a Python repo and produces `Repo`, `Package/Module`, `File`, `Class`, `Function` and `Test` nodes, with `contains`, `defines` and `imports` relations | MVP |
| RF-11 | Extracts `Dependency` and `Config` from `pyproject.toml` and `requirements*.txt` | MVP |
| RF-12 | Detects tests (pytest convention) and creates `tests` relations to the code they import or call | MVP |
| RF-13 | Extracts `calls` relations between functions (static analysis, no completeness guarantee) | v0.3 (moves to v0.2 if the benchmark shows `kg impact` needs it) |
| RF-14 | Extracts `Person` and `authored_by` from git history | Future |
| RF-15 | Extractors for JS/TS and other ecosystems | Future |

### 4.3 Agent integration
| ID | Requirement | Priority |
|----|-------------|----------|
| RF-20 | **Guidelines/skill** for agents are provided: how to walk a repo or a text, which entities and relations to look for at minimum (standard catalog), how to assign stable IDs, how to fill in provenance and confidence, and how to validate and iterate with `kg validate` | MVP |
| RF-21 | `kg add <json>` adds the entities and relations of a valid JSON to the store | MVP |
| RF-22 | Every command accepts `--json` to produce machine-readable output | MVP |
| RF-23 | **MCP server** that exposes the main operations (validate, add, query, impact, render, export) as tools | v0.3 |
| RF-24 | `kg` does **not** call any LLM nor require API keys | MVP (constraint) |

### 4.4 Merging and deduplication
| ID | Requirement | Priority |
|----|-------------|----------|
| RF-30 | **Basic merge by ID**: adding an entity with an existing ID combines its attributes instead of duplicating it | MVP (required by RF-21) |
| RF-31 | **Multiple provenance**: an entity or relation confirmed by several sources keeps all of its provenances | v0.3 |
| RF-32 | **Advanced deduplication**: detects equivalent entities with different IDs (e.g. `pandas` in the docs and `Dependency:pandas` in the code) through normalization or aliases, and merges them or proposes merging them | v0.3 |
| RF-33 | Configurable conflict policy when two sources disagree on an attribute (by default the parser wins over the LLM) | v0.3 |

### 4.5 Queries and analysis
| ID | Requirement | Priority |
|----|-------------|----------|
| RF-40 | `kg query` can: get a node and its attributes, incoming and outgoing neighbors, filter by type or attribute, and find paths between two nodes | v0.2 |
| RF-41 | `kg impact <node>` lists transitive dependents (everything that directly or indirectly depends on the node), with their depth | v0.2 |
| RF-42 | Predefined queries supporting the use cases: untested code (CU-02) and undocumented code or documents referencing non-existent entities (CU-03) | v0.2 |
| RF-43 | **Coverage limits**: `kg query` and `kg impact` state the limits of their answer when they apply: files skipped by the last extraction, relation types the parser does not produce (e.g. dynamic calls) and a stale graph (RF-77). An empty result reads "no relation found in the graph", never "no dependency". Possible effects are reported as possible, with the relation path and provenance | v0.2 (added 2026-10-13) |
| RF-44 | **Topic views**: named sets of entity and relation types (documentation, tests, development, decisions) that `query`, `impact` and `render` can be restricted to. The v0.2 benchmark uses the type filters of RF-40; named views are only added if the benchmark shows that focused graphs help | v0.3 (added 2026-10-13) |

### 4.6 Visualization
| ID | Requirement | Priority |
|----|-------------|----------|
| RF-50 | `kg render --png` / `--svg` produces a static image of the graph | MVP |
| RF-51 | `kg render --html` produces a self-contained interactive HTML (works offline) | MVP |
| RF-52 | The HTML includes colors per entity type, style or label per relation type and a **legend** | MVP |
| RF-53 | The HTML includes **filters** by entity type and relation type | MVP |
| RF-54 | The HTML shows **node details on click**: attributes and provenance | MVP |
| RF-55 | The HTML includes a **simple search** by name or ID | MVP |
| RF-56 | Audience-specific views (high level for stakeholders, detail for developers) and grouping/collapsing modules | Future |

### 4.7 Export
| ID | Requirement | Priority |
|----|-------------|----------|
| RF-60 | `kg export --format mermaid` | v0.3 |
| RF-61 | `kg export --format dot` (Graphviz) | v0.3 |
| RF-62 | Export to Neo4j/Cypher | Future |

### 4.8 Storage, versioning and updates
| ID | Requirement | Priority |
|----|-------------|----------|
| RF-70 | `kg init` creates the `.kg/` store inside the analyzed repo | MVP |
| RF-71 | The store uses **readable JSON with deterministic ordering**, so git diffs are clean and reviewable in PRs. Versioning is delegated to the repo's git | MVP |
| RF-72 | **Consistent update**: a new `kg extract` leaves the graph faithful to the code. Derived elements (`method: parser`) that the extraction no longer produces are removed (deleted, renamed or moved code); `llm`/`manual` knowledge is kept, and agent edges whose endpoints disappeared are reported, not deleted. A failed extraction leaves the store unchanged. Reworded 2026-10-13: a full rebuild of the parser layer is acceptable; processing only changed files is RF-78 | v0.2 |
| RF-73 | Optional **post-commit hook** that triggers the update (RF-72, or RF-78 once available) | v0.3 |
| RF-74 | `kg log`, `kg diff <v1> <v2>` (nodes and relations added, removed or modified) and `kg checkout <version>`, based on the store's git history | v0.3 |
| RF-75 | `kg remove` deletes nodes (with their edges) and individual edges from the store, all or nothing, with `--dry-run` | MVP (added 2026-10-12, #28) |
| RF-76 | `kg edit` modifies a node (ID, type, label, description, attributes); renaming rewrites its edges; the result is validated before saving | MVP (added 2026-10-12, #28) |
| RF-77 | **Stale graph detection**: the store records what the last extraction saw (git commit, dirty working tree, time). `kg validate --kg-dir`, `kg query` and `kg impact` warn when the repo has changed since, naming the commit or the changed files. Without git (S-01) only the time is recorded | v0.2 (added 2026-10-13) |
| RF-78 | **Incremental extraction**: `kg extract` only reprocesses the files git reports as changed, with the same result as a full update (RF-72). An optimization, needed only if full updates become slow (RNF-06) | v0.3 (added 2026-10-13; split from RF-72) |

---

## 5. Command-line interface

```
kg init                         Create the .kg/ store in the repo
kg extract <path>               Deterministic extraction (Python)
kg add <file.json>              Add and merge entities and relations
kg validate <file.json>         Validate against the schema without applying changes
kg remove <id>… | --edge s t d  Remove nodes or edges from the store
kg edit <id> [--label …]        Modify a node of the store
kg query ...                    Nodes, neighbors, paths and filters       (v0.2)
kg impact <node>                Transitive dependents                     (v0.2)
kg render --png|--svg|--html    Visualization
kg export --format mermaid|dot  Export                                    (v0.3)
kg log | diff | checkout        History and version comparison            (v0.3)

Global options: --json (machine-readable output), --kg-dir <path>
```

Exit codes: `0` OK, `1` validation error, `2` usage error, `>2` internal error.

---

## 6. Non-functional requirements

| ID | Requirement |
|----|-------------|
| RNF-01 | **Language**: Python ≥ 3.12, built on NetworkX |
| RNF-02 | **Platform**: Linux. macOS and Windows are not officially supported |
| RNF-03 | **Distribution**: local install. The README documents both the user install (`pip install git+https://github.com/Cristian1A/kg.git`, or `pipx`) and the development one (`pip install -e ".[dev]"`), v0.2. Must be dockerizable (Dockerfile in v0.3). PyPI is left for the future |
| RNF-04 | **Privacy**: works 100 % offline; the tool does not send code or data to any service |
| RNF-05 | **License**: MIT |
| RNF-06 | **Performance**: no fixed target in the MVP; measured in [mvp-validation.md](mvp-validation.md). Target for v0.2 (stretch): CLI start-up under 0.5 s, and `extract` and `render` under 5 s for a repo of 100 files |
| RNF-07 | **Quality**: pytest tests, including specific tests for validation messages (RF-04). Linting with ruff. From v0.2, **CI** runs the tests and the linter on every push and pull request, and installs kg in a clean environment for a smoke test |
| RNF-08 | **Determinism**: the same input produces the same store, byte for byte, and the same visualization layout (fixed seed) |
| RNF-09 | **Scalability**: designed for small repos in the MVP. No decision should prevent scaling to medium or large repos |
| RNF-10 | **Measured value** (added 2026-10-13): whether the graph improves an agent's answers is measured with a reproducible benchmark (questions over code vs. over the graph: accuracy, traceability, tokens, time). The benchmark calls an LLM, so it lives **outside the `kg` package** with its own optional dependencies; `kg` still calls no LLM (RF-24). v0.2 |

---

## 7. Release plan

| Version | Content |
|---------|---------|
| **v0.1 (MVP)** | Schema and validation (RF-01–05), Python extractor (RF-10–12), agent guidelines and `add` (RF-20–22, 24), basic merge by ID (RF-30), PNG/SVG/HTML render (RF-50–55), `.kg/` store (RF-70–71), removing and editing (RF-75–76) |
| **v0.2 — evidence** | Find out whether kg solves a problem, in a bounded phase (about two weeks of work). Queries and impact (RF-40–43), a graph consistent with the code and stale-graph detection (RF-72, RF-77), CI and user install (RNF-03, RNF-07), the benchmark (RNF-10) and a reproducible demo. Stretch: start-up time (RNF-06) |
| **v0.3** | Scope reviewed with the v0.2 results. Candidates: MCP server (RF-23), `calls` (RF-13), topic views (RF-44), multiple provenance and advanced deduplication (RF-31–33), Mermaid/DOT export (RF-60–61), hook, history and incremental extraction (RF-73, RF-74, RF-78), Dockerfile |
| **Future** | Audience-specific views, Neo4j, git blame/authors, other languages, PyPI |

The action plan (order, dependencies, issues and exit criteria) is in [roadmap.md](roadmap.md).

---

## 8. Acceptance criteria

### 8.1 MVP

Met on 2026-10-12; see [mvp-validation.md](mvp-validation.md).

The MVP is considered a **success** if:

1. The full CU-01 flow (`init → extract → add → render`) runs without errors on **at least 3 different small Python repos**, e.g. this one and two public repos with fewer than 100 files.
2. In each repo, an external agent with access to the graph only answers the three reference questions correctly and verifiably:
   - "Which tests are missing?"
   - "Is the documentation in line with the code?"
   - "How can this project be extended if I give it these 2 new requirements?"
3. A deliberately invalid JSON produces errors that let an agent fix it in **one iteration**.
4. The HTML lets you find a node with the search box, filter it by type and see its provenance.
5. Running `kg extract` twice in a row does not create duplicate nodes (RF-30).

### 8.2 v0.2

v0.2 is **done** when:

1. The benchmark (RNF-10, #39) has been run with 15–30 questions on several repos, and its report is published. **Any outcome counts**: if the graph does not improve the answers, the report says where and why, and v0.3 is redesigned with that evidence. The report includes the per-topic and two-commit variants, and states its sample-size limits.
2. `kg query` and `kg impact` give the structured part of the three reference questions (section 8.1) on the example repos, with the relations and provenance that justify each result and their coverage limits (RF-40–43).
3. After modifying, deleting, renaming or moving code, a new `kg extract` leaves no stale derived elements and keeps agent knowledge (RF-72). Querying a graph that is older than the repo produces a warning (RF-77).
4. CI is green on `main`, and a new user can install kg and run the demo (#40) from the published instructions alone (RNF-03, RNF-07).
5. The phase stays within its time box (about two weeks of work). If it runs over, the stretch items and the extra benchmark variants are cut, not the time box extended.

---

## 9. Out of scope

Confirmed by the client on 2026-10-07:
- An LLM embedded in the tool (an `ask` command, API calls or API key management).
- A web server or graph hosting; real-time multi-user collaboration.
- Official macOS and Windows support.
- Real-time *watch* mode (updates are triggered manually or by a hook).
- Deep semantic code analysis: types, data flow and dynamic runtime analysis.
- A graph database as primary storage. Neo4j only as a future export format.

> **Pending (#41).** Publishing a hosted app (e.g. Streamlit) to present the
> results would be a project-site decision, not a feature of `kg`. It needs an
> explicit exception to "a web server or graph hosting" before it is accepted.

---

## 10. Assumptions and decisions

### Assumptions (accepted)
- S-01: The analyzed repo uses git. Without git, `kg` works, but without incremental updates or versioning.
- S-02: LLM extraction is always done by an external agent, which is responsible for its own cost and privacy.
- S-03: The MVP's basic merge (RF-30) is included even though full merging (C) was scheduled for later, because without it `add` and `extract` would create duplicates.

### Decisions (resolved open questions)
| ID | Decision |
|----|----------|
| PA-01 | The project and CLI name is **`kg`** for now; it will be reviewed before publishing to PyPI |
| PA-02 | Entities with no physical origin use `<type>:<slug>` IDs (e.g. `concept:knowledge-graph`, `decision:use-networkx`) |
| PA-03 | The interactive HTML is built on **vis.js** (vis-network, the engine pyvis wraps), bundled to work offline. Updated 2026-10-12 (#10): kg embeds vis-network 9.1.2 with its own page instead of depending on pyvis, whose template lacks filters, search and the details panel, and which pulls in ipython |
| PA-04 | Out-of-scope list confirmed (section 9) |
| PA-05 | **Proposed (1.2, pending approval).** v0.2 is a short evidence phase (benchmark, queries, a reliable graph, a demo). The remaining v0.2 items move to v0.3, whose scope is reviewed with the benchmark results. Origin: external feedback, 2026-10-13 |

---

## 11. Change log

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-10-06 | First version, in Spanish. Approved on 2026-10-07 |
| 1.1 | 2026-10-12 | English translation. RF-75 and RF-76 added (#28); PA-03 updated (#10); link to discovery.md (#33) |
| 1.2 (draft) | 2026-10-13 | v0.2 re-scoped to the evidence phase (#43). New: RF-43, RF-44, RF-77, RF-78, RNF-10, section 8.2, PA-05. Reworded: RF-72 (consistent update; incremental extraction split into RF-78), RNF-03 (user install), RNF-06 (v0.2 targets), RNF-07 (CI). Moved to v0.3: RF-13, RF-23, RF-31–33, RF-60–61, RF-73–74, Dockerfile |
