# samples/

Directory for manual testing of `kg` on third-party repos. Repos cloned here
are **not committed** (`samples/*` is in `.gitignore`); only this README is
versioned.

It serves MVP acceptance criterion 1 (section 8 of `docs/requirements.md`:
the CU-01 flow on at least 3 small Python repos) and for timing `extract` and
`render` (RNF-06). Tracked in issue #12.

## Test repos

| Repo | Why |
|------|-----|
| [alfredodeza/basic-python-cli](https://github.com/alfredodeza/basic-python-cli) | Minimal CLI, very few files |

Add every new repo you test with here.

## Usage

```bash
git clone --depth 1 https://github.com/alfredodeza/basic-python-cli samples/basic-python-cli
kg init --kg-dir samples/basic-python-cli/.kg
kg extract samples/basic-python-cli --kg-dir samples/basic-python-cli/.kg
kg add agent-graph.json --kg-dir samples/basic-python-cli/.kg
kg render --html --kg-dir samples/basic-python-cli/.kg -o samples/basic-python-cli.html
```

Subcommands become available as their issues land (`extract` #6, `render` #9…).
