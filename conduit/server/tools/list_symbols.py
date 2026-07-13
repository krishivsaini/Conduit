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

from ..access import resolve_allowed_path
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
    count: int = Field(description="Number returned (capped at limit).")
    truncated: bool = Field(description="True if more symbols matched than were returned.")
    symbols: list[SymbolOut] = Field(description="The matching symbols.")


def register(mcp: FastMCP, config: ServerConfig) -> None:
    """Register the list_symbols tool on the server."""
    index = RepoIndex(config.repo_root)
    index.build()

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
            Field(description="Restrict to symbols defined in this repo-relative file."),
        ] = None,
        query: Annotated[
            str | None,
            Field(description="Restrict to symbols whose name contains this substring."),
        ] = None,
        limit: Annotated[int, Field(description="Max symbols to return.", ge=1, le=500)] = 100,
    ) -> ListSymbolsResult:
        """List functions, classes, and methods, optionally filtered.

        Give a ``path`` to list a file's symbols, a ``query`` to find symbols by
        name across the repo, or both. Use it to orient before reading a file.
        Denied files are excluded and never appear here.

        Returns:
            A structured result with the applied filters, the total match count,
            the (capped) symbols, and a truncated flag.
        """
        rel: str | None = None
        if path is not None:
            try:
                target = resolve_allowed_path(config.repo_root, path)
            except ActionableError as e:
                raise to_tool_error(e)
            rel = str(target.relative_to(config.repo_root.resolve()))

        total, page = index.symbols(path=rel, query=query, limit=limit)
        return ListSymbolsResult(
            path=path,
            query=query,
            total=total,
            count=len(page),
            truncated=len(page) < total,
            symbols=[
                SymbolOut(name=s.name, kind=s.kind, path=s.path, line=s.line, parent=s.parent)
                for s in page
            ],
        )
