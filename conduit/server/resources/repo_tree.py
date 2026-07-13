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


def register(mcp: FastMCP, config: ServerConfig) -> None:
    """Register the repo_tree resource on the server."""
    index = RepoIndex(config.repo_root)

    @mcp.resource(
        REPO_TREE_URI,
        name="repo_tree",
        title="Repository file tree",
        description="The served repo's file tree (deny-listed files excluded), as JSON.",
        mime_type="application/json",
    )
    def repo_tree() -> str:
        """Return the repo file tree as pretty-printed JSON."""
        return json.dumps(index.file_tree(), indent=2)
