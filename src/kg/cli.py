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
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, NoReturn

from kg import (
    __version__,
    agents,
    analysis,
    edit,
    extract,
    merge,
    render,
    store,
    update,
)
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
    result = _store_call(update.update_store, args.kg_dir, extraction, args.dry_run)
    if result.merge is None:  # a bug in the extractor, not the user's fault
        raise KgError(
            "the extractor produced an invalid document; the store was not modified",
            result.validation.to_dict(),
        )

    skipped = extraction.skipped
    n_files = len(extraction.files)
    files = f"{n_files} {'file' if n_files == 1 else 'files'}"
    if not result.changed:
        head = f"no changes: {files} from {root} already in {result.graph_path}"
    elif args.dry_run:
        head = (
            f"dry run, {result.graph_path} was not modified; "
            f"{files} from {root} would change:"
        )
    else:
        head = f"extracted {files} from {root} into {result.graph_path}"
    lines = [head, result.merge.to_text(max_conflicts=MAX_CONFLICTS_SHOWN)]
    if removed := result.removed.to_text():
        lines.append(removed)
    if skipped:
        lines.append(f"  skipped {len(skipped)}:")
        lines += [f"    {s.to_text()}" for s in skipped]
    data: dict[str, Any] = {
        "path": str(root),
        "graph": str(result.graph_path),
        "files": n_files,
        "skipped": [asdict(s) for s in skipped],
        **result.merge.to_dict(),
        "changed": result.changed,
        "removed": result.removed.to_dict(),
        "dry_run": args.dry_run,
        "warnings": [asdict(i) for i in result.validation.warnings],
    }
    return Result("\n".join(lines), data)


def _status(args: argparse.Namespace) -> Result:
    root: Path = args.path
    if not root.is_dir():
        raise UsageError(f"not a directory: {root}")
    graph = _store_call(store.load_graph, args.kg_dir)
    try:
        state = update.staleness(graph, root)
    except update.RepoMismatchError as e:
        raise UsageError(str(e)) from e

    counts = _method_counts(graph)
    summary = ", ".join(f"{n} {method}" for method, n in counts.items())
    lines = [
        f"{store.graph_path(args.kg_dir)}: {graph.number_of_nodes()} nodes, "
        f"{graph.number_of_edges()} edges" + (f" ({summary})" if summary else "")
    ]
    if not state.stale:
        lines.append(f"up to date with {root}")
    else:
        lines.append(f"stale: {root} changed since the last `kg extract`")
        for name in ("modified", "added", "deleted", "unknown"):
            paths = getattr(state, name)
            if paths:
                lines.append(f"  {name} ({len(paths)}): {', '.join(paths)}")
        if state.unknown:
            lines.append(
                "  (unknown: no digest recorded; the file could not be read, or it "
                "was extracted before kg recorded digests)"
            )
        lines.append(f"run `kg extract {root}` to update the graph")
    data = {
        "path": str(root),
        "graph": str(store.graph_path(args.kg_dir)),
        "nodes": graph.number_of_nodes(),
        "edges": graph.number_of_edges(),
        "methods": counts,
        **state.to_dict(),
    }
    return Result("\n".join(lines), data)


def _method_counts(graph: Any) -> dict[str, int]:
    """Nodes by provenance method (`parser`, `llm`, `manual`)."""
    counts: dict[str, int] = {}
    for _, data in graph.nodes(data=True):
        method = (data.get("provenance") or {}).get("method", "unknown")
        counts[method] = counts.get(method, 0) + 1
    return dict(sorted(counts.items()))


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


# --- Queries (RF-40–RF-43) ------------------------------------------------------


def _query_node(args: argparse.Namespace) -> Result:
    graph = _store_call(store.load_graph, args.kg_dir)
    fields = _query_call(analysis.node_fields, graph, args.id)
    hits = analysis.neighbors(
        graph,
        args.id,
        direction=args.direction,
        relations=args.relation,
        types=args.type,
        depth=args.depth,
    )
    lines = [f"{args.id} ({fields.get('type')})"]
    for name in ("label", "description"):
        if fields.get(name):
            lines.append(f"  {name}: {fields[name]}")
    for key, value in sorted((fields.get("attrs") or {}).items()):
        lines.append(f"  attrs.{key}: {json.dumps(value, ensure_ascii=False)}")
    if prov := fields.get("provenance"):
        lines.append(f"  provenance: {_provenance_text(prov)}")
    if hits:
        lines.append(f"{_plural(len(hits), 'neighbor')}:")
        lines += [_neighbor_text(args.id, hit) for hit in hits]
    else:
        lines.append("no neighbors in the graph with these options")
    limits = _limits(args, graph)
    if args.brief:
        return _brief_node(args.id, fields, hits, limits)
    lines += _limits_text(limits)
    data = {
        "node": fields,
        "neighbors": [h.to_dict() for h in hits],
        "limits": limits,
    }
    return Result("\n".join(lines), data)


def _query_find(args: argparse.Namespace) -> Result:
    if not (args.text or args.type or args.attr):
        raise UsageError("kg query find: give TEXT, --type or --attr")
    graph = _store_call(store.load_graph, args.kg_dir)
    ids = analysis.find(graph, args.text, args.type, dict(args.attr))
    lines = [_node_text(graph, node_id) for node_id in ids]
    if not ids:
        lines = ["no node in the graph matches"]
    if args.brief:
        shown = ids[:BRIEF_LIMIT]
        lines = [f"{i} ({graph.nodes[i].get('type')})" for i in shown]
        lines = lines or ["no node in the graph matches"]
        if len(ids) > len(shown):
            lines.append(f"… {len(ids) - len(shown)} more; narrow with --type")
        return Result("\n".join(lines), {"nodes": shown, "total": len(ids)})
    nodes = [_node_summary(graph, node_id) for node_id in ids]
    return Result("\n".join(lines), {"nodes": nodes})


def _query_path(args: argparse.Namespace) -> Result:
    graph = _store_call(store.load_graph, args.kg_dir)
    found = _query_call(
        analysis.shortest_path, graph, args.source, args.target, args.relation
    )
    limits = _limits(args, graph)
    if found is None:
        lines = [f"no path between {args.source} and {args.target} in the graph"]
        data: dict[str, Any] = {"found": False, "direction": None, "path": []}
    else:
        direction, steps = found
        how = {
            "forward": "",
            "backward": " (edges point back)",
            "mixed": " (edges in both directions)",
        }
        lines = [f"path of {_plural(len(steps), 'edge')}{how[direction]}:"]
        lines += [f"  {step.label}  [{_step_source(step)}]" for step in steps]
        data = {
            "found": True,
            "direction": direction,
            "path": [s.to_dict() for s in steps],
        }
    if args.brief:
        data["path"] = [step.label for step in found[1]] if found else []
    lines += _limits_text(limits)
    data |= {"source": args.source, "target": args.target, "limits": limits}
    return Result("\n".join(lines), data)


# What `untested` and `tested` count as tested (see `analysis.coverage`)
TESTED_CRITERION = (
    "tested: a `tests` edge points to it, because a test module imports it or "
    "a test function refers to it; a static heuristic that misses indirect use"
)


def _query_untested(args: argparse.Namespace) -> Result:
    graph = _store_call(store.load_graph, args.kg_dir)
    types = args.type or analysis.CODE_TYPES
    ids = analysis.untested(graph, types, args.include_private)
    return _id_list(
        args,
        graph,
        ids,
        f"{_plural(len(ids), 'element')} with no `tests` edge:",
        "every element of these types has a `tests` edge",
        ["tests"],
        criterion=TESTED_CRITERION,
    )


def _query_tested(args: argparse.Namespace) -> Result:
    graph = _store_call(store.load_graph, args.kg_dir)
    types = args.type or analysis.CODE_TYPES
    found = analysis.tested(graph, types, args.include_private)
    limits = _limits(args, graph, ["tests"])
    if found:
        lines = [
            f"{_plural(len(found), 'element')} with a `tests` edge:",
            f"  ({TESTED_CRITERION})",
        ]
        for node_id, tests in found.items():
            lines.append(f"  {_node_text(graph, node_id)}")
            lines += [f"      <-[tests]- {t}" for t in tests]
    else:
        lines = ["no element of these types has a `tests` edge"]
    lines += _limits_text(limits)
    nodes = [{**_node_summary(graph, i), "tests": t} for i, t in found.items()]
    data = {"nodes": nodes, "criterion": TESTED_CRITERION, "limits": limits}
    return Result("\n".join(lines), data)


def _query_undocumented(args: argparse.Namespace) -> Result:
    graph = _store_call(store.load_graph, args.kg_dir)
    types = args.type or analysis.DOCUMENTABLE_TYPES
    ids = analysis.undocumented(graph, types, args.include_private)
    return _id_list(
        args,
        graph,
        ids,
        f"{_plural(len(ids), 'element')} that no document points to:",
        "every element of these types has a `documents` edge",
        ["documents"],
    )


def _id_list(
    args: argparse.Namespace,
    graph: Any,
    ids: list[str],
    head: str,
    empty: str,
    relations: list[str],
    criterion: str | None = None,
) -> Result:
    limits = _limits(args, graph, relations)
    lines = [head, *(f"  {_node_text(graph, i)}" for i in ids)] if ids else [empty]
    if criterion:
        lines.insert(1, f"  ({criterion})")
    lines += _limits_text(limits)
    data: dict[str, Any] = {"nodes": [_node_summary(graph, i) for i in ids]}
    if criterion:
        data["criterion"] = criterion
    return Result("\n".join(lines), data | {"limits": limits})


def _impact(args: argparse.Namespace) -> Result:
    graph = _store_call(store.load_graph, args.kg_dir)
    relations = args.relation or analysis.IMPACT_RELATIONS
    reached = _query_call(
        analysis.impact,
        graph,
        args.id,
        args.depth,
        relations,
        not args.no_containment,
    )
    hits = [h for h in reached if not args.type or h.type in args.type]
    omitted = dict(sorted(Counter(h.type for h in reached if h not in hits).items()))
    limits = _limits(args, graph, relations)
    if args.brief:
        return _brief_impact(args, relations, hits, omitted, limits)
    if hits:
        lines = [
            f"a change in {args.id} may affect {_plural(len(hits), 'element')} "
            "(possible effects, not certain ones):"
        ]
        for hit in hits:
            kind = "direct" if hit.depth == 1 else f"depth {hit.depth}"
            lines.append(f"  {_node_text(graph, hit.id)}  [{kind}]")
            lines += [
                f"      {step.label}  [{_step_source(step)}]" for step in hit.path
            ]
    else:
        lines = [
            f"no relation found in the graph through which {args.id} affects others"
        ]
    if omitted:
        counts = ", ".join(f"{t} {n}" for t, n in omitted.items())
        lines.append(f"left out by --type: {counts}")
    lines += _limits_text(limits)
    data = {
        "id": args.id,
        "depth": args.depth,
        "relations": sorted(relations),
        "containment": not args.no_containment,
        "types": args.type,
        "results": [h.to_dict() for h in hits],
        "omitted": omitted,
        "limits": limits,
    }
    return Result("\n".join(lines), data)


# --- Brief output (--brief) --------------------------------------------------------

# At most this many neighbors, matches or results in a brief answer
BRIEF_LIMIT = 30


def _brief_provenance(provenance: dict[str, Any]) -> dict[str, Any]:
    """Where a node comes from, once: method, file and lines; confidence if < 1."""
    keep = {k: provenance[k] for k in ("method", "source", "lines") if k in provenance}
    if provenance.get("confidence", 1) < 1:
        keep["confidence"] = provenance["confidence"]
    return keep


def _brief_hit(origin: str, hit: analysis.Hit) -> str:
    """One line per neighbor or result: the edge that reaches it, its provenance
    only when it is not the parser's."""
    step = hit.path[-1]
    if hit.depth == 1 and origin in (step.source, step.target):
        arrow = f"-[{step.type}]->" if step.source == origin else f"<-[{step.type}]-"
        text = f"{arrow} {hit.id}"
    else:
        text = f"{hit.id} (depth {hit.depth}, via {step.label})"
    if step.method and step.method != "parser":
        text += f" [{_step_source(step)}]"
    return text


def _brief_list(
    origin: str, hits: list[analysis.Hit]
) -> tuple[list[str], dict[str, int]]:
    """The first `BRIEF_LIMIT` hits as lines, and the rest counted by type."""
    shown = [_brief_hit(origin, h) for h in hits[:BRIEF_LIMIT]]
    more = Counter(h.type for h in hits[BRIEF_LIMIT:])
    return shown, dict(sorted(more.items()))


def _more_text(more: dict[str, int]) -> list[str]:
    if not more:
        return []
    return ["… more: " + ", ".join(f"{t} {n}" for t, n in more.items())]


def _brief_node(
    node_id: str,
    fields: dict[str, Any],
    hits: list[analysis.Hit],
    limits: list[dict[str, Any]],
) -> Result:
    card = {"id": node_id} | {
        k: v
        for k, v in fields.items()
        if k in ("type", "label", "description", "attrs")
    }
    if prov := fields.get("provenance"):
        card["provenance"] = _brief_provenance(prov)
    neighbors, more = _brief_list(node_id, hits)
    lines = [f"{node_id} ({fields.get('type')})"]
    if fields.get("description"):
        lines.append(f"  {fields['description']}")
    for key, value in sorted((fields.get("attrs") or {}).items()):
        lines.append(f"  {key}: {json.dumps(value, ensure_ascii=False)}")
    if prov:
        lines.append(f"  at: {_location(prov)}")
    lines += [f"  {n}" for n in neighbors] + _more_text(more) + _limits_text(limits)
    data = {"node": card, "neighbors": neighbors, "more": more, "limits": limits}
    return Result("\n".join(lines), data)


def _brief_impact(
    args: argparse.Namespace,
    relations: Sequence[str],
    hits: list[analysis.Hit],
    omitted: dict[str, int],
    limits: list[dict[str, Any]],
) -> Result:
    results, more = _brief_list(args.id, hits)
    lines = [
        f"a change in {args.id} may affect {_plural(len(hits), 'element')} "
        "(possible effects, not certain ones):",
        *(f"  {r}" for r in results),
        *_more_text(more),
    ]
    if omitted:
        counts = ", ".join(f"{t} {n}" for t, n in omitted.items())
        lines.append(f"left out by --type: {counts}")
    lines += _limits_text(limits)
    data = {
        "id": args.id,
        "relations": sorted(relations),
        "types": args.type,
        "results": results,
        "total": len(hits),
        "more": more,
        "omitted": omitted,
        "limits": limits,
    }
    return Result("\n".join(lines), data)


def _location(provenance: dict[str, Any]) -> str:
    """`path:first-last` (or the path alone) of a provenance."""
    lines = provenance.get("lines")
    source = provenance.get("source", "")
    return f"{source}:{lines[0]}-{lines[1]}" if lines else str(source)


def _query_call(func: Callable[..., Any], *args: Any) -> Any:
    """Run an analysis query, mapping an unknown ID to a usage error."""
    try:
        return func(*args)
    except analysis.QueryError as e:
        message = e.message + (
            f"\n  suggestion: {e.suggestion}" if e.suggestion else ""
        )
        raise UsageError(message, {"suggestion": e.suggestion}) from e


def _limits(
    args: argparse.Namespace, graph: Any, relations: Sequence[str] = ()
) -> list[dict[str, Any]]:
    """What the answer may miss (RF-43): a stale graph, unread files, and
    relation types the graph has no edges of."""
    limits: list[dict[str, Any]] = []
    root = args.kg_dir.resolve().parent  # the store lives in its repo (RF-70)
    try:
        state = update.staleness(graph, root)
    except update.RepoMismatchError:
        limits.append(
            {
                "code": "freshness_unknown",
                "message": "could not check whether the graph is up to date: the "
                "store is not inside its repo; run `kg status <repo>`",
            }
        )
    else:
        changed = state.modified + state.added + state.deleted
        if changed:
            limits.append(
                {
                    "code": "stale_graph",
                    "message": f"the code changed since the last `kg extract` "
                    f"({_plural(len(changed), 'file')}; see `kg status`): "
                    "the graph may not match it",
                    "files": changed,
                }
            )
    unread = analysis.unread_files(graph)
    if unread:
        limits.append(
            {
                "code": "unread_files",
                "message": f"{_plural(len(unread), 'file')} could not be fully "
                "extracted; their contents may be missing",
                "files": unread,
            }
        )
    missing = analysis.missing_relations(graph, relations)
    if missing:
        names = ", ".join(f"`{r}`" for r in missing)
        extra = (
            " (`kg extract` does not produce `calls`, RF-13)"
            if "calls" in missing
            else ""
        )
        limits.append(
            {
                "code": "missing_relations",
                "message": f"the graph has no {names} edges; whatever depends "
                f"on them is not in this answer{extra}",
                "relations": missing,
            }
        )
    return limits


def _limits_text(limits: list[dict[str, Any]]) -> list[str]:
    return [f"note: {limit['message']}" for limit in limits]


def _node_summary(graph: Any, node_id: str) -> dict[str, Any]:
    data = graph.nodes[node_id]
    return {"id": node_id, "type": data.get("type"), "label": data.get("label")}


def _node_text(graph: Any, node_id: str) -> str:
    data = graph.nodes[node_id]
    return f"{node_id} ({data.get('type')})"


def _neighbor_text(origin: str, hit: analysis.Hit) -> str:
    if hit.depth == 1:
        step = hit.path[0]
        arrow = f"-[{step.type}]->" if step.source == origin else f"<-[{step.type}]-"
        return f"  {arrow} {hit.id} ({hit.type})  [{_step_source(step)}]"
    via = "; ".join(step.label for step in hit.path)
    return f"  depth {hit.depth}: {hit.id} ({hit.type})  via {via}"


def _step_source(step: analysis.Step) -> str:
    if step.confidence is None:
        return str(step.method)
    return f"{step.method}, {step.confidence:g}"


def _provenance_text(provenance: dict[str, Any]) -> str:
    text = f"{provenance.get('method')} ({provenance.get('extractor')}"
    if "confidence" in provenance:
        text += f", confidence {provenance['confidence']:g}"
    text += ")"
    if source := provenance.get("source"):
        lines = provenance.get("lines")
        text += f" from {source}" + (f":{lines[0]}-{lines[1]}" if lines else "")
    return text


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


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
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would be added, merged and removed without saving",
    )

    p = add("status", "whether the graph is up to date with the repo", _status)
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

    help_ = "look up nodes, neighbors and paths in the graph"
    p = sub.add_parser("query", help=help_, description=help_, parents=[common])
    queries = p.add_subparsers(dest="query", metavar="<query>", required=True)

    def query(name: str, help_: str, handler: Handler) -> argparse.ArgumentParser:
        q = queries.add_parser(name, help=help_, description=help_, parents=[common])
        q.set_defaults(handler=handler)
        return q

    q = query("node", "a node, its attributes and its neighbors", _query_node)
    q.add_argument("id", metavar="ID", help="ID of the node")
    _brief_option(q)
    q.add_argument(
        "--direction",
        choices=("out", "in", "both"),
        default="both",
        help="edges to follow (default: both)",
    )
    _relation_option(q, "relation types to follow (default: all)")
    _type_option(q, "entity types to list (others are still walked through)")
    q.add_argument(
        "--depth",
        type=_positive_int,
        default=1,
        metavar="N",
        help="how many edges away (default: 1)",
    )

    q = query(
        "find", "find nodes by name, ID, description, type or attribute", _query_find
    )
    _brief_option(q)
    q.add_argument("text", nargs="?", help="text in the label, ID or description")
    _type_option(q, "entity types to return")
    q.add_argument(
        "--attr",
        type=_key_value,
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="attrs.KEY equals VALUE (JSON if it parses, else text; repeatable)",
    )

    q = query("path", "the shortest chain of edges between two nodes", _query_path)
    _brief_option(q)
    q.add_argument("source", metavar="FROM", help="ID of the first node")
    q.add_argument("target", metavar="TO", help="ID of the second node")
    _relation_option(q, "relation types the path may use (default: all)")

    q = query("untested", "code with no `tests` edge (CU-02)", _query_untested)
    _type_option(q, f"types to check (default: {','.join(analysis.CODE_TYPES)})")
    q.add_argument(
        "--include-private", action="store_true", help="also `_private` names"
    )

    q = query("tested", "code with a `tests` edge, and its tests", _query_tested)
    _type_option(q, f"types to check (default: {','.join(analysis.CODE_TYPES)})")
    q.add_argument(
        "--include-private", action="store_true", help="also `_private` names"
    )

    q = query(
        "undocumented", "code that no document points to (CU-03)", _query_undocumented
    )
    _type_option(
        q, f"types to check (default: {','.join(analysis.DOCUMENTABLE_TYPES)})"
    )
    q.add_argument(
        "--include-private", action="store_true", help="also `_private` names"
    )

    p = add("impact", "what a change in a node may affect", _impact)
    p.add_argument("id", metavar="ID", help="ID of the node that changes")
    _brief_option(p)
    p.add_argument(
        "--depth",
        type=_positive_int,
        metavar="N",
        help="at most N edges away (default: no limit)",
    )
    _relation_option(
        p,
        "relations that propagate a change, walked backwards "
        f"(default: {','.join(analysis.IMPACT_RELATIONS)})",
    )
    p.add_argument(
        "--no-containment",
        action="store_true",
        help="do not reach the module or class that defines a changed element",
    )
    _type_option(p, "entity types to list (others are still walked through)")

    return parser


def _brief_option(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--brief",
        action="store_true",
        help=f"compact answer: one line per edge, provenance once, at most "
        f"{BRIEF_LIMIT} items",
    )


def _relation_option(p: argparse.ArgumentParser, help_: str) -> None:
    p.add_argument("--relation", type=_type_list, metavar="R1,R2", help=help_)


def _type_option(p: argparse.ArgumentParser, help_: str) -> None:
    p.add_argument("--type", type=_type_list, metavar="T1,T2", help=help_)


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
