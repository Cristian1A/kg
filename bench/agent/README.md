# Agent layers pinned for the benchmark

`examples/agent/kg.json` follows this repo's current code. The benchmark pins
`kg` to `1a342c4` (and builds `kg-stale` at `ebd078d`), so it uses the agent
layer as it was at that commit. It is the layer every kg run in
`bench/results/` was built with.

| File | Source |
|------|--------|
| `kg-1a342c4.json` | `git show 1a342c4:examples/agent/kg.json` |
