"""list_symbols tool — functions/classes/methods for a file or matching a query.

Backed by the stdlib-``ast`` symbol index (Python sources). readOnlyHint=True.
When a ``path`` is given it is security-checked (confinement + deny-list) before
use, so symbols from denied files are never returned.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from ..access import resolve_scope
from ..app import ServerConfig
from ..errors import ActionableError, to_tool_error
from ..indexer import RepoIndex


class SymbolOut(BaseModel):
    """One code symbol."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="Symbol name.")
    kind: str = Field(description="'function', 'class', or 'method'.")
    path: str = Field(description="Repo-relative file the symbol is defined in.")
    line: int = Field(description="1-indexed line of the definition.")
    parent: str | None = Field(description="Enclosing class name for methods, else null.")


class ListSymbolsResult(BaseModel):
    """Structured symbol listing."""

    model_config = ConfigDict(extra="forbid")

    path: str | None = Field(description="File filter that was applied, if any.")
    query: str | None = Field(description="Name filter that was applied, if any.")
    total: int = Field(description="Total matching symbols.")
    count: int = Field(description="Number of symbols in this page.")
    offset: int = Field(description="Offset of this page.")
    has_more: bool = Field(description="True if more symbols match beyond this page.")
    next_offset: int | None = Field(description="Offset to pass for the next page, or null.")
    truncated: bool = Field(description="Same as has_more; kept for existing clients.")
    symbols: list[SymbolOut] = Field(description="The matching symbols.")


def register(mcp: FastMCP, config: ServerConfig, index: RepoIndex) -> None:
    """Register the list_symbols tool on the server."""
    @mcp.tool(
        name="list_symbols",
        title="List code symbols (functions, classes, methods)",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def list_symbols(
        path: Annotated[
            str | None,
            Field(description="Restrict to symbols defined in this repo-relative file or directory."),
        ] = None,
        query: Annotated[
            str | None,
            Field(description="Restrict to symbols whose name contains this substring."),
        ] = None,
        limit: Annotated[int, Field(description="Max symbols to return.", ge=1, le=500)] = 100,
        offset: Annotated[int, Field(description="Symbols to skip (pagination).", ge=0)] = 0,
    ) -> ListSymbolsResult:
        """List functions, classes, and methods, optionally filtered.

        Give a ``path`` to list the symbols in a file or directory, a ``query``
        to find symbols by name across the repo, or both. Use it to orient before reading a file.
        Denied files are excluded and never appear here.

        Returns:
            A structured result with the applied filters, the total match count,
            this page of symbols, and pagination info (has_more, next_offset).
        """
        try:
            rel = resolve_scope(config.repo_root, path, config.deny_patterns)
        except ActionableError as e:
            raise to_tool_error(e)

        total, page = index.symbols(path=rel, query=query, limit=limit, offset=offset)
        has_more = offset + len(page) < total
        return ListSymbolsResult(
            path=path,
            query=query,
            total=total,
            count=len(page),
            offset=offset,
            has_more=has_more,
            next_offset=(offset + len(page)) if has_more else None,
            truncated=has_more,
            symbols=[
                SymbolOut(name=s.name, kind=s.kind, path=s.path, line=s.line, parent=s.parent)
                for s in page
            ],
        )
