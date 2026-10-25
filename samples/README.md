# samples/

Directory for manual testing of `kg` on third-party repos. Repos cloned here
are **not committed** (`samples/*` is in `.gitignore`); only this README is
versioned.

It serves MVP acceptance criterion 1 (section 8 of `docs/requirements.md`:
the CU-01 flow on at least 3 small Python repos) and for timing `extract` and
`render` (RNF-06). Tracked in issue #12.

## Test repos

Only repos under a permissive license (MIT, BSD) are used, since their graphs
are published in `docs/examples/` (credits there).

| Level | Repo | Why | Commit |
|-------|------|-----|--------|
| Easy | [alfredodeza/basic-python-cli](https://github.com/alfredodeza/basic-python-cli) | Minimal CLI, one file | `d0379bb` |
| Intermediate | [bramvdklinkenberg/my_first_data_project](https://github.com/bramvdklinkenberg/my_first_data_project) | ETL scripts, CI workflows, empty tests | `3d57177` |
| Complex | [wesleey/python-clean-architecture](https://github.com/wesleey/python-clean-architecture) | Layered backend, 17 test files | `6f58de5` |
| Self | `kg` (this repo) | Dogfooding; benchmark repo (#39) | `e18f574` |
| Large | [scrapy/scrapy](https://github.com/scrapy/scrapy) | About 300 modules, docs and SEPs; the large repo of #52 | `8026dee` (2.19.0) |
| Memory (#71) | [Gentleman-Programming/engram](https://github.com/Gentleman-Programming/engram) | Experiment 2's second corpus and reference memory system; Go, MIT; full history (1 225 commits) | `7192931` |
| Memory, large (#71) | [pandas-dev/pandas](https://github.com/pandas-dev/pandas) | Experiment 2's third corpus, for scale; BSD-3; full history (39 611 commits) | `199f52b12c` |

Add every new repo you test with here.

## Usage

```bash
git clone --depth 1 https://github.com/alfredodeza/basic-python-cli samples/basic-python-cli
git clone --depth 1 --branch 2.19.0 https://github.com/scrapy/scrapy samples/scrapy
git clone . samples/kg && git -C samples/kg checkout e18f574
git clone --filter=blob:none https://github.com/Gentleman-Programming/engram samples/engram
git clone --filter=blob:none https://github.com/pandas-dev/pandas samples/pandas
kg init --kg-dir samples/runs/basic-python-cli/.kg
kg extract samples/basic-python-cli --kg-dir samples/runs/basic-python-cli/.kg
kg add examples/agent/basic-python-cli.json --kg-dir samples/runs/basic-python-cli/.kg
kg render --html --kg-dir samples/runs/basic-python-cli/.kg -o samples/runs/basic-python-cli/graph.html
```

`tests/test_flow.py` checks `examples/agent/<repo>.json` against these clones
when they are present (`tests/test_guide.py` checks `kg.json` against this
repo). Published graphs and images: `docs/examples/` (regeneration steps
there). Results: `docs/mvp-validation.md`.
