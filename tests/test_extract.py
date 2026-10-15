import json
import re
import shutil
import subprocess
import textwrap

import pytest

from kg import store
from kg.cli import EXIT_INTERNAL, EXIT_OK, EXIT_USAGE, main
from kg.extract import EXTRACTOR, extract_python
from kg.extract.files import file_digest, python_files
from kg.schema.validation import validate_document

PARSER = {"method": "parser", "extractor": EXTRACTOR, "confidence": 1.0}


def write(root, files):
    for path, text in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(textwrap.dedent(text), encoding="utf-8")


def nodes(extraction):
    return {n["id"]: n for n in extraction.document["nodes"]}


def edges(extraction, type_=None):
    return {
        (e["source"], e["target"])
        for e in extraction.document["edges"]
        if type_ is None or e["type"] == type_
    }


@pytest.fixture
def repo(tmp_path):
    """src layout with a package, a subpackage, tests and a root script."""
    root = tmp_path / "proj"
    write(
        root,
        {
            "src/app/__init__.py": '"""The app.\n\nMore text."""\nVERSION = "1"\n',
            "src/app/core.py": """\
                import json
                import os.path
                from typing import TYPE_CHECKING

                import numpy as np
                from yaml_lib.sub import thing

                from . import util
                from .util import helper as h

                if TYPE_CHECKING:
                    from app.db import models


                class Engine(Base, metaclass=Meta):
                    \"\"\"Runs things.\"\"\"

                    @property
                    def speed(self):
                        return 1

                    @speed.setter
                    def speed(self, value):
                        pass

                    class Config:
                        pass

                    def _private(self):
                        def inner():
                            pass


                async def run():
                    import requests


                def __getattr__(name):
                    pass
                """,
            "src/app/util.py": "def helper():\n    pass\n",
            "src/app/db/__init__.py": "from .models import Row\n",
            "src/app/db/models.py": "class Row:\n    pass\n",
            "tests/test_core.py": "from app.core import Engine\nimport helpers\n",
            "tests/helpers.py": "",
            "script.py": "import app\nfrom ... import nothing\n",
        },
    )
    return root


# --- Nodes ---------------------------------------------------------------------


def test_extracts_standard_node_types_with_stable_ids(repo):
    found = nodes(extract_python(repo))
    assert {n: found[n]["type"] for n in found if not n.startswith("file:")} == {
        "repo:proj": "Repo",
        "package:app": "Package",
        "package:app.db": "Package",
        "module:app.core": "Module",
        "module:app.util": "Module",
        "module:app.db.models": "Module",
        "test:tests.test_core": "Test",
        "module:tests.helpers": "Module",
        "module:script": "Module",
        "class:app.core.Engine": "Class",
        "class:app.core.Engine.Config": "Class",
        "class:app.db.models.Row": "Class",
        "function:app.core.Engine.speed": "Function",
        "function:app.core.Engine._private": "Function",
        "function:app.core.run": "Function",
        "function:app.core.__getattr__": "Function",
        "function:app.util.helper": "Function",
        "dependency:numpy": "Dependency",
        "dependency:yaml-lib": "Dependency",
        "dependency:requests": "Dependency",
    }
    assert found["file:src/app/core.py"]["type"] == "File"
    assert found["file:src/app/core.py"]["label"] == "core.py"


def test_document_is_valid_against_the_schema(repo):
    report = validate_document(extract_python(repo).document)
    assert report.ok, report.to_text("extraction")
    assert report.warnings == []


def test_parser_provenance_with_file_and_lines(repo):
    found = nodes(extract_python(repo))
    engine = found["class:app.core.Engine"]
    assert engine["provenance"] == {
        **PARSER,
        "source": "src/app/core.py",
        "lines": [15, 31],
    }
    # A decorated function starts at its first decorator
    assert found["function:app.core.Engine.speed"]["provenance"]["lines"] == [18, 20]
    assert found["repo:proj"]["provenance"] == {**PARSER, "source": "."}
    # A module spans its whole file, so its size shows without opening it
    core = found["module:app.core"]["provenance"]
    assert core["lines"][0] == 1
    assert core["lines"][1] == len((repo / "src/app/core.py").read_text().splitlines())
    for edge in extract_python(repo).document["edges"]:
        assert edge["provenance"].items() >= PARSER.items()


def test_descriptions_and_attributes(repo):
    found = nodes(extract_python(repo))
    assert found["package:app"]["description"] == "The app."
    assert found["class:app.core.Engine"]["description"] == "Runs things."
    assert "description" not in found["function:app.util.helper"]
    assert found["class:app.core.Engine"]["attrs"] == {
        "public": True,
        "bases": ["Base"],
    }
    assert found["function:app.core.Engine.speed"]["attrs"] == {
        "public": True,
        "decorators": ["property"],
        "signature": "(self)",
    }
    run = found["function:app.core.run"]["attrs"]
    assert run == {"public": True, "async": True, "signature": run["signature"]}
    assert found["function:app.core.Engine._private"]["attrs"]["public"] is False
    assert found["function:app.core.__getattr__"]["attrs"]["public"] is True
    assert found["dependency:yaml-lib"]["attrs"] == {"import_name": "yaml_lib"}


def test_redefinition_keeps_the_first_and_skips_nested_functions(repo):
    found = nodes(extract_python(repo))
    # The setter has the same qualified name as the getter
    assert found["function:app.core.Engine.speed"]["attrs"]["decorators"] == [
        "property"
    ]
    assert not any(n.endswith(".inner") for n in found)


def test_definitions_inside_module_level_blocks(tmp_path):
    write(
        tmp_path,
        {
            "m.py": """\
                try:
                    def a(): pass
                except ImportError:
                    def b(): pass
                if True:
                    class C: pass
                else:
                    def d(): pass
                """
        },
    )
    found = nodes(extract_python(tmp_path))
    for id_ in ("function:m.a", "function:m.b", "class:m.C", "function:m.d"):
        assert id_ in found


# --- Edges ---------------------------------------------------------------------


def test_contains_edges(repo):
    contains = edges(extract_python(repo), "contains")
    assert ("repo:proj", "file:src/app/core.py") in contains
    assert ("repo:proj", "package:app") in contains
    assert ("package:app", "module:app.core") in contains
    assert ("package:app", "package:app.db") in contains
    assert ("package:app.db", "module:app.db.models") in contains
    assert ("repo:proj", "test:tests.test_core") in contains
    assert ("repo:proj", "module:script") in contains


def test_defines_edges(repo):
    defines = edges(extract_python(repo), "defines")
    assert ("file:src/app/core.py", "module:app.core") in defines
    assert ("file:src/app/__init__.py", "package:app") in defines
    assert ("file:src/app/core.py", "class:app.core.Engine") in defines
    assert ("class:app.core.Engine", "function:app.core.Engine.speed") in defines
    assert ("class:app.core.Engine", "class:app.core.Engine.Config") in defines
    assert ("file:src/app/core.py", "function:app.core.run") in defines


def test_imports_internal_and_external(repo):
    imports = edges(extract_python(repo), "imports")
    assert imports == {
        # `from . import util` and `from .util import helper`: one edge
        ("module:app.core", "module:app.util"),
        ("module:app.core", "module:app.db.models"),
        ("module:app.core", "dependency:numpy"),
        ("module:app.core", "dependency:yaml-lib"),
        ("module:app.core", "dependency:requests"),
        ("package:app.db", "module:app.db.models"),
        ("test:tests.test_core", "module:app.core"),
        # next to the test file, which is on sys.path
        ("test:tests.test_core", "module:tests.helpers"),
        ("module:script", "package:app"),
    }


def test_import_edge_provenance_points_to_the_first_statement(repo):
    edge = next(
        e
        for e in extract_python(repo).document["edges"]
        if e["type"] == "imports" and e["target"] == "module:app.util"
    )
    assert edge["provenance"]["lines"] == [8, 8]
    assert edge["provenance"]["source"] == "src/app/core.py"


def test_root_init_makes_the_repo_a_package(tmp_path):
    root = tmp_path / "lib"
    write(root, {"__init__.py": "", "a.py": "from . import b\n", "b.py": ""})
    extraction = extract_python(root)
    assert {"package:lib", "module:lib.a", "module:lib.b"} <= nodes(extraction).keys()
    assert edges(extraction, "imports") == {("module:lib.a", "module:lib.b")}


# --- Edge and error cases ------------------------------------------------------


def test_empty_directory(tmp_path):
    extraction = extract_python(tmp_path)
    assert extraction.files == []
    assert [n["type"] for n in extraction.document["nodes"]] == ["Repo"]
    assert extraction.document["edges"] == []


def test_syntax_error_is_reported_and_skipped(tmp_path):
    write(tmp_path, {"bad.py": "def f(:\n", "good.py": "def g():\n    pass\n"})
    extraction = extract_python(tmp_path)
    assert [s.to_text() for s in extraction.skipped] == [
        "bad.py:1: syntax error: invalid syntax"
    ]
    found = nodes(extraction)
    assert "function:good.g" in found
    # The file and its module exist; their contents were not read
    assert {"file:bad.py", "module:bad"} <= found.keys()
    assert validate_document(extraction.document).ok


def test_null_bytes_are_reported(tmp_path):
    (tmp_path / "bin.py").write_bytes(b"x = 1\0\n")
    skipped = extract_python(tmp_path).skipped
    assert [(s.path, s.line) for s in skipped] == [("bin.py", None)]
    assert "null bytes" in skipped[0].message


def test_files_record_a_content_digest(tmp_path):
    write(tmp_path, {"a.py": "x = 1\n", "b.py": "x = 1\n", "c.py": "x = 2\n"})
    found = nodes(extract_python(tmp_path))
    digests = {
        p: found[f"file:{p}"]["attrs"]["digest"] for p in ("a.py", "b.py", "c.py")
    }
    assert digests["a.py"] == digests["b.py"] == file_digest(tmp_path / "a.py")
    assert digests["c.py"] != digests["a.py"]
    assert re.fullmatch(r"sha256:[0-9a-f]{16}", digests["a.py"])


def test_invalid_utf8_is_reported(tmp_path):
    (tmp_path / "bad.py").write_bytes(b'x = "\xff\xfe"\n')
    write(tmp_path, {"good.py": "def g():\n    pass\n"})
    extraction = extract_python(tmp_path)
    assert [s.path for s in extraction.skipped] == ["bad.py"]
    assert "utf-8" in extraction.skipped[0].message
    assert "function:good.g" in nodes(extraction)


def test_declared_source_encoding_is_honoured(tmp_path):
    source = '# -*- coding: latin-1 -*-\nNAME = "caf\xe9"\n\n\ndef f():\n    pass\n'
    (tmp_path / "latin.py").write_bytes(source.encode("latin-1"))
    extraction = extract_python(tmp_path)
    assert extraction.skipped == []
    assert "function:latin.f" in nodes(extraction)


def test_broken_and_looping_symlinks_are_ignored(tmp_path):
    write(tmp_path, {"app.py": "def run():\n    pass\n"})
    (tmp_path / "dangling.py").symlink_to(tmp_path / "missing.py")
    (tmp_path / "loop").symlink_to(tmp_path, target_is_directory=True)
    extraction = extract_python(tmp_path)
    assert extraction.files == ["app.py"]
    assert extraction.skipped == []


def test_syntax_warnings_are_silenced(tmp_path, capfd):
    write(tmp_path, {"w.py": 'PATTERN = "\\d"\n'})
    extract_python(tmp_path)
    assert capfd.readouterr().err == ""


def test_module_name_clash_keeps_the_first_file(tmp_path):
    write(
        tmp_path,
        {
            "a/b.py": "",  # loose: module a.b
            "src/a/__init__.py": "",
            "src/a/b.py": "",  # package: module a.b too
        },
    )
    extraction = extract_python(tmp_path)
    assert nodes(extraction)["module:a.b"]["provenance"]["source"] == "a/b.py"
    assert [s.to_text() for s in extraction.skipped] == [
        "src/a/b.py: module a.b is already defined by a/b.py"
    ]


def test_extraction_is_deterministic(repo):
    first = extract_python(repo).document
    assert extract_python(repo).document == first


# --- Files ---------------------------------------------------------------------


def test_skips_virtualenvs_and_caches(tmp_path):
    write(
        tmp_path,
        {
            "app.py": "",
            "env/lib/x.py": "",
            ".venv/lib/x.py": "",
            ".git/hooks/x.py": "",
            "pkg/__pycache__/x.py": "",
            "myvenv/pyvenv.cfg": "",
            "myvenv/lib/x.py": "",
            "notes.txt": "",
        },
    )
    assert python_files(tmp_path) == ["app.py"]


def test_gitignore_without_git(tmp_path, monkeypatch):
    monkeypatch.setattr("kg.extract.files._git_files", lambda root: None)
    write(
        tmp_path,
        {
            ".gitignore": "# comment\nbuild/\n/gen_*.py\n*_local.py\n!keep_local.py\n",
            "app.py": "",
            "build/x.py": "",
            "gen_a.py": "",
            "sub/gen_b.py": "",  # `/gen_*.py` is anchored to the root
            "sub/x_local.py": "",
            "keep_local.py": "",
        },
    )
    assert python_files(tmp_path) == ["app.py", "keep_local.py", "sub/gen_b.py"]


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_gitignore_with_git(tmp_path):
    write(
        tmp_path,
        {
            ".gitignore": "ignored/\n",
            "sub/.gitignore": "secret.py\n",
            "tracked.py": "",
            "untracked.py": "",
            "ignored/x.py": "",
            "sub/secret.py": "",
            "sub/ok.py": "",
        },
    )
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "tracked.py"], cwd=tmp_path, check=True)
    assert python_files(tmp_path) == ["sub/ok.py", "tracked.py", "untracked.py"]
    # A subdirectory that the enclosing repo ignores is walked instead
    assert python_files(tmp_path / "ignored") == ["x.py"]


# --- CLI -----------------------------------------------------------------------


@pytest.fixture
def kg_dir(tmp_path):
    path = tmp_path / ".kg"
    store.init_store(path)
    return path


def test_cli_extract_twice_does_not_duplicate(repo, kg_dir, capsys):
    argv = ["extract", str(repo), "--kg-dir", str(kg_dir)]
    assert main(argv) == EXIT_OK
    first = store.graph_path(kg_dir).read_text(encoding="utf-8")
    assert "extracted 8 files" in capsys.readouterr().out

    assert main(argv) == EXIT_OK
    assert store.graph_path(kg_dir).read_text(encoding="utf-8") == first
    out = capsys.readouterr().out
    assert out.startswith("no changes:")
    assert "0 added, 0 merged" in out


def test_cli_extract_json(tmp_path, kg_dir, capsys):
    write(tmp_path / "r", {"bad.py": "def f(:\n", "ok.py": ""})
    argv = ["extract", str(tmp_path / "r"), "--kg-dir", str(kg_dir), "--json"]
    assert main(argv) == EXIT_OK
    result = json.loads(capsys.readouterr().out)["result"]
    assert result["files"] == 2
    assert result["changed"] is True
    assert result["skipped"] == [
        {"path": "bad.py", "line": 1, "message": "syntax error: invalid syntax"}
    ]
    assert "module:ok" in result["nodes"]["added"]


def test_cli_extract_text_lists_skipped_files(tmp_path, kg_dir, capsys):
    write(tmp_path / "r", {"bad.py": "def f(:\n"})
    assert main(["extract", str(tmp_path / "r"), "--kg-dir", str(kg_dir)]) == EXIT_OK
    assert "    bad.py:1: syntax error" in capsys.readouterr().out


def test_cli_extract_reports_changes_as_conflicts(tmp_path, kg_dir, capsys):
    root = tmp_path / "r"
    write(root, {"m.py": "def f():\n    pass\n"})
    main(["extract", str(root), "--kg-dir", str(kg_dir)])
    write(root, {"m.py": "\n\ndef f():\n    pass\n"})
    capsys.readouterr()
    assert main(["extract", str(root), "--kg-dir", str(kg_dir)]) == EXIT_OK
    out = capsys.readouterr().out
    assert "function:m.f · provenance" in out
    lines = store.load_graph(kg_dir).nodes["function:m.f"]["provenance"]["lines"]
    assert lines == [3, 4]


def test_cli_extract_without_store(repo, tmp_path, capsys):
    argv = ["extract", str(repo), "--kg-dir", str(tmp_path / "missing")]
    assert main(argv) == EXIT_USAGE
    assert "kg init" in capsys.readouterr().err


def test_cli_extract_missing_path(kg_dir, tmp_path, capsys):
    argv = ["extract", str(tmp_path / "nope"), "--kg-dir", str(kg_dir)]
    assert main(argv) == EXIT_USAGE
    assert "not a directory" in capsys.readouterr().err


def test_cli_extract_invalid_document_is_internal_error(
    repo, kg_dir, monkeypatch, capsys
):
    def broken(root):
        extraction = extract_python(root)
        extraction.document["nodes"].append(dict(extraction.document["nodes"][0]))
        return extraction

    monkeypatch.setattr("kg.extract.extract_repo", broken)
    assert main(["extract", str(repo), "--kg-dir", str(kg_dir)]) == EXIT_INTERNAL
    assert "the store was not modified" in capsys.readouterr().err
    assert store.load_graph(kg_dir).number_of_nodes() == 0


def test_scripts_inside_a_package_import_their_siblings(tmp_path):
    """`./etl/job.py` run as a script imports `etl/utils.py` as `utils`."""
    write(
        tmp_path,
        {
            "etl/__init__.py": "",
            "etl/utils.py": "def connect():\n    pass\n",
            "etl/job.py": "import json\nfrom utils import connect\nimport pandas\n",
            "etl/tests/__init__.py": "",
            "etl/tests/test_job.py": "from utils import connect\n\n\n"
            "def test_connect():\n    connect()\n",
        },
    )
    extraction = extract_python(tmp_path)
    imports = edges(extraction, "imports")
    assert ("module:etl.job", "module:etl.utils") in imports
    assert ("module:etl.job", "dependency:pandas") in imports
    assert ("module:etl.job", "dependency:utils") not in imports
    # Not a sibling of etl/tests/test_job.py: stays external
    assert ("test:etl.tests.test_job", "dependency:utils") in imports


def test_function_signatures(tmp_path):
    (tmp_path / "m.py").write_text(
        "def f(a, b: int = 1, *args, c, **kw) -> str:\n    return ''\n\n\n"
        "class K:\n    async def g(self, x=None):\n        pass\n"
    )
    found = nodes(extract_python(tmp_path))
    assert found["function:m.f"]["attrs"]["signature"] == (
        "(a, b: int=1, *args, c, **kw) -> str"
    )
    assert found["function:m.K.g"]["attrs"]["signature"] == "(self, x=None)"
    assert "signature" not in found["class:m.K"]["attrs"]
