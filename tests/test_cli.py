import json
import subprocess
import sys
from pathlib import Path

import pytest

from kg import __version__
from kg.cli import (
    DEFAULT_KG_DIR,
    EXIT_INTERNAL,
    EXIT_OK,
    EXIT_USAGE,
    Result,
    build_parser,
    main,
)

COMMANDS = ["init", "extract", "add", "validate", "render"]


def test_help_lists_mvp_commands(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == EXIT_OK
    out = capsys.readouterr().out
    for command in COMMANDS:
        assert command in out
    assert "--json" in out
    assert "--kg-dir" in out


def test_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == EXIT_OK
    assert __version__ in capsys.readouterr().out


@pytest.mark.parametrize(
    "argv",
    [
        ["--json", "--kg-dir", "x", "validate", "a.json"],
        ["validate", "a.json", "--json", "--kg-dir", "x"],
    ],
)
def test_global_options_before_or_after_command(argv):
    args = build_parser().parse_args(argv)
    assert args.json is True
    assert args.kg_dir == Path("x")


def test_global_option_before_command_is_not_overridden():
    args = build_parser().parse_args(["--kg-dir", "x", "init"])
    assert args.kg_dir == Path("x")


def test_global_option_defaults(monkeypatch, capsys):
    seen = {}

    def handler(args):
        seen.update(json=args.json, kg_dir=args.kg_dir)
        return Result("hecho")

    monkeypatch.setattr("kg.cli._not_implemented", lambda issue: handler)
    assert main(["render", "--html"]) == EXIT_OK
    assert seen == {"json": False, "kg_dir": Path(DEFAULT_KG_DIR)}
    assert capsys.readouterr().out.strip() == "hecho"


def test_success_json_output(monkeypatch, capsys):
    monkeypatch.setattr(
        "kg.cli._not_implemented", lambda issue: lambda args: Result("x", {"n": 1})
    )
    assert main(["render", "--html", "--json"]) == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"ok": True, "command": "render", "result": {"n": 1}}


@pytest.mark.parametrize(
    "argv",
    [
        ["render", "--html"],
        ["render", "--html", "-o", "x.html"],
    ],
)
def test_stub_commands_report_not_implemented(argv, capsys):
    assert main(argv) == EXIT_INTERNAL
    err = capsys.readouterr().err
    assert "not implemented yet" in err
    assert "#" in err


def test_stub_command_json_error(capsys):
    assert main(["render", "--html", "--json"]) == EXIT_INTERNAL
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["command"] == "render"
    assert payload["error"]["code"] == EXIT_INTERNAL
    assert payload["error"]["details"] == {"issue": 10}


@pytest.mark.parametrize(
    "argv",
    [[], ["desconocido"], ["validate"], ["render"], ["render", "--png", "--svg"]],
)
def test_usage_errors_exit_2(argv, capsys):
    assert main(argv) == EXIT_USAGE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("error: ")


def test_usage_error_json(capsys):
    assert main(["--json", "desconocido"]) == EXIT_USAGE
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["command"] is None
    assert payload["error"]["code"] == EXIT_USAGE
    assert payload["error"]["type"] == "UsageError"


def test_unexpected_exception_is_internal_error(monkeypatch, capsys):
    def boom(args):
        raise RuntimeError("unexpected failure")

    monkeypatch.setattr("kg.cli._not_implemented", lambda issue: boom)
    assert main(["render", "--html", "--json"]) == EXIT_INTERNAL
    payload = json.loads(capsys.readouterr().out)
    assert "unexpected failure" in payload["error"]["message"]
    assert payload["error"]["details"] == {"exception": "RuntimeError"}


def test_python_dash_m_entrypoint():
    proc = subprocess.run(
        [sys.executable, "-m", "kg", "--version"],
        capture_output=True,
        text=True,
        cwd=Path(__file__).parents[1],
        env={"PYTHONPATH": "src"},
    )
    assert proc.returncode == EXIT_OK
    assert __version__ in proc.stdout
