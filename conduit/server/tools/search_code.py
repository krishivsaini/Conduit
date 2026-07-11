"""search_code tool — lexical/symbol search across the repo, paginated.

Returns matches as file + line + snippet. Deny-listed files never appear in
results. Paginated so one call can't dump the whole repo. readOnlyHint=True.

Status: scaffolded on Day 1; implemented on Day 5.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from mcp.server.fastmcp import FastMCP

from ..app import ServerConfig


class SearchCodeInput(BaseModel):
    """Input schema for search_code."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    query: str = Field(
        ..., description="Text or symbol to search for across the repo.", min_length=1
    )
    limit: int = Field(default=20, description="Max matches to return.", ge=1, le=100)
    offset: int = Field(default=0, description="Matches to skip (pagination).", ge=0)


def register(mcp: FastMCP, config: ServerConfig) -> None:
    """Register the search_code tool on the server."""
    raise NotImplementedError("Day 5: implement search_code")
