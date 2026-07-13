"""Lexical index over the served repository.

Pure-Python, dependency-free lexical search (ripgrep-style behavior without the
ripgrep binary, so the clean-clone/offline path has no external requirement).
The sample repo is tiny; for very large repos this would be swapped for a real
indexer — a documented scope choice, not a limitation of the design.

No embeddings / vector search — lexical + (Day 6) symbolic only, by design.

The walk respects the security model:
  - the deny-list (secrets never enter the index),
  - symlinks are NOT followed (prevents escaping the root during a walk), and
  - obvious vendor/noise directories are skipped for signal and speed.

The symbol index (functions/classes via stdlib ``ast``) is added on Day 6 for
list_symbols.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from .security.denylist import DEFAULT_DENY_PATTERNS, is_denied

# Vendor/noise directories skipped during the walk (separate from the secrets
# deny-list — these are about signal, not security).
IGNORE_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        "dist",
        "build",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".ollama",
    }
)

# Skip files larger than this (bytes) to bound index size and time.
MAX_FILE_BYTES = 1_000_000
# Truncate each returned snippet to keep results context-friendly.
SNIPPET_MAX = 200


@dataclass(frozen=True)
class SearchMatch:
    """A single lexical match: file + 1-indexed line + trimmed snippet."""

    path: str
    line: int
    snippet: str


@dataclass(frozen=True)
class Symbol:
    """A definition in the code: function, class, or method."""

    name: str
    kind: str  # "function" | "class" | "method"
    path: str
    line: int
    parent: str | None = None  # enclosing class name, for methods


def _extract_symbols(rel: str, source: str) -> list[Symbol]:
    """Extract top-level functions/classes and methods via stdlib ast.

    Dependency-free and robust: a file that fails to parse yields no symbols
    rather than raising.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    out: list[Symbol] = []

    def visit(node: ast.AST, parent: str | None) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out.append(
                    Symbol(child.name, "method" if parent else "function", rel, child.lineno, parent)
                )
            elif isinstance(child, ast.ClassDef):
                out.append(Symbol(child.name, "class", rel, child.lineno, parent))
                visit(child, parent=child.name)

    visit(tree, parent=None)
    return out


class RepoIndex:
    """Builds and holds an in-memory lexical index for a repo root.

    Denied files never enter the index, so they can never appear in results.
    """

    def __init__(self, repo_root: Path, deny_patterns: tuple[str, ...] = DEFAULT_DENY_PATTERNS) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.deny_patterns = deny_patterns
        self._files: list[tuple[str, list[str]]] = []
        self._symbols: list[Symbol] = []
        self._built = False

    def build(self) -> None:
        """Walk the repo and load indexable text files + Python symbols."""
        self._files = []
        self._symbols = []
        for path, rel in self._iter_text_files():
            try:
                if path.stat().st_size > MAX_FILE_BYTES:
                    continue
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                # Unreadable or binary → not indexable.
                continue
            self._files.append((rel, text.splitlines()))
            if rel.endswith(".py"):
                self._symbols.extend(_extract_symbols(rel, text))
        self._built = True

    def _iter_text_files(self):
        """Yield (path, relative_str) for candidate files under the root.

        Prunes ignore-dirs and deny-listed paths, and never follows symlinks.
        """
        stack: list[Path] = [self.repo_root]
        while stack:
            directory = stack.pop()
            try:
                children = sorted(directory.iterdir())
            except OSError:
                continue
            for child in children:
                if child.is_symlink():
                    # Do not follow symlinks: avoids escaping the root and loops.
                    continue
                rel = str(child.relative_to(self.repo_root))
                if is_denied(rel, self.deny_patterns):
                    continue
                if child.is_dir():
                    if child.name in IGNORE_DIRS:
                        continue
                    stack.append(child)
                elif child.is_file():
                    yield child, rel

    def search(
        self,
        query: str,
        *,
        limit: int = 20,
        offset: int = 0,
        case_sensitive: bool = False,
    ) -> tuple[int, list[SearchMatch]]:
        """Return (total_matches, page) for a literal substring query.

        Matches are ordered by (path, line) for stable pagination.
        """
        if not self._built:
            self.build()

        needle = query if case_sensitive else query.lower()
        matches: list[SearchMatch] = []
        for rel, lines in self._files:
            for lineno, line in enumerate(lines, start=1):
                haystack = line if case_sensitive else line.lower()
                if needle in haystack:
                    matches.append(SearchMatch(rel, lineno, line.strip()[:SNIPPET_MAX]))

        matches.sort(key=lambda m: (m.path, m.line))
        total = len(matches)
        return total, matches[offset : offset + limit]

    def symbols(
        self,
        *,
        path: str | None = None,
        query: str | None = None,
        limit: int = 100,
    ) -> tuple[int, list[Symbol]]:
        """Return (total, page) of symbols, optionally filtered by file/name.

        Args:
            path: If given, restrict to symbols defined in this repo-relative
                file (already security-checked by the caller).
            query: If given, restrict to symbols whose name contains it
                (case-insensitive).
            limit: Max symbols to return.
        """
        if not self._built:
            self.build()

        result = self._symbols
        if path is not None:
            result = [s for s in result if s.path == path]
        if query:
            needle = query.lower()
            result = [s for s in result if needle in s.name.lower()]

        result = sorted(result, key=lambda s: (s.path, s.line))
        total = len(result)
        return total, result[:limit]

    def file_tree(self) -> dict:
        """Build a nested file tree (deny-list applied, symlinks skipped).

        Directories in :data:`IGNORE_DIRS` and any deny-listed path are omitted,
        so secrets never appear in the tree.
        """

        def node_for(directory: Path) -> dict:
            children: list[dict] = []
            try:
                entries = sorted(directory.iterdir())
            except OSError:
                entries = []
            for child in entries:
                if child.is_symlink():
                    continue
                rel = str(child.relative_to(self.repo_root))
                if is_denied(rel, self.deny_patterns):
                    continue
                if child.is_dir():
                    if child.name in IGNORE_DIRS:
                        continue
                    children.append(node_for(child))
                elif child.is_file():
                    try:
                        size = child.stat().st_size
                    except OSError:
                        size = None
                    children.append({"name": child.name, "path": rel, "type": "file", "size": size})
            rel_root = "." if directory == self.repo_root else str(directory.relative_to(self.repo_root))
            return {"name": directory.name, "path": rel_root, "type": "dir", "children": children}

        return node_for(self.repo_root)
