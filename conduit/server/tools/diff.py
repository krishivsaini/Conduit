"""diff tool — structured diff between two refs or two files.

readOnlyHint=True. All path inputs are boundary-checked before access.

Status: scaffolded on Day 1; implemented on Day 6.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from mcp.server.fastmcp import FastMCP

from ..app import ServerConfig


class DiffInput(BaseModel):
    """Input schema for diff."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    a: str = Field(..., description="First side: a repo-relative file path or a git ref.")
    b: str = Field(..., description="Second side: a repo-relative file path or a git ref.")


def register(mcp: FastMCP, config: ServerConfig) -> None:
    """Register the diff tool on the server."""
    raise NotImplementedError("Day 6: implement diff")
