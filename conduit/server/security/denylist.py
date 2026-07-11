"""Secrets deny-list (§8.2).

Even inside the repo root, configured sensitive paths/patterns are never
exposed — not in ``repo_tree``, not in ``search_code`` results, not via
``read_file``. Applied uniformly at every exposure point.

Default denied patterns: ``.env``, ``*.key``, ``*.pem``, ``.git/``, and
common credential files.

Proven by: tests/test_security_denylist.py

Status: scaffolded on Day 1; implemented on Day 4.
"""

from __future__ import annotations

from pathlib import Path

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


def is_denied(relative_path: str, patterns: tuple[str, ...] = DEFAULT_DENY_PATTERNS) -> bool:
    """Return True if ``relative_path`` matches any deny pattern.

    Status: scaffolded on Day 1; implemented on Day 4.
    """
    raise NotImplementedError("Day 4: deny-list matching")
