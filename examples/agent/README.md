# Agent output

What an agent (Claude Code) added to each example graph, following `kg guide`:
documents, design decisions, domain concepts and documentation issues. Each
file points to nodes created by `kg extract`, so it is merged on top of an
extraction. The published graphs are in [docs/examples](../../docs/examples/README.md).

| File | Repo | Nodes | Edges |
|------|------|-------|-------|
| `basic-python-cli.json` | basic-python-cli `d0379bb` | 6 | 8 |
| `my_first_data_project.json` | my_first_data_project `3d57177` | 25 | 42 |
| `python-clean-architecture.json` | python-clean-architecture `6f58de5` | 22 | 35 |
| `kg.json` | this repo; first written in the #11 trial, refreshed in #53 | 58 | 133 |
| `scrapy.json` | scrapy 2.19.0 `8026dee` (#53) | 102 | 228 |

For this repo:

```bash
kg init && kg extract .
kg add examples/agent/kg.json --dry-run   # check
kg add examples/agent/kg.json
kg render --html
```

`tests/test_guide.py` checks that `kg.json` still fits the code, and
`tests/test_flow.py` checks the others against their clones in `samples/`.
