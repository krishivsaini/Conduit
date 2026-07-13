"""diff tool — structured unified diff between two files in the repo.

Operates on two files' *contents* (stdlib ``difflib``). It deliberately does
NOT diff git refs: doing so would require executing ``git`` as a subprocess,
which the server's provably read-only / no-exec posture (§8.3) forbids — a
principled scope choice, not a shortcut. Both paths are security-checked
(confinement + deny-list). readOnlyHint=True.
"""

from __future__ import annotations

import difflib
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from ..access import read_text_file
from ..app import ServerConfig
from ..errors import ActionableError, to_tool_error

# Bound the diff so one call can't emit an unbounded blob.
MAX_DIFF_LINES = 2000


class DiffResult(BaseModel):
    """Structured unified diff between two files."""

    model_config = ConfigDict(extra="forbid")

    a: str = Field(description="First (left) repo-relative file path.")
    b: str = Field(description="Second (right) repo-relative file path.")
    identical: bool = Field(description="True if the two files have identical content.")
    added_lines: int = Field(description="Number of added lines (present in b, not a).")
    removed_lines: int = Field(description="Number of removed lines (present in a, not b).")
    truncated: bool = Field(description="True if the diff was capped at MAX_DIFF_LINES.")
    diff: list[str] = Field(description="Unified-diff lines (may be truncated).")


def register(mcp: FastMCP, config: ServerConfig) -> None:
    """Register the diff tool on the server."""
    repo_root = config.repo_root

    @mcp.tool(
        name="diff",
        title="Unified diff between two files",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def diff(
        a: Annotated[str, Field(description="First (left) file, repo-relative.", min_length=1)],
        b: Annotated[str, Field(description="Second (right) file, repo-relative.", min_length=1)],
    ) -> DiffResult:
        """Produce a unified diff between two files within the repo.

        Both paths are confined to the repo root and screened against the
        deny-list. Note: this diffs file *contents*, not git refs (the server
        does not execute git).

        Returns:
            A structured result with the two paths, an ``identical`` flag,
            added/removed line counts, and the (possibly truncated) unified-diff
            lines.
        """
        try:
            _, a_lines = read_text_file(repo_root, a)
            _, b_lines = read_text_file(repo_root, b)
        except ActionableError as e:
            raise to_tool_error(e)

        full = list(
            difflib.unified_diff(a_lines, b_lines, fromfile=a, tofile=b, lineterm="")
        )
        identical = len(full) == 0
        added = sum(1 for ln in full if ln.startswith("+") and not ln.startswith("+++"))
        removed = sum(1 for ln in full if ln.startswith("-") and not ln.startswith("---"))

        truncated = len(full) > MAX_DIFF_LINES
        return DiffResult(
            a=a,
            b=b,
            identical=identical,
            added_lines=added,
            removed_lines=removed,
            truncated=truncated,
            diff=full[:MAX_DIFF_LINES],
        )
