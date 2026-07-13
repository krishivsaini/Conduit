"""Structured, actionable errors — the shared convention for all tools.

Every tool returns errors that tell the LLM *what* went wrong and *what to do*
next, never a raw stack trace into the client (mcp-builder best practice).

The pattern:
  - Domain code raises :class:`ActionableError` (or a subclass such as
    :class:`~conduit.server.access.FileAccessError`) carrying a client-safe,
    actionable message.
  - Each tool wraps its body and converts :class:`ActionableError` into an MCP
    ``ToolError`` (see :func:`to_tool_error`), so the message reaches the client
    as a clean ``isError`` result and the exception/stack never does.
"""

from __future__ import annotations

from mcp.server.fastmcp.exceptions import ToolError


class ActionableError(Exception):
    """A client-safe error carrying an actionable message (what + how to fix)."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def actionable(what: str, fix: str) -> ActionableError:
    """Build an :class:`ActionableError` from a 'what went wrong' + 'how to fix'."""
    return ActionableError(f"{what} {fix}")


def to_tool_error(error: ActionableError) -> ToolError:
    """Convert an :class:`ActionableError` to an MCP ``ToolError``.

    FastMCP already prefixes ``Error executing tool <name>:``, so only the
    actionable body is surfaced.
    """
    return ToolError(error.message)
