"""Shared, security-checked file access for tools.

One place that turns a client-supplied path into a readable file, applying the
security boundaries in order: repo-root confinement (§8.1) → secrets deny-list
(§8.2) → the repo's own exclusions (.gitignore, vendor dirs) → existence/type/
encoding checks. Tools (read_file, diff, list_symbols)
use this so the enforcement order is identical everywhere and never duplicated.
"""

from __future__ import annotations

from pathlib import Path

from .errors import ActionableError
from .indexer import hidden_reason
from .security.boundary import PathOutsideRootError, resolve_within_root
from .security.denylist import DEFAULT_DENY_PATTERNS, is_denied


class FileAccessError(ActionableError):
    """An actionable error for a refused or invalid file access."""


def resolve_allowed_path(
    repo_root: Path, path: str, deny_patterns: tuple[str, ...] = DEFAULT_DENY_PATTERNS
) -> Path:
    """Confine ``path`` to the root and screen it against the deny-list.

    Returns the resolved absolute path (which may not exist yet). Raises
    :class:`FileAccessError` with an actionable message on a traversal attempt
    or a deny-listed path. The deny-list is checked on the *resolved* path so a
    symlink pointing at a secret is caught too.
    """
    try:
        target = resolve_within_root(repo_root, path)
    except PathOutsideRootError as e:
        raise FileAccessError(e.actionable())

    relative = target.relative_to(Path(repo_root).resolve())
    if is_denied(str(relative), deny_patterns):
        raise FileAccessError(
            f"path '{path}' is excluded by the server's secrets deny-list and cannot be accessed."
        )
    # Same view as the tree and search: a file the walk leaves out isn't served.
    reason = hidden_reason(repo_root, relative.as_posix(), target.is_dir())
    if reason:
        raise FileAccessError(
            f"path '{path}' is not served: {reason}. The server serves the files a "
            "repository tracks; search_code or the repo tree shows what is available."
        )
    return target


def resolve_scope(
    repo_root: Path, path: str | None, deny_patterns: tuple[str, ...] = DEFAULT_DENY_PATTERNS
) -> str | None:
    """A file or directory to narrow a search or listing to, as a posix
    repo-relative path; None for the whole repo. Checked like any other path, so
    a scope can't point outside the root, at a secret, or at an ignored file."""
    if path is None:
        return None
    target = resolve_allowed_path(repo_root, path, deny_patterns)
    if not target.exists():
        raise FileAccessError(
            f"'{path}' does not exist. Give a file or directory relative to the repo root."
        )
    rel = target.relative_to(Path(repo_root).resolve()).as_posix()
    return None if rel == "." else rel


def read_text_file(
    repo_root: Path, path: str, deny_patterns: tuple[str, ...] = DEFAULT_DENY_PATTERNS
) -> tuple[Path, list[str]]:
    """Resolve + confine + deny-check, then read a UTF-8 text file.

    Returns ``(resolved_path, lines)``. Raises :class:`FileAccessError` for a
    missing path, a directory, a non-UTF-8 file, or a security refusal.
    """
    target = resolve_allowed_path(repo_root, path, deny_patterns)
    if not target.exists():
        raise FileAccessError(
            f"file '{path}' does not exist. Check the path relative to the repo root."
        )
    if not target.is_file():
        raise FileAccessError(
            f"'{path}' is not a file. Provide a path to a file, not a directory."
        )
    try:
        text = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise FileAccessError(
            f"'{path}' is not a UTF-8 text file. This tool serves text files only."
        )
    return target, text.splitlines()
