# Contributing

The repository is written in English: code, CLI messages, docs, commits,
issues and PRs. History from before the switch (issue #20) stays in Spanish.

## Commits — Conventional Commits

```
<type>(<scope>): <imperative summary, ≤ 72 characters, no trailing period>

<optional body: WHAT changes and WHY, not how. Lines ≤ 72.>

Refs: #<issue>   |   Closes: #<issue>
RF: RF-10, RF-11
```

**Types**

| Type | Use |
|------|-----|
| `feat` | New feature |
| `fix` | Bug fix |
| `docs` | Documentation only |
| `test` | Add or fix tests |
| `refactor` | Code change without behavior change |
| `perf` | Performance improvement |
| `build` | Dependencies, packaging, Docker |
| `ci` | Continuous integration |
| `chore` | Maintenance (config, .gitignore…) |

**Scopes** (project modules): `schema`, `extract`, `store`, `merge`, `query`, `render`, `export`, `cli`, `mcp`, `agents`, `docs`.

**Examples**
```
feat(schema): add JSON Schema with the standard entity catalog

Defines nodes/edges, provenance and custom types with a warning.

Closes: #3
RF: RF-01, RF-02
```
```
fix(extract): skip .py files inside env/ and .venv/

Refs: #12
```

- One commit = one logical change. Tests go in the same commit as the code.
- A breaking change is marked with `!` (`feat(cli)!: …`) and a `BREAKING CHANGE: …` footer.
- Local template: `git config commit.template .gitmessage`.

## Branches

`<type>/<issue>-<slug>` → `feat/3-json-schema`, `fix/12-skip-venv`.
`main` is always stable; changes land through Pull Requests.

## Issues

Opened with the templates in `.github/ISSUE_TEMPLATE/`:

- **Title**: `[<scope>] <short description>` → `[schema] Validate broken references between edges`
- **Feature**: related RF/RNF requirement(s), description, acceptance criteria as a checklist, technical notes.
- **Bug**: steps to reproduce, expected vs. actual result, version/environment, logs.

Requirement IDs (`RF-xx`, `RNF-xx`) keep their original Spanish prefixes; see the note in `docs/requirements.md`.

**Labels**

| Group | Labels |
|-------|--------|
| Type | `type:feature`, `type:bug`, `type:docs`, `type:chore` |
| Priority (release phase) | `prio:mvp`, `prio:v0.2`, `prio:futuro` |
| Scope | `area:schema`, `area:extract`, `area:store`, `area:merge`, `area:query`, `area:render`, `area:export`, `area:cli`, `area:mcp`, `area:agents` |
| Status | `status:blocked`, `good first issue` |

Milestones: `v0.1 (MVP)`, `v0.2`.
