import json
import re
from pathlib import Path

import pytest

from kg import agents
from kg.cli import EXIT_OK, main
from kg.extract import extract_repo
from kg.schema import STANDARD_EDGE_TYPES, STANDARD_NODE_TYPES
from kg.schema.validation import validate_document

ROOT = Path(__file__).parents[1]
SKILL = ROOT / ".agents" / "skills" / "kg-graph" / "SKILL.md"
AGENT_EXAMPLE = ROOT / "examples" / "agent" / "kg.json"


def json_blocks(markdown):
    return [
        json.loads(block)
        for block in re.findall(r"```json\n(.*?)```", markdown, re.S)
        if block.lstrip().startswith('{\n  "version"')
    ]


def test_guide_covers_the_whole_standard_catalog():
    guide = agents.load_guide()
    for type_ in STANDARD_NODE_TYPES | STANDARD_EDGE_TYPES:
        assert f"`{type_}`" in guide, type_


@pytest.mark.parametrize(
    "topic",
    [
        "kg add draft.json --dry-run --json",  # the validation loop
        "kg validate",
        "method` is `llm`",  # provenance
        "confidence",
        "one language",  # issue #11 comment: a single language
        "custom type",
        "Which tests are missing?",  # the reference questions
        "Is the documentation in line with the code?",
        "How can the project be extended",
        "Every node you create has a `description`",  # issue #36
        "missing_description",
        "Describe the main extracted nodes that lack one",
        "kg query untested",  # issue #38: answering with the query commands
        "kg impact <id>",
        "possible",
    ],
)
def test_guide_covers_the_required_topics(topic):
    assert topic in agents.load_guide()


def test_guide_example_is_valid_and_uses_llm_provenance():
    [example] = json_blocks(agents.load_guide())
    # It points to nodes that `kg extract` creates
    report = validate_document(example, known_ids={"module:size", "function:size.main"})
    assert report.ok, report.to_text("guide example")
    assert report.warnings == []
    for item in [*example["nodes"], *example["edges"]]:
        assert item["provenance"]["method"] == "llm"
        assert "source" in item["provenance"]


def test_guide_description_snippet_enriches_an_extracted_node():
    blocks = re.findall(r"```json\n(.*?)```", agents.load_guide(), re.S)
    [snippet] = [json.loads(b) for b in blocks if b.lstrip().startswith('{ "id"')]
    report = validate_document({"version": "1", "nodes": [snippet], "edges": []})
    assert report.ok and report.warnings == []
    assert snippet["provenance"]["method"] == "llm"
    assert snippet["id"] == "module:size"  # an ID `kg extract` creates


def test_skill_file_is_the_exported_guide():
    assert SKILL.read_text(encoding="utf-8") == agents.skill_text(), (
        "regenerate it: kg guide --skill > .agents/skills/kg-graph/SKILL.md"
    )


def test_skill_front_matter():
    text = agents.skill_text()
    match = re.match(r"---\nname: (.+)\ndescription: (.+)\n---\n", text)
    assert match is not None
    assert match.group(1) == "kg-graph"
    assert json.loads(match.group(2)) == agents.SKILL_DESCRIPTION


def test_agent_trial_on_this_repo_still_fits_the_code():
    """examples/agent/kg.json (the #11 trial) only points to existing code."""
    document = json.loads(AGENT_EXAMPLE.read_text(encoding="utf-8"))
    extracted = {n["id"] for n in extract_repo(ROOT).document["nodes"]}
    report = validate_document(document, known_ids=extracted)
    assert report.ok, report.to_text(str(AGENT_EXAMPLE))
    assert report.warnings == []
    assert not {n["id"] for n in document["nodes"]} & extracted  # no duplicates
    assert {i["provenance"]["method"] for i in document["nodes"]} == {"llm"}


# --- CLI -----------------------------------------------------------------------


def test_cli_guide(capsys):
    assert main(["guide"]) == EXIT_OK
    out = capsys.readouterr().out
    assert out.startswith("# Building a kg knowledge graph as an agent")


def test_cli_guide_skill_and_path(capsys):
    assert main(["guide", "--skill"]) == EXIT_OK
    assert capsys.readouterr().out.startswith("---\nname: kg-graph\n")
    assert main(["guide", "--path"]) == EXIT_OK
    assert Path(capsys.readouterr().out.strip()) == agents.guide_path()
    assert agents.guide_path().is_file()


def test_cli_guide_json(capsys):
    assert main(["guide", "--json"]) == EXIT_OK
    result = json.loads(capsys.readouterr().out)["result"]
    assert result["guide"] == agents.load_guide()
    assert result["path"] == str(agents.guide_path())
