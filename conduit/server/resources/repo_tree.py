"""repo_tree resource — the file tree + basic metadata for orientation.

Exposed as an MCP *resource* (context), not a tool: it is a browsable view of
what's available, not a parameterized action. The deny-list is applied so
sensitive files never appear in the tree.

Status: scaffolded on Day 1; implemented on Day 6.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ..app import ServerConfig


def register(mcp: FastMCP, config: ServerConfig) -> None:
    """Register the repo_tree resource on the server."""
    raise NotImplementedError("Day 6: implement repo_tree resource")
