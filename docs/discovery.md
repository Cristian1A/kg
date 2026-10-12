# Requirements discovery

Summary of the interview with the client (October 2026) that led to
[requirements.md](requirements.md). It records **why** the requirements are
what they are; the approved requirements themselves live in that document.
Translated from Spanish and condensed.

## 1. Vision and context

| Topic | Answer |
|-------|--------|
| Problem | A CLI that both people and AI agents can use to build graphs from several sources of knowledge: turn JSON describing entities and relations into knowledge graphs that can be rendered and exported. |
| Example use case | Give a repo to an agent and ask it for a graph of what it knows about it: documentation, dependencies and so on, visualized and exportable. |
| Users | The client, experimentally at first. The work can arrive half done (JSON ready to render) or as plain text that an agent turns into entities and relations. Images and HTML make the result understandable to experts and non-experts alike. |
| What the graph represents | Anything, but the focus is software projects: how a repo is organized (docs, files, dependencies…), so that developers and stakeholders understand what it is about. |
| Moment of success | Asking complex questions about how a project is built: which technology it uses, what a change would imply given the current design. |
| Nature | Exploratory for now; possibly a portfolio side project with larger ambitions. |

## 2. Data and graph model

| Topic | Decision |
|-------|----------|
| Input format | Both a guideline and freedom: a **standard catalog** of entities and relations as a recommended minimum, and **custom types** allowed for what it does not cover. |
| Entities | Repo, package/module, file, class/function, external dependency, document, person, configuration, service/endpoint, concept: as much as possible, down to classes and functions. |
| Relations | `contains`, `imports`, `depends_on`, `defines`, `calls`, `documents`, `tests`, `configures`, `authored_by` as the minimum an agent must consider; free types allowed beyond them. |
| Extraction | Both: **deterministic** (parsing code and manifests) **and by an LLM** (an agent reading files). |
| Several sources | Merge the same entity into **one node**: no redundancy, or graphs grow endlessly. Keep the **provenance** of each fact (file and line, parser or LLM, confidence) to audit it and keep agents from inventing. |
| Repo size | Small repos (< 100 files) for the MVP; expand if it works. |
| Evolution | **Incremental updates**; the graph is versioned like code, so any version can be rebuilt and compared. |
| First ecosystem | Python (`ast`, `pyproject.toml`, requirements files); JS/TS later. |

## 3. Features

| Topic | Decision |
|-------|----------|
| Who answers questions | (a) The CLI, with structured queries (neighbors, paths, "what depends on X"), and (b) an **external agent** that reads the graph and reasons in natural language, (b) being the convenient one. No `ask` command calling an LLM from the CLI. |
| Reference questions | *Which tests are missing?* · *Is the documentation in line with the code?* · *How can this project be extended given these two new requirements?* |
| Impact analysis | List the transitive dependents of a node. |
| Visualization | Both a static image (PNG/SVG) and an interactive HTML with colors per entity type and relation, a legend, filters, details on click and a simple search. Audience-specific views are a possible future improvement. |
| Export | Graphviz and Mermaid; Neo4j/Cypher in the future. |
| Validation | Essential: clear, understandable error messages, tested. |
| Agent integration | Machine-readable output (`--json`) on every command; an MCP server would be welcome. |

## 4. Operation and priorities

| Topic | Decision |
|-------|----------|
| Commands | `kg init`, `extract`, `add`, `validate`, `query`, `impact`, `render`, `export`, `log`/`diff`/`checkout`, as proposed. |
| Storage | A `.kg/` folder inside the analyzed repo, readable JSON, versioned with the repo's own git. |
| Incremental trigger | A post-commit hook. |
| LLM extraction | Done by the **external agent**; `kg` provides the schema, the guidelines and validation, and needs no API keys. |
| Distribution | Local only for now; a Docker image would be welcome. |
| License · OS · privacy | MIT · Linux · works 100 % offline. |
| Performance | "Under 10 s for a small repo" is a reference, not a commitment: measure first, then optimize. |
| MVP scope | Schema, standard catalog and validation; Python extractor; render PNG/SVG and HTML; agent guidelines. |
| MVP success | The client's criterion, extended: run on **several repos** and check that an agent answers the three reference questions with the graph. |
| Name and scope | `kg` (for *knowledge graph*) is fine for now. Out of scope was left open in the interview and confirmed later (section 9 of the requirements). |
