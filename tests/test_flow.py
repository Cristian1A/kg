"""End-to-end CU-01 flow, as validated on real repos in docs/mvp-validation.md."""

import json
from pathlib import Path

import pytest

from kg import store
from kg.analysis import untested
from kg.cli import EXIT_OK, EXIT_VALIDATION, main
from kg.extract import extract_repo
from kg.schema.validation import validate_document

ROOT = Path(__file__).parents[1]
LLM = {"method": "llm", "extractor": "claude-code", "confidence": 0.9}


def run(capsys, *argv):
    """Run the CLI with --json and return (exit code, payload)."""
    code = main([*argv, "--json"])
    return code, json.loads(capsys.readouterr().out)


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "shop"
    files = {
        "README.md": "# Shop\n\nPrices include VAT.\n",
        "requirements.txt": "requests==2.32\n",
        "shop/__init__.py": "",
        "shop/prices.py": '"""Prices."""\n\n\n'
        "def with_vat(net):\n    return net * 1.21\n",
        "shop/api.py": "import requests\n\nfrom shop.prices import with_vat\n\n\n"
        "def quote(net):\n    return with_vat(net)\n",
        "tests/test_prices.py": "from shop.prices import with_vat\n\n\n"
        "def test_with_vat():\n    assert with_vat(100) == 121\n",
    }
    for path, text in files.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(text, encoding="utf-8")
    return root


def agent_document():
    prov = {**LLM, "source": "README.md", "lines": [3, 3]}
    return {
        "version": "1",
        "nodes": [
            {
                "id": "document:README.md",
                "type": "Document",
                "label": "README",
                "provenance": prov,
            },
            {
                "id": "concept:vat",
                "type": "Concept",
                "label": "VAT",
                "description": "Prices include 21 % VAT.",
                "provenance": prov,
            },
        ],
        "edges": [
            {
                "source": "document:README.md",
                "target": "module:shop.prices",
                "type": "documents",
                "provenance": prov,
            },
            {
                "source": "function:shop.prices.with_vat",
                "target": "concept:vat",
                "type": "implements",
                "provenance": prov,
            },
        ],
    }


def test_cu01_flow(repo, tmp_path, capsys):
    kg = str(tmp_path / ".kg")
    assert run(capsys, "init", "--kg-dir", kg)[0] == EXIT_OK

    code, extracted = run(capsys, "extract", str(repo), "--kg-dir", kg)
    assert code == EXIT_OK
    assert extracted["result"]["skipped"] == []
    # Criterion 5: extracting twice changes nothing
    assert (
        run(capsys, "extract", str(repo), "--kg-dir", kg)[1]["result"]["changed"]
        is False
    )

    agent = tmp_path / "agent.json"
    agent.write_text(json.dumps(agent_document()), encoding="utf-8")
    code, dry = run(capsys, "add", str(agent), "--dry-run", "--kg-dir", kg)
    assert code == EXIT_OK and dry["result"]["dry_run"] is True
    assert (
        run(capsys, "add", str(agent), "--kg-dir", kg)[1]["result"]["changed"] is True
    )
    assert (
        run(capsys, "add", str(agent), "--kg-dir", kg)[1]["result"]["changed"] is False
    )

    for fmt in ("html", "png", "svg"):
        out = tmp_path / f"graph.{fmt}"
        code, rendered = run(
            capsys, "render", f"--{fmt}", "-o", str(out), "--kg-dir", kg
        )
        assert code == EXIT_OK and out.stat().st_size > 0
        assert rendered["result"]["nodes"] > 0

    # The graph holds what the reference questions need
    graph = store.load_graph(Path(kg))
    assert graph.has_edge(
        "test:tests.test_prices.test_with_vat", "function:shop.prices.with_vat", "tests"
    )
    assert untested(graph) == ["function:shop.api.quote"]
    assert graph.has_edge("document:README.md", "module:shop.prices", "documents")
    assert graph.has_edge("module:shop.api", "dependency:requests", "imports")


def test_invalid_document_is_fixed_in_one_iteration(repo, tmp_path, capsys):
    """Criterion 3: the messages alone are enough to fix every mistake."""
    kg = str(tmp_path / ".kg")
    main(["init", "--kg-dir", kg])
    main(["extract", str(repo), "--kg-dir", kg])
    capsys.readouterr()

    document = agent_document()
    document["nodes"][1]["provenance"] = {**LLM, "confidence": 1.5}
    document["nodes"][1]["notes"] = "draft"
    document["edges"][1]["source"] = "function:shop.prices.with_vta"
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(document), encoding="utf-8")

    code, payload = run(capsys, "add", str(bad), "--dry-run", "--kg-dir", kg)
    assert code == EXIT_VALIDATION
    errors = {e["code"]: e for e in payload["error"]["details"]["errors"]}
    assert set(errors) == {"out_of_range", "unknown_field", "broken_reference"}
    assert '"function:shop.prices.with_vat"' in errors["broken_reference"]["suggestion"]
    assert "attrs" in errors["unknown_field"]["suggestion"]

    # One iteration, applying the suggestions
    document["nodes"][1]["provenance"]["confidence"] = 0.9
    document["nodes"][1]["attrs"] = {"notes": document["nodes"][1].pop("notes")}
    document["edges"][1]["source"] = "function:shop.prices.with_vat"
    bad.write_text(json.dumps(document), encoding="utf-8")
    assert run(capsys, "add", str(bad), "--dry-run", "--kg-dir", kg)[0] == EXIT_OK


SAMPLES = [
    "basic-python-cli",
    "my_first_data_project",
    "python-clean-architecture",
    "scrapy",
]


@pytest.mark.parametrize("name", SAMPLES)
def test_published_agent_documents_fit_their_repos(name):
    """examples/agent/<repo>.json only points to code that the repo has."""
    sample = ROOT / "samples" / name
    if not sample.is_dir():
        pytest.skip(f"clone {name} into samples/ (see docs/examples/README.md)")
    document = json.loads(
        (ROOT / "examples" / "agent" / f"{name}.json").read_text("utf-8")
    )
    extracted = {n["id"] for n in extract_repo(sample).document["nodes"]}
    report = validate_document(document, known_ids=extracted)
    assert report.ok, report.to_text(name)
    assert report.warnings == []
    assert not {n["id"] for n in document["nodes"]} & extracted
