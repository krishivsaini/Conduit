"""Read-only posture enforcement (§8.3).

The server exposes no tool that mutates the filesystem or executes code. This
module enforces that invariant at server-build time (:func:`enforce_readonly`
is called from ``build_server``, so the server refuses to start if a
non-read-only tool is ever registered) and it is proven by
tests/test_security_readonly.py, which also statically asserts no server code
path opens a file for writing or shells out.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # avoid importing FastMCP at module import time
    from mcp.server.fastmcp import FastMCP

# The complete set of actions the server is permitted to expose. Anything
# outside this set (write, delete, exec, move, ...) is a bug this catches.
ALLOWED_READONLY_TOOLS: frozenset[str] = frozenset(
    {"search_code", "read_file", "list_symbols", "diff"}
)


class ReadOnlyViolationError(Exception):
    """Raised when a tool outside the read-only allow-set is registered."""


def assert_readonly_toolset(registered_tool_names: frozenset[str]) -> None:
    """Assert every registered tool is in the read-only allow-set.

    Raises:
        ReadOnlyViolationError: If any registered tool is not allow-listed.
    """
    unexpected = set(registered_tool_names) - ALLOWED_READONLY_TOOLS
    if unexpected:
        raise ReadOnlyViolationError(
            f"non-read-only tool(s) registered: {sorted(unexpected)}. "
            f"The server is read-only by design; remove them or update "
            f"ALLOWED_READONLY_TOOLS deliberately."
        )


def enforce_readonly(mcp: "FastMCP") -> None:
    """Enforce the read-only posture over a built server.

    Checks both that every registered tool is allow-listed and that each
    carries ``readOnlyHint=True``.
    """
    tools = mcp._tool_manager.list_tools()
    assert_readonly_toolset(frozenset(t.name for t in tools))

    missing_hint = [
        t.name for t in tools if not (t.annotations and t.annotations.readOnlyHint)
    ]
    if missing_hint:
        raise ReadOnlyViolationError(
            f"tool(s) missing readOnlyHint=True: {missing_hint}. "
            f"Read-only tools must declare readOnlyHint=True."
        )
