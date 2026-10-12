# MVP validation (v0.1)

Validation of the MVP acceptance criteria (section 8 of
[requirements.md](requirements.md)) on three public, MIT-licensed projects of
increasing difficulty, plus `kg` itself. Issue #12. Run on 2026-10-12.

## Summary

| # | Criterion | Result |
|---|-----------|--------|
| 1 | `init → extract → add → render` runs without errors on ≥ 3 small Python repos | ✅ 3 repos + `kg`; no file skipped, re-running `extract` and `add` changes nothing |
| 2 | An agent with only the graph answers the three reference questions, verifiably | ✅ answers below, each backed by node IDs |
| 3 | A deliberately invalid JSON is fixed in one iteration | ✅ 4 errors and 2 warnings, all fixed from the messages alone |
| 4 | HTML: find a node with search, filter by type, see its provenance | ✅ checked in headless Chrome (deep link, filters, details panel); covered by `tests/test_html.py` |
| 5 | Running `kg extract` twice creates no duplicates | ✅ second run: `changed: false` on all four repos |

The runs found two bugs and one gap in `kg`, fixed in the same PR (see
[Findings](#findings)).

## Projects

| Level | Project | Topic | Files (`.py`) | License | Commit |
|-------|---------|-------|---------------|---------|--------|
| Easy | [alfredodeza/basic-python-cli](https://github.com/alfredodeza/basic-python-cli) | CLI and basic Python | 5 (1) | MIT | `d0379bb` |
| Intermediate | [bramvdklinkenberg/my_first_data_project](https://github.com/bramvdklinkenberg/my_first_data_project) | Data engineering: ETL with Bash, Python, SQL and GitHub Actions | 22 (9) | MIT | `3d57177` |
| Complex | [wesleey/python-clean-architecture](https://github.com/wesleey/python-clean-architecture) | Clean Architecture backend: Flask, SQLAlchemy, PostgreSQL | 104 (91) | MIT | `6f58de5` |
| Dogfooding | `kg` (this repo) | — | — | MIT | this PR |

`python-clean-architecture` has 104 files, slightly above the "fewer than 100"
of criterion 1; it is kept as the complex case on purpose. Credits and license
texts: [examples/README.md](examples/README.md). The resulting graphs are
published in [`docs/examples/`](examples/).

## Flow and timings (RNF-06)

Median of three runs; Linux x86_64, 16 cores, Python 3.12.3, `kg` 0.1.0.dev0.
Stores in `samples/runs/<repo>/.kg` (not versioned).

| Repo | Files read | Nodes / edges after `extract` | `extract` | `add` (agent) | `render --png` | `--svg` | `--html` | Final nodes / edges |
|------|-----------:|------------------------------:|----------:|--------------:|---------------:|--------:|---------:|--------------------:|
| basic-python-cli | 1 | 4 / 4 | 0.65 s | 1.3 s | 0.77 s | 0.71 s | 0.65 s | 10 / 12 |
| my_first_data_project | 10 | 43 / 56 | 0.67 s | 1.1 s | 1.11 s | 0.98 s | 0.67 s | 66 / 98 |
| python-clean-architecture | 92 | 376 / 702 | 1.03 s | 1.0 s | 1.97 s | 1.68 s | 0.82 s | 398 / 737 |
| kg | 40 | 609 / 1194 | 1.41 s | — | 1.83 s | 1.56 s | 0.95 s | — |

- Every command stays well under the rough 10 s reference of RNF-06.
- About **1 s of each command is start-up**: `kg --version` alone takes
  1.05 s, and 0.56 s of it is importing matplotlib, which the CLI loads even
  for commands that draw nothing. Importing the renderers lazily would make
  `validate`, `add`, `extract`, `remove` and `edit` roughly twice as fast on
  small repos. Proposed target for v0.2: start-up under 0.5 s; `extract` and
  `render` under 5 s for 100 files.
- The PNG/SVG of the complex repo hides `Function`, `Test`, `File` and `Class`
  to stay at 150 nodes (141 drawn); the HTML keeps all 398 nodes, with
  `Function` and `Test` initially unticked.

## Agent enrichment (CU-01)

An agent (Claude Code) read each project following `kg guide` and wrote one
document per repo, in English: [`examples/agent/`](../examples/agent/).

| Repo | Nodes added | Edges added | What |
|------|------------:|------------:|------|
| basic-python-cli | 6 | 8 | README and video tutorial, 2 decisions, 1 concept, the CLI endpoint |
| my_first_data_project | 25 | 42 | README and TODO, 5 CI workflows (`Config`), 4 decisions, 3 concepts, 9 TODO items and 2 documentation issues |
| python-clean-architecture | 22 | 35 | README, 5 decisions, 6 concepts (layers, user, create-user), 3 services, the HTTP endpoint, 4 configs, 2 documentation issues |

All three passed `kg add --dry-run` **on the first attempt**, and adding them
twice changes nothing. Every element carries `method: llm`, the file and the
lines it comes from, and a confidence from the guide's rubric (one inferred
decision at 0.75).

## Reference questions (CU-02, CU-03, CU-04)

Answered from the stored graphs only (`kg.analysis.untested()`,
`documents`/`justifies`/`implements` edges and `Issue` nodes).

### basic-python-cli

- **Which tests are missing?** All of them: no `Test` nodes and no `tests`
  edges. `untested()` returns `function:size.main`, and `module:size` has no
  test either. First test to write: `main()` on a known file
  (`concept:file-size-in-mb`: bytes / 1024², rounded down, so a 1.5 MB file
  must print `1 MB`).
- **Is the documentation in line with the code?** Yes. `document:README.md`
  documents `module:size` and `function:size.main`; its claims (single file,
  no dependencies, help without arguments) match
  `decision:no-external-dependencies` (no `Dependency` nodes besides the
  standard library, which is not modeled) and the
  `endpoint:python size.py <file>` entry point.
- **How to extend it with (1) output in other units and (2) several files at
  once?** Both touch only `module:size`: (1) generalize
  `concept:file-size-in-mb` into a unit parameter of `function:size.main`;
  (2) change `endpoint:python size.py <file>` to accept a list. Both
  collide with `decision:single-argument-interface` and the README's "next
  steps" (argparse or Click), so the natural path is to adopt `argparse`
  (standard library, keeps `decision:no-external-dependencies`).

### my_first_data_project

- **Which tests are missing?** All: the three `Test` modules in `etl/tests`
  have no test functions (`test functions: 0`), so `untested()` returns the
  12 public functions and the 4 modules. `issue:todo-unit-tests` already
  tracks it. Priorities from the graph: the two transformations that
  implement concepts, `transform_humidity_data` (`concept:humidity-reading`)
  and `transform_weather_data` (`concept:hourly-weather`), which are pure
  pandas functions and easy to test without Azure.
- **Is the documentation in line with the code?** Partly. The README documents
  the package and its four modules, but `issue:readme-workflow-count` (it
  announces four workflows and lists five) and `issue:readme-init-imports`
  (it says `etl/__init__.py` imports the modules; the file is empty) flag
  drift. None of the 12 public functions has a docstring
  (`issue:todo-docstrings`).
- **How to extend it with (1) the electricity and gas module from the TODO and
  (2) data quality checks?** (1) `issue:todo-energy-module`: a new
  `module:etl.energy_data_etl_pipeline` following `concept:etl-pipeline`,
  reusing `module:etl.utils` (connection) and `module:etl.constants`
  (`decision:configuration-from-environment`), with its own workflow next to
  the humidity and weather ones (`decision:manual-pipelines`) and loading into
  the same database (`decision:azure-postgresql-target`). (2)
  `issue:todo-data-quality-checks`: checks between the transform and load
  steps of both pipelines; they depend on `issue:todo-data-model` and
  `issue:todo-data-schema`, which should come first.

### python-clean-architecture

- **Which tests are missing?** 35 test functions reach 55 code elements; 63
  public definitions have none. Real gaps: the HTTP layer
  (`create_user_blueprint` in both Flask apps and `create_flask_app`, i.e.
  `endpoint:POST /v1/user/` has no test), the error handlers
  (`format_error_response`), `LoggerDefault` and the entry points. Many others
  are expected: interfaces (`IUserRepository`, `ICreateUserPresenter`…) and
  constructors (`__init__`), see [Findings](#findings).
- **Is the documentation in line with the code?** The README documents the
  three entry points and `endpoint:POST /v1/user/`, consistent with the
  blueprints (`/user/` under the `/v1` prefix). Gaps:
  `issue:readme-reference-link` (a reference URL mixes GitHub and LinkedIn)
  and `issue:readme-no-test-instructions` (17 test files, no word on how to
  run them). 106 of 110 public definitions have neither a docstring nor a
  document describing them.
- **How to extend it with (1) "get a user by id" and (2) "update a user's
  email"?** `decision:clean-architecture` fixes where each piece goes, layer by
  layer (`concept:*-layer`): a use case next to `CreateUserUseCase`
  (`concept:create-user`) with its DTOs and Cerberus validator
  (`decision:cerberus-validation`) in `src.interactor`; repository methods in
  `IUserRepository` and both adapters (`decision:swappable-adapters`; for (1)
  both adapters already have `get`, so only the use case and its delivery are
  missing; (2) needs an `update` method in both); a new
  endpoint in each Flask app (`service:flask-api`, `service:flask-memory-api`)
  and, for the CLI, a controller and view. (2) also needs a migration
  (`decision:alembic-migrations`) only if the email constraint changes.

### kg (dogfooding)

The #11 trial ([`examples/agent/kg.json`](../examples/agent/kg.json)) found
stale text in `docs/render.md` (the HTML "will reuse" the style: it already
did), recorded as an `Issue` and fixed.

## Invalid JSON in one iteration (criterion 3)

A document with five typical agent mistakes, sent with
`kg add --dry-run` to the `my_first_data_project` store:

| Mistake | What kg said | Fix applied |
|---------|--------------|-------------|
| `"type": "Decison"` | warning `custom_type`: *If it means "Decision", use the standard type* | `Decision` |
| `"confidence": 1.5` | error `out_of_range`: *a number between 0 and 1* | `0.9` |
| extra field `"notes"` | error `unknown_field`: *Custom attributes go in `attrs`* | moved to `attrs` |
| `"method": "LLM"` | error `not_allowed`: *Use "llm"* | `llm` |
| edge to `…get_api_respons` | error `broken_reference`: *Did you mean "…get_api_response"?* | fixed ID |

The second `--dry-run` was valid. The one misleading message: for the `Decison`
typo, the `id_prefix_mismatch` warning suggests renaming the ID to
`decison:…` instead of fixing the type; that belongs to #18.

## Findings

Fixed in this PR:

- **Imports between scripts of a package** (`extract`): in
  `my_first_data_project`, `etl/*.py` run as scripts import each other with
  `from utils import …`. They became external dependencies
  (`dependency:utils`, `dependency:constants`). Now resolved to
  `module:etl.utils` and `module:etl.constants`.
- **Agent nodes unlabeled in large images** (`render`): above 60 nodes only
  code types were labeled, so decisions and concepts showed as bare markers.
  `Document`, `Decision`, `Concept`, `Service` and `Endpoint` are now always
  labeled.
- **Guide and CI configuration** (`agents`): the guide forbade agents to add
  `config:` nodes, but the parser only reads `pyproject.toml` and
  requirements files. It now asks agents to add CI workflows,
  `docker-compose.yml`, `.env.example` and similar as `Config`.

Open, for v0.2:

- **Start-up time**: lazy-import matplotlib (see timings).
- **Untested false positives**: `Class(...)` counts as testing the class but
  not its `__init__`, and interfaces implemented by mocks or adapters are never
  referenced directly. Candidates: treat a call to a class as a reference to
  its `__init__`, and skip abstract classes or let `untested()` exclude them.
- **Import name vs distribution name** (RF-32): `azure` vs `azure-identity`
  and `azure-storage-blob`, `psycopg2` vs `psycopg2-binary`, `dotenv` vs
  `python-dotenv` appear as separate `Dependency` nodes.
- **Misleading prefix suggestion** for misspelled standard types (#18).
- **Bug noticed in a sample, outside kg**: `load_weather_data` in
  `my_first_data_project` inserts two values into three placeholders. It is not
  in the graph (the guide only records issues that documents mention); it
  could be reported upstream.

## Publication

The README *Examples* section links the three pages, served with GitHub Pages
from `docs/` (`https://cristian1a.github.io/kg/examples/`), and embeds the
PNG of `my_first_data_project`, chosen by the client.
