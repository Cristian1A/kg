# Agent output

`kg.json` is what an agent (Claude Code), following `kg guide`, added to the
graph of this repo during the #11 trial: documents, design decisions, domain
concepts and one documentation issue. It points to nodes created by
`kg extract`, so it is merged on top of an extraction:

```bash
kg init && kg extract .
kg add examples/agent/kg.json --dry-run   # check
kg add examples/agent/kg.json
kg render --html
```

`tests/test_guide.py` checks that it still fits the code.
