#!/usr/bin/env bash
# Smoke test of an installed kg: the full CU-01 flow on a tiny repo.
# Run it with the `kg` under test on PATH, e.g. after `pip install .`.
# Usage: .github/smoke-test.sh [workdir]
set -euo pipefail

examples="$(cd "$(dirname "$0")/../examples" && pwd)"
work="${1:-$(mktemp -d)}"
repo="$work/demo"
mkdir -p "$repo/src/demo" "$repo/tests"

cat > "$repo/pyproject.toml" <<'TOML'
[project]
name = "demo"
version = "0.1.0"
dependencies = ["requests>=2"]
TOML
cat > "$repo/src/demo/__init__.py" <<'PY'
"""Demo package."""
PY
cat > "$repo/src/demo/core.py" <<'PY'
import requests


def fetch(url):
    """Fetch a URL."""
    return requests.get(url, timeout=5)
PY
cat > "$repo/tests/test_core.py" <<'PY'
from demo.core import fetch


def test_fetch():
    assert fetch
PY

cd "$repo"
kg --version
kg --help > /dev/null
kg schema > /dev/null
kg guide > /dev/null
kg validate "$examples/minimal.json"
kg init
kg extract .
kg status . | grep -q "up to date"
kg add "$examples/minimal.json"
kg validate .kg/graph.json
kg render --html -o graph.html
kg render --png -o graph.png
kg render --svg -o graph.svg
test -s graph.html && test -s graph.png && test -s graph.svg

# The JSON contract agents rely on (RF-22)
kg --json extract . | python -c 'import json, sys; assert json.load(sys.stdin)["ok"]'

# The bundled assets are installed, so the HTML works offline (RF-51)
grep -q "vis-network" graph.html
echo "smoke test passed in $repo"
