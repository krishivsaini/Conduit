"""MCP client — connect to the server, discover tools/resources, call tools.

Uses the stable MCP Python SDK client API (ClientSession over a stdio
transport). The discovered tool list is returned to the loop as-is; nothing
about the tool set is hardcoded here (§9).

Status: scaffolded on Day 1; implemented on Day 8.
"""

from __future__ import annotations

from typing import Any


class MCPCodebaseClient:
    """Connects to the Conduit MCP server and exposes discover/call."""

    async def discover_tools(self) -> list[dict[str, Any]]:
        """Return the tool schemas advertised by the server (runtime discovery)."""
        raise NotImplementedError("Day 8: connect + list_tools discovery")

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Invoke a server tool by name over MCP and return its result."""
        raise NotImplementedError("Day 8: call_tool over MCP")
