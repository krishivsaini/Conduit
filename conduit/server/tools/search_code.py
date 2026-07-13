"""search_code tool — lexical search across the repo, paginated.

Returns matches as file + line + snippet. Deny-listed files never enter the
index, so secrets can never appear in results. Paginated so one call can't dump
the whole repo. readOnlyHint=True.

Search is literal substring matching (case-insensitive by default) — lexical,
not semantic, by design.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from ..app import ServerConfig
from ..indexer import RepoIndex


class SearchMatchOut(BaseModel):
    """One lexical match."""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(description="Repo-relative path of the file containing the match.")
    line: int = Field(description="1-indexed line number of the match.")
    snippet: str = Field(description="The matching line, trimmed.")


class SearchResult(BaseModel):
    """Paginated search results."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(description="The query that was searched.")
    total_matches: int = Field(description="Total matches across the whole repo.")
    count: int = Field(description="Number of matches in this page.")
    offset: int = Field(description="Offset of this page.")
    has_more: bool = Field(description="True if more matches exist beyond this page.")
    next_offset: int | None = Field(description="Offset to pass for the next page, or null.")
    matches: list[SearchMatchOut] = Field(description="The matches on this page.")


def register(mcp: FastMCP, config: ServerConfig) -> None:
    """Register the search_code tool on the server."""
    index = RepoIndex(config.repo_root)
    index.build()

    @mcp.tool(
        name="search_code",
        title="Search the repo for a text/symbol substring",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def search_code(
        query: Annotated[
            str,
            Field(description="Literal substring to search for (e.g. a function name).", min_length=1),
        ],
        limit: Annotated[int, Field(description="Max matches to return.", ge=1, le=100)] = 20,
        offset: Annotated[int, Field(description="Matches to skip (pagination).", ge=0)] = 0,
        case_sensitive: Annotated[bool, Field(description="Case-sensitive match.")] = False,
    ) -> SearchResult:
        """Search the served repo for a literal substring, paginated.

        Use this to locate where something is defined or referenced (e.g. a
        function name, a constant, an error string), then read_file the result.
        Secrets are excluded — deny-listed files are never indexed. Matches are
        ordered by path then line for stable pagination.

        Returns:
            A structured result with the total match count, this page's matches
            (path + line + snippet), and pagination info (has_more, next_offset).
        """
        total, page = index.search(query, limit=limit, offset=offset, case_sensitive=case_sensitive)
        count = len(page)
        has_more = offset + count < total
        return SearchResult(
            query=query,
            total_matches=total,
            count=count,
            offset=offset,
            has_more=has_more,
            next_offset=(offset + count) if has_more else None,
            matches=[SearchMatchOut(path=m.path, line=m.line, snippet=m.snippet) for m in page],
        )
