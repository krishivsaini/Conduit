"""Read-only posture enforcement (§8.3).

The server exposes no tool that mutates the filesystem or executes code.
This module documents and (in test) asserts that invariant: the registered
tool set contains only read-only actions, and no code path opens a file for
writing or shells out.

Proven by: tests/test_security_readonly.py

Status: scaffolded on Day 1; implemented on Day 4.
"""

from __future__ import annotations

# The complete set of actions the server is permitted to expose. Anything
# outside this set (write, delete, exec, move, ...) is a bug the read-only
# test must catch.
ALLOWED_READONLY_TOOLS: frozenset[str] = frozenset(
    {"search_code", "read_file", "list_symbols", "diff"}
)


def assert_readonly_toolset(registered_tool_names: frozenset[str]) -> None:
    """Assert every registered tool is in the read-only allow-set.

    Status: scaffolded on Day 1; implemented on Day 4.
    """
    raise NotImplementedError("Day 4: read-only posture assertion")
