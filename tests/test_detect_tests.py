import ast
import json
import textwrap

import pytest

from kg import store
from kg.analysis import untested
from kg.cli import EXIT_OK, main
from kg.extract import extract_python
from kg.extract.references import bindings, references
from kg.schema.validation import validate_document


def write(root, files):
    for path, text in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(textwrap.dedent(text), encoding="utf-8")


def nodes(extraction):
    return {n["id"]: n for n in extraction.document["nodes"]}


def relation_pairs(extraction):
    return {
        (e["source"], e["target"])
        for e in extraction.document["edges"]
        if e["type"] == "tests"
    }


def targets(extraction, source):
    return {t for s, t in relation_pairs(extraction) if s == source}


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "proj"
    write(
        root,
        {
            "src/app/__init__.py": "from .core import Engine, run\n",
            "src/app/core.py": """\
                class Engine:
                    def start(self):
                        pass

                    def stop(self):
                        pass

                    def _reset(self):
                        pass


                def run():
                    pass


                def untouched():
                    pass
                """,
            "src/app/util.py": "def helper():\n    pass\n",
            "tests/conftest.py": "import pytest\n\n\n@pytest.fixture\ndef eng():\n"
            "    pass\n",
            "tests/test_core.py": """\
                import pytest

                import app.util as u
                from app import Engine
                from app.core import run as go


                def make():
                    return Engine()


                def test_start():
                    engine = Engine()
                    engine.start()


                def test_chain_and_alias():
                    Engine().stop()
                    go()
                    u.helper()


                async def test_async():
                    pass


                class TestGroup:
                    def test_method(self):
                        make()

                    def helper(self):
                        pass


                class Checks(unittest.TestCase):
                    def test_case(self):
                        pass


                class NotATest:
                    def test_ignored(self):
                        pass
                """,
            "tests/core_test.py": "def test_other():\n    pass\n",
            "tests/helpers.py": "def test_like_name():\n    pass\n",
        },
    )
    return root


# --- Detection -----------------------------------------------------------------


def test_detects_test_files_functions_and_classes(repo):
    found = nodes(extract_python(repo))
    tests = {n: v["attrs"]["kind"] for n, v in found.items() if v["type"] == "Test"}
    assert tests == {
        "test:tests.test_core": "module",
        "test:tests.core_test": "module",
        "test:tests.test_core.test_start": "function",
        "test:tests.test_core.test_chain_and_alias": "function",
        "test:tests.test_core.test_async": "function",
        "test:tests.test_core.TestGroup": "class",
        "test:tests.test_core.TestGroup.test_method": "function",
        "test:tests.test_core.Checks": "class",
        "test:tests.test_core.Checks.test_case": "function",
        "test:tests.core_test.test_other": "function",
    }
    # Helpers and fixtures stay as code; files outside the convention too
    assert found["function:tests.test_core.make"]["type"] == "Function"
    assert found["function:tests.test_core.TestGroup.helper"]["type"] == "Function"
    assert found["class:tests.test_core.NotATest"]["type"] == "Class"
    assert "function:tests.test_core.NotATest.test_ignored" in found
    assert found["function:tests.conftest.eng"]["type"] == "Function"
    assert found["module:tests.helpers"]["type"] == "Module"
    assert found["function:tests.helpers.test_like_name"]["type"] == "Function"


def test_test_nodes_keep_the_usual_attributes_and_edges(repo):
    extraction = extract_python(repo)
    node = nodes(extraction)["test:tests.test_core.test_async"]
    assert node["attrs"] == {"public": True, "async": True, "kind": "function"}
    assert node["provenance"]["source"] == "tests/test_core.py"
    edges = {
        (e["source"], e["target"], e["type"]) for e in extraction.document["edges"]
    }
    assert ("file:tests/test_core.py", "test:tests.test_core", "defines") in edges
    assert (
        "test:tests.test_core.TestGroup",
        "test:tests.test_core.TestGroup.test_method",
        "defines",
    ) in edges
    assert ("test:tests.test_core", "package:app", "imports") in edges


def test_document_is_valid(repo):
    report = validate_document(extract_python(repo).document)
    assert report.ok, report.to_text("extraction")
    assert report.warnings == []


# --- tests edges ---------------------------------------------------------------


def test_function_level_relation_pairs(repo):
    extraction = extract_python(repo)
    # Through a package re-export and an instance
    assert targets(extraction, "test:tests.test_core.test_start") == {
        "class:app.core.Engine",
        "function:app.core.Engine.start",
    }
    # Class(...).method, `import … as` and `from … import … as`
    assert targets(extraction, "test:tests.test_core.test_chain_and_alias") == {
        "class:app.core.Engine",
        "function:app.core.Engine.stop",
        "function:app.core.run",
        "function:app.util.helper",
    }
    # Through a helper in the test file: not followed
    assert targets(extraction, "test:tests.test_core.TestGroup.test_method") == set()
    assert targets(extraction, "test:tests.test_core.test_async") == set()


def test_module_level_relation_pairs(repo):
    extraction = extract_python(repo)
    assert targets(extraction, "test:tests.test_core") == {
        "module:app.util",
        "package:app",
        "module:app.core",
    }
    assert targets(extraction, "test:tests.core_test") == set()


def test_tests_edge_provenance(repo):
    edge = next(
        e
        for e in extract_python(repo).document["edges"]
        if e["type"] == "tests" and e["target"] == "function:app.core.run"
    )
    assert edge["provenance"] == {
        "method": "parser",
        "extractor": "python-ast@0.1",
        "confidence": 1.0,
        "source": "tests/test_core.py",
        "lines": [19, 19],
    }


def test_no_tests_edges_to_test_code_or_externals(repo):
    for source, target in relation_pairs(extract_python(repo)):
        assert source.startswith("test:")
        assert target.split(":")[0] in {"module", "package", "class", "function"}
        assert not target.startswith(("function:tests.", "module:tests."))


def test_repo_without_tests(tmp_path):
    write(tmp_path, {"a.py": "def f():\n    pass\n"})
    extraction = extract_python(tmp_path)
    assert not any(n["type"] == "Test" for n in extraction.document["nodes"])
    assert relation_pairs(extraction) == set()


def test_unparsable_test_file_keeps_its_test_node(tmp_path):
    write(tmp_path, {"test_bad.py": "def test_x(:\n"})
    extraction = extract_python(tmp_path)
    assert nodes(extraction)["test:test_bad"]["type"] == "Test"
    assert [s.path for s in extraction.skipped] == ["test_bad.py"]
    assert relation_pairs(extraction) == set()


def test_reexport_cycle_does_not_hang(tmp_path):
    write(
        tmp_path,
        {
            "p/__init__.py": "from p.q import x\n",
            "p/q.py": "from p import x\n",
            "test_p.py": "from p import x\n\n\ndef test_x():\n    x()\n",
        },
    )
    assert ("test:test_p.test_x", "package:p") in relation_pairs(
        extract_python(tmp_path)
    )


def test_loose_test_next_to_its_module(tmp_path):
    write(
        tmp_path,
        {
            "scripts/size.py": "def main():\n    pass\n",
            "scripts/test_size.py": "import size\n\n\ndef test_main():\n"
            "    size.main()\n",
        },
    )
    assert relation_pairs(extract_python(tmp_path)) >= {
        ("test:scripts.test_size", "module:scripts.size"),
        ("test:scripts.test_size.test_main", "function:scripts.size.main"),
    }


# --- references ----------------------------------------------------------------


def parse(code):
    return ast.parse(textwrap.dedent(code))


def test_bindings():
    tree = parse(
        """\
        import a.b
        import c.d as e
        from f import g, h as i
        from . import j
        from ..k import m
        from n import *
        import a.z  # `a` is already bound
        def fn():
            from late import thing
        """
    )
    assert bindings(tree, ["pkg", "sub"]) == {
        "a": "a",
        "e": "c.d",
        "g": "f.g",
        "i": "f.h",
        "j": "pkg.sub.j",
        "m": "pkg.k.m",
        "thing": "late.thing",
    }
    # Beyond the top-level package: ignored
    assert bindings(parse("from .. import x\n"), ["pkg"]) == {}


def test_references():
    tree = parse(
        """\
        def test_x(tmp_path):
            obj = mod.Cls(arg=helper())
            obj.run()
            mod.Cls().stop()
            unknown.thing(mod.f)
            self.assertEqual(mod.g(), 1)
            mod.CONSTANT = 2
            local = 3
            print(local)
        """
    )
    refs = references(tree.body[0], {"mod": "pkg.mod", "helper": "pkg.h"})
    assert refs == [
        ("pkg.h", 2),
        ("pkg.mod.Cls", 2),
        ("pkg.mod.Cls.run", 3),
        ("pkg.mod.Cls.stop", 4),
        ("pkg.mod.f", 5),
        ("pkg.mod.g", 6),
        ("pkg.mod.CONSTANT", 7),
    ]


# --- untested ------------------------------------------------------------------


def test_untested_lists_code_without_incoming_tests(repo, tmp_path):
    kg_dir = tmp_path / ".kg"
    store.init_store(kg_dir)
    assert main(["extract", str(repo), "--kg-dir", str(kg_dir)]) == EXIT_OK
    graph = store.load_graph(kg_dir)
    # tests/helpers.py is not a test file (pytest convention), so it counts
    assert untested(graph) == [
        "function:app.core.untouched",
        "function:tests.helpers.test_like_name",
    ]
    assert "function:app.core.Engine._reset" in untested(graph, include_private=True)
    assert untested(graph, types=["Module", "Package"]) == ["module:tests.helpers"]


def test_untested_on_empty_graph():
    assert (
        untested(store.document_to_graph({"version": "1", "nodes": [], "edges": []}))
        == []
    )


def test_cli_extract_json_counts_relation_pairs(repo, tmp_path, capsys):
    kg_dir = tmp_path / ".kg"
    store.init_store(kg_dir)
    assert main(["extract", str(repo), "--kg-dir", str(kg_dir), "--json"]) == EXIT_OK
    added = json.loads(capsys.readouterr().out)["result"]["edges"]["added"]
    assert "test:tests.test_core.test_start -[tests]-> class:app.core.Engine" in added
