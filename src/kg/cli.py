"""Entry point of the `kg` CLI.

Conventions (docs/requirements.md, section 5):
- Global options `--json` and `--kg-dir`, valid before or after the subcommand.
- With `--json` all output is a single JSON object on stdout (RF-22).
- Exit codes: 0 OK, 1 validation, 2 usage, 3 internal error.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, NoReturn

from kg import __version__, agents, edit, extract, merge, render, store
from kg import schema as kg_schema
from kg.schema import validation

EXIT_OK = 0
EXIT_VALIDATION = 1
EXIT_USAGE = 2
EXIT_INTERNAL = 3

DEFAULT_KG_DIR = ".kg"
# Conflicts listed in text output; `--json` has all of them.
MAX_CONFLICTS_SHOWN = 10


class KgError(Exception):
    """Handled error that the CLI turns into a message and an exit code."""

    exit_code = EXIT_INTERNAL

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ValidationError(KgError):
    exit_code = EXIT_VALIDATION


class UsageError(KgError):
    exit_code = EXIT_USAGE


@dataclass
class Result:
    """Result of a subcommand: `message` for humans, `data` for `--json`."""

    message: str
    data: dict[str, Any] = field(default_factory=dict)


Handler = Callable[[argparse.Namespace], Result]


class _Parser(argparse.ArgumentParser):
    """ArgumentParser that raises UsageError instead of printing and exiting."""

    def error(self, message: str) -> NoReturn:
        raise UsageError(f"{self.prog}: {message}")


def _schema(args: argparse.Namespace) -> Result:
    path = kg_schema.schema_path()
    if args.path:
        return Result(str(path), {"path": str(path)})
    data = kg_schema.load_schema()
    text = json.dumps(data, ensure_ascii=False, indent=2)
    return Result(text, {"path": str(path), "schema": data})


def _guide(args: argparse.Namespace) -> Result:
    path = agents.guide_path()
    if args.path:
        return Result(str(path), {"path": str(path)})
    text = agents.skill_text() if args.skill else agents.load_guide()
    return Result(text.rstrip("\n"), {"path": str(path), "guide": text})


def _init(args: argparse.Namespace) -> Result:
    try:
        path = store.init_store(args.kg_dir)
    except store.StoreError as e:
        raise UsageError(e.message, {"path": str(e.path)}) from e
    return Result(
        f"store created at {path} (format v{store.FORMAT_VERSION})",
        {
            "kg_dir": str(args.kg_dir),
            "graph": str(path),
            "version": store.FORMAT_VERSION,
        },
    )


def _add(args: argparse.Namespace) -> Result:
    name = "stdin" if str(args.file) == "-" else str(args.file)
    text = sys.stdin.read() if name == "stdin" else _read(args.file)
    result = _store_call(merge.add_to_store, args.kg_dir, text, args.dry_run)

    report = result.validation
    data: dict[str, Any] = {"file": name, "graph": str(result.graph_path)}
    if result.merge is None:
        raise ValidationError(
            report.to_text(name) + "\nthe store was not modified",
            {**data, **report.to_dict()},
        )
    data |= {
        **result.merge.to_dict(),
        "dry_run": args.dry_run,
        "warnings": [asdict(i) for i in report.warnings],
    }
    if not result.merge.changed:
        head = f"no changes: {name} is already in {result.graph_path}"
    elif args.dry_run:
        head = f"dry run, {result.graph_path} was not modified; {name} would merge:"
    else:
        head = f"{name} merged into {result.graph_path}"
    lines = [head, result.merge.to_text()]
    lines += [issue.to_text() for issue in report.warnings]
    return Result("\n".join(lines), data)


def _extract(args: argparse.Namespace) -> Result:
    root: Path = args.path
    if not root.is_dir():
        raise UsageError(f"not a directory: {root}")
    extraction = extract.extract_repo(root)
    result = _store_call(merge.add_document, args.kg_dir, extraction.document)
    if result.merge is None:  # a bug in the extractor, not the user's fault
        raise KgError(
            "the extractor produced an invalid document; the store was not modified",
            result.validation.to_dict(),
        )

    skipped = extraction.skipped
    n_files = len(extraction.files)
    files = f"{n_files} {'file' if n_files == 1 else 'files'}"
    head = (
        f"extracted {files} from {root} into {result.graph_path}"
        if result.merge.changed
        else f"no changes: {files} from {root} already in {result.graph_path}"
    )
    lines = [head, result.merge.to_text(max_conflicts=MAX_CONFLICTS_SHOWN)]
    if skipped:
        lines.append(f"  skipped {len(skipped)}:")
        lines += [f"    {s.to_text()}" for s in skipped]
    data: dict[str, Any] = {
        "path": str(root),
        "graph": str(result.graph_path),
        "files": n_files,
        "skipped": [asdict(s) for s in skipped],
        **result.merge.to_dict(),
        "warnings": [asdict(i) for i in result.validation.warnings],
    }
    return Result("\n".join(lines), data)


def _store_call(func: Callable[..., Any], *args: Any) -> Any:
    """Call a store operation, mapping `StoreError`s to CLI errors."""
    try:
        return func(*args)
    except store.StoreCorruptError as e:
        raise ValidationError(
            e.message, {"path": str(e.path), **e.report.to_dict()}
        ) from e
    except store.StoreError as e:
        raise UsageError(e.message, {"path": str(e.path)}) from e


def _remove(args: argparse.Namespace) -> Result:
    if not args.ids and not args.edges:
        raise UsageError("kg remove: give node IDs and/or --edge SOURCE TYPE TARGET")
    graph = _store_call(store.load_graph, args.kg_dir)
    edges = [tuple(e) for e in args.edges]
    try:
        result, report = edit.remove(graph, args.ids, edges)
    except edit.EditError as e:
        raise _edit_error(e) from e
    return _save_edit(args, result, report.to_text(), report.to_dict(), "remove")


def _edit(args: argparse.Namespace) -> Result:
    texts = {
        name: value
        for name, value in (("label", args.label), ("description", args.description))
        if value is not None
    }
    graph = _store_call(store.load_graph, args.kg_dir)
    try:
        result, report = edit.edit_node(
            graph,
            args.id,
            new_id=args.new_id,
            type_=args.type,
            texts=texts,
            set_attrs=dict(args.set),
            unset_attrs=args.unset,
        )
    except edit.EditError as e:
        raise _edit_error(e) from e
    changed = report.changed
    return _save_edit(
        args, result if changed else None, report.to_text(), report.to_dict(), "edit"
    )


def _save_edit(
    args: argparse.Namespace,
    graph: Any,
    summary: str,
    data: dict[str, Any],
    verb: str,
) -> Result:
    """Save unless `--dry-run` (or nothing changed) and build the result."""
    path = store.graph_path(args.kg_dir)
    if graph is None:
        head = f"no changes in {path}"
    elif args.dry_run:
        head = f"dry run, {path} was not modified; it would {verb}:"
    else:
        _store_call(store.save_graph, graph, args.kg_dir)
        head = f"{path} updated:"
    saved = graph is not None and not args.dry_run
    return Result(
        f"{head}\n{summary}",
        {"graph": str(path), "dry_run": args.dry_run, "saved": saved, **data},
    )


def _edit_error(e: edit.EditError) -> UsageError:
    message = e.message + (f"\n  suggestion: {e.suggestion}" if e.suggestion else "")
    return UsageError(message, {"suggestion": e.suggestion})


def _render(args: argparse.Namespace) -> Result:
    output: Path = args.output or Path(f"kg-graph.{args.format}")
    if not output.parent.is_dir():
        raise UsageError(f"directory {output.parent} does not exist")
    graph = _store_call(store.load_graph, args.kg_dir)
    if args.format == "html":
        return _render_html(args, graph, output)
    try:
        selection = render.render_static(
            graph,
            output,
            args.format,
            types=args.types,
            max_nodes=args.max_nodes,
            dpi=args.dpi,
            title=_repo_label(graph),
        )
    except render.RenderError as e:
        raise UsageError(str(e)) from e
    except OSError as e:
        raise UsageError(f"cannot write {output}: {e.strerror}") from e

    shown = selection.graph
    nodes, edges = shown.number_of_nodes(), shown.number_of_edges()
    lines = [f"rendered {nodes} nodes and {edges} edges to {output}"]
    if selection.hidden:
        hidden = ", ".join(f"{n} {t}" for t, n in selection.hidden.items())
        lines.append(f"  hidden: {hidden}")
        if args.types is None:
            lines.append(
                f"  (more than {args.max_nodes} nodes; choose them with --types "
                "or raise --max-nodes)"
            )
    data = {
        "path": str(output),
        "format": args.format,
        "nodes": nodes,
        "edges": edges,
        "hidden": selection.hidden,
    }
    return Result("\n".join(lines), data)


def _render_html(args: argparse.Namespace, graph: Any, output: Path) -> Result:
    if args.types is not None:
        graph = graph.subgraph(
            n for n, d in graph.nodes(data=True) if d.get("type") in args.types
        )
    try:
        result = render.render_html(graph, output, title=_repo_label(graph))
    except OSError as e:
        raise UsageError(f"cannot write {output}: {e.strerror}") from e
    lines = [f"rendered {result.nodes} nodes and {result.edges} edges to {output}"]
    if result.hidden:
        lines.append(
            f"  {', '.join(result.hidden)} start hidden (more than "
            f"{render.INITIAL_NODES} nodes); tick them under Entity types"
        )
    data = {
        "path": str(output),
        "format": "html",
        "nodes": result.nodes,
        "edges": result.edges,
        "hidden": result.hidden,
    }
    return Result("\n".join(lines), data)


def _repo_label(graph: Any) -> str | None:
    """Title of the image: the name of the (first) Repo node."""
    repos = sorted(n for n, d in graph.nodes(data=True) if d.get("type") == "Repo")
    if not repos:
        return None
    return graph.nodes[repos[0]].get("label") or repos[0].split(":", 1)[-1]


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as e:
        raise UsageError(f"file not found: {path}") from e
    except UnicodeDecodeError as e:
        raise ValidationError(f"{path} is not UTF-8 (byte {e.start})") from e
    except OSError as e:
        raise UsageError(f"cannot read {path}: {e.strerror}") from e


def _validate(args: argparse.Namespace) -> Result:
    # Does not touch the store: it only reads the file (RF-03).
    name = "stdin" if str(args.file) == "-" else str(args.file)
    try:
        if name == "stdin":
            report = validation.validate_text(sys.stdin.read())
        else:
            report = validation.validate_path(args.file)
    except FileNotFoundError as e:
        raise UsageError(f"file not found: {args.file}") from e
    except OSError as e:
        raise UsageError(f"cannot read {args.file}: {e.strerror}") from e

    data = {"file": name, **report.to_dict()}
    if not report.ok:
        raise ValidationError(report.to_text(name), data)
    return Result(report.to_text(name), data)


def _global_options() -> argparse.ArgumentParser:
    # default=SUPPRESS so a value given before the subcommand is not overwritten
    # by the subparser's default; defaults are applied in main().
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--json",
        action="store_true",
        default=argparse.SUPPRESS,
        help="machine-readable JSON output",
    )
    common.add_argument(
        "--kg-dir",
        type=Path,
        default=argparse.SUPPRESS,
        metavar="PATH",
        help=f"path of the graph store (default: {DEFAULT_KG_DIR})",
    )
    return common


def build_parser() -> argparse.ArgumentParser:
    common = _global_options()
    parser = _Parser(
        prog="kg",
        description="Turn a codebase's knowledge into a queryable knowledge graph.",
        parents=[common],
    )
    parser.add_argument("--version", action="version", version=f"kg {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<command>", required=True)

    def add(name: str, help_: str, handler: Handler) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help_, description=help_, parents=[common])
        p.set_defaults(handler=handler)
        return p

    add("init", "create the .kg/ store in the repo", _init)

    p = add("extract", "deterministic extraction of a Python repo", _extract)
    p.add_argument("path", nargs="?", type=Path, default=Path("."), help="repo path")

    p = add("add", "add and merge entities and relations", _add)
    p.add_argument(
        "file", type=Path, help="JSON file conforming to the schema (`-` for stdin)"
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="validate against the store and report the merge without saving",
    )

    p = add(
        "remove", "remove nodes (with their edges) or edges from the store", _remove
    )
    p.add_argument("ids", nargs="*", metavar="ID", help="IDs of the nodes to remove")
    p.add_argument(
        "--edge",
        dest="edges",
        nargs=3,
        action="append",
        default=[],
        metavar=("SOURCE", "TYPE", "TARGET"),
        help="an edge to remove (repeatable)",
    )
    p.add_argument("--dry-run", action="store_true", help="show, do not save")

    p = add("edit", "modify a node of the store", _edit)
    p.add_argument("id", metavar="ID", help="ID of the node")
    p.add_argument("--id", dest="new_id", metavar="NEW_ID", help="rename the node")
    p.add_argument("--type", help="change its entity type")
    p.add_argument("--label", help="set the label (empty string: remove it)")
    p.add_argument("--description", help="set the description (empty: remove it)")
    p.add_argument(
        "--set",
        type=_key_value,
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="set attrs.KEY; VALUE is JSON if it parses, else text (repeatable)",
    )
    p.add_argument(
        "--unset", action="append", default=[], metavar="KEY", help="remove attrs.KEY"
    )
    p.add_argument("--dry-run", action="store_true", help="show, do not save")

    p = add("guide", "print the guidelines for agents that enrich the graph", _guide)
    p.add_argument("--path", action="store_true", help="print only the file path")
    p.add_argument(
        "--skill",
        action="store_true",
        help="as an agent skill (SKILL.md with front matter)",
    )

    p = add("schema", "print the JSON Schema of the input format", _schema)
    p.add_argument("--path", action="store_true", help="print only the file path")

    p = add("validate", "validate a JSON file against the schema", _validate)
    p.add_argument("file", type=Path, help="JSON file to validate (`-` for stdin)")

    p = add("render", "render a visualization of the graph", _render)
    fmt = p.add_mutually_exclusive_group(required=True)
    for name in ("png", "svg", "html"):
        fmt.add_argument(
            f"--{name}",
            dest="format",
            action="store_const",
            const=name,
            help=f"{name.upper()} format",
        )
    p.add_argument(
        "-o", "--output", type=Path, help="output file (default: kg-graph.<format>)"
    )
    p.add_argument(
        "--types",
        type=_type_list,
        metavar="T1,T2",
        help="entity types to draw, comma-separated (default: all)",
    )
    p.add_argument(
        "--dpi",
        type=_positive_int,
        default=render.DPI,
        metavar="N",
        help=f"PNG resolution in dots per inch (default: {render.DPI}); "
        "raise it to zoom into the image",
    )
    p.add_argument(
        "--max-nodes",
        type=_positive_int,
        default=render.MAX_NODES,
        metavar="N",
        help="PNG/SVG: hide the most numerous types (Function, Test, File, Class) "
        f"until at most N nodes remain (default: {render.MAX_NODES})",
    )

    return parser


def _key_value(value: str) -> tuple[str, Any]:
    key, sep, raw = value.partition("=")
    if not sep or not key.strip():
        raise argparse.ArgumentTypeError(f"expected KEY=VALUE, got {value!r}")
    return key.strip(), edit.parse_value(raw)


def _type_list(value: str) -> list[str]:
    types = [t.strip() for t in value.split(",") if t.strip()]
    if not types:
        raise argparse.ArgumentTypeError("expected at least one type, e.g. Module")
    return types


def _positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        number = 0
    if number < 1:
        raise argparse.ArgumentTypeError(f"expected a positive integer, got {value!r}")
    return number


def _emit(
    as_json: bool, command: str | None, result: Result | None, error: KgError | None
) -> None:
    if as_json:
        payload: dict[str, Any] = {"ok": error is None, "command": command}
        if error is None:
            payload["result"] = result.data if result else {}
        else:
            payload["error"] = {
                "code": error.exit_code,
                "type": type(error).__name__,
                "message": error.message,
                "details": error.details,
            }
        print(json.dumps(payload, ensure_ascii=False, default=str))
    elif error is not None:
        print(f"error: {error.message}", file=sys.stderr)
    elif result is not None and result.message:
        print(result.message)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return the exit code."""
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        args = build_parser().parse_args(argv)
    except UsageError as e:
        _emit("--json" in argv, None, None, e)
        return e.exit_code

    args.json = getattr(args, "json", False)
    args.kg_dir = getattr(args, "kg_dir", Path(DEFAULT_KG_DIR))

    try:
        result = args.handler(args)
    except KgError as e:
        _emit(args.json, args.command, None, e)
        return e.exit_code
    except Exception as e:  # noqa: BLE001 — the CLI must never end with a traceback
        err = KgError(f"internal error: {e}", {"exception": type(e).__name__})
        _emit(args.json, args.command, None, err)
        return EXIT_INTERNAL

    _emit(args.json, args.command, result, None)
    return EXIT_OK
