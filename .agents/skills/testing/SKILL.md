---
name: testing
description: Write and run pytest tests for the project's graph code. Use it when adding features, fixing bugs or when coverage is requested.
---

# Testing

## When to use it
- When creating or changing functions in `src/kg/`.
- When reproducing a bug (first a failing test, then the fix).

## Conventions
- Framework: **pytest**. Files `tests/test_<module>.py`, functions `test_<behavior>`.
- Small, deterministic graphs built in fixtures (`tests/conftest.py`) or helper functions.
- Compare graphs with `nx.utils.graphs_equal(G1, G2)` or by comparing `sorted(G.edges(data=True))`.
- For random layouts fix the seed: `nx.spring_layout(G, seed=42)`.
- Plotting tests: use the `Agg` backend and never `plt.show()`.
- Filesystem tests use `tmp_path`; never write into the repo.

## Example

```python
from kg import store
from kg.analysis import untested

PROV = {"method": "parser", "extractor": "python-ast@0.1", "confidence": 1.0}


def test_function_without_tests_is_listed():
    graph = store.document_to_graph(
        {
            "version": "1",
            "nodes": [
                {"id": "function:app.run", "type": "Function", "provenance": PROV}
            ],
            "edges": [],
        }
    )
    assert untested(graph) == ["function:app.run"]
```

## Commands
```bash
pytest                      # all tests
pytest -k untested -x -q    # filter and stop at the first failure
pytest --cov=kg
```

## Checklist
- [ ] Normal case, edge case (empty graph, missing node) and error case (`nx.NetworkXNoPath`, `nx.NodeNotFound`).
- [ ] All tests pass before finishing.
