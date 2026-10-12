"""Punto de entrada de la CLI `kg`.

Convenciones (docs/requisitos-funcionales.md, sección 5):
- Opciones globales `--json` y `--kg-dir`, válidas antes o después del subcomando.
- Con `--json` toda la salida es un único objeto JSON en stdout (RF-22).
- Códigos de salida: 0 OK, 1 validación, 2 uso, 3 error interno.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NoReturn

from kg import __version__, store
from kg import schema as kg_schema
from kg.schema import validation

EXIT_OK = 0
EXIT_VALIDATION = 1
EXIT_USAGE = 2
EXIT_INTERNAL = 3

DEFAULT_KG_DIR = ".kg"


class KgError(Exception):
    """Error controlado que la CLI convierte en mensaje y código de salida."""

    exit_code = EXIT_INTERNAL

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ValidationError(KgError):
    exit_code = EXIT_VALIDATION


class UsageError(KgError):
    exit_code = EXIT_USAGE


class NotImplementedYetError(KgError):
    """Subcomando previsto en el MVP pero aún sin implementar."""


@dataclass
class Result:
    """Resultado de un subcomando: `message` para humanos, `data` para `--json`."""

    message: str
    data: dict[str, Any] = field(default_factory=dict)


Handler = Callable[[argparse.Namespace], Result]


class _Parser(argparse.ArgumentParser):
    """ArgumentParser que lanza UsageError en vez de imprimir y salir."""

    def error(self, message: str) -> NoReturn:
        raise UsageError(f"{self.prog}: {message}")


def _not_implemented(issue: int) -> Handler:
    def handler(args: argparse.Namespace) -> Result:
        raise NotImplementedYetError(
            f"`kg {args.command}` aún no está implementado (issue #{issue}).",
            {"issue": issue},
        )

    return handler


def _schema(args: argparse.Namespace) -> Result:
    path = kg_schema.schema_path()
    if args.path:
        return Result(str(path), {"path": str(path)})
    data = kg_schema.load_schema()
    text = json.dumps(data, ensure_ascii=False, indent=2)
    return Result(text, {"path": str(path), "schema": data})


def _init(args: argparse.Namespace) -> Result:
    try:
        path = store.init_store(args.kg_dir)
    except store.StoreError as e:
        raise UsageError(e.message, {"path": str(e.path)}) from e
    return Result(
        f"almacén creado en {path} (formato v{store.FORMAT_VERSION})",
        {
            "kg_dir": str(args.kg_dir),
            "graph": str(path),
            "version": store.FORMAT_VERSION,
        },
    )


def _validate(args: argparse.Namespace) -> Result:
    # No toca el almacén: solo lee el archivo (RF-03).
    name = "stdin" if str(args.file) == "-" else str(args.file)
    try:
        if name == "stdin":
            report = validation.validate_text(sys.stdin.read())
        else:
            report = validation.validate_path(args.file)
    except FileNotFoundError as e:
        raise UsageError(f"no existe el archivo: {args.file}") from e
    except OSError as e:
        raise UsageError(f"no se puede leer {args.file}: {e.strerror}") from e

    data = {"file": name, **report.to_dict()}
    if not report.ok:
        raise ValidationError(report.to_text(name), data)
    return Result(report.to_text(name), data)


def _global_options() -> argparse.ArgumentParser:
    # default=SUPPRESS para que el valor dado antes del subcomando no se
    # sobrescriba con el default del subparser; los defaults se aplican en main().
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--json",
        action="store_true",
        default=argparse.SUPPRESS,
        help="salida en JSON legible por máquinas",
    )
    common.add_argument(
        "--kg-dir",
        type=Path,
        default=argparse.SUPPRESS,
        metavar="RUTA",
        help=f"ruta del almacén del grafo (por defecto: {DEFAULT_KG_DIR})",
    )
    return common


def build_parser() -> argparse.ArgumentParser:
    common = _global_options()
    parser = _Parser(
        prog="kg",
        description="Convierte el conocimiento de un proyecto en un grafo consultable.",
        parents=[common],
    )
    parser.add_argument("--version", action="version", version=f"kg {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<comando>", required=True)

    def add(name: str, help_: str, handler: Handler) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help_, description=help_, parents=[common])
        p.set_defaults(handler=handler)
        return p

    add("init", "crea el almacén .kg/ en el repo", _init)

    p = add("extract", "extracción determinista de un repo Python", _not_implemented(6))
    p.add_argument(
        "path", nargs="?", type=Path, default=Path("."), help="ruta del repo"
    )

    p = add("add", "añade y fusiona entidades y relaciones", _not_implemented(5))
    p.add_argument("file", type=Path, help="archivo JSON conforme al esquema")

    p = add("schema", "muestra el JSON Schema del formato de entrada", _schema)
    p.add_argument(
        "--path", action="store_true", help="muestra solo la ruta del archivo"
    )

    p = add("validate", "valida un JSON contra el esquema", _validate)
    p.add_argument("file", type=Path, help="archivo JSON a validar (`-` para stdin)")

    p = add("render", "genera una visualización del grafo", _not_implemented(9))
    fmt = p.add_mutually_exclusive_group(required=True)
    for name in ("png", "svg", "html"):
        fmt.add_argument(
            f"--{name}",
            dest="format",
            action="store_const",
            const=name,
            help=f"formato {name.upper()}",
        )
    p.add_argument("-o", "--output", type=Path, help="archivo de salida")

    return parser


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
    """Ejecuta la CLI y devuelve el código de salida."""
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
    except Exception as e:  # noqa: BLE001 — la CLI nunca debe terminar con traceback
        err = KgError(f"error interno: {e}", {"exception": type(e).__name__})
        _emit(args.json, args.command, None, err)
        return EXIT_INTERNAL

    _emit(args.json, args.command, result, None)
    return EXIT_OK
