"""Conduit MCP server entry point.

Constructs the FastMCP server, wires the served repo root through the security
boundary, registers tools + resources, and runs over stdio (the local
transport; streamable HTTP is a documented optional alternative — §11).

Registration is intentionally incremental per the build plan:
  Day 2 → read_file      Day 5 → search_code
  Day 6 → list_symbols, diff, repo_tree

Run:
    conduit-server --repo-root ./sample-repo
    # or, for manual testing:  npx @modelcontextprotocol/inspector conduit-server ...
"""

from __future__ import annotations

import argparse
import difflib
import os
from dataclasses import dataclass
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import ValidationError

from .security.denylist import DEFAULT_DENY_PATTERNS


class ConduitMCP(FastMCP):
    """FastMCP that refuses arguments a tool doesn't take.

    FastMCP ignores unknown arguments, so a model that guesses a name
    (``read_file(line_start=1, line_end=3)`` for ``start_line``/``end_line``,
    seen with a real model) silently gets defaults: here, the whole file
    instead of three lines, with no hint that anything went wrong. Refusing
    with the right names lets the model correct itself on the next step.
    """

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        tool = self._tool_manager.get_tool(name)
        if tool is not None:
            unknown_argument_check(name, tool.parameters, arguments)
            # FastMCP would raise pydantic's raw text (type codes, a docs URL).
            # Validate the same way first, and say what's wrong in plain words.
            try:
                tool.fn_metadata.arg_model.model_validate(tool.fn_metadata.pre_parse_json(arguments))
            except ValidationError as e:
                raise ToolError(_explain_invalid(name, tool.parameters, e)) from None
        return await super().call_tool(name, arguments)


def unknown_argument_check(tool: str, schema: dict[str, Any], arguments: dict[str, Any]) -> None:
    """Raise an actionable ToolError naming any argument ``schema`` doesn't define."""
    valid = list(schema.get("properties", {}))
    # An explicit null carries no intent (models send `path: null` for a
    # parameter they imagine is optional), so only a value is worth refusing.
    unknown = [a for a, v in arguments.items() if a not in valid and v is not None]
    if not unknown:
        return
    parts = []
    for arg in unknown:
        guess = _closest(arg, valid)
        parts.append(f"'{arg}'" + (f" (did you mean '{guess}'?)" if guess else ""))
    raise ToolError(
        f"{tool} does not take {', '.join(parts)}. "
        f"Its arguments are: {', '.join(valid) or 'none'}."
    )


def _explain_invalid(tool: str, schema: dict[str, Any], error: ValidationError) -> str:
    problems = []
    for e in error.errors():
        field = ".".join(str(part) for part in e["loc"]) or "arguments"
        if e["type"] == "missing":
            problems.append(f"'{field}' is required")
        else:
            msg = e["msg"].removeprefix("Input ").removeprefix("Value ")
            problems.append(f"'{field}' {msg} (got {e['input']!r})")
    valid = ", ".join(schema.get("properties", {})) or "none"
    return f"{tool}: {'; '.join(problems)}. Its arguments are: {valid}."


def _closest(arg: str, valid: list[str]) -> str | None:
    words = sorted(arg.lower().split("_"))
    for name in valid:  # the same words in another order: line_start -> start_line
        if sorted(name.lower().split("_")) == words:
            return name
    close = difflib.get_close_matches(arg, valid, n=1, cutoff=0.6)
    return close[0] if close else None


@dataclass(frozen=True)
class ServerConfig:
    """Resolved configuration for a server instance."""

    repo_root: Path
    deny_patterns: tuple[str, ...] = DEFAULT_DENY_PATTERNS


def load_config(repo_root: str | None = None, deny: Sequence[str] = ()) -> ServerConfig:
    """Resolve server config from explicit args and the environment.

    The repo root comes from ``repo_root`` or ``CONDUIT_REPO_ROOT``. Extra deny
    patterns come from ``CONDUIT_DENY`` (comma-separated) and ``deny``; they are
    *added* to :data:`DEFAULT_DENY_PATTERNS`, never replace it, so configuring
    the server can only make it refuse more.
    """
    root = repo_root or os.environ.get("CONDUIT_REPO_ROOT", "./sample-repo")
    from_env = [p.strip() for p in os.environ.get("CONDUIT_DENY", "").split(",")]
    extra = [p for p in (*from_env, *deny) if p]
    patterns = tuple(dict.fromkeys((*DEFAULT_DENY_PATTERNS, *extra)))
    return ServerConfig(repo_root=Path(root).resolve(), deny_patterns=patterns)


def build_server(config: ServerConfig) -> FastMCP:
    """Create the FastMCP server and register its tools and resource.

    Each registration gets ``config``, so path inputs go through the security
    boundary with this deployment's deny-list. The tools that query the repo
    share one :class:`RepoIndex`, built here once and kept current per query.
    """
    # FastMCP logs every request at INFO. Over stdio that stream is the host's
    # stderr, so a CLI user would see server chatter interleaved with their
    # answer. Default to WARNING; FASTMCP_LOG_LEVEL=INFO brings it back.
    mcp = ConduitMCP("conduit_mcp", log_level=os.environ.get("FASTMCP_LOG_LEVEL", "WARNING"))

    # --- Registration ---
    from .indexer import RepoIndex
    from .resources import repo_tree
    from .tools import diff, list_symbols, read_file, search_code

    index = RepoIndex(config.repo_root, config.deny_patterns)
    index.build()

    read_file.register(mcp, config)
    search_code.register(mcp, config, index)
    list_symbols.register(mcp, config, index)
    diff.register(mcp, config)
    repo_tree.register(mcp, config, index)

    # Read-only posture (§8.3): refuse to start if any non-read-only tool was
    # registered. This is enforcement, not decoration.
    from .security.readonly import enforce_readonly

    enforce_readonly(mcp)
    return mcp


def main() -> None:
    """CLI entry point: parse ``--repo-root``/``--deny`` and run over stdio."""
    parser = argparse.ArgumentParser(description="Conduit MCP codebase server")
    parser.add_argument(
        "--repo-root",
        default=None,
        help="Directory to serve (defaults to $CONDUIT_REPO_ROOT or ./sample-repo)",
    )
    parser.add_argument(
        "--deny",
        action="append",
        default=[],
        metavar="PATTERN",
        help="Extra deny-list pattern, added to the defaults (repeatable; "
        "a trailing / denies a directory, e.g. --deny 'eval/')",
    )
    args = parser.parse_args()

    config = load_config(args.repo_root, args.deny)
    server = build_server(config)
    server.run()  # stdio transport (FastMCP default)


if __name__ == "__main__":
    main()
