"""Lexical + symbol index over the served repository.

Lexical search is ripgrep-style text matching; the symbol index is built for
Python sources with the stdlib :mod:`ast` module (functions/classes), which
keeps the whole thing dependency-free and portable for a clean-clone run.

No embeddings / vector search — lexical + symbolic only, by design (§1.3).

Status: scaffolded on Day 1; search index Day 5, symbol index Day 6.
"""

from __future__ import annotations

from pathlib import Path


class RepoIndex:
    """Builds and holds the lexical/symbol index for a repo root.

    The index respects the security boundary and deny-list so denied files
    never enter search results or the symbol table.
    """

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root

    def build(self) -> None:
        """Walk the repo (deny-list applied) and build the indexes."""
        raise NotImplementedError("Day 5/6: build lexical + symbol indexes")
