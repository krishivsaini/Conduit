"""repo_tree resource — the file tree + basic metadata for orientation.

Exposed as an MCP *resource* (context), not a tool: it is a browsable view of
what's available, not a parameterized action. The deny-list is applied so
sensitive files (``.env``, ``*.key``, ``.git/`` …) never appear in the tree.
"""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from ..app import ServerConfig
from ..indexer import RepoIndex

REPO_TREE_URI = "repo://tree"


def register(mcp: FastMCP, config: ServerConfig, index: RepoIndex) -> None:
    """Register the repo_tree resource on the server."""

    @mcp.resource(
        REPO_TREE_URI,
        name="repo_tree",
        title="Repository file tree",
        description=(
            "The served repo's file tree as JSON (deny-listed and .gitignored files excluded). "
            "On a large repo, deep directories are collapsed to a file_count: use search_code "
            "or list_symbols to find files inside them."
        ),
        mime_type="application/json",
    )
    def repo_tree() -> str:
        """Return the repo file tree as pretty-printed JSON."""
        return json.dumps(index.file_tree(), indent=2)
