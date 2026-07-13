"""read_file tool — read a file *within the repo root*, line-range bounded.

Annotation: readOnlyHint=True. Returns structured output (path, line span,
total lines, truncation flag, content). Bad inputs produce actionable errors,
never a stack trace.

Path confinement here is a MINIMAL Day-2 guard (``_confine``). The hardened,
symlink-aware defense and its violation test move to
``conduit.server.security.boundary`` on Day 3, and the deny-list is wired in on
Day 4. Until then this guard already refuses absolute paths and ``..`` escapes.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from ..access import read_text_file
from ..app import ServerConfig
from ..errors import ActionableError, to_tool_error

# Bounded output: cap a single read so one call can't dump an enormous file
# into the model's context (a mild abuse boundary — §8.4).
MAX_LINES = 2000


class ReadFileResult(BaseModel):
    """Structured result of a read_file call."""

    path: str = Field(description="The repo-relative path that was read.")
    start_line: int = Field(description="1-indexed first line returned (0 if the file is empty).")
    end_line: int = Field(description="1-indexed last line returned (0 if the file is empty).")
    total_lines: int = Field(description="Total number of lines in the file.")
    truncated: bool = Field(description="True if the requested span was capped at MAX_LINES.")
    content: str = Field(description="The selected file text.")


def register(mcp: FastMCP, config: ServerConfig) -> None:
    """Register the read_file tool on the server."""
    repo_root = config.repo_root

    @mcp.tool(
        name="read_file",
        title="Read a file within the repo",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def read_file(
        path: Annotated[
            str,
            Field(description="File path relative to the repo root, e.g. 'src/auth.py'.", min_length=1),
        ],
        start_line: Annotated[
            int | None,
            Field(description="1-indexed first line to return (inclusive).", ge=1),
        ] = None,
        end_line: Annotated[
            int | None,
            Field(description="1-indexed last line to return (inclusive).", ge=1),
        ] = None,
    ) -> ReadFileResult:
        """Read a UTF-8 text file within the served repo, optionally a line range.

        Use this to inspect a file's contents after locating it (e.g. via
        search). Paths are relative to the repo root; absolute paths and '..'
        escapes are refused. Large reads are capped at MAX_LINES; pass
        start_line/end_line to page through a big file.

        Returns:
            A structured result with the path, the 1-indexed line span actually
            returned, the file's total line count, a truncated flag, and the
            selected content.
        """
        # One error exit: security (confine → deny-list) and range validation
        # both raise ActionableError, converted to a clean MCP ToolError.
        try:
            _target, lines = read_text_file(repo_root, path)

            total = len(lines)
            if total == 0:
                return ReadFileResult(
                    path=path, start_line=0, end_line=0, total_lines=0, truncated=False, content=""
                )

            start = start_line or 1
            end = end_line or total
            if start > total:
                raise ActionableError(
                    f"start_line {start} exceeds the file length ({total} lines). "
                    f"Provide start_line <= {total}."
                )
            if end < start:
                raise ActionableError(
                    f"end_line {end} is before start_line {start}. Provide end_line >= start_line."
                )
            end = min(end, total)

            truncated = False
            if end - start + 1 > MAX_LINES:
                end = start + MAX_LINES - 1
                truncated = True
        except ActionableError as e:
            raise to_tool_error(e)

        return ReadFileResult(
            path=path,
            start_line=start,
            end_line=end,
            total_lines=total,
            truncated=truncated,
            content="\n".join(lines[start - 1 : end]),
        )
