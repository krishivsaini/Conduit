"""Secrets deny-list (§8.2).

Even inside the repo root, configured sensitive paths/patterns are never
exposed — not in ``repo_tree``, not in ``search_code`` results, not via
``read_file``. Applied uniformly at every exposure point so there is one
answer to "is this path allowed to leave the server?".

Matching is glob-based and **case-insensitive** (a case-insensitive filesystem
must not let ``.ENV`` slip past a ``.env`` rule), evaluated against every
component of the path so a secret in a subdirectory is caught too. Patterns
ending in ``/`` denote a directory that is denied wherever it appears
(e.g. ``.git/``).

Proven by: tests/test_security_denylist.py
"""

from __future__ import annotations

from fnmatch import fnmatch
from pathlib import PurePosixPath

# Default patterns refused even inside the root. Configurable per-deployment.
DEFAULT_DENY_PATTERNS: tuple[str, ...] = (
    ".env",
    ".env.*",
    "*.key",
    "*.pem",
    "*.p12",
    "*.pfx",
    "id_rsa",
    "id_ed25519",
    "credentials",
    ".git/",
)


def _components(relative_path: str) -> list[str]:
    """Split a relative path into meaningful components (posix-normalized)."""
    rel = PurePosixPath(relative_path.replace("\\", "/"))
    return [p for p in rel.parts if p not in ("", ".")]


def is_denied(relative_path: str, patterns: tuple[str, ...] = DEFAULT_DENY_PATTERNS) -> bool:
    """Return True if ``relative_path`` matches any deny pattern.

    Args:
        relative_path: A path relative to the repo root (already confined by the
            boundary). May point at a file or directory.
        patterns: Glob patterns / ``dir/`` markers to deny. Defaults to
            :data:`DEFAULT_DENY_PATTERNS`.
    """
    parts = _components(relative_path)
    if not parts:
        return False

    for pattern in patterns:
        if pattern.endswith("/"):
            # Directory marker: deny if the dir appears anywhere in the path.
            dirname = pattern[:-1].lower()
            if any(part.lower() == dirname for part in parts):
                return True
        else:
            # File/glob: deny if any path component matches (case-insensitive).
            if any(fnmatch(part.lower(), pattern.lower()) for part in parts):
                return True
    return False
