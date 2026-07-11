"""list_symbols tool — functions/classes for a file or matching a query.

Backed by the stdlib-``ast`` symbol index (Python sources). readOnlyHint=True.

Status: scaffolded on Day 1; implemented on Day 6.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from mcp.server.fastmcp import FastMCP

from ..app import ServerConfig


class ListSymbolsInput(BaseModel):
    """Input schema for list_symbols."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    path: str | None = Field(
        default=None,
        description="Restrict to symbols defined in this file (repo-relative).",
    )
    query: str | None = Field(
        default=None, description="Return symbols whose name matches this query."
    )


def register(mcp: FastMCP, config: ServerConfig) -> None:
    """Register the list_symbols tool on the server."""
    raise NotImplementedError("Day 6: implement list_symbols")
