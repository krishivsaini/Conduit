"""Structured, actionable error helpers.

Every tool returns errors that tell the LLM *what* went wrong and *what to do*
next — never a raw stack trace into the client (mcp-builder best practice).

Status: scaffolded on Day 1; used across tools from Day 7.
"""

from __future__ import annotations


class ConduitError(Exception):
    """Base class for actionable, client-facing errors.

    Attributes:
        what: A short statement of what went wrong.
        fix: A concrete suggestion for how the caller should proceed.
    """

    def __init__(self, what: str, fix: str) -> None:
        self.what = what
        self.fix = fix
        super().__init__(f"{what} {fix}")

    def to_actionable(self) -> str:
        """Render a single actionable error string for the tool response."""
        return f"Error: {self.what} {self.fix}"
