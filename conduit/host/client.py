"""MCP client — connect to the server, discover tools/resources, call tools.

Uses the stable MCP Python SDK client (``ClientSession`` over a stdio
transport). The discovered tool list is returned to the loop as-is; **nothing
about the tool set is hardcoded here** (§9). Add or rename a tool on the server
and this client picks it up on the next connection with no change here — that is
the property proven by tests/test_dynamic_discovery.py.
"""

from __future__ import annotations

import sys
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import CallToolResult


@dataclass(frozen=True)
class DiscoveredTool:
    """A tool learned from the server at runtime (not hardcoded)."""

    name: str
    description: str | None
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class DiscoveredResource:
    """A resource learned from the server at runtime."""

    uri: str
    name: str | None
    mime_type: str | None


def conduit_server_params(repo_root: str | Path, python_executable: str | None = None) -> StdioServerParameters:
    """Build stdio params that launch the Conduit server for ``repo_root``.

    Uses the current interpreter by default so the client and server share the
    same environment.
    """
    return StdioServerParameters(
        command=python_executable or sys.executable,
        args=["-m", "conduit.server.app", "--repo-root", str(repo_root)],
    )


class MCPCodebaseClient:
    """Connects to the Conduit MCP server and exposes discover/call.

    Use as an async context manager::

        async with MCPCodebaseClient(params) as client:
            tools = await client.discover_tools()
            result = await client.call_tool("read_file", {"path": "src/x.py"})
    """

    def __init__(self, server_params: StdioServerParameters) -> None:
        self._params = server_params
        self._session: ClientSession | None = None
        self._stack: AsyncExitStack | None = None

    async def __aenter__(self) -> "MCPCodebaseClient":
        self._stack = AsyncExitStack()
        read, write = await self._stack.enter_async_context(stdio_client(self._params))
        session = await self._stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        self._session = session
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        if self._stack is not None:
            await self._stack.aclose()
        self._session = None
        self._stack = None

    @property
    def session(self) -> ClientSession:
        if self._session is None:
            raise RuntimeError("client is not connected; use 'async with MCPCodebaseClient(...)'")
        return self._session

    async def discover_tools(self) -> list[DiscoveredTool]:
        """Return the tool schemas advertised by the server (runtime discovery)."""
        result = await self.session.list_tools()
        return [
            DiscoveredTool(name=t.name, description=t.description, input_schema=t.inputSchema)
            for t in result.tools
        ]

    async def discover_resources(self) -> list[DiscoveredResource]:
        """Return the resources advertised by the server."""
        result = await self.session.list_resources()
        return [
            DiscoveredResource(uri=str(r.uri), name=r.name, mime_type=r.mimeType)
            for r in result.resources
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> CallToolResult:
        """Invoke a server tool by name over MCP and return its result."""
        return await self.session.call_tool(name, arguments)
