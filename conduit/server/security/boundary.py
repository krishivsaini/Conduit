"""Repo-root confinement and path-traversal defense (§8.1).

Every path arriving from the client is untrusted. Before any filesystem
access, it is resolved to a canonical absolute path — collapsing ``..`` **and
following symlinks** — and asserted to live inside the configured repo root.
Attempts like ``../../etc/passwd``, absolute paths outside the root, and
symlink escapes (a symlink inside the root pointing outside it) are refused
with an actionable :class:`PathOutsideRootError`.

Why symlink-aware resolution matters: a lexical ``..`` check alone can be
defeated by a symlink whose *target* is outside the root. ``Path.resolve()``
follows symlinks in the existing prefix, so the containment check below sees
the real destination. Resolving the root itself first also handles platforms
where the root sits under a symlink (e.g. macOS ``/tmp`` -> ``/private/tmp``).

Proven by: tests/test_security_traversal.py
"""

from __future__ import annotations

from pathlib import Path


class PathOutsideRootError(Exception):
    """Raised when a requested path resolves outside the repo root."""

    def __init__(self, requested: str, reason: str) -> None:
        self.requested = requested
        self.reason = reason
        super().__init__(f"path '{requested}' is outside the repo root: {reason}")

    def actionable(self) -> str:
        """A client-facing message: what went wrong and how to fix it."""
        return (
            f"path '{self.requested}' is outside the repo root. Provide a path "
            f"relative to the root; absolute paths, '..' escapes, and symlink "
            f"escapes are refused."
        )


def resolve_within_root(repo_root: Path, requested: str) -> Path:
    """Resolve ``requested`` against ``repo_root`` and confine it to the root.

    Args:
        repo_root: The single directory the server is allowed to serve.
        requested: A client-supplied path relative to the root (untrusted).

    Returns:
        The canonical absolute :class:`~pathlib.Path`, guaranteed inside the
        root (or the root itself). Existence is *not* required here — a missing
        file resolves cleanly and is reported downstream as "does not exist".

    Raises:
        PathOutsideRootError: If the resolved path escapes the root, or if an
            absolute path is supplied.
    """
    # Canonicalize the root first so symlinks in the root path don't cause a
    # spurious mismatch against the resolved candidate.
    root = Path(repo_root).resolve()

    req = Path(requested)
    if req.is_absolute():
        raise PathOutsideRootError(requested, "absolute paths are not allowed")

    # Resolve '..' and any symlinks in the candidate. strict=False so a
    # not-yet-existing tail resolves without error.
    resolved = (root / req).resolve()

    # Containment via path ancestry (not string prefixing, which would wrongly
    # accept a sibling like '<root>-evil').
    if resolved != root and root not in resolved.parents:
        raise PathOutsideRootError(requested, "resolves outside the root ('..' or symlink escape)")

    return resolved
