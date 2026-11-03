"""Lexical + symbol index over the served repository.

Pure-Python lexical search (ripgrep-style behaviour without the ripgrep binary,
so the clean-clone/offline path needs no external tool) plus a Python symbol
index built with stdlib ``ast``. No embeddings or vector search, by design.

One index is shared by every tool on a server, and it stays current: before each
query it re-stats the repo and re-reads only the files whose size or mtime
changed, so an edit made after the server started is visible to search_code and
list_symbols, not only to read_file. Measured on 2,700 files / 730k lines: a
cold build takes ~2 s, the freshness check ~0.1 s.

What the server serves is decided in this order:
  - the secrets deny-list (denied paths never enter the index and are refused),
  - symlinks are not followed by the walk (no escaping the root, no loops),
  - the repo's own ``.gitignore`` files, nested ones and ``.git/info/exclude``
    included: build output and private files a repo keeps out of git are not
    part of the repo the server presents, and
  - :data:`IGNORE_DIRS`, for vendor/noise directories in repos that aren't git
    repos or don't ignore them.

The server presents one view of the repo. A file that the walk leaves out is
also refused by read_file, diff and list_symbols (:func:`hidden_reason`), so
there is no file a model can open but not see. That matters because
``.gitignore`` itself is served, and it lists the names of the files a repo
keeps private. The user's global git excludes (``core.excludesFile``) are not
read: they describe one person's machine, not the repo.

The deny-list stays the boundary for secrets: it can't be overridden, and it
applies whatever a ``.gitignore`` says (``!.env`` does not re-include a secret).
"""

from __future__ import annotations

import ast
import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from pathspec import GitIgnoreSpec

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
# The tree is meant to be read in one go. Past this many characters (compact
# JSON) deep directories are collapsed to a file count instead of being listed.
TREE_MAX_CHARS = 6000


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


@dataclass
class _Entry:
    """One file as last indexed. ``lines`` is None if it isn't indexable text."""

    mtime_ns: int
    size: int
    lines: list[str] | None
    symbols: list[Symbol] = field(default_factory=list)


def _extract_symbols(rel: str, source: str) -> list[Symbol]:
    """Extract top-level functions/classes and methods via stdlib ast.

    A file that fails to parse yields no symbols rather than raising.
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


class _GitIgnore:
    """The ignore rules in force inside one directory, outermost first.

    Mirrors git's precedence: a deeper ``.gitignore`` overrides a shallower one,
    and within one file the last matching rule wins (``!`` re-includes).
    """

    def __init__(self, rules: tuple[tuple[str, GitIgnoreSpec], ...] = ()) -> None:
        self.rules = rules

    @classmethod
    def for_root(cls, root: Path) -> "_GitIgnore":
        exclude = root / ".git" / "info" / "exclude"  # lowest precedence
        return cls(()).with_file(exclude, "")

    def with_file(self, path: Path, base: str) -> "_GitIgnore":
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            return self
        return _GitIgnore(self.rules + ((base, GitIgnoreSpec.from_lines(lines)),))

    def ignored(self, rel: str, is_dir: bool) -> bool:
        verdict = False
        for base, spec in self.rules:
            sub = rel[len(base) + 1 :] if base else rel
            result = spec.check_file(sub + "/" if is_dir else sub).include
            if result is not None:
                verdict = result
        return verdict


def hidden_reason(repo_root: Path, rel: str, is_dir: bool) -> str | None:
    """Why the server leaves ``rel`` out of the repo it serves, or None if it doesn't.

    Applies the walk's rules (:data:`IGNORE_DIRS`, then ``.gitignore``) to each
    component of the path, from the root down, so a path is served exactly when
    the walk would have reached it. ``rel`` is posix, relative to the root, and
    already confined and deny-checked by the caller. The deny-list is not
    checked here.
    """
    root = Path(repo_root).resolve()
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    rules = _GitIgnore.for_root(root)
    prefix = ""
    for i, name in enumerate(parts):
        rules = rules.with_file(root / prefix / ".gitignore", prefix)
        current = f"{prefix}/{name}" if prefix else name
        current_is_dir = is_dir if i == len(parts) - 1 else True
        if current_is_dir and name in IGNORE_DIRS:
            return f"'{current}' is a vendor or cache directory, which the server does not serve"
        if rules.ignored(current, current_is_dir):
            return f"the repository's .gitignore ignores '{current}'"
        prefix = current
    return None


class RepoIndex:
    """An always-current lexical and symbol index of one repo root.

    Denied files never enter the index, so they can never appear in results.
    """

    def __init__(
        self,
        repo_root: Path,
        deny_patterns: tuple[str, ...] = DEFAULT_DENY_PATTERNS,
        *,
        respect_gitignore: bool = True,
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.deny_patterns = deny_patterns
        self.respect_gitignore = respect_gitignore
        self._entries: dict[str, _Entry] = {}

    # --- Keeping the index current -----------------------------------------

    def refresh(self) -> None:
        """Bring the index up to date with the files on disk.

        Re-reads only files that are new or whose size/mtime changed; drops
        files that were deleted or have become ignored or denied.
        """
        current: dict[str, _Entry] = {}
        for path, rel, is_dir in self._walk():
            if is_dir:
                continue
            try:
                st = path.stat()
            except OSError:
                continue
            old = self._entries.get(rel)
            if old is not None and (old.mtime_ns, old.size) == (st.st_mtime_ns, st.st_size):
                current[rel] = old
            else:
                current[rel] = self._load(path, rel, st.st_mtime_ns, st.st_size)
        self._entries = current

    build = refresh  # the first refresh is the build

    @staticmethod
    def _load(path: Path, rel: str, mtime_ns: int, size: int) -> _Entry:
        if size > MAX_FILE_BYTES:
            return _Entry(mtime_ns, size, None)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):  # unreadable or binary
            return _Entry(mtime_ns, size, None)
        symbols = _extract_symbols(rel, text) if rel.endswith(".py") else []
        return _Entry(mtime_ns, size, text.splitlines(), symbols)

    def _walk(self) -> Iterator[tuple[Path, str, bool]]:
        """Yield ``(path, posix_rel, is_dir)`` for every visible entry.

        Sorted, parents before their children. Prunes denied, ignored and noise
        paths, and never follows symlinks.
        """
        root_rules = _GitIgnore.for_root(self.repo_root) if self.respect_gitignore else _GitIgnore()

        def visit(directory: Path, rel_dir: str, rules: _GitIgnore):
            if self.respect_gitignore:
                rules = rules.with_file(directory / ".gitignore", rel_dir)
            try:
                children = sorted(directory.iterdir())
            except OSError:
                return
            for child in children:
                if child.is_symlink():
                    continue
                rel = f"{rel_dir}/{child.name}" if rel_dir else child.name
                if is_denied(rel, self.deny_patterns):
                    continue
                is_dir = child.is_dir()
                if is_dir and child.name in IGNORE_DIRS:
                    continue
                if not is_dir and not child.is_file():
                    continue
                if rules.ignored(rel, is_dir):
                    continue
                yield child, rel, is_dir
                if is_dir:
                    yield from visit(child, rel, rules)

        yield from visit(self.repo_root, "", root_rules)

    # --- Queries -----------------------------------------------------------

    def search(
        self,
        query: str,
        *,
        limit: int = 20,
        offset: int = 0,
        case_sensitive: bool = False,
        path: str | None = None,
    ) -> tuple[int, list[SearchMatch]]:
        """Return (total_matches, page) for a literal substring query.

        ``path`` narrows the search to one file or directory (repo-relative,
        already security-checked by the caller). Matches are ordered by
        (path, line) for stable pagination.
        """
        self.refresh()
        needle = query if case_sensitive else query.lower()
        matches: list[SearchMatch] = []
        for rel, entry in self._entries.items():
            if not _in_scope(rel, path):
                continue
            for lineno, line in enumerate(entry.lines or (), start=1):
                haystack = line if case_sensitive else line.lower()
                if needle in haystack:
                    matches.append(SearchMatch(rel, lineno, line.strip()[:SNIPPET_MAX]))

        matches.sort(key=lambda m: (m.path, m.line))
        return len(matches), matches[offset : offset + limit]

    def symbols(
        self,
        *,
        path: str | None = None,
        query: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[int, list[Symbol]]:
        """Return (total, page) of symbols, optionally filtered by file/name.

        Args:
            path: If given, restrict to symbols defined in this repo-relative
                file, or in files under this directory (already security-checked
                by the caller).
            query: If given, restrict to symbols whose name contains it
                (case-insensitive).
            limit: Max symbols to return.
            offset: Symbols to skip (pagination), in (path, line) order.
        """
        self.refresh()
        result = [s for rel, entry in self._entries.items() if _in_scope(rel, path) for s in entry.symbols]
        if query:
            needle = query.lower()
            result = [s for s in result if needle in s.name.lower()]

        result.sort(key=lambda s: (s.path, s.line))
        return len(result), result[offset : offset + limit]

    def file_tree(self, max_chars: int | None = TREE_MAX_CHARS) -> dict:
        """The visible file tree, collapsed if needed to fit ``max_chars``.

        Same visibility rules as the index: denied, ignored and noise paths and
        symlinks are left out, so secrets never appear. When the full tree is
        too long, the deepest directories are collapsed first, each to a
        ``file_count``, so the result is always a whole, valid tree.
        """
        root: dict = {"name": self.repo_root.name, "path": ".", "type": "dir", "children": []}
        dirs = {"": root}
        for path, rel, is_dir in self._walk():
            parent = dirs[rel.rpartition("/")[0]]
            if is_dir:
                node = {"name": path.name, "path": rel, "type": "dir", "children": []}
                dirs[rel] = node
            else:
                try:
                    size = path.stat().st_size
                except OSError:
                    size = None
                node = {"name": path.name, "path": rel, "type": "file", "size": size}
            parent["children"].append(node)

        if max_chars is not None:
            _fit_tree(root, dirs, max_chars)
        return root


def _in_scope(rel: str, scope: str | None) -> bool:
    """True if ``rel`` is the file ``scope`` or lies under the directory ``scope``."""
    return scope is None or rel == scope or rel.startswith(scope + "/")


def _compact_len(node: dict) -> int:
    return len(json.dumps(node, separators=(",", ":")))


def _count_files(node: dict) -> int:
    if node["type"] == "file":
        return 1
    if "children" not in node:
        return node["file_count"]
    return sum(_count_files(c) for c in node["children"])


def _fit_tree(root: dict, dirs: dict[str, dict], max_chars: int) -> None:
    """Collapse directories until the tree fits: deepest level first, and within
    a level the biggest first, stopping as soon as it fits. So one huge
    directory costs only its own listing, not everything at its depth."""
    by_depth: dict[int, list[dict]] = {}
    for rel, node in dirs.items():
        if rel:
            by_depth.setdefault(rel.count("/") + 1, []).append(node)

    total = _compact_len(root)
    for depth in sorted(by_depth, reverse=True):
        for node in sorted(by_depth[depth], key=_compact_len, reverse=True):
            if total <= max_chars:
                return
            before = _compact_len(node)
            count = _count_files(node)
            node.pop("children")
            node["collapsed"] = True
            node["file_count"] = count
            total -= before - _compact_len(node)  # exact: compact JSON nests verbatim

    # Still too long: the top level alone is too wide. List what fits.
    children = root["children"]
    omitted = 0
    while children and _compact_len(root) > max_chars:
        children.pop()
        omitted += 1
        root["omitted_entries"] = omitted
