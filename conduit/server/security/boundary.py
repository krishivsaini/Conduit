"""Repo-root confinement and path-traversal defense (§8.1).

Every path arriving from the client is untrusted. Before any filesystem
access, it is resolved to a canonical absolute path (collapsing ``..`` and
following symlinks) and asserted to live inside the configured repo root.
Attempts like ``../../etc/passwd``, absolute paths outside the root, and
symlink escapes are refused with an actionable error.

Proven by: tests/test_security_traversal.py

Status: scaffolded on Day 1; implemented on Day 3.
"""

from __future__ import annotations

from pathlib import Path


class PathOutsideRootError(Exception):
    """Raised when a requested path resolves outside the repo root."""


def resolve_within_root(repo_root: Path, requested: str) -> Path:
    """Resolve ``requested`` against ``repo_root`` and confine it to the root.

    Args:
        repo_root: The single directory the server is allowed to serve.
        requested: A client-supplied path (relative to the root, untrusted).

    Returns:
        The canonical absolute :class:`~pathlib.Path`, guaranteed inside the root.

    Raises:
        PathOutsideRootError: If the resolved path escapes the root.
    """
    raise NotImplementedError("Day 3: repo-root confinement / traversal defense")
