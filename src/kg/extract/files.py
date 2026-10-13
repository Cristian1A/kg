"""Discovery of the Python files to extract from a repo.

Inside a git work tree, `git ls-files` decides what is ignored (every
`.gitignore`, `.git/info/exclude` and the global excludes). Without git, the
tree is walked and only the root `.gitignore` is applied, with a simplified
matcher. Virtual environments and tool caches are always skipped.
"""

from __future__ import annotations

import fnmatch
import hashlib
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

# Directories never walked, wherever they are in the tree.
EXCLUDED_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".kg",
        ".mypy_cache",
        ".nox",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "__pycache__",
        "env",
        "node_modules",
        "venv",
    }
)


def python_files(root: Path) -> list[str]:
    """Paths of the `.py` files under `root`, relative, with `/` and sorted."""
    candidates = _git_files(root)
    if candidates is None:
        candidates = _walk(root, _read_gitignore(root))
    return sorted(
        path
        for path in set(candidates)
        if path.endswith(".py")
        and not _in_excluded_dir(root, path)
        and (root / path).is_file()
    )


# Key in `attrs` of `File` and `Config` nodes
DIGEST = "digest"


def file_digest(path: Path) -> str | None:
    """Short content hash of a file (`sha256:` + 16 hex digits), `None` if unreadable.

    Stored as `attrs.digest` on `File` and `Config` nodes so `kg status` can tell
    which files changed since the last extraction (RF-77).
    """
    try:
        data = path.read_bytes()
    except OSError:
        return None
    return f"sha256:{hashlib.sha256(data).hexdigest()[:16]}"


def _git_files(root: Path) -> list[str] | None:
    """Tracked and untracked, not ignored, files; `None` if git cannot tell.

    That includes a `root` that the enclosing repo ignores (e.g. a copy under
    `samples/` without its own `.git`): git would list nothing.
    """
    ignored = _git(root, "check-ignore", "-q", ".")
    if ignored is None or ignored.returncode == 0:
        return None
    proc = _git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    if proc is None or proc.returncode != 0:
        return None
    return [p for p in proc.stdout.decode("utf-8", "surrogateescape").split("\0") if p]


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[bytes] | None:
    try:
        return subprocess.run(
            ["git", *args], cwd=root, capture_output=True, check=False
        )
    except OSError:  # git is not installed
        return None


def _walk(root: Path, ignore: _GitIgnore) -> list[str]:
    files: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = Path(dirpath).relative_to(root).as_posix()
        prefix = "" if rel_dir == "." else f"{rel_dir}/"
        dirnames[:] = [
            d
            for d in dirnames
            if d not in EXCLUDED_DIRS
            and not _is_virtualenv(Path(dirpath) / d)
            and not ignore.match(prefix + d, is_dir=True)
        ]
        files += [
            prefix + f for f in filenames if not ignore.match(prefix + f, is_dir=False)
        ]
    return files


def _in_excluded_dir(root: Path, path: str) -> bool:
    parts = path.split("/")[:-1]
    if any(part in EXCLUDED_DIRS for part in parts):
        return True
    return any(
        _is_virtualenv(root.joinpath(*parts[: i + 1])) for i in range(len(parts))
    )


def _is_virtualenv(path: Path) -> bool:
    # Every venv has a `pyvenv.cfg`, whatever its directory is called.
    return (path / "pyvenv.cfg").is_file()


@dataclass(frozen=True)
class _Pattern:
    glob: str
    negated: bool
    dir_only: bool
    anchored: bool


class _GitIgnore:
    """Simplified `.gitignore`: globs, `!`, a trailing `/` and anchoring by `/`."""

    def __init__(self, lines: list[str]) -> None:
        self.patterns: list[_Pattern] = []
        for raw in lines:
            line = raw.rstrip()
            if not line or line.startswith("#"):
                continue
            negated = line.startswith("!")
            line = line.removeprefix("!")
            dir_only = line.endswith("/")
            line = line.rstrip("/")
            anchored = "/" in line
            self.patterns.append(
                _Pattern(line.lstrip("/"), negated, dir_only, anchored)
            )

    def match(self, path: str, *, is_dir: bool) -> bool:
        """Whether `path` (relative, with `/`) is ignored; the last match wins."""
        ignored = False
        name = path.rsplit("/", 1)[-1]
        for p in self.patterns:
            if p.dir_only and not is_dir:
                continue
            if fnmatch.fnmatchcase(path if p.anchored else name, p.glob):
                ignored = not p.negated
        return ignored


def _read_gitignore(root: Path) -> _GitIgnore:
    try:
        text = (root / ".gitignore").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return _GitIgnore([])
    return _GitIgnore(text.splitlines())
