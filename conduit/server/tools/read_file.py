"""read_file tool — read a file *within the repo root*, line-range bounded.

Security-checked (§8): the path is confined to the root and screened against
the deny-list before any read. Bounded output prevents whole-repo exfiltration
in one call. Annotation: readOnlyHint=True.

Status: scaffolded on Day 1; implemented on Day 2 (boundary wired Day 3-4).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from mcp.server.fastmcp import FastMCP

from ..app import ServerConfig


class ReadFileInput(BaseModel):
    """Input schema for read_file."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    path: str = Field(
        ...,
        description="Path to the file, relative to the repo root (e.g. 'src/auth.py').",
        min_length=1,
    )
    start_line: int | None = Field(
        default=None, description="1-indexed first line to return (inclusive).", ge=1
    )
    end_line: int | None = Field(
        default=None, description="1-indexed last line to return (inclusive).", ge=1
    )


def register(mcp: FastMCP, config: ServerConfig) -> None:
    """Register the read_file tool on the server."""
    raise NotImplementedError("Day 2: implement read_file")
