import json
import textwrap

import pytest

from kg import store
from kg.cli import EXIT_OK, main
from kg.extract import combine, extract_dependencies, extract_repo
from kg.extract.deps import Requirement, parse_requirement, requirement_files
from kg.extract.files import file_digest
from kg.schema.validation import validate_document

REPO = "repo:proj"


def write(root, files):
    for path, text in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(textwrap.dedent(text), encoding="utf-8")


def nodes(extraction):
    return {n["id"]: n for n in extraction.document["nodes"]}


def edges(extraction, type_):
    return {
        (e["source"], e["target"])
        for e in extraction.document["edges"]
        if e["type"] == type_
    }


PYPROJECT = """\
    [project]
    name = "proj"
    version = "0.1.0"
    requires-python = ">=3.12"
    dependencies = [
        "NetworkX>=3.7",
        "requests[socks,security] >=2.0 ; python_version < '3.13'",
        "attrs",
    ]

    [project.optional-dependencies]
    dev = ["pytest>=8", "ruff"]
    docs = ["mkdocs"]

    [dependency-groups]
    lint = ["ruff==0.9", {include-group = "dev"}]

    [tool.ruff]
    line-length = 88

    [tool.pytest.ini_options]
    testpaths = ["tests"]
    """

REQUIREMENTS = """\
    # pinned
    --index-url https://example.org/simple
    -r requirements-dev.txt
    -e .
    networkx==3.7.1  # inline comment
    Pillow==12.0 \\
        ; sys_platform == "linux"
    git+https://github.com/org/repo@v1#egg=repo
    ./local/pkg
    mypkg @ https://example.org/mypkg.whl

    """


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "proj"
    write(
        root,
        {
            "pyproject.toml": PYPROJECT,
            "requirements.txt": REQUIREMENTS,
            "requirements-dev.txt": "pytest==8.3\n",
            "requirements/docs.txt": "mkdocs-material\n",
        },
    )
    return root


# --- parse_requirement ---------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("networkx", Requirement("networkx", "")),
        ("networkx>=3.7,<4", Requirement("networkx", ">=3.7,<4")),
        ("zope.interface ~= 6.0", Requirement("zope.interface", "~= 6.0")),
        (
            "requests[socks, security]>=2 ; python_version<'3.13'",
            Requirement(
                "requests", ">=2", ("security", "socks"), "python_version<'3.13'"
            ),
        ),
        ("pkg @ https://x/pkg.whl", Requirement("pkg", "@ https://x/pkg.whl")),
        ("a (>=1.0)", Requirement("a", "(>=1.0)")),
    ],
)
def test_parse_requirement(text, expected):
    assert parse_requirement(text) == expected


@pytest.mark.parametrize("text", ["", ">=1.0", "pkg foo", "-pkg", "pkg[extra"])
def test_parse_requirement_rejects_invalid(text):
    assert parse_requirement(text) is None


# --- Nodes and edges -----------------------------------------------------------


def test_config_nodes_and_configures_edges(repo):
    extraction = extract_dependencies(repo, REPO)
    found = nodes(extraction)
    attrs = found["config:pyproject.toml"]["attrs"]
    assert attrs.pop("digest") == file_digest(repo / "pyproject.toml")
    assert attrs == {
        "format": "pyproject",
        "name": "proj",
        "version": "0.1.0",
        "requires_python": ">=3.12",
        "tools": ["pytest", "ruff"],
    }
    assert found["config:requirements/docs.txt"]["label"] == "docs.txt"
    assert edges(extraction, "configures") == {
        ("config:pyproject.toml", REPO),
        ("config:requirements.txt", REPO),
        ("config:requirements-dev.txt", REPO),
        ("config:requirements/docs.txt", REPO),
    }
    assert extraction.files == [
        "pyproject.toml",
        "requirements.txt",
        "requirements-dev.txt",
        "requirements/docs.txt",
    ]


def test_dependencies_from_every_source(repo):
    extraction = extract_dependencies(repo, REPO)
    deps = {n for n, v in nodes(extraction).items() if v["type"] == "Dependency"}
    assert deps == {
        "dependency:networkx",
        "dependency:requests",
        "dependency:attrs",
        "dependency:pytest",
        "dependency:ruff",
        "dependency:mkdocs",
        "dependency:pillow",
        "dependency:mypkg",
        "dependency:mkdocs-material",
    }
    assert edges(extraction, "depends_on") == {(REPO, d) for d in deps}
    assert extraction.skipped == []


def test_same_dependency_in_several_sources_is_one_node(repo):
    found = nodes(extract_dependencies(repo, REPO))
    networkx = found["dependency:networkx"]
    # The first declaration (pyproject) gives label, spec and provenance
    assert networkx["label"] == "NetworkX"
    assert networkx["attrs"] == {
        "spec": ">=3.7",
        "groups": ["main"],
        "declared_in": ["pyproject.toml", "requirements.txt"],
    }
    assert networkx["provenance"] == {
        "method": "parser",
        "extractor": "pyproject@0.1",
        "confidence": 1.0,
        "source": "pyproject.toml",
    }
    assert found["dependency:ruff"]["attrs"] == {
        "groups": ["dev", "lint"],
        "declared_in": ["pyproject.toml"],
    }
    assert found["dependency:pytest"]["attrs"]["declared_in"] == [
        "pyproject.toml",
        "requirements-dev.txt",
    ]


def test_version_extras_and_markers_as_attributes(repo):
    found = nodes(extract_dependencies(repo, REPO))
    assert found["dependency:requests"]["attrs"] == {
        "spec": ">=2.0",
        "extras": ["security", "socks"],
        "markers": "python_version < '3.13'",
        "groups": ["main"],
        "declared_in": ["pyproject.toml"],
    }
    # Joined continuation line; the provenance points to its first line
    pillow = found["dependency:pillow"]
    assert pillow["attrs"]["markers"] == 'sys_platform == "linux"'
    assert pillow["provenance"]["extractor"] == "requirements@0.1"
    assert pillow["provenance"]["lines"] == [6, 6]
    assert (
        found["dependency:mypkg"]["attrs"]["spec"] == "@ https://example.org/mypkg.whl"
    )


def test_document_is_valid(repo):
    document = extract_dependencies(repo, REPO).document
    # A fragment: the Repo node comes from the code extractor
    report = validate_document(document, known_ids={REPO})
    assert report.ok, report.to_text("deps")
    assert report.warnings == []


def test_requirement_files_order(tmp_path):
    write(
        tmp_path,
        {
            "requirements-dev.txt": "",
            "requirements.txt": "",
            "requirements_test.txt": "",
            "requirements/b.txt": "",
            "requirements/a.txt": "",
            "requirements/notes.md": "",
            "other.txt": "",
        },
    )
    assert requirement_files(tmp_path) == [
        "requirements.txt",
        "requirements-dev.txt",
        "requirements_test.txt",
        "requirements/a.txt",
        "requirements/b.txt",
    ]


# --- Edge and error cases ------------------------------------------------------


def test_no_manifests(tmp_path):
    extraction = extract_dependencies(tmp_path, REPO)
    assert extraction.document["nodes"] == []
    assert extraction.files == []


def test_pyproject_without_project_table(tmp_path):
    write(tmp_path, {"pyproject.toml": "[tool.black]\nline-length = 100\n"})
    found = nodes(extract_dependencies(tmp_path, REPO))
    attrs = found["config:pyproject.toml"]["attrs"]
    assert attrs.pop("digest").startswith("sha256:")
    assert attrs == {"format": "pyproject", "tools": ["black"]}
    assert len(found) == 1


def test_invalid_toml_is_reported_and_keeps_the_config_node(tmp_path):
    write(tmp_path, {"pyproject.toml": "[project\n", "requirements.txt": "six\n"})
    extraction = extract_dependencies(tmp_path, REPO)
    assert [(s.path, s.message[:12]) for s in extraction.skipped] == [
        ("pyproject.toml", "cannot parse")
    ]
    assert {"config:pyproject.toml", "dependency:six"} <= nodes(extraction).keys()


def test_wrong_types_and_invalid_entries_are_reported(tmp_path):
    write(
        tmp_path,
        {
            "pyproject.toml": """\
                [project]
                dependencies = "networkx"
                optional-dependencies = ["x"]

                [dependency-groups]
                dev = ["pytest", 3, "bad name"]
                """,
            "requirements.txt": "ok\nnot a requirement\n",
        },
    )
    extraction = extract_dependencies(tmp_path, REPO)
    assert [s.to_text() for s in extraction.skipped] == [
        "pyproject.toml: project.optional-dependencies is not a table",
        "pyproject.toml: project.dependencies is not a list",
        "pyproject.toml: dependency-groups.dev: not a valid requirement: 3",
        "pyproject.toml: dependency-groups.dev: not a valid requirement: 'bad name'",
        "requirements.txt:2: not a valid requirement: not a requirement",
    ]
    assert {"dependency:pytest", "dependency:ok"} <= nodes(extraction).keys()


def test_non_utf8_requirements_is_reported(tmp_path):
    (tmp_path / "requirements.txt").write_bytes(b"caf\xe9\n")
    skipped = extract_dependencies(tmp_path, REPO).skipped
    assert [s.path for s in skipped] == ["requirements.txt"]
    assert skipped[0].message.startswith("cannot read")


# --- Combined with the code extractor -----------------------------------------


def test_combine_first_wins_and_attrs_are_joined():
    prov_a = {"method": "parser", "extractor": "a", "confidence": 1.0}
    prov_b = {"method": "parser", "extractor": "b", "confidence": 1.0}
    first = {
        "version": "1",
        "nodes": [
            {
                "id": "dependency:x",
                "type": "Dependency",
                "attrs": {"spec": "1"},
                "provenance": prov_a,
            }
        ],
        "edges": [],
    }
    second = {
        "version": "1",
        "nodes": [
            {
                "id": "dependency:x",
                "type": "Dependency",
                "label": "x",
                "attrs": {"spec": "2", "import_name": "x"},
                "provenance": prov_b,
            },
            {"id": "dependency:y", "type": "Dependency", "provenance": prov_b},
        ],
        "edges": [],
    }
    combined = {n["id"]: n for n in combine([first, second])["nodes"]}
    assert combined["dependency:x"] == {
        "id": "dependency:x",
        "type": "Dependency",
        "label": "x",
        "attrs": {"spec": "1", "import_name": "x"},
        "provenance": prov_a,
    }
    assert "dependency:y" in combined


def test_imported_and_declared_dependency_is_one_node(repo):
    write(repo, {"src/proj/__init__.py": "import networkx as nx\nimport yaml\n"})
    extraction = extract_repo(repo)
    found = nodes(extraction)
    networkx = found["dependency:networkx"]
    assert networkx["provenance"]["extractor"] == "pyproject@0.1"
    assert networkx["attrs"]["import_name"] == "networkx"
    assert networkx["attrs"]["spec"] == ">=3.7"
    # Imported but not declared: only from the code extractor
    assert found["dependency:yaml"]["attrs"] == {"import_name": "yaml"}
    assert ("package:proj", "dependency:networkx") in edges(extraction, "imports")
    assert "pyproject.toml" in extraction.files
    assert "src/proj/__init__.py" in extraction.files
    assert validate_document(extraction.document).ok


def test_cli_extract_with_manifests_is_idempotent(repo, tmp_path, capsys):
    kg_dir = tmp_path / ".kg"
    store.init_store(kg_dir)
    argv = ["extract", str(repo), "--kg-dir", str(kg_dir), "--json"]
    assert main(argv) == EXIT_OK
    result = json.loads(capsys.readouterr().out)["result"]
    assert result["files"] == 4
    assert "dependency:networkx" in result["nodes"]["added"]
    assert main(argv) == EXIT_OK
    assert json.loads(capsys.readouterr().out)["result"]["changed"] is False
